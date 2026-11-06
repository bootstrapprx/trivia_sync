import hashlib
import json

import frappe


def sync_lms_question(source):
	options = json.loads(source.options or "{}")
	if len(options) < 2 or source.correct_option not in options:
		return "skipped"

	text = frappe.get_doc("Texto de Apoio", source.texto_apoio) if source.texto_apoio else None
	question_text = source.enunciado
	if text and text.conteudo:
		question_text = f"<p><strong>Texto de apoio</strong></p>{text.conteudo}<hr>{question_text}"
	fields = {
		"question": question_text,
		"type": "Choices",
		"marks": 1,
		"trivia_qcode": source.qcode,
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
	}
	for index, letter in enumerate("ABCDE", start=1):
		fields[f"option_{index}"] = options.get(letter, "")
		fields[f"is_correct_{index}"] = int(letter == source.correct_option)
		fields[f"explanation_{index}"] = source.explanation if letter == source.correct_option else ""

	sync_hash = hashlib.sha256(
		json.dumps(
			[source.sync_hash, text.sync_hash if text else None, source.ai_enrichment_hash],
			ensure_ascii=False,
		).encode("utf-8")
	).hexdigest()
	fields["trivia_sync_hash"] = sync_hash

	name = frappe.db.get_value("LMS Question", {"trivia_qcode": source.qcode}, "name")
	if name:
		question = frappe.get_doc("LMS Question", name)
		if question.trivia_sync_hash == sync_hash:
			return "skipped"
	else:
		question = frappe.new_doc("LMS Question")

	for field, value in fields.items():
		question.set(field, value)

	if question.is_new():
		question.insert(ignore_permissions=True)
		return "created"
	question.save(ignore_permissions=True)
	return "updated"
