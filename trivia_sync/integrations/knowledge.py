import hashlib
import json
import re
import unicodedata

import frappe


def slugify_concept(text: str) -> str:
	raw = unicodedata.normalize("NFKD", str(text or "").casefold())
	ascii_text = "".join(ch for ch in raw if not unicodedata.combining(ch))
	slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
	if not slug:
		slug = "concept-" + hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:10]
	return slug[:80]


def upsert_knowledge_page(
	title: str,
	summary: str = "",
	explanation: str = "",
	examples: str = "",
	exam_traps: str = "",
	parent_concept: str | None = None,
	trivia_subject: str | None = None,
	trivia_topic: str | None = None,
	origin: str = "AI",
	ai_model: str | None = None,
) -> dict:
	cleaned_title = str(title or "").strip()
	if not cleaned_title:
		frappe.throw("Knowledge page title is required.")
	slug = slugify_concept(cleaned_title)
	existing = frappe.db.get_value("Trivia Knowledge Page", {"slug": slug}, "name") or frappe.db.get_value(
		"Trivia Knowledge Page", slug, "name"
	)
	if existing:
		return {"name": existing, "slug": slug, "created": False}
	doc = frappe.new_doc("Trivia Knowledge Page")
	doc.title = cleaned_title
	doc.slug = slug
	doc.parent_concept = parent_concept if parent_concept and parent_concept != slug else None
	doc.trivia_subject = trivia_subject or None
	doc.trivia_topic = trivia_topic or None
	doc.summary = (summary or "").strip()
	doc.explanation = (explanation or summary or cleaned_title).strip()
	doc.examples = (examples or "").strip()
	doc.exam_traps = (exam_traps or "").strip()
	doc.status = "Draft"
	doc.origin = origin
	doc.ai_model = ai_model or None
	doc.insert(ignore_permissions=True)
	return {"name": doc.name, "slug": doc.slug, "created": True}


def _append_unique_knowledge_link(doc, fieldname: str, target_name: str) -> bool:
	if not target_name or target_name == getattr(doc, "name", None):
		return False
	existing = {
		getattr(row, "knowledge_page", None)
		for row in (getattr(doc, fieldname, None) or [])
		if getattr(row, "knowledge_page", None)
	}
	if target_name in existing:
		return False
	if hasattr(doc, "append"):
		doc.append(fieldname, {"knowledge_page": target_name})
		return True
	return False


def link_knowledge_concepts(question, concepts: list[dict], ai_model: str | None = None) -> dict:
	subject = getattr(question, "trivia_materia", None)
	topic = getattr(question, "trivia_assunto", None)
	created = []
	reused = []
	linked = []
	main_pages = []

	for concept in concepts or []:
		if not isinstance(concept, dict) or not (concept.get("title") or "").strip():
			continue
		main_res = upsert_knowledge_page(
			title=concept["title"],
			summary=concept.get("summary") or "",
			explanation=concept.get("explanation") or "",
			examples=concept.get("examples") or "",
			exam_traps=concept.get("exam_traps") or "",
			trivia_subject=subject,
			trivia_topic=topic,
			origin="AI",
			ai_model=ai_model,
		)
		main_name = main_res["name"]
		main_pages.append(main_name)
		(created if main_res["created"] else reused).append(main_name)
		if _append_unique_knowledge_link(question, "knowledge_pages", main_name):
			linked.append(main_name)

		sub_names = []
		for sub in concept.get("sub_concepts") or []:
			if not isinstance(sub, dict) or not (sub.get("title") or "").strip():
				continue
			sub_res = upsert_knowledge_page(
				title=sub["title"],
				summary=sub.get("summary") or "",
				explanation=sub.get("explanation") or "",
				examples=sub.get("examples") or "",
				exam_traps=sub.get("exam_traps") or "",
				parent_concept=main_name,
				trivia_subject=subject,
				trivia_topic=topic,
				origin="AI",
				ai_model=ai_model,
			)
			sub_name = sub_res["name"]
			sub_names.append(sub_name)
			(created if sub_res["created"] else reused).append(sub_name)

		if sub_names:
			try:
				main_doc = frappe.get_doc("Trivia Knowledge Page", main_name)
				changed = False
				for sub_name in sub_names:
					if _append_unique_knowledge_link(main_doc, "related_concepts", sub_name):
						changed = True
				if changed:
					main_doc.save(ignore_permissions=True)
			except Exception:
				pass

	# Cross-link multiple main concepts discovered for the same question
	if len(main_pages) > 1:
		for page_name in main_pages:
			try:
				doc = frappe.get_doc("Trivia Knowledge Page", page_name)
				changed = False
				for other in main_pages:
					if other != page_name and _append_unique_knowledge_link(doc, "related_concepts", other):
						changed = True
				if changed:
					doc.save(ignore_permissions=True)
			except Exception:
				pass

	return {
		"knowledge_pages_linked": linked,
		"knowledge_pages_created": list(dict.fromkeys(created)),
		"knowledge_pages_reused": list(dict.fromkeys(reused)),
	}


