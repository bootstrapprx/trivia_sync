import hashlib
import html
import json
import re

import frappe
from frappe.utils.html_utils import sanitize_html
from frappe.utils.pdf import get_pdf

from trivia_sync.integrations.ai_enricher import OpenAICompatibleAdapter, get_ai_adapter


LEVELS = {"mais", "180", "360"}
ACTIVE_VERSION_STATUSES = ("Draft", "Pending Approval", "Approved", "Published")
IMMUTABLE_CONTENT_STATUSES = ("Approved", "Published", "Superseded", "Archived")
RECIPE_DOCTYPES = ("Trivia Lesson Recipe", "Trivia Study Guide Recipe")


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
			frappe.throw("The selected methodology is inactive.")
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


def _material_marker(recipe_name, level, version_number):
	return "trivia-" + hashlib.sha256(f"{recipe_name}:{level}:{version_number}".encode()).hexdigest()[:16]


def _next_version(recipe, level):
	return max((int(row.version or 0) for row in (recipe.material_versions or []) if row.level == level), default=0) + 1


def _find_version(recipe, level, version_number):
	return next(
		(row for row in (recipe.material_versions or []) if row.level == level and int(row.version or 0) == int(version_number)),
		None,
	)


def _latest_version(recipe, level, statuses):
	candidates = [
		row for row in (recipe.material_versions or [])
		if row.level == level and row.status in statuses
	]
	if not candidates:
		return None
	return max(candidates, key=lambda row: int(getattr(row, "version", 0) or 0))


def validate_material_recipe(recipe):
	if getattr(getattr(recipe, "flags", None), "from_material_lifecycle", False):
		return
	if getattr(recipe, "course_lesson", None) and getattr(recipe, "course", None) and hasattr(frappe, "db"):
		lesson_course = frappe.db.get_value("Course Lesson", recipe.course_lesson, "course")
		if lesson_course and lesson_course != recipe.course:
			frappe.throw("The lesson must belong to the recipe course.")
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

	prev_rows = {
		(row.level, int(row.version or 0)): row
		for row in (getattr(previous, "material_versions", None) or [])
	}
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


def _generate(doctype, recipe_name, level, kind, require_lesson):
	if level not in LEVELS:
		frappe.throw("Invalid level; use mais, 180, or 360.")
	settings = frappe.get_single("Trivia Sync Settings")
	if not settings.ai_enabled:
		frappe.throw("Enable the AI adapter in settings before generating material.")
	recipe = frappe.get_doc(doctype, recipe_name)
	if getattr(recipe, "status", None) == "Archived":
		frappe.throw("Archived recipes cannot generate new material versions.")
	_check_course(recipe, require_lesson=require_lesson)
	digest, source_keys, rows, methodology = _current_source_hash(recipe)
	if not rows:
		frappe.throw("There are no approved and licensed questions to support this material.")
	adapter = get_ai_adapter(settings) if getattr(settings, "ai_backend", None) else OpenAICompatibleAdapter(settings)
	result = adapter.generate_material(_prompt(recipe, level, rows, methodology, kind), level, kind)
	version = _next_version(recipe, level)
	recipe.source_hash = digest
	recipe.source_keys = json.dumps(source_keys, ensure_ascii=False)
	recipe.append("material_versions", {
		"level": level,
		"version": version,
		"origin": "AI",
		"content": result["content"],
		"summary": result.get("summary"),
		"source_hash": digest,
		"source_keys": recipe.source_keys,
		"model": result.get("model") or settings.ai_model,
		"status": "Draft",
	})
	_save_recipe(recipe)
	return {"recipe": recipe.name, "level": level, "version": version, "origin": "AI", "status": "Draft", "source_hash": digest}


def generate_lesson_material(recipe_name, level):
	return _generate("Trivia Lesson Recipe", recipe_name, level, "lesson", True)


def generate_apostila_material(recipe_name, level):
	return _generate("Trivia Study Guide Recipe", recipe_name, level, "apostila", False)


def _create_manual_material(doctype, recipe_name, level, content, summary="", require_lesson=False):
	_require_any_role("Trivia Editor")
	if level not in LEVELS:
		frappe.throw("Invalid level; use mais, 180, or 360.")
	if not (content or "").strip():
		frappe.throw("Provide material content to create a draft version.")
	recipe = frappe.get_doc(doctype, recipe_name)
	if getattr(recipe, "status", None) == "Archived":
		frappe.throw("Archived recipes cannot receive new draft versions.")
	_check_course(recipe, require_lesson=require_lesson)
	digest, source_keys, _, _ = _current_source_hash(recipe)
	version = _next_version(recipe, level)
	recipe.source_hash = digest
	recipe.source_keys = json.dumps(source_keys, ensure_ascii=False)
	recipe.append("material_versions", {
		"level": level,
		"version": version,
		"origin": "Manual",
		"content": content,
		"summary": (summary or "").strip(),
		"source_hash": digest,
		"source_keys": recipe.source_keys,
		"model": "manual",
		"status": "Draft",
	})
	_save_recipe(recipe)
	return {"recipe": recipe.name, "level": level, "version": version, "origin": "Manual", "status": "Draft", "source_hash": digest}


