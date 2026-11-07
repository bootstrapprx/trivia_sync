import hashlib
import html
import json

import frappe
from frappe.utils.html_utils import sanitize_html
from frappe.utils.pdf import get_pdf

from trivia_sync.integrations.ai_enricher import OpenAICompatibleAdapter


LEVELS = {"mais", "180", "360"}


def _check_course(recipe, require_lesson=False):
	course = frappe.get_doc("LMS Course", recipe.course)
	course.check_permission("write")
	lesson = None
	if require_lesson:
		lesson = frappe.get_doc("Course Lesson", recipe.course_lesson)
		if lesson.course != recipe.course:
			frappe.throw("A aula precisa pertencer ao curso da receita.")
		lesson.check_permission("write")
	return course, lesson


def _current_source_hash(recipe):
	filters = {"review_status": "Approved", "redistribution_status": "Approved"}
	if recipe.concurso_cargo:
		filters["concurso_cargo"] = recipe.concurso_cargo
	rows = frappe.get_all(
		"Trivia Question",
		filters=filters,
		fields=["source_key", "content_hash", "enunciado", "materia", "assunto"],
		order_by="source_key asc",
	)
	methodology = ""
	if getattr(recipe, "methodology", None):
		doc = frappe.get_doc("Trivia Methodology", recipe.methodology)
		if not doc.active:
			frappe.throw("A metodologia selecionada está inativa.")
		methodology = doc.instructions or ""
	source_keys = [row.get("source_key") for row in rows]
	input_data = {
		"sources": [{key: row.get(key) for key in ("source_key", "content_hash", "enunciado", "materia", "assunto")} for row in rows],
		"methodology": methodology,
		"prompt": recipe.prompt or "",
		"title": recipe.title,
	}
	digest = hashlib.sha256(json.dumps(input_data, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
	return digest, source_keys, rows, methodology


def _prompt(recipe, level, rows, methodology, kind):
	return json.dumps({
		"tarefa": "Criar material de estudo original, mantendo-se dentro do conteúdo fornecido.",
		"tipo": kind,
		"nivel": level,
		"titulo": recipe.title,
		"metodologia": methodology,
		"instrucoes_adicionais": recipe.prompt or "",
		"fontes_aprovadas": [{key: row.get(key) for key in ("enunciado", "materia", "assunto")} for row in rows],
		"restricoes": ["Não mostrar gabaritos", "Não inventar legislação ou citações", "Manter o resultado como rascunho"],
	}, ensure_ascii=False)


def _generate(doctype, recipe_name, level, kind, require_lesson):
	if level not in LEVELS:
		frappe.throw("Nível inválido; use mais, 180 ou 360.")
	settings = frappe.get_single("Trivia Sync Settings")
	if not settings.ai_enabled:
		frappe.throw("Habilite o adaptador IA nas configurações antes de gerar material.")
	recipe = frappe.get_doc(doctype, recipe_name)
	_check_course(recipe, require_lesson=require_lesson)
	digest, source_keys, rows, methodology = _current_source_hash(recipe)
	if not rows:
		frappe.throw("Não há questões aprovadas e licenciadas para fundamentar este material.")
	result = OpenAICompatibleAdapter(settings).generate_material(_prompt(recipe, level, rows, methodology, kind), level, kind)
	version = max((int(row.version or 0) for row in recipe.material_versions if row.level == level), default=0) + 1
	recipe.source_hash = digest
	recipe.source_keys = json.dumps(source_keys, ensure_ascii=False)
	recipe.append("material_versions", {
		"level": level, "version": version, "content": result["content"], "summary": result.get("summary"),
		"source_hash": digest, "source_keys": recipe.source_keys, "model": result.get("model") or settings.ai_model,
		"status": "Draft",
	})
	recipe.save(ignore_permissions=True)
	return {"recipe": recipe.name, "level": level, "version": version, "status": "Draft", "source_hash": digest}


def generate_lesson_material(recipe_name, level):
	return _generate("Trivia Lesson Recipe", recipe_name, level, "lesson", True)


def generate_apostila_material(recipe_name, level):
	return _generate("Trivia Apostila Recipe", recipe_name, level, "apostila", False)


def _approve_material(doctype, recipe_name, level, version_number, reason=""):
	roles = frappe.get_roles(frappe.session.user)
	if "Trivia Reviewer" not in roles and "System Manager" not in roles:
		frappe.throw("Apenas revisores podem aprovar material didático.", frappe.PermissionError)
	recipe = frappe.get_doc(doctype, recipe_name)
	version = next((row for row in recipe.material_versions if row.level == level and int(row.version) == int(version_number)), None)
	if not version or version.status not in ("Draft", "Stale"):
		frappe.throw("Versão de material não encontrada ou já publicada.")
	digest, _, _, _ = _current_source_hash(recipe)
	if version.source_hash != digest:
		version.status = "Stale"
		recipe.save(ignore_permissions=True)
		return {"recipe": recipe.name, "level": level, "version": int(version.version), "status": "Stale"}
	version.status = "Approved"
	version.approved_by = frappe.session.user
	version.approved_at = frappe.utils.now_datetime()
	version.review_reason = (reason or "").strip()
	recipe.save(ignore_permissions=True)
	return {"recipe": recipe.name, "level": level, "version": int(version.version), "status": version.status}


def approve_lesson_material(recipe_name, level, version_number, reason=""):
	return _approve_material("Trivia Lesson Recipe", recipe_name, level, version_number, reason)


def approve_apostila_material(recipe_name, level, version_number, reason=""):
	return _approve_material("Trivia Apostila Recipe", recipe_name, level, version_number, reason)


def _append_material(lesson, recipe, version):
	marker = "trivia-" + hashlib.sha256(f"{recipe.name}:{version.level}:{version.version}".encode()).hexdigest()[:16]
	content = sanitize_html(version.content or "", always_sanitize=True)
	if lesson.content:
		try:
			data = frappe.parse_json(lesson.content)
		except (TypeError, ValueError):
			frappe.throw("O conteúdo da aula não é EditorJS válido e foi preservado sem alterações.")
		if not isinstance(data, dict) or not isinstance(data.get("blocks"), list):
			frappe.throw("A aula não contém blocos EditorJS válidos e foi preservada sem alterações.")
		if not any(block.get("id") == marker for block in data["blocks"]):
			data["blocks"].append({"id": marker, "type": "paragraph", "data": {"text": content}})
		lesson.content = json.dumps(data, ensure_ascii=False)
	else:
		comment = f"<!-- {marker} -->"
		if comment not in (lesson.body or ""):
			lesson.body = f"{(lesson.body or '').rstrip()}\n\n{comment}\n{content}".lstrip()
	lesson.save(ignore_permissions=True)


def publish_lesson_material(recipe_name, level):
	if level not in LEVELS:
		frappe.throw("Nível inválido.")
	recipe = frappe.get_doc("Trivia Lesson Recipe", recipe_name)
	_, lesson = _check_course(recipe, require_lesson=True)
	version = next((row for row in recipe.material_versions if row.level == level and row.status in ("Approved", "Published")), None)
	if not version:
		frappe.throw("Aprove uma versão do material antes de publicar.")
	digest, _, _, _ = _current_source_hash(recipe)
	if version.source_hash != digest:
		version.status = "Stale"
		recipe.save(ignore_permissions=True)
		return {"recipe": recipe.name, "level": level, "version": int(version.version), "status": "Stale", "reused": False}
	if version.status == "Published":
		return {"recipe": recipe.name, "level": level, "version": int(version.version), "status": "Published", "reused": True}
	_append_material(lesson, recipe, version)
	version.status = "Published"
	version.published_at = frappe.utils.now_datetime()
	recipe.status = "Published"
	recipe.save(ignore_permissions=True)
	return {"recipe": recipe.name, "level": level, "version": int(version.version), "status": "Published", "reused": False}


def export_apostila(recipe_name, levels):
	if isinstance(levels, str):
		levels = frappe.parse_json(levels)
	if not isinstance(levels, list) or not levels or set(levels) - LEVELS:
		frappe.throw("Selecione um ou mais níveis válidos para exportar.")
	recipe = frappe.get_doc("Trivia Apostila Recipe", recipe_name)
	course, _ = _check_course(recipe)
	digest, _, _, _ = _current_source_hash(recipe)
	versions = []
	for level in levels:
		version = next((row for row in recipe.material_versions if row.level == level and row.status == "Approved"), None)
		if not version or version.source_hash != digest:
			frappe.throw(f"O nível {level} precisa de uma versão aprovada e atualizada.")
		versions.append(version)
	body = "".join(
		f"<section><h2>{html.escape(version.level)}</h2>{sanitize_html(version.content or '', always_sanitize=True)}</section>"
		for version in versions
	)
	markup = f"<html><body><h1>{html.escape(recipe.title)}</h1>{body}</body></html>"
	pdf = get_pdf(markup)
	is_private = int(not course.published or course.paid_course)
	file = frappe.get_doc({
		"doctype": "File", "file_name": f"{recipe.name}-apostila.pdf", "content": pdf,
		"is_private": is_private, "attached_to_doctype": "Trivia Apostila Recipe", "attached_to_name": recipe.name,
	})
	file.insert(ignore_permissions=True)
	return {"file": file.name, "file_url": file.file_url, "is_private": is_private}
