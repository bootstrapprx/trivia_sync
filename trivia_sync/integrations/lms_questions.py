import hashlib
import json

import frappe
from trivia_sync.integrations.editorial import question_options, validate_projection_eligibility


def _projection_fields(source):
	options = validate_projection_eligibility(source)
	_, correct_options = question_options(source)
	text = frappe.get_doc("Trivia Supporting Text", source.texto_apoio) if source.texto_apoio else None
	question_text = source.enunciado
	if text and text.conteudo:
		question_text = f"<p><strong>Texto de apoio</strong></p>{text.conteudo}<hr>{question_text}"
	ordered_options = sorted(options.items())
	correct_indexes = {index for index, (letter, _) in enumerate(ordered_options, start=1) if letter in correct_options}
	fields = {
		"question": question_text,
		"type": "Choices",
		"marks": int(source.marks if getattr(source, "marks", None) not in (None, "") else 1),
		"multiple": int(len(correct_options) > 1),
		"trivia_qcode": source.qcode,
		"trivia_source_key": source.source_key,
		"trivia_question": source.name,
		"trivia_banca": source.banca,
		"trivia_orgao": source.orgao,
		"trivia_cargo": source.cargo,
		"trivia_ano": source.ano or None,
		"trivia_materia": source.materia,
		"trivia_assunto": source.assunto,
		"trivia_source_url": source.source_url,
		"trivia_texto_apoio": source.texto_apoio,
		"trivia_ai_difficulty_stars": source.ai_difficulty_stars,
		"trivia_ai_difficulty_label": source.ai_difficulty_label,
		"trivia_ai_difficulty_reason": source.ai_difficulty_reason,
		"trivia_ai_learning_objective": source.ai_learning_objective,
		"trivia_ai_topics": source.ai_topics,
		"trivia_ai_model": source.ai_model,
		"trivia_ai_enriched_at": source.ai_enriched_at,
		"trivia_editorial_difficulty": getattr(source, "editorial_difficulty", None),
		"trivia_source_license": source.source_license,
		"trivia_source_attribution": source.source_attribution,
		"trivia_source_authors": getattr(source, "source_authors", None),
		"trivia_redistribution_reference": source.redistribution_reference,
		"trivia_redistribution_status": source.redistribution_status,
		"trivia_detected_option_count": len(ordered_options),
		"trivia_allow_variable_options": int(bool(getattr(source, "allow_variable_options", 0))),
		"trivia_exception_reason": getattr(source, "exception_reason", None),
	}
	for index in range(1, 11):
		letter, value = ordered_options[index - 1] if index <= len(ordered_options) else (None, "")
		fields[f"option_{index}"] = value
		fields[f"is_correct_{index}"] = int(index in correct_indexes)
		fields[f"explanation_{index}"] = source.explanation if index in correct_indexes else ""
	sync_hash = hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
	fields["trivia_sync_hash"] = sync_hash
	fields["trivia_projection_key"] = hashlib.sha256(f"{source.source_key}:{sync_hash}".encode("utf-8")).hexdigest()
	return fields


def validate_lms_question(question):
	if not getattr(question, "trivia_question", None):
		return
	source = frappe.get_doc("Trivia Question", question.trivia_question)
	for field, expected in _projection_fields(source).items():
		if question.get(field) != expected:
			frappe.throw("Trivia-linked LMS questions must be changed in Trivia Sync and projected again.")


def sync_lms_question(source):
	fields = _projection_fields(source)
	sync_hash = fields["trivia_sync_hash"]
	projection_key = fields["trivia_projection_key"]
	name = frappe.db.get_value("LMS Question", {"trivia_projection_key": projection_key}, "name")
	if not name:
		name = frappe.db.get_value("LMS Question", {"trivia_source_key": source.source_key}, "name")
	if not name and source.qcode:
		name = frappe.db.get_value("LMS Question", {"trivia_qcode": source.qcode}, "name")
	if name:
		question = frappe.get_doc("LMS Question", name)
		if question.trivia_source_key and question.trivia_source_key != source.source_key:
			frappe.throw("The legacy LMS question code points to a different source identity.")
		if question.trivia_sync_hash == sync_hash and question.trivia_source_key == source.source_key:
			source.lms_question = question.name
			source.editorial_status = "Published"
			source.projection_status = "Projected"
			source.projection_hash = sync_hash
			source.projected_at = frappe.utils.now_datetime()
			source.projection_error = None
			source.save(ignore_permissions=True)
			return question.name
		if question.trivia_sync_hash != sync_hash and frappe.db.exists("LMS Quiz Question", {"question": question.name}):
			question = frappe.new_doc("LMS Question")
	else:
		question = frappe.new_doc("LMS Question")

	for field, value in fields.items():
		question.set(field, value)

	if question.is_new():
		question.insert(ignore_permissions=True)
	else:
		question.save(ignore_permissions=True)
	source.lms_question = question.name
	source.editorial_status = "Published"
	source.projection_status = "Projected"
	source.projection_hash = sync_hash
	source.projected_at = frappe.utils.now_datetime()
	source.projection_error = None
	source.save(ignore_permissions=True)
	return question.name