def create_manual_lesson_material(recipe_name, level, content, summary=""):
	return _create_manual_material("Trivia Lesson Recipe", recipe_name, level, content, summary, require_lesson=True)


def create_manual_apostila_material(recipe_name, level, content, summary=""):
	return _create_manual_material("Trivia Study Guide Recipe", recipe_name, level, content, summary, require_lesson=False)


def _submit_material(doctype, recipe_name, level, version_number):
	_require_any_role("Trivia Editor")
	recipe = frappe.get_doc(doctype, recipe_name)
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


def submit_lesson_material(recipe_name, level, version_number):
	return _submit_material("Trivia Lesson Recipe", recipe_name, level, version_number)


def submit_apostila_material(recipe_name, level, version_number):
	return _submit_material("Trivia Study Guide Recipe", recipe_name, level, version_number)


def _approve_material(doctype, recipe_name, level, version_number, reason=""):
	_require_any_role("Trivia Reviewer")
	recipe = frappe.get_doc(doctype, recipe_name)
	version = _find_version(recipe, level, version_number)
	if not version or version.status not in ("Pending Approval",):
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


def approve_lesson_material(recipe_name, level, version_number, reason=""):
	return _approve_material("Trivia Lesson Recipe", recipe_name, level, version_number, reason)


def approve_apostila_material(recipe_name, level, version_number, reason=""):
	return _approve_material("Trivia Study Guide Recipe", recipe_name, level, version_number, reason)


def _reject_material(doctype, recipe_name, level, version_number, reason=""):
	_require_any_role("Trivia Reviewer")
	cleaned_reason = (reason or "").strip()
	if not cleaned_reason:
		frappe.throw("Provide a reason when rejecting a material version.")
	recipe = frappe.get_doc(doctype, recipe_name)
	version = _find_version(recipe, level, version_number)
	if not version or version.status != "Pending Approval":
		frappe.throw("Only Pending Approval material versions can be rejected.")
	version.status = "Rejected"
	version.rejected_by = frappe.session.user
	version.rejected_at = frappe.utils.now_datetime()
	version.review_reason = cleaned_reason
	_save_recipe(recipe)
	return {"recipe": recipe.name, "level": level, "version": int(version.version), "status": "Rejected"}


def reject_lesson_material(recipe_name, level, version_number, reason=""):
	return _reject_material("Trivia Lesson Recipe", recipe_name, level, version_number, reason)


def reject_apostila_material(recipe_name, level, version_number, reason=""):
	return _reject_material("Trivia Study Guide Recipe", recipe_name, level, version_number, reason)


def _strip_body_markers(body, markers):
	result = body or ""
	for marker in markers:
		start = re.escape(f"<!-- {marker} -->")
		end = re.escape(f"<!-- /{marker} -->")
		result = re.sub(rf"\n*{start}[\s\S]*?{end}\n*", "\n\n", result)
		result = re.sub(rf"\n*{start}\n[^\n]*\n*", "\n\n", result)
	return result.strip()


def _write_lesson_material(lesson, recipe, version=None, old_markers=None):
	old_markers = {marker for marker in (old_markers or []) if marker}
	new_marker = _material_marker(recipe.name, version.level, version.version) if version else None
	content = sanitize_html(version.content or "", always_sanitize=True) if version else ""
	if lesson.content:
		try:
			data = frappe.parse_json(lesson.content)
		except (TypeError, ValueError):
			frappe.throw("The lesson content is not valid EditorJS and was preserved unchanged.")
		if not isinstance(data, dict) or not isinstance(data.get("blocks"), list):
			frappe.throw("The lesson has no valid EditorJS blocks and was preserved unchanged.")
		blocks = [block for block in data["blocks"] if block.get("id") not in old_markers]
		if new_marker and not any(block.get("id") == new_marker for block in blocks):
			blocks.append({"id": new_marker, "type": "paragraph", "data": {"text": content}})
		data["blocks"] = blocks
		lesson.content = json.dumps(data, ensure_ascii=False)
	else:
		body = _strip_body_markers(lesson.body or "", old_markers)
		if new_marker:
			comment = f"<!-- {new_marker} -->"
			end_comment = f"<!-- /{new_marker} -->"
			if comment not in body:
				body = f"{body.rstrip()}\n\n{comment}\n{content}\n{end_comment}".lstrip()
		lesson.body = body
	lesson.save(ignore_permissions=True)


