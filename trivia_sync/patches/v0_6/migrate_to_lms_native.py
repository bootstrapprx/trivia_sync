import contextlib
import json

import frappe

from trivia_sync.integrations.lms_questions import compose_lms_question_html, disambiguate_option_pairs

RETIRED_DOCTYPES = (
	"Trivia Question",
	"Trivia Exam",
	"Trivia Exam Block",
	"Trivia Exam Block Syllabus Topic",
	"Trivia Exam Question",
	"Trivia Exam Version",
	"Trivia Prova",
	"Prova",
	"Trivia Lesson Recipe",
)

OBSOLETE_LMS_FIELDNAMES = (
	"trivia_question",
	"trivia_projection_key",
	"trivia_redistribution_reference",
	"trivia_redistribution_status",
	"trivia_allow_variable_options",
	"trivia_exception_reason",
)

OBSOLETE_CUSTOM_FIELD_NAMES = tuple(f"LMS Question-{fn}" for fn in OBSOLETE_LMS_FIELDNAMES)


def _parse_dict(raw):
	if isinstance(raw, dict):
		return raw
	try:
		parsed = json.loads(raw or "{}")
		return parsed if isinstance(parsed, dict) else {}
	except (TypeError, ValueError):
		return {}


def _parse_list(raw):
	if isinstance(raw, list):
		return raw
	try:
		parsed = json.loads(raw or "[]")
		return parsed if isinstance(parsed, list) else []
	except (TypeError, ValueError):
		return []


def _existing_link(doctype: str, value) -> str | None:
	val = str(value or "").strip()
	if not val:
		return None
	if hasattr(frappe, "db") and hasattr(frappe.db, "exists"):
		return val if frappe.db.exists(doctype, val) else None
	return val


def _delete_custom_field_safely(cf_name: str):
	if not cf_name:
		return
	try:
		frappe.delete_doc("Custom Field", cf_name, ignore_permissions=True, force=True)
	except Exception:
		if hasattr(frappe.db, "delete"):
			frappe.db.delete("Custom Field", {"name": cf_name})


def cleanup_retired_metadata():
	"""Remove any Custom Field, Property Setter, link, or DocType metadata referencing retired DocTypes."""
	if not hasattr(frappe, "db"):
		return

	# 1. Remove known obsolete Custom Fields by explicit name
	for obsolete_cf in OBSOLETE_CUSTOM_FIELD_NAMES:
		if frappe.db.exists("Custom Field", obsolete_cf):
			_delete_custom_field_safely(obsolete_cf)

	# 2. Remove any Custom Field (regardless of name) pointing to retired DocTypes or obsolete LMS fieldnames
	if hasattr(frappe, "get_all") and callable(frappe.get_all):
		with contextlib.suppress(Exception):
			for cf_name in frappe.get_all(
				"Custom Field",
				filters={"dt": "LMS Question", "fieldname": ["in", list(OBSOLETE_LMS_FIELDNAMES)]},
				pluck="name",
			) or []:
				_delete_custom_field_safely(cf_name)

		with contextlib.suppress(Exception):
			for cf_name in frappe.get_all(
				"Custom Field",
				filters={"options": ["in", list(RETIRED_DOCTYPES)]},
				pluck="name",
			) or []:
				_delete_custom_field_safely(cf_name)

		with contextlib.suppress(Exception):
			for cf_name in frappe.get_all(
				"Custom Field",
				filters={"dt": ["in", list(RETIRED_DOCTYPES)]},
				pluck="name",
			) or []:
				_delete_custom_field_safely(cf_name)

		# 3. Clean up Property Setters referencing obsolete fields or retired DocTypes
		with contextlib.suppress(Exception):
			for ps_name in frappe.get_all(
				"Property Setter",
				filters={"doc_type": ["in", list(RETIRED_DOCTYPES)]},
				pluck="name",
			) or []:
				frappe.delete_doc("Property Setter", ps_name, ignore_permissions=True, force=True)

		with contextlib.suppress(Exception):
			for ps_name in frappe.get_all(
				"Property Setter",
				filters={"doc_type": "LMS Question", "field_name": ["in", list(OBSOLETE_LMS_FIELDNAMES)]},
				pluck="name",
			) or []:
				frappe.delete_doc("Property Setter", ps_name, ignore_permissions=True, force=True)

		with contextlib.suppress(Exception):
			for ps in frappe.get_all(
				"Property Setter",
				filters={"doc_type": "LMS Question", "property": "field_order"},
				fields=["name", "value"],
			) or []:
				order = _parse_list(ps.get("value"))
				cleaned = [f for f in order if f not in OBSOLETE_LMS_FIELDNAMES]
				if order and cleaned != order and hasattr(frappe.db, "set_value"):
					frappe.db.set_value("Property Setter", ps["name"], "value", json.dumps(cleaned), update_modified=False)

		# 4. Clean up custom DocType Links, Kanban Boards, List Filters, Client Scripts, Flow Knowledge Sources
		for dt_name, filter_field in (
			("DocType Link", "link_doctype"),
			("DocType Link", "parent"),
			("Kanban Board", "reference_doctype"),
			("List Filter", "reference_doctype"),
			("Client Script", "dt"),
			("User Permission", "allow"),
			("Flow Knowledge Source", "reference_doctype"),
		):
			with contextlib.suppress(Exception):
				if frappe.db.exists("DocType", dt_name):
					for rec_name in frappe.get_all(
						dt_name,
						filters={filter_field: ["in", list(RETIRED_DOCTYPES)]},
						pluck="name",
					) or []:
						frappe.delete_doc(dt_name, rec_name, ignore_permissions=True, force=True)

	# 5. Clear legacy `trivia_question` column values on tabLMS Question if column still exists
	with contextlib.suppress(Exception):
		if hasattr(frappe.db, "has_column") and frappe.db.has_column("LMS Question", "trivia_question"):
			frappe.db.sql("UPDATE `tabLMS Question` SET `trivia_question` = NULL WHERE `trivia_question` IS NOT NULL")

	# 6. Remove retired DocType metadata records from Desk if present
	for retired_dt in RETIRED_DOCTYPES:
		if frappe.db.exists("DocType", retired_dt):
			with contextlib.suppress(Exception):
				frappe.delete_doc("DocType", retired_dt, ignore_permissions=True, force=True)

	# 7. Flush cached metadata for LMS Question so Desk never serves stale Link definitions
	if hasattr(frappe, "clear_cache") and callable(frappe.clear_cache):
		with contextlib.suppress(Exception):
			frappe.clear_cache(doctype="LMS Question")


