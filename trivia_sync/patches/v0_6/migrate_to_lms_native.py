import json

import frappe


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


def _cleanup_retired_doctypes():
	for retired_dt in (
		"Trivia Question",
		"Trivia Exam",
		"Trivia Exam Block",
		"Trivia Exam Block Syllabus Topic",
		"Trivia Exam Question",
		"Trivia Exam Version",
		"Trivia Prova",
		"Prova",
		"Trivia Lesson Recipe",
	):
		if frappe.db.exists("DocType", retired_dt):
			try:
				frappe.delete_doc("DocType", retired_dt, ignore_permissions=True, force=True)
			except Exception:
				pass


def execute():
	# Clean up obsolete Custom Fields that pointed to retired Trivia Question
	for obsolete_cf in (
		"LMS Question-trivia_question",
		"LMS Question-trivia_projection_key",
		"LMS Question-trivia_redistribution_reference",
		"LMS Question-trivia_redistribution_status",
		"LMS Question-trivia_allow_variable_options",
		"LMS Question-trivia_exception_reason",
	):
		if frappe.db.exists("Custom Field", obsolete_cf):
			frappe.delete_doc("Custom Field", obsolete_cf, ignore_permissions=True, force=True)

	if not frappe.db.table_exists("Trivia Question"):
		_cleanup_retired_doctypes()
		frappe.db.commit()
		return {"migrated": 0, "updated": 0, "skipped": 0}

	rows = frappe.db.sql("SELECT * FROM `tabTrivia Question`", as_dict=True)
	migrated = updated = skipped = 0

	for row in rows:
		options = _parse_dict(row.get("options"))
		ordered_options = [(str(k).upper(), v) for k, v in sorted(options.items()) if v not in (None, "")]
		if len(ordered_options) < 2 or not (row.get("enunciado") or "").strip():
			skipped += 1
			continue

		correct_letters = {str(x).upper() for x in _parse_list(row.get("correct_options")) if x}
		if not correct_letters and row.get("correct_option"):
			correct_letters = {str(row.get("correct_option")).upper()}
		if not correct_letters:
			skipped += 1
			continue

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
		doc.question = row.get("enunciado")
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

		is_approved = row.get("review_status") == "Approved" or row.get("editorial_status") in ("Approved", "Published")
		doc.trivia_status = "Ready" if (is_approved or all_explained) else "In Preparation"
		doc.trivia_source_type = row.get("source_type") or ("QAPI" if row.get("qcode") else "Manual")
		doc.trivia_qcode = row.get("qcode")
		doc.trivia_source_key = row.get("source_key")
		doc.trivia_texto_apoio = row.get("texto_apoio")
		doc.trivia_banca = row.get("banca")
		doc.trivia_orgao = row.get("orgao")
		doc.trivia_cargo = row.get("cargo")
		doc.trivia_ano = row.get("ano") or None
		doc.trivia_materia = row.get("materia")
		doc.trivia_assunto = row.get("assunto")
		doc.trivia_subject_link = row.get("trivia_materia")
		doc.trivia_topic_link = row.get("trivia_assunto")
		doc.trivia_concurso = row.get("concurso")
		doc.trivia_concurso_cargo = row.get("concurso_cargo")
		doc.trivia_general_explanation = general_exp
		doc.trivia_editorial_difficulty = row.get("editorial_difficulty")
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
				if sr.conteudo_programatico and sr.conteudo_programatico not in existing_syl:
					doc.append("trivia_syllabus_topics", {"conteudo_programatico": sr.conteudo_programatico})

		if frappe.db.table_exists("Trivia Knowledge Link"):
			kp_rows = frappe.db.sql(
				"SELECT knowledge_page FROM `tabTrivia Knowledge Link` WHERE parent=%s AND parenttype='Trivia Question'",
				(row.get("name"),),
				as_dict=True,
			)
			existing_kp = {r.knowledge_page for r in (doc.get("trivia_knowledge_pages") or []) if r.knowledge_page}
			for kr in kp_rows:
				if kr.knowledge_page and kr.knowledge_page not in existing_kp:
					doc.append("trivia_knowledge_pages", {"knowledge_page": kr.knowledge_page})

		if is_new:
			doc.insert(ignore_permissions=True)
			migrated += 1
		else:
			doc.save(ignore_permissions=True)
			updated += 1

	_cleanup_retired_doctypes()
	frappe.db.commit()
	return {"migrated": migrated, "updated": updated, "skipped": skipped}
