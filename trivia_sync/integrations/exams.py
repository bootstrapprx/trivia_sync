import hashlib
import json
import re

import frappe


def _select_pool(pool, blocks):
	selected = []
	used = set()
	for block in blocks:
		count = int(block.get("count") or 0)
		topics = set(block.get("topics") or [])
		candidates = [row for row in pool if row["name"] not in used and (not topics or topics.intersection(row.get("topics", set())))]
		candidates.sort(key=lambda row: row.get("source_key") or row["name"])
		if len(candidates) < count:
			label = block.get("name") or "prova"
			criteria = ", ".join(sorted(topics)) if topics else "pool elegível"
			raise ValueError(f"{label}: necessárias {count}, elegíveis {len(candidates)} para {criteria}.")
		for row in candidates[:count]:
			selected.append((block.get("name"), row))
			used.add(row["name"])
	return selected


def _eligible_pool(prova):
	rows = frappe.get_all(
		"Trivia Question",
		filters={
			"concurso_cargo": prova.concurso_cargo,
			"review_status": "Approved",
			"redistribution_status": "Approved",
		},
		fields=["name", "source_key", "content_hash", "projection_hash", "lms_question", "source_license", "redistribution_reference"],
		order_by="source_key asc",
	)
	links = frappe.get_all(
		"Trivia Question Syllabus Topic",
		filters={"parent": ["in", [row.get("name") for row in rows]]},
		fields=["parent", "conteudo_programatico"],
	) if rows else []
	topics = {}
	for link in links:
		topics.setdefault(link.get("parent"), set()).add(link.get("conteudo_programatico"))
	return [
		{**row, "topics": topics.get(row.get("name"), set())}
		for row in rows
		if row.get("lms_question") and (row.get("source_license") or row.get("redistribution_reference"))
	]


def _requested_blocks(prova):
	if prova.exam_blocks:
		blocks = []
		for row in prova.exam_blocks:
			blocks.append({
				"name": row.titulo or row.name,
				"count": int(row.question_count or 0),
				"topics": {topic.conteudo_programatico for topic in row.conteudos_programaticos if topic.conteudo_programatico},
				"exam_block": row.name,
			})
		if not any(block["count"] for block in blocks):
			frappe.throw("Defina a quantidade de questões em cada bloco da prova.")
		if prova.requested_questions and sum(block["count"] for block in blocks) != int(prova.requested_questions):
			frappe.throw("A soma das questões dos blocos deve corresponder à quantidade solicitada.")
		return blocks
	if int(prova.requested_questions or 0) < 1:
		frappe.throw("Defina a quantidade de questões solicitadas.")
	return [{"name": prova.titulo or prova.name, "count": int(prova.requested_questions), "topics": set(), "exam_block": None}]


def _blueprint_hash(selected):
	content = [
		(block, row["name"], row.get("source_key"), row.get("content_hash"), row.get("projection_hash"), marks)
		for block, row, marks in selected
	]
	return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def build_simulado(prova_name):
	prova = frappe.get_doc("Prova", prova_name)
	if prova.status in ("Superseded", "Archived"):
		frappe.throw("Provas substituídas ou arquivadas não podem gerar um novo simulado.")
	if not prova.concurso_cargo or not prova.lms_course or not prova.lms_lesson:
		frappe.throw("Vincule cargo do concurso, curso e aula LMS antes de montar o simulado.")
	cargo = frappe.get_doc("Concurso Cargo", prova.concurso_cargo)
	if cargo.lms_course != prova.lms_course or cargo.concurso != prova.concurso:
		frappe.throw("O curso e o concurso da prova devem corresponder ao cargo vinculado.")
	lesson = frappe.get_doc("Course Lesson", prova.lms_lesson)
	if lesson.course != prova.lms_course:
		frappe.throw("A aula LMS deve pertencer ao curso vinculado ao cargo.")
	lesson.check_permission("write")
	blocks = _requested_blocks(prova)
	try:
		selected = _select_pool(_eligible_pool(prova), blocks)
	except ValueError as exc:
		frappe.throw(str(exc))
	selected_rows = []
	for block_name, question in selected:
		block = next((row for row in prova.exam_blocks if row.name == block_name), None) if block_name else None
		marks = next((row.marks for row in prova.exam_questions if row.question == question["name"] and row.marks), None)
		selected_rows.append((block_name, question, marks or (block.marks if block and block.marks else 1)))
	digest = _blueprint_hash(selected_rows)
	if prova.lms_quiz and prova.blueprint_hash == digest and int(prova.exam_version or 0):
		return {"quiz": prova.lms_quiz, "version": int(prova.exam_version), "questions": len(selected), "reused": True}

	version = int(prova.exam_version or 0) + 1
	quiz = frappe.new_doc("LMS Quiz")
	quiz.title = f"Simulado {prova.name} v{version}"
	quiz.course = prova.lms_course
	quiz.lesson = prova.lms_lesson
	quiz.show_answers = 0
	for _, question, marks in selected_rows:
		quiz.append("questions", {"question": question["lms_question"], "marks": marks, "type": "Choices"})
	quiz.insert(ignore_permissions=True)

	prova.set("exam_questions", [])
	for block_name, question, marks in selected_rows:
		block = next((item for item in prova.exam_blocks if item.name == block_name), None) if block_name else None
		prova.append("exam_questions", {
			"question": question["name"], "exam_block": block.name if block else None,
			"ordem": len(prova.exam_questions) + 1, "marks": marks,
		})
	prova.append("exam_versions", {"version": version, "quiz": quiz.name, "status": "Ready"})
	prova.exam_version = version
	prova.blueprint_hash = digest
	prova.lms_quiz = quiz.name
	prova.status = "Ready"
	prova.save(ignore_permissions=True)
	return {"quiz": quiz.name, "version": version, "questions": len(selected), "reused": False}