def _append_material(lesson, recipe, version):
	_write_lesson_material(lesson, recipe, version=version)


def publish_lesson_material(recipe_name, level):
	if level not in LEVELS:
		frappe.throw("Invalid level.")
	recipe = frappe.get_doc("Trivia Lesson Recipe", recipe_name)
	if getattr(recipe, "status", None) == "Archived":
		frappe.throw("Archived recipes cannot be published.")
	_, lesson = _check_course(recipe, require_lesson=True)
	version = _latest_version(recipe, level, ("Approved", "Published"))
	if not version:
		frappe.throw("Approve a material version before publishing.")
	digest, _, _, _ = _current_source_hash(recipe)
	if version.source_hash != digest:
		version.status = "Stale"
		_save_recipe(recipe)
		return {"recipe": recipe.name, "level": level, "version": int(version.version), "status": "Stale", "reused": False}
	if version.status == "Published":
		return {"recipe": recipe.name, "level": level, "version": int(version.version), "status": "Published", "reused": True}
	prior_published = [
		row for row in (recipe.material_versions or [])
		if row.level == level and row.status == "Published" and row is not version
	]
	old_markers = [_material_marker(recipe.name, row.level, row.version) for row in prior_published]
	_write_lesson_material(lesson, recipe, version=version, old_markers=old_markers)
	for row in prior_published:
		row.status = "Superseded"
	version.status = "Published"
	version.published_at = frappe.utils.now_datetime()
	recipe.status = "Published"
	_save_recipe(recipe)
	return {
		"recipe": recipe.name,
		"level": level,
		"version": int(version.version),
		"status": "Published",
		"reused": False,
		"superseded_versions": [int(row.version) for row in prior_published],
	}


def unpublish_lesson_material(recipe_name, level=None):
	_require_any_role("Trivia Integrator")
	if level and level not in LEVELS:
		frappe.throw("Invalid level.")
	recipe = frappe.get_doc("Trivia Lesson Recipe", recipe_name)
	_, lesson = _check_course(recipe, require_lesson=True)
	targets = [
		row for row in (recipe.material_versions or [])
		if row.status == "Published" and (not level or row.level == level)
	]
	if not targets:
		frappe.throw("No published material version found to unpublish.")
	markers = [_material_marker(recipe.name, row.level, row.version) for row in targets]
	_write_lesson_material(lesson, recipe, version=None, old_markers=markers)
	now = frappe.utils.now_datetime()
	for row in targets:
		row.status = "Archived"
		row.unpublished_at = now
		row.archived_at = now
	if not any(row.status == "Published" for row in (recipe.material_versions or [])):
		recipe.status = "Draft"
	_save_recipe(recipe)
	return {
		"recipe": recipe.name,
		"unpublished_versions": [{"level": row.level, "version": int(row.version)} for row in targets],
		"status": recipe.status,
	}


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
	markup = f"<html><body><h1>{html.escape(recipe.title)}</h1>{body}</body></html>"
	pdf = get_pdf(markup)
	is_private = int(not course.published or course.paid_course)
	file = frappe.get_doc({
		"doctype": "File",
		"file_name": f"{recipe.name}-apostila.pdf",
		"content": pdf,
		"is_private": is_private,
		"attached_to_doctype": "Trivia Study Guide Recipe",
		"attached_to_name": recipe.name,
	})
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


def _archive_recipe(doctype, recipe_name, require_lesson=False):
	_require_any_role("Trivia Integrator")
	recipe = frappe.get_doc(doctype, recipe_name)
	if require_lesson and getattr(recipe, "course_lesson", None):
		_, lesson = _check_course(recipe, require_lesson=True)
		published_rows = [row for row in (recipe.material_versions or []) if row.status == "Published"]
		if published_rows:
			markers = [_material_marker(recipe.name, row.level, row.version) for row in published_rows]
			_write_lesson_material(lesson, recipe, version=None, old_markers=markers)
	else:
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


def archive_lesson_recipe(recipe_name):
	return _archive_recipe("Trivia Lesson Recipe", recipe_name, require_lesson=True)


def archive_apostila_recipe(recipe_name):
	return _archive_recipe("Trivia Study Guide Recipe", recipe_name, require_lesson=False)


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
	cargo = getattr(doc, "concurso_cargo", None)
	filters_list = [{"concurso_cargo": ["in", ["", None]]}]
	if cargo:
		filters_list.append({"concurso_cargo": cargo})
	return _invalidate_recipes(filters_list)


def invalidate_stale_materials_for_methodology(doc, method=None):
	if not getattr(doc, "name", None):
		return []
	return _invalidate_recipes([{"methodology": doc.name}])