def ensure_lms_native_clean():
	"""Idempotent `after_migrate` hook to guarantee no dangling references to retired DocTypes remain."""
	cleanup_retired_metadata()
	if hasattr(frappe, "db") and hasattr(frappe.db, "commit"):
		frappe.db.commit()


def _migrate_single_row(row: dict) -> str:
	options = _parse_dict(row.get("options"))
	ordered_options = [
		(str(k).upper(), str(v).strip())
		for k, v in sorted(options.items())
		if str(v or "").strip()
	]
	if not (2 <= len(ordered_options) <= 10) or not (row.get("enunciado") or "").strip():
		return "skipped"

	ordered_options = disambiguate_option_pairs(ordered_options)

	correct_letters = {str(x).upper() for x in _parse_list(row.get("correct_options")) if x}
	if not correct_letters and row.get("correct_option"):
		correct_letters = {str(row.get("correct_option")).upper()}
	valid_letters = {k for k, _ in ordered_options}
	correct_letters = correct_letters & valid_letters
	if not correct_letters:
		return "skipped"

	opt_explanations = _parse_dict(row.get("option_explanations"))
	general_exp = str(row.get("explanation") or "").strip()

	existing_name = row.get("lms_question")
	if existing_name and not frappe.db.exists("LMS Question", existing_name):
		existing_name = None
	if not existing_name and row.get("source_key"):
		existing_name = frappe.db.get_value("LMS Question", {"trivia_source_key": row.get("source_key")}, "name")
	if not existing_name and row.get("qcode"):
		existing_name = frappe.db.get_value("LMS Question", {"trivia_qcode": row.get("qcode")}, "name")

	doc = frappe.get_doc("LMS Question", existing_name) if existing_name else frappe.new_doc("LMS Question")
	is_new = doc.is_new()

	doc.type = "Choices"
	doc.marks = max(1, int(row.get("marks") or 1))
	doc.multiple = int(len(correct_letters) > 1)

	all_explained = True
	for idx in range(1, 11):
		if idx <= len(ordered_options):
			letter, text_val = ordered_options[idx - 1]
			is_corr = int(letter in correct_letters)
			exp_text = str(opt_explanations.get(letter) or opt_explanations.get(letter.lower()) or "").strip()
			if not exp_text and is_corr and general_exp:
				exp_text = general_exp
			if not exp_text:
				all_explained = False
			doc.set(f"option_{idx}", text_val)
			doc.set(f"is_correct_{idx}", is_corr)
			doc.set(f"explanation_{idx}", exp_text)
		else:
			doc.set(f"option_{idx}", "")
			doc.set(f"is_correct_{idx}", 0)
			doc.set(f"explanation_{idx}", "")

	texto_apoio = _existing_link("Trivia Supporting Text", row.get("texto_apoio"))
	is_approved = row.get("review_status") == "Approved" or row.get("editorial_status") in ("Approved", "Published")
	doc.trivia_status = "Ready" if (is_approved or all_explained) else "In Preparation"
	doc.trivia_source_type = row.get("source_type") or ("QAPI" if row.get("qcode") else "Manual")
	doc.trivia_qcode = row.get("qcode")
	doc.trivia_source_key = row.get("source_key")
	doc.trivia_texto_apoio = texto_apoio
	doc.trivia_banca = row.get("banca")
	doc.trivia_orgao = row.get("orgao")
	doc.trivia_cargo = row.get("cargo")
	doc.trivia_ano = row.get("ano") or None
	doc.trivia_materia = row.get("materia")
	doc.trivia_assunto = row.get("assunto")
	doc.trivia_subject_link = _existing_link("Trivia Subject", row.get("trivia_materia"))
	doc.trivia_topic_link = _existing_link("Trivia Topic", row.get("trivia_assunto"))
	doc.trivia_concurso = _existing_link("Trivia Contest", row.get("concurso"))
	doc.trivia_concurso_cargo = _existing_link("Trivia Contest Position", row.get("concurso_cargo"))
	doc.trivia_general_explanation = general_exp
	raw_ed = float(row.get("editorial_difficulty") or 0)
	doc.trivia_editorial_difficulty = round(raw_ed / 5.0, 2) if raw_ed > 1.0 else (raw_ed or None)
	raw_stars = float(row.get("ai_difficulty_stars") or 0)
	doc.trivia_ai_difficulty_stars = round(raw_stars / 5.0, 2) if raw_stars > 1.0 else raw_stars
	doc.trivia_ai_difficulty_label = row.get("ai_difficulty_label")
	doc.trivia_ai_difficulty_reason = row.get("ai_difficulty_reason")
	doc.trivia_ai_learning_objective = row.get("ai_learning_objective")
	doc.trivia_ai_topics = row.get("ai_topics")
	doc.trivia_ai_model = row.get("ai_model")
	doc.trivia_ai_enriched_at = row.get("ai_enriched_at")
	doc.trivia_detected_option_count = len(ordered_options)
	doc.trivia_source_url = row.get("source_url")
	doc.trivia_source_license = row.get("source_license")
	doc.trivia_source_attribution = row.get("source_attribution")
	doc.trivia_source_authors = row.get("source_authors")
	doc.trivia_sync_hash = row.get("sync_hash")
	doc.trivia_raw_payload = row.get("raw_payload")

	if frappe.db.table_exists("Trivia Question Syllabus Topic"):
		syl_rows = frappe.db.sql(
			"SELECT conteudo_programatico FROM `tabTrivia Question Syllabus Topic` WHERE parent=%s AND parenttype='Trivia Question'",
			(row.get("name"),),
			as_dict=True,
		)
		existing_syl = {r.conteudo_programatico for r in (doc.get("trivia_syllabus_topics") or []) if r.conteudo_programatico}
		for sr in syl_rows:
			syl_name = _existing_link("Trivia Syllabus Topic", sr.get("conteudo_programatico"))
			if syl_name and syl_name not in existing_syl:
				doc.append("trivia_syllabus_topics", {"conteudo_programatico": syl_name})
				existing_syl.add(syl_name)

	if frappe.db.table_exists("Trivia Knowledge Link"):
		kp_rows = frappe.db.sql(
			"SELECT knowledge_page FROM `tabTrivia Knowledge Link` WHERE parent=%s AND parenttype='Trivia Question'",
			(row.get("name"),),
			as_dict=True,
		)
		existing_kp = {r.knowledge_page for r in (doc.get("trivia_knowledge_pages") or []) if r.knowledge_page}
		for kr in kp_rows:
			kp_name = _existing_link("Trivia Knowledge Page", kr.get("knowledge_page"))
			if kp_name and kp_name not in existing_kp:
				doc.append("trivia_knowledge_pages", {"knowledge_page": kp_name})
				existing_kp.add(kp_name)

	doc.question = compose_lms_question_html(
		row.get("enunciado") or "",
		texto_apoio=texto_apoio,
		knowledge_rows=doc.get("trivia_knowledge_pages"),
	)

	if hasattr(doc, "flags") and doc.flags is not None:
		doc.flags.ignore_links = True

	if is_new:
		doc.insert(ignore_permissions=True)
		return "migrated"
	doc.save(ignore_permissions=True)
	return "updated"