def _rewrite_lesson(lesson, new_quiz, old_quizzes):
	old_quizzes = {name for name in old_quizzes if name}
	if lesson.content:
		try:
			content = frappe.parse_json(lesson.content)
		except (TypeError, ValueError):
			frappe.throw("O conteúdo da aula não é um documento EditorJS válido; não foi alterado.")
		if not isinstance(content, dict) or not isinstance(content.get("blocks"), list):
			frappe.throw("O conteúdo da aula não contém blocos EditorJS; não foi alterado.")
		blocks = [
			block for block in content["blocks"]
			if not (block.get("type") == "quiz" and (block.get("data") or {}).get("quiz") in old_quizzes)
		]
		if new_quiz and not any(block.get("type") == "quiz" and (block.get("data") or {}).get("quiz") == new_quiz for block in blocks):
			blocks.append({"id": frappe.generate_hash(length=10), "type": "quiz", "data": {"quiz": new_quiz}})
		content["blocks"] = blocks
		lesson.content = json.dumps(content, ensure_ascii=False)
	else:
		body = lesson.body or ""
		for old in old_quizzes:
			body = re.sub(r"\{\{\s*Quiz\(\s*(['\"])" + re.escape(old) + r"\1\s*\)\s*\}\}", "", body)
		macro = "{{ Quiz('" + new_quiz + "') }}" if new_quiz else ""
		if new_quiz and macro not in body:
			body = f"{body.rstrip()}\n\n{macro}".lstrip()
		lesson.body = body
	lesson.save(ignore_permissions=True)


def publish_prova(prova_name, lesson_name=None):
	prova = frappe.get_doc("Prova", prova_name)
	if prova.status not in ("Ready", "Published") or not prova.lms_quiz:
		frappe.throw("Monte e valide o simulado antes de publicar.")
	lesson_name = lesson_name or prova.lms_lesson
	if not lesson_name:
		frappe.throw("Informe uma aula LMS para publicar a prova.")
	lesson = frappe.get_doc("Course Lesson", lesson_name)
	if lesson.course != prova.lms_course:
		frappe.throw("A aula de destino precisa pertencer ao curso do cargo.")
	lesson.check_permission("write")
	version_row = next((row for row in prova.exam_versions if row.version == prova.exam_version), None)
	if not version_row:
		frappe.throw("A versão atual do simulado não foi registrada.")
	if version_row.status == "Published" and version_row.lesson == lesson_name:
		return {"quiz": prova.lms_quiz, "status": "Published", "reused": True}
	old_quizzes = []
	for row in prova.exam_versions:
		if row.status != "Published":
			continue
		if row.version == prova.exam_version:
			if row.lesson and row.lesson != lesson_name:
				old_lesson = frappe.get_doc("Course Lesson", row.lesson)
				old_lesson.check_permission("write")
				_rewrite_lesson(old_lesson, "", [row.quiz])
				row.lesson = lesson_name
			continue
		old_quizzes.append(row.quiz)
		if row.lesson and row.lesson != lesson_name:
			old_lesson = frappe.get_doc("Course Lesson", row.lesson)
			old_lesson.check_permission("write")
			_rewrite_lesson(old_lesson, "", [row.quiz])
		row.status = "Superseded"
	version_row.lesson = lesson_name
	version_row.status = "Published"
	version_row.published_at = frappe.utils.now_datetime()
	_rewrite_lesson(lesson, prova.lms_quiz, old_quizzes)
	prova.lms_lesson = lesson_name
	prova.status = "Published"
	prova.save(ignore_permissions=True)
	return {"quiz": prova.lms_quiz, "status": "Published", "reused": False}
