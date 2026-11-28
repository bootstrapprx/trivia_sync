import hashlib
import html
import json
import re

import frappe
from frappe.utils.html_utils import sanitize_html
from frappe.utils.pdf import get_pdf

from trivia_sync.integrations.ai_enricher import OpenAICompatibleAdapter, get_ai_adapter
from trivia_sync.integrations.lms_questions import strip_question_embeds


LEVELS = {"mais", "180", "360"}
ACTIVE_VERSION_STATUSES = ("Draft", "Pending Approval", "Approved", "Published")
IMMUTABLE_CONTENT_STATUSES = ("Approved", "Published", "Superseded", "Archived")
RECIPE_DOCTYPES = ("Trivia Study Guide Recipe",)


def _require_any_role(*roles):
	user_roles = set(frappe.get_roles(frappe.session.user))
	if "System Manager" in user_roles or user_roles.intersection(roles):
		return
	frappe.throw("You do not have permission to perform this material lifecycle action.", frappe.PermissionError)


def _save_recipe(recipe):
	flags = getattr(recipe, "flags", None)
	if flags is not None:
		flags.from_material_lifecycle = True
	save = getattr(recipe, "save", None)
	if callable(save):
		save(ignore_permissions=True)


def _check_course(recipe, require_lesson=False):
	course = frappe.get_doc("LMS Course", recipe.course)
	course.check_permission("write")
	lesson = None
	if require_lesson:
		lesson = frappe.get_doc("Course Lesson", recipe.course_lesson)
		if lesson.course != recipe.course:
			frappe.throw("The lesson must belong to the recipe course.")
		lesson.check_permission("write")
	return course, lesson


def _query_lms_sources(concurso_cargo=None, trivia_subject=None, trivia_topic=None, syllabus_topic=None, only_ready=True):
	filters: dict = {"type": "Choices"}
	if only_ready:
		filters["trivia_status"] = "Ready"
	if concurso_cargo:
		filters["trivia_concurso_cargo"] = concurso_cargo
	if trivia_subject:
		filters["trivia_subject_link"] = trivia_subject
	if trivia_topic:
		filters["trivia_topic_link"] = trivia_topic

	if syllabus_topic:
		linked_questions = frappe.get_all(
			"Trivia Question Syllabus Topic",
			filters={"conteudo_programatico": syllabus_topic, "parenttype": "LMS Question"},
			pluck="parent",
		) or []
		if not linked_questions:
			return []
		filters["name"] = ["in", linked_questions]

	raw_rows = frappe.get_all(
		"LMS Question",
		filters=filters,
		fields=["name", "trivia_source_key", "trivia_sync_hash", "question", "trivia_materia", "trivia_assunto"],
		order_by="name asc",
		limit_page_length=200,
	) or []

	sources = []
	for row in raw_rows:
		enunciado = strip_question_embeds(row.get("question") or "")
		key = row.get("trivia_source_key") or f"lms:{row.get('name')}"
		chash = row.get("trivia_sync_hash") or hashlib.sha256(enunciado.encode("utf-8")).hexdigest()
		sources.append(
			{
				"source_key": key,
				"content_hash": chash,
				"enunciado": enunciado,
				"materia": row.get("trivia_materia"),
				"assunto": row.get("trivia_assunto"),
			}
		)
	return sources