def set_knowledge_page_status(page_name: str, status: str) -> dict:
	if status not in ("Draft", "Published", "Archived"):
		frappe.throw("Invalid knowledge page status.")
	user_roles = set(frappe.get_roles(frappe.session.user))
	if status in ("Published", "Archived"):
		if not user_roles.intersection({"System Manager", "Trivia Reviewer", "Trivia Integrator"}):
			frappe.throw("Only reviewers or integrators can publish or archive knowledge pages.", frappe.PermissionError)
	else:
		if not user_roles.intersection({"System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"}):
			frappe.throw("You do not have permission to update this knowledge page.", frappe.PermissionError)
	doc = frappe.get_doc("Trivia Knowledge Page", page_name)
	doc.status = status
	now = frappe.utils.now_datetime()
	if status == "Published":
		doc.reviewed_by = frappe.session.user
		doc.reviewed_at = now
		doc.published_at = now
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "slug": doc.slug, "status": doc.status}


def get_question_knowledge_pages(question_name: str) -> list[dict]:
	rows = frappe.get_all(
		"Trivia Knowledge Link",
		filters={"parent": question_name, "parenttype": "Trivia Question", "parentfield": "knowledge_pages"},
		pluck="knowledge_page",
	) or []
	if not rows:
		return []
	pages = frappe.get_all(
		"Trivia Knowledge Page",
		filters={"name": ["in", rows]},
		fields=["name", "title", "slug", "status", "summary", "parent_concept"],
	) or []
	by_name = {page.get("name"): page for page in pages}
	return [by_name[name] for name in rows if name in by_name]


def get_knowledge_page_backlinks(page_name: str) -> dict:
	sub_concepts = frappe.get_all(
		"Trivia Knowledge Page",
		filters={"parent_concept": page_name},
		fields=["name", "title", "slug", "status", "summary"],
		order_by="title asc",
	) or []
	question_names = frappe.get_all(
		"Trivia Knowledge Link",
		filters={"knowledge_page": page_name, "parenttype": "Trivia Question", "parentfield": "knowledge_pages"},
		pluck="parent",
		limit_page_length=50,
	) or []
	questions = (
		frappe.get_all(
			"Trivia Question",
			filters={"name": ["in", question_names]},
			fields=["name", "qcode", "materia", "assunto", "editorial_status"],
		)
		if question_names
		else []
	)
	return {"sub_concepts": sub_concepts, "questions": questions}


def list_published_knowledge_pages(subject: str | None = None) -> list[dict]:
	filters = {"status": "Published"}
	if subject:
		filters["trivia_subject"] = subject
	pages = frappe.get_all(
		"Trivia Knowledge Page",
		filters=filters,
		fields=["name", "title", "slug", "summary", "parent_concept", "trivia_subject", "trivia_topic", "published_at"],
		order_by="title asc",
	) or []
	return pages


def get_published_knowledge_page(slug: str) -> dict:
	rows = frappe.get_all(
		"Trivia Knowledge Page",
		filters={"slug": slug, "status": "Published"},
		fields=[
			"name", "title", "slug", "summary", "explanation", "examples", "exam_traps",
			"parent_concept", "trivia_subject", "trivia_topic", "published_at",
		],
		page_length=1,
	)
	if not rows:
		frappe.throw("Knowledge page not found.", frappe.DoesNotExistError)
	page = dict(rows[0])

	# Build ancestor breadcrumb chain (guard against accidental cycles)
	breadcrumbs = []
	cursor = page.get("parent_concept")
	visited = {page["name"]}
	while cursor and cursor not in visited:
		visited.add(cursor)
		parent_rows = frappe.get_all(
			"Trivia Knowledge Page",
			filters={"name": cursor, "status": "Published"},
			fields=["name", "title", "slug", "parent_concept"],
			page_length=1,
		)
		if not parent_rows:
			break
		breadcrumbs.insert(0, parent_rows[0])
		cursor = parent_rows[0].get("parent_concept")

	sub_concepts = frappe.get_all(
		"Trivia Knowledge Page",
		filters={"parent_concept": page["name"], "status": "Published"},
		fields=["name", "title", "slug", "summary"],
		order_by="title asc",
	) or []

	rel_names = frappe.get_all(
		"Trivia Knowledge Link",
		filters={"parent": page["name"], "parenttype": "Trivia Knowledge Page", "parentfield": "related_concepts"},
		pluck="knowledge_page",
	) or []
	related = (
		frappe.get_all(
			"Trivia Knowledge Page",
			filters={"name": ["in", rel_names], "status": "Published"},
			fields=["name", "title", "slug", "summary"],
			order_by="title asc",
		)
		if rel_names
		else []
	)

	question_count = frappe.db.count(
		"Trivia Knowledge Link",
		filters={"knowledge_page": page["name"], "parenttype": "Trivia Question", "parentfield": "knowledge_pages"},
	)

	page["breadcrumbs"] = breadcrumbs
	page["sub_concepts"] = sub_concepts
	page["related_concepts"] = related
	page["question_count"] = int(question_count or 0)
	return page


