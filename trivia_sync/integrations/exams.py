import frappe


def build_lms_quiz_from_bank(
	quiz_name: str,
	count: int = 10,
	subject: str | None = None,
	topic: str | None = None,
	board: str | None = None,
	concurso_cargo: str | None = None,
	syllabus_topic: str | None = None,
	only_ready: bool = True,
	append_existing: bool = False,
	marks: int | None = None,
) -> dict:
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	requested = max(1, min(int(count or 10), 200))
	quiz = frappe.get_doc("LMS Quiz", quiz_name)
	quiz.check_permission("write")

	filters: dict = {"type": "Choices"}
	if only_ready:
		filters["trivia_status"] = "Ready"
	if subject:
		if frappe.db.exists("Trivia Subject", subject):
			filters["trivia_subject_link"] = subject
		else:
			filters["trivia_materia"] = ["like", f"%{subject}%"]
	if topic:
		if frappe.db.exists("Trivia Topic", topic):
			filters["trivia_topic_link"] = topic
		else:
			filters["trivia_assunto"] = ["like", f"%{topic}%"]
	if board:
		filters["trivia_banca"] = ["like", f"%{board}%"]
	if concurso_cargo:
		filters["trivia_concurso_cargo"] = concurso_cargo

	if syllabus_topic:
		linked = frappe.get_all(
			"Trivia Question Syllabus Topic",
			filters={"conteudo_programatico": syllabus_topic, "parenttype": "LMS Question"},
			pluck="parent",
		) or []
		if not linked:
			frappe.throw("No LMS questions are linked to the selected syllabus topic.")
		filters["name"] = ["in", linked]

	candidates = frappe.get_all(
		"LMS Question",
		filters=filters,
		fields=["name", "marks", "trivia_qcode", "trivia_source_key"],
		order_by="modified desc",
		limit_page_length=requested * 3,
	) or []

	existing_names = {
		row.question for row in (quiz.get("questions") or []) if getattr(row, "question", None)
	}
	if append_existing:
		available = [row for row in candidates if row.get("name") not in existing_names]
	else:
		available = candidates

	if len(available) < requested:
		frappe.throw(
			f"Requested {requested} questions, but only {len(available)} matched the selected filters."
		)

	selected = available[:requested]
	if not append_existing:
		quiz.set("questions", [])

	default_marks = max(1, int(marks)) if marks not in (None, "", 0) else None
	for row in selected:
		q_marks = default_marks or max(1, int(row.get("marks") or 1))
		quiz.append("questions", {"question": row["name"], "marks": q_marks, "type": "Choices"})

	quiz.save(ignore_permissions=True)
	return {
		"quiz": quiz.name,
		"added": len(selected),
		"total_questions": len(quiz.get("questions") or []),
	}