def _current_source_hash(recipe):
	rows = _query_lms_sources(
		concurso_cargo=getattr(recipe, "concurso_cargo", None),
		trivia_subject=getattr(recipe, "trivia_subject", None),
		trivia_topic=getattr(recipe, "trivia_topic", None),
		syllabus_topic=getattr(recipe, "syllabus_topic", None),
		only_ready=True,
	)
	methodology = ""
	if getattr(recipe, "methodology", None):
		doc = frappe.get_doc("Trivia Methodology", recipe.methodology)
		if not doc.active:
			frappe.throw("The selected methodology is inactive.")
		methodology = doc.instructions or ""
	source_keys = [row.get("source_key") for row in rows]
	input_data = {
		"sources": rows,
		"methodology": methodology,
		"prompt": recipe.prompt or "",
		"title": recipe.title,
	}
	digest = hashlib.sha256(json.dumps(input_data, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
	return digest, source_keys, rows, methodology


def _prompt(title, extra_prompt, level, rows, methodology, kind):
	return json.dumps(
		{
			"tarefa": "Criar material de estudo original em português brasileiro, orientando o estudante pelos conceitos cobrados.",
			"tipo": kind,
			"nivel": level,
			"titulo": title,
			"metodologia": methodology,
			"instrucoes_adicionais": extra_prompt or "",
			"fontes_questoes": [{key: row.get(key) for key in ("enunciado", "materia", "assunto")} for row in rows[:60]],
			"restricoes": ["Não mostrar gabaritos diretos das questões", "Não inventar legislação ou citações"],
		},
		ensure_ascii=False,
	)


def _material_marker(key_prefix, level):
	return "trivia-" + hashlib.sha256(f"{key_prefix}:{level}".encode()).hexdigest()[:16]


def _next_version(recipe, level):
	return max((int(row.version or 0) for row in (recipe.material_versions or []) if row.level == level), default=0) + 1


def _find_version(recipe, level, version_number):
	return next(
		(row for row in (recipe.material_versions or []) if row.level == level and int(row.version or 0) == int(version_number)),
		None,
	)


def _latest_version(recipe, level, statuses):
	candidates = [row for row in (recipe.material_versions or []) if row.level == level and row.status in statuses]
	if not candidates:
		return None
	return max(candidates, key=lambda row: int(getattr(row, "version", 0) or 0))


def validate_material_recipe(recipe):
	if getattr(getattr(recipe, "flags", None), "from_material_lifecycle", False):
		return
	seen_versions = set()
	for row in getattr(recipe, "material_versions", None) or []:
		key = (row.level, int(row.version or 0))
		if key in seen_versions:
			frappe.throw(f"Duplicate material version {row.level} v{row.version}.")
		seen_versions.add(key)

	previous = recipe.get_doc_before_save() if hasattr(recipe, "is_new") and not recipe.is_new() else None
	if not previous:
		if getattr(recipe, "status", "Draft") == "Published":
			frappe.throw("New material recipes must start in Draft status.")
		for row in getattr(recipe, "material_versions", None) or []:
			if getattr(row, "status", "Draft") != "Draft":
				frappe.throw("New material versions must start in Draft status.")
		return

	if getattr(recipe, "status", None) == "Published" and not any(
		getattr(row, "status", None) == "Published" for row in (getattr(recipe, "material_versions", None) or [])
	):
		frappe.throw("A recipe cannot be marked Published without a published material version.")

	prev_rows = {(row.level, int(row.version or 0)): row for row in (getattr(previous, "material_versions", None) or [])}
	for row in getattr(recipe, "material_versions", None) or []:
		prev_row = prev_rows.get((row.level, int(row.version or 0)))
		if not prev_row:
			if getattr(row, "status", "Draft") != "Draft":
				frappe.throw("New material versions must start in Draft status.")
			continue
		if prev_row.status != row.status:
			frappe.throw("Use the material lifecycle actions to change version status.")
		if prev_row.content != row.content and prev_row.status in IMMUTABLE_CONTENT_STATUSES:
			frappe.throw("Do not edit approved or published material directly; create a new draft version.")


def _write_lesson_block(lesson, marker: str, html_content: str):
	clean_html = sanitize_html(html_content or "", always_sanitize=True)
	if lesson.content:
		try:
			data = frappe.parse_json(lesson.content)
		except (TypeError, ValueError):
			frappe.throw("The lesson content is not valid EditorJS and was preserved unchanged.")
		if not isinstance(data, dict) or not isinstance(data.get("blocks"), list):
			frappe.throw("The lesson has no valid EditorJS blocks and was preserved unchanged.")
		blocks = [b for b in data["blocks"] if b.get("id") != marker]
		blocks.append({"id": marker, "type": "paragraph", "data": {"text": clean_html}})
		data["blocks"] = blocks
		lesson.content = json.dumps(data, ensure_ascii=False)
	else:
		body = lesson.body or ""
		start = re.escape(f"<!-- {marker} -->")
		end = re.escape(f"<!-- /{marker} -->")
		body = re.sub(rf"\n*{start}[\s\S]*?{end}\n*", "\n\n", body).strip()
		lesson.body = f"{body}\n\n<!-- {marker} -->\n{clean_html}\n<!-- /{marker} -->".strip()
	lesson.save(ignore_permissions=True)


def generate_course_lesson_draft(
	lesson_name: str,
	level: str = "180",
	trivia_subject: str | None = None,
	trivia_topic: str | None = None,
	syllabus_topic: str | None = None,
	methodology: str | None = None,
	prompt: str = "",
) -> dict:
	"""Generate study content directly into a native Frappe LMS Course Lesson."""
	_require_any_role("Trivia Editor", "Trivia Reviewer", "Trivia Integrator")
	if level not in LEVELS:
		frappe.throw("Invalid level; use mais, 180, or 360.")
	settings = frappe.get_single("Trivia Sync Settings")
	if not settings.ai_enabled:
		frappe.throw("Enable AI enrichment in Trivia Sync Settings before generating lesson content.")
	lesson = frappe.get_doc("Course Lesson", lesson_name)
	lesson.check_permission("write")

	rows = _query_lms_sources(
		trivia_subject=trivia_subject,
		trivia_topic=trivia_topic,
		syllabus_topic=syllabus_topic,
		only_ready=False,
	)
	method_text = ""
	if methodology:
		m_doc = frappe.get_doc("Trivia Methodology", methodology)
		if not m_doc.active:
			frappe.throw("The selected methodology is inactive.")
		method_text = m_doc.instructions or ""

	adapter = get_ai_adapter(settings) if getattr(settings, "ai_backend", None) else OpenAICompatibleAdapter(settings)
	result = adapter.generate_material(
		_prompt(lesson.title or lesson.name, prompt, level, rows, method_text, "lesson"),
		level,
		"lesson",
	)
	marker = _material_marker(lesson.name, level)
	_write_lesson_block(lesson, marker, result["content"])
	return {
		"lesson": lesson.name,
		"level": level,
		"model": result.get("model") or getattr(settings, "ai_model", None),
		"source_questions": len(rows),
	}


def generate_apostila_material(recipe_name, level):
	if level not in LEVELS:
		frappe.throw("Invalid level; use mais, 180, or 360.")
	settings = frappe.get_single("Trivia Sync Settings")
	if not settings.ai_enabled:
		frappe.throw("Enable the AI adapter in settings before generating material.")
	recipe = frappe.get_doc("Trivia Study Guide Recipe", recipe_name)
	if getattr(recipe, "status", None) == "Archived":
		frappe.throw("Archived recipes cannot generate new material versions.")
	_check_course(recipe, require_lesson=False)
	digest, source_keys, rows, methodology = _current_source_hash(recipe)
	if not rows:
		frappe.throw("There are no Ready LMS questions matching this study guide's filters.")
	adapter = get_ai_adapter(settings) if getattr(settings, "ai_backend", None) else OpenAICompatibleAdapter(settings)
	result = adapter.generate_material(_prompt(recipe.title, recipe.prompt, level, rows, methodology, "apostila"), level, "apostila")
	version = _next_version(recipe, level)
	recipe.source_hash = digest
	recipe.source_keys = json.dumps(source_keys, ensure_ascii=False)
	recipe.append(
		"material_versions",
		{
			"level": level,
			"version": version,
			"origin": "AI",
			"content": result["content"],
			"summary": result.get("summary"),
			"source_hash": digest,
			"source_keys": recipe.source_keys,
			"model": result.get("model") or settings.ai_model,
			"status": "Draft",
		},
	)
	_save_recipe(recipe)
	return {"recipe": recipe.name, "level": level, "version": version, "origin": "AI", "status": "Draft", "source_hash": digest}


def create_manual_apostila_material(recipe_name, level, content, summary=""):
	_require_any_role("Trivia Editor")
	if level not in LEVELS:
		frappe.throw("Invalid level; use mais, 180, or 360.")
	if not (content or "").strip():
		frappe.throw("Provide material content to create a draft version.")
	recipe = frappe.get_doc("Trivia Study Guide Recipe", recipe_name)
	if getattr(recipe, "status", None) == "Archived":
		frappe.throw("Archived recipes cannot receive new draft versions.")
	_check_course(recipe, require_lesson=False)
	digest, source_keys, _, _ = _current_source_hash(recipe)
	version = _next_version(recipe, level)
	recipe.source_hash = digest
	recipe.source_keys = json.dumps(source_keys, ensure_ascii=False)
	recipe.append(
		"material_versions",
		{
			"level": level,
			"version": version,
			"origin": "Manual",
			"content": content,
			"summary": (summary or "").strip(),
			"source_hash": digest,
			"source_keys": recipe.source_keys,
			"model": "manual",
			"status": "Draft",
		},
	)
	_save_recipe(recipe)
	return {"recipe": recipe.name, "level": level, "version": version, "origin": "Manual", "status": "Draft", "source_hash": digest}


def submit_apostila_material(recipe_name, level, version_number):
	_require_any_role("Trivia Editor")
	recipe = frappe.get_doc("Trivia Study Guide Recipe", recipe_name)
	if getattr(recipe, "status", None) == "Archived":
		frappe.throw("Archived recipes cannot be submitted for approval.")
	version = _find_version(recipe, level, version_number)
	if not version or version.status not in ("Draft", "Rejected"):
		frappe.throw("Only Draft or Rejected material versions can be submitted for approval.")
	digest, _, _, _ = _current_source_hash(recipe)
	if version.source_hash != digest:
		version.status = "Stale"
		_save_recipe(recipe)
		return {"recipe": recipe.name, "level": level, "version": int(version.version), "status": "Stale"}
	version.status = "Pending Approval"
	version.submitted_by = frappe.session.user
	version.submitted_at = frappe.utils.now_datetime()
	_save_recipe(recipe)
	return {"recipe": recipe.name, "level": level, "version": int(version.version), "status": "Pending Approval"}


def approve_apostila_material(recipe_name, level, version_number, reason=""):
	_require_any_role("Trivia Reviewer")
	recipe = frappe.get_doc("Trivia Study Guide Recipe", recipe_name)
	version = _find_version(recipe, level, version_number)
	if not version or version.status != "Pending Approval":
		frappe.throw("Material version must be Pending Approval before it can be approved.")
	digest, _, _, _ = _current_source_hash(recipe)
	if version.source_hash != digest:
		version.status = "Stale"
		_save_recipe(recipe)
		return {"recipe": recipe.name, "level": level, "version": int(version.version), "status": "Stale"}
	version.status = "Approved"
	version.approved_by = frappe.session.user
	version.approved_at = frappe.utils.now_datetime()
	version.review_reason = (reason or "").strip()
	_save_recipe(recipe)
	return {"recipe": recipe.name, "level": level, "version": int(version.version), "status": version.status}


def reject_apostila_material(recipe_name, level, version_number, reason=""):
	_require_any_role("Trivia Reviewer")
	cleaned_reason = (reason or "").strip()
	if not cleaned_reason:
		frappe.throw("Provide a reason when rejecting a material version.")
	recipe = frappe.get_doc("Trivia Study Guide Recipe", recipe_name)
	version = _find_version(recipe, level, version_number)
	if not version or version.status != "Pending Approval":
		frappe.throw("Only Pending Approval material versions can be rejected.")
	version.status = "Rejected"
	version.rejected_by = frappe.session.user
	version.rejected_at = frappe.utils.now_datetime()
	version.review_reason = cleaned_reason
	_save_recipe(recipe)
	return {"recipe": recipe.name, "level": level, "version": int(version.version), "status": "Rejected"}


def export_apostila(recipe_name, levels):
	if isinstance(levels, str):
		levels = frappe.parse_json(levels)
	if not isinstance(levels, list) or not levels or set(levels) - LEVELS:
		frappe.throw("Select one or more valid levels to export.")
	recipe = frappe.get_doc("Trivia Study Guide Recipe", recipe_name)
	if getattr(recipe, "status", None) == "Archived":
		frappe.throw("Archived study guides cannot be exported.")
	course, _ = _check_course(recipe)
	digest, _, _, _ = _current_source_hash(recipe)
	versions = []
	for level in levels:
		version = _latest_version(recipe, level, ("Approved", "Published"))
		if not version:
			frappe.throw(f"Level {level} requires an approved and up-to-date version.")
		if version.source_hash != digest:
			version.status = "Stale"
			_save_recipe(recipe)
			frappe.throw(f"Level {level} requires an approved and up-to-date version.")
		versions.append(version)
	body = "".join(
		f"<section><h2>{html.escape(version.level)}</h2>{sanitize_html(version.content or '', always_sanitize=True)}</section>"
		for version in versions
	)
	brand_header = (
		'<header style="border-bottom:2px solid #08245A;padding-bottom:12px;margin-bottom:20px;">'
		'<img src="/assets/trivia_sync/images/whitelabel/trivia-logo-full.png" alt="Trivia Concursos" '
		'style="height:56px;width:auto;vertical-align:middle;margin-right:12px;">'
		'<span style="font-size:12px;color:#08245A;font-weight:700;letter-spacing:0.06em;">'
		"TRIVIA CONCURSOS · MATERIAL DE ESTUDO DIRIGIDO"
		"</span></header>"
	)
	brand_footer = (
		'<footer style="border-top:1px solid #cbd5e1;margin-top:28px;padding-top:10px;'
		'font-size:11px;color:#475569;text-align:center;">'
		"Trivia Concursos"
		"</footer>"
	)
	markup = f"<html><body>{brand_header}<h1>{html.escape(recipe.title)}</h1>{body}{brand_footer}</body></html>"
	pdf = get_pdf(markup)
	is_private = int(not course.published or course.paid_course)
	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{recipe.name}-apostila.pdf",
			"content": pdf,
			"is_private": is_private,
			"attached_to_doctype": "Trivia Study Guide Recipe",
			"attached_to_name": recipe.name,
		}
	)
	file.insert(ignore_permissions=True)
	now = frappe.utils.now_datetime() if hasattr(getattr(frappe, "utils", None), "now_datetime") else None
	for version in versions:
		for prior in (recipe.material_versions or []):
			if prior.level == version.level and prior.status == "Published" and prior is not version:
				prior.status = "Superseded"
		version.status = "Published"
		if now is not None:
			version.published_at = now
		version.exported_file = file.name
		version.exported_file_url = file.file_url
	recipe.status = "Published"
	_save_recipe(recipe)
	return {
		"file": file.name,
		"file_url": file.file_url,
		"is_private": is_private,
		"status": "Published",
		"versions": [{"level": row.level, "version": int(getattr(row, "version", 0) or 0)} for row in versions],
	}