def execute():
	cleanup_retired_metadata()
	if hasattr(frappe.db, "commit"):
		frappe.db.commit()

	if not frappe.db.table_exists("Trivia Question"):
		return {"migrated": 0, "updated": 0, "skipped": 0, "failed": 0}

	rows = frappe.db.sql("SELECT * FROM `tabTrivia Question`", as_dict=True)
	migrated = updated = skipped = failed = 0

	for idx, row in enumerate(rows, start=1):
		sp_name = f"trivia_q_mig_{idx}"
		has_sp = hasattr(frappe.db, "savepoint") and callable(frappe.db.savepoint)
		try:
			if has_sp:
				frappe.db.savepoint(sp_name)
			outcome = _migrate_single_row(row)
			if outcome == "migrated":
				migrated += 1
			elif outcome == "updated":
				updated += 1
			else:
				skipped += 1
		except Exception as exc:
			failed += 1
			if has_sp and hasattr(frappe.db, "rollback"):
				with contextlib.suppress(Exception):
					frappe.db.rollback(save_point=sp_name)
			if hasattr(frappe, "log_error") and callable(frappe.log_error):
				with contextlib.suppress(Exception):
					frappe.log_error(
						f"Row {row.get('name')} ({row.get('qcode')}): {type(exc).__name__}: {exc}",
						"Trivia Sync · LMS Question migration",
					)

	cleanup_retired_metadata()
	if hasattr(frappe.db, "commit"):
		frappe.db.commit()
	return {"migrated": migrated, "updated": updated, "skipped": skipped, "failed": failed}