FLOW_KB_TITLE = "Trivia Knowledge"
FLOW_SOURCE_TITLE = "Trivia Knowledge Pages"
FLOW_SKILL_TITLE = "Trivia Knowledge & Concepts"
FLOW_SKILL_INSTRUCTIONS = """Você é um assistente especialista em concursos públicos no Trivia Sync.

REGRAS FUNDAMENTAIS:
1. USE SEMPRE TODO O SEU CONHECIMENTO GERAL DE DOMÍNIO para responder, analisar questões, explicar conceitos, classificar dificuldade e criar novos conteúdos. NUNCA se restrinja apenas ao conhecimento local nem diga que "não encontrou na base local" quando você já sabe a resposta.
2. A base local (`Trivia Knowledge` / DocType `Trivia Knowledge Page`) é MATERIAL COMPLEMENTAR de estudo, consulta e referência vinculada às questões — use-a para enriquecer respostas dentro de uma questão e citar links `/conhecimento?slug=<slug>` das páginas já publicadas, sem substituir seu próprio conhecimento.
3. Ao auxiliar na revisão de uma `Trivia Question`, nunca entregue o gabarito nas explicações das alternativas incorretas; se houver conceitos pré-requisitos em `knowledge_pages`, mencione-os como apoio de estudo.
4. Para enriquecer questões individualmente ou em lote no Trivia Sync, prefira as ações do app (`trivia_sync.api.enrich_question_all`, `trivia_sync.api.run_ai_batch_now` ou `trivia_sync.api.enqueue_ai_batch`).
"""


def setup_flow_knowledge_and_skill() -> dict:
	frappe.only_for("System Manager")
	warnings = []
	kb_name = None
	source_name = None
	skill_name = None

	if frappe.db.exists("DocType", "Flow Knowledge Base") and frappe.db.exists("DocType", "Flow Knowledge Source"):
		try:
			kb_name = frappe.db.get_value("Flow Knowledge Base", {"title": FLOW_KB_TITLE}, "name")
			if not kb_name:
				kb = frappe.new_doc("Flow Knowledge Base")
				kb.title = FLOW_KB_TITLE
				kb.description = "Conceitos, sub-conceitos, exemplos e pegadinhas de concursos públicos do Trivia Sync."
				kb.enabled = 1
				kb.insert(ignore_permissions=True)
				kb_name = kb.name
			source_name = frappe.db.get_value(
				"Flow Knowledge Source",
				{"knowledge_base": kb_name, "reference_doctype": "Trivia Knowledge Page"},
				"name",
			)
			if not source_name:
				src = frappe.new_doc("Flow Knowledge Source")
				src.title = FLOW_SOURCE_TITLE
				src.knowledge_base = kb_name
				src.source_type = "DocType"
				src.reference_doctype = "Trivia Knowledge Page"
				src.content_fields = "title,summary,explanation,examples,exam_traps"
				src.filters = json.dumps({"status": "Published"})
				src.auto_sync = 1
				src.insert(ignore_permissions=True)
				source_name = src.name
		except Exception as exc:
			warnings.append(f"Flow Knowledge Base skipped: {exc}")
	else:
		warnings.append("Frappe Flow Knowledge Base DocTypes are not installed on this site.")

	if frappe.db.exists("DocType", "Flow Skill"):
		try:
			skill_name = frappe.db.get_value("Flow Skill", {"title": FLOW_SKILL_TITLE}, "name")
			if skill_name:
				skill = frappe.get_doc("Flow Skill", skill_name)
				skill.description = "Consulta e cita páginas de conhecimento (conceitos, sub-conceitos, exemplos e pegadinhas) do Trivia Sync."
				skill.instructions = FLOW_SKILL_INSTRUCTIONS
				skill.enabled = 1
				skill.user_invocable = 1
				skill.save(ignore_permissions=True)
			else:
				skill = frappe.new_doc("Flow Skill")
				skill.title = FLOW_SKILL_TITLE
				skill.description = "Consulta e cita páginas de conhecimento (conceitos, sub-conceitos, exemplos e pegadinhas) do Trivia Sync."
				skill.instructions = FLOW_SKILL_INSTRUCTIONS
				skill.enabled = 1
				skill.user_invocable = 1
				skill.insert(ignore_permissions=True)
				skill_name = skill.name
		except Exception as exc:
			warnings.append(f"Flow Skill skipped: {exc}")
	else:
		warnings.append("Frappe Flow Skill DocType is not installed on this site.")

	return {
		"ok": bool(kb_name or skill_name),
		"knowledge_base": kb_name,
		"knowledge_source": source_name,
		"skill": skill_name,
		"warnings": warnings,
	}