def archive_apostila_recipe(recipe_name):
	_require_any_role("Trivia Integrator")
	recipe = frappe.get_doc("Trivia Study Guide Recipe", recipe_name)
	_check_course(recipe, require_lesson=False)
	now = frappe.utils.now_datetime()
	for row in (recipe.material_versions or []):
		if row.status == "Published":
			row.unpublished_at = now
		if row.status != "Archived":
			row.status = "Archived"
			row.archived_at = now
	recipe.status = "Archived"
	_save_recipe(recipe)
	return {"recipe": recipe.name, "status": "Archived"}


def check_material_freshness(doctype, recipe_name, require_role=True):
	if require_role:
		_require_any_role("Trivia Editor", "Trivia Reviewer", "Trivia Integrator")
	recipe = frappe.get_doc(doctype, recipe_name)
	if getattr(recipe, "status", None) == "Archived":
		return {"recipe": recipe.name, "current_hash": recipe.source_hash, "stale_versions": []}
	digest, _, _, _ = _current_source_hash(recipe)
	stale = []
	for row in (recipe.material_versions or []):
		if row.status in ACTIVE_VERSION_STATUSES and row.source_hash != digest:
			row.status = "Stale"
			stale.append({"level": row.level, "version": int(row.version or 0)})
	if stale:
		_save_recipe(recipe)
	return {"recipe": recipe.name, "current_hash": digest, "stale_versions": stale}


def _invalidate_recipes(filters_list):
	updated = []
	for doctype in RECIPE_DOCTYPES:
		seen = set()
		for filters in filters_list:
			names = frappe.get_all(doctype, filters={**filters, "status": ["!=", "Archived"]}, pluck="name") or []
			for name in names:
				if name in seen:
					continue
				seen.add(name)
				try:
					res = check_material_freshness(doctype, name, require_role=False)
					if res["stale_versions"]:
						updated.append({"doctype": doctype, "recipe": name, "stale_versions": res["stale_versions"]})
				except Exception:
					continue
	return updated


def invalidate_stale_materials_for_question(doc, method=None):
	cargo = getattr(doc, "trivia_concurso_cargo", None)
	filters_list = [{"concurso_cargo": ["in", ["", None]]}]
	if cargo:
		filters_list.append({"concurso_cargo": cargo})
	return _invalidate_recipes(filters_list)


def invalidate_stale_materials_for_methodology(doc, method=None):
	if not getattr(doc, "name", None):
		return []
	return _invalidate_recipes([{"methodology": doc.name}])
