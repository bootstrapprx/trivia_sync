import hashlib
import json
import re
import unicodedata

import frappe


def _catalog_get_value(doctype, filters, field):
	return frappe.db.get_value(doctype, filters, field)


def _catalog_get_all(doctype, filters, fields):
	return frappe.get_all(doctype, filters=filters, fields=fields)


def _catalog_set_value(doctype, name, field, value):
	frappe.db.set_value(doctype, name, field, value)


def normalize_name(value):
	value = unicodedata.normalize("NFKD", str(value or "").casefold())
	value = "".join(char for char in value if not unicodedata.combining(char))
	return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", value)).strip()


def resolve_catalog(doctype, external_id=None, name=None):
	if external_id:
		for field in ("source_id", "qapi_id"):
			match = _catalog_get_value(doctype, {field: str(external_id)}, "name")
			if match:
				return {"status": "resolved", "name": match, "method": "external_id"}
	if not name:
		return {"status": "unmatched", "name": None, "method": None}
	meta = frappe.get_meta(doctype)
	fields = ["name"] + [field for field in ("nome", "titulo") if meta.has_field(field)]
	rows = _catalog_get_all(doctype, {}, fields)
	needle = normalize_name(name)
	matches = [row.get("name") for row in rows if needle and needle in {normalize_name(row.get("nome")), normalize_name(row.get("titulo"))}]
	if len(matches) == 1:
		return {"status": "resolved", "name": matches[0], "method": "unique_name"}
	return {"status": "ambiguous" if matches else "unmatched", "name": None, "method": None}


LMS_QUESTION_CLASSIFICATION = (
	("materia", "trivia_materia", "Trivia Subject", "trivia_subject_link"),
	("assunto", "trivia_assunto", "Trivia Topic", "trivia_topic_link"),
	("concurso", "trivia_concurso", "Trivia Contest", "trivia_concurso"),
	("concurso_cargo", "trivia_concurso_cargo", "Trivia Contest Position", "trivia_concurso_cargo"),
)


def reconcile_question_classification(question):
	raw_str = getattr(question, "trivia_raw_payload", None) or getattr(question, "raw_payload", None) or "{}"
	try:
		raw = json.loads(raw_str)
	except (TypeError, ValueError):
		raw = {}
	results = {}
	for raw_key, text_attr, doctype, link_field in LMS_QUESTION_CLASSIFICATION:
		value = raw.get(raw_key) or raw.get(f"{raw_key}Id") or raw.get(f"{raw_key}_id")
		external_id = value.get("id") or value.get("_id") or value.get("codigo") if isinstance(value, dict) else value
		name = getattr(question, text_attr, "") if text_attr != link_field else ""
		resolution = resolve_catalog(doctype, external_id, name)
		if resolution["name"] and not getattr(question, link_field, None):
			setattr(question, link_field, resolution["name"])
		results[raw_key] = resolution
	return results


def _flatten(rows, parent_path="", depth=0):
	occurrences = {}
	for position, row in enumerate(rows or []):
		if not isinstance(row, dict):
			continue
		external_id = str(row.get("id") or row.get("_id") or row.get("codigo") or "").strip()
		title = str(row.get("titulo") or row.get("title") or row.get("nome") or row.get("name") or "").strip()
		if external_id:
			segment = f"id:{external_id}"
		else:
			base = normalize_name(title)
			occurrences[base] = occurrences.get(base, 0) + 1
			segment = f"name:{base}" if occurrences[base] == 1 else f"name:{base}:{occurrences[base]}"
		path = "/".join(filter(None, [parent_path, segment]))
		yield row, path, depth, position
		children = row.get("children") or row.get("filhos") or row.get("items") or []
		yield from _flatten(children, path, depth + 1)


def sync_syllabus_tree(concurso_cargo, rows, source_version):
	seen = set()
	created = updated = unchanged = 0
	parent_names = {}
	for row, path, depth, position in _flatten(rows):
		seen.add(path)
		content = str(row.get("texto") or row.get("descricao") or row.get("conteudo") or row.get("titulo") or row.get("title") or "")
		fingerprint = json.dumps(
			{
				"title": row.get("titulo") or row.get("title") or row.get("nome") or row.get("name") or content,
				"content": content,
				"order": row.get("ordem") or row.get("order") or position,
				"group": bool(row.get("children") or row.get("filhos") or row.get("items")),
			},
			ensure_ascii=False,
			sort_keys=True,
		)
		digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
		filters = {"concurso_cargo": concurso_cargo, "source_path": path}
		name = _catalog_get_value("Trivia Syllabus Topic", filters, "name")
		if name:
			doc = frappe.get_doc("Trivia Syllabus Topic", name)
			if doc.source_hash == digest and doc.source_version == source_version and not doc.is_obsolete:
				unchanged += 1
				parent_names[path] = name
				continue
		else:
			doc = frappe.new_doc("Trivia Syllabus Topic")
			doc.qapi_id = hashlib.sha256(f"{concurso_cargo}:{path}".encode()).hexdigest()[:24]
			doc.source_type = "QAPI"
			doc.source_id = f"{concurso_cargo}:{row.get('id') or row.get('_id') or row.get('codigo') or path}"
			doc.source_key = f"qapi:syllabus:{concurso_cargo}:{path}"
			created += 1
		if name:
			updated += 1
		doc.titulo = str(row.get("titulo") or row.get("title") or row.get("nome") or row.get("name") or content)
		doc.source_text = content
		doc.source_path = path
		doc.source_version = source_version
		doc.source_hash = digest
		doc.concurso_cargo = concurso_cargo
		doc.parent_conteudo = parent_names.get("/".join(path.split("/")[:-1])) if "/" in path else None
		doc.nivel = depth
		doc.ordem = int(row.get("ordem") or row.get("order") or position)
		doc.is_group = int(bool(row.get("children") or row.get("filhos") or row.get("items")))
		doc.is_obsolete = 0
		if name:
			doc.save(ignore_permissions=True)
		else:
			doc.insert(ignore_permissions=True)
		parent_names[path] = doc.name
	obsolete = 0
	for doc in _catalog_get_all("Trivia Syllabus Topic", {"concurso_cargo": concurso_cargo, "is_obsolete": 0}, ["name", "source_path"]):
		if doc.get("source_path") not in seen:
			_catalog_set_value("Trivia Syllabus Topic", doc.get("name"), "is_obsolete", 1)
			obsolete += 1
	return {"created": created, "updated": updated, "unchanged": unchanged, "obsolete": obsolete, "deleted": 0}


def question_coverage(concurso_cargo):
	questions = frappe.get_all(
		"LMS Question",
		filters={"trivia_concurso_cargo": concurso_cargo},
		fields=["trivia_subject_link", "trivia_topic_link", "trivia_materia", "trivia_assunto", "trivia_status", "trivia_source_type"],
	)
	coverage = {key: {} for key in ("subject", "topic", "review", "license", "source")}
	for question in questions:
		status = question.get("trivia_status") or "In Preparation"
		review_key = "Ready" if status == "Ready" else "Pending"
		for bucket, value in (
			("subject", question.get("trivia_subject_link") or question.get("trivia_materia")),
			("topic", question.get("trivia_topic_link") or question.get("trivia_assunto")),
			("review", review_key),
			("source", question.get("trivia_source_type") or "LMS"),
		):
			key = value or "Unclassified"
			coverage[bucket][key] = coverage[bucket].get(key, 0) + 1
	eligible = sum(1 for q in questions if q.get("trivia_status") == "Ready")
	return {"total": len(questions), "eligible": eligible, **coverage}


def resolve_resource_links(doctype, data):
	try:
		raw = json.loads(data.get("raw_payload") or "{}")
	except (TypeError, ValueError):
		raw = {}
	links = {
		"Trivia Syllabus Topic": {"disciplina": "Trivia Discipline", "parent_conteudo": "Trivia Syllabus Topic", "concurso_cargo": "Trivia Contest Position"},
		"Trivia Discipline": {"concurso": "Trivia Contest"},
		"Flashcard": {"conteudo": "Trivia Syllabus Topic"},
	}.get(doctype, {})
	for field, target in links.items():
		value = raw.get(field) or raw.get(f"{field}Id") or raw.get(f"{field}_id") or data.get(field)
		external_id = (value.get("id") or value.get("_id") or value.get("codigo")) if isinstance(value, dict) else value
		name = value.get("nome") or value.get("name") or value.get("titulo") if isinstance(value, dict) else value
		resolved = resolve_catalog(target, external_id, name)
		data[field] = resolved["name"]
	return data


def resolve_or_create_catalog(doctype, name, extra_fields=None):
	cleaned = str(name or "").strip()
	if not cleaned:
		return None
	resolution = resolve_catalog(doctype, name=cleaned)
	if resolution["status"] == "resolved":
		return resolution["name"]
	needle = normalize_name(cleaned)
	if not needle:
		return None
	if resolution["status"] == "ambiguous":
		meta = frappe.get_meta(doctype)
		fields = ["name"] + [field for field in ("nome", "titulo") if meta.has_field(field)]
		rows = _catalog_get_all(doctype, {}, fields)
		for row in rows:
			if needle in {normalize_name(row.get("nome")), normalize_name(row.get("titulo"))}:
				return row.get("name")
	slug = needle.replace(" ", "-")[:80]
	existing_by_key = _catalog_get_value(doctype, {"source_key": f"manual:{slug}"}, "name")
	if existing_by_key:
		return existing_by_key
	doc = frappe.new_doc(doctype)
	doc.source_type = "Manual"
	doc.source_id = slug
	doc.source_key = f"manual:{slug}"
	doc.nome = cleaned
	for field, value in (extra_fields or {}).items():
		if value not in (None, ""):
			setattr(doc, field, value)
	doc.insert(ignore_permissions=True)
	return doc.name


def candidate_syllabus_topics(concurso_cargo=None, limit=60):
	filters = {"is_obsolete": 0}
	if concurso_cargo:
		filters["concurso_cargo"] = concurso_cargo
	rows = frappe.get_all(
		"Trivia Syllabus Topic",
		filters=filters,
		fields=["name", "titulo", "source_path", "concurso_cargo"],
		order_by="ordem asc",
		limit_page_length=limit,
	)
	return rows or []


def match_syllabus_topics_by_names(topics, concurso_cargo=None):
	needles = {normalize_name(topic) for topic in (topics or []) if normalize_name(topic)}
	if not needles:
		return []
	candidates = candidate_syllabus_topics(concurso_cargo=concurso_cargo, limit=200)
	matched = []
	for row in candidates:
		title_norm = normalize_name(row.get("titulo"))
		if title_norm and (title_norm in needles or any(needle in title_norm or title_norm in needle for needle in needles if len(needle) >= 5)):
			matched.append(row.get("name"))
	return list(dict.fromkeys(name for name in matched if name))


def _add_frappe_tag(doctype, name, tag, doc=None):
	cleaned = re.sub(r"[,\r\n]+", " ", str(tag or "")).strip()[:60]
	if not cleaned or not name:
		return None
	try:
		if doctype == "LMS Question" and hasattr(frappe, "db") and hasattr(frappe.db, "has_column"):
			from trivia_sync.integrations.lms_questions import build_question_title

			if frappe.db.has_column("LMS Question", "trivia_title"):
				current_title = frappe.db.get_value("LMS Question", name, "trivia_title")
				if not current_title or len(str(current_title)) > 140:
					q_html = getattr(doc, "question", None) or frappe.db.get_value("LMS Question", name, "question") or ""
					short_title = build_question_title(q_html, fallback=name)
					frappe.db.set_value("LMS Question", name, "trivia_title", short_title, update_modified=False)
					if doc is not None:
						doc.trivia_title = short_title

		from frappe.desk.doctype.tag.tag import add_tag

		add_tag(cleaned, doctype, name)
		return cleaned
	except Exception:
		return None


def apply_ai_topics_to_question(
	question,
	topics=None,
	suggested_materia=None,
	suggested_assunto=None,
	syllabus_topic_names=None,
):
	if topics is None:
		raw_topics = getattr(question, "trivia_ai_topics", None)
		if isinstance(raw_topics, str):
			try:
				topics = json.loads(raw_topics or "[]")
			except (TypeError, ValueError):
				topics = []
		elif isinstance(raw_topics, list):
			topics = raw_topics
		else:
			topics = []
	cleaned_topics = list(dict.fromkeys(str(t).strip() for t in (topics or []) if str(t or "").strip()))

	subject_name = (getattr(question, "trivia_materia", None) or "").strip() or (suggested_materia or "").strip()
	if subject_name and not (getattr(question, "trivia_materia", None) or "").strip():
		question.trivia_materia = subject_name
	if subject_name and not getattr(question, "trivia_subject_link", None):
		question.trivia_subject_link = resolve_or_create_catalog("Trivia Subject", subject_name)

	topic_name = (
		(getattr(question, "trivia_assunto", None) or "").strip()
		or (suggested_assunto or "").strip()
		or (cleaned_topics[0] if cleaned_topics else "")
	)
	if topic_name and not (getattr(question, "trivia_assunto", None) or "").strip():
		question.trivia_assunto = topic_name
	if topic_name and not getattr(question, "trivia_topic_link", None):
		question.trivia_topic_link = resolve_or_create_catalog(
			"Trivia Topic",
			topic_name,
			extra_fields={"materia": getattr(question, "trivia_materia", None)},
		)

	cargo = getattr(question, "trivia_concurso_cargo", None)
	valid_candidates = {
		row.get("name")
		for row in candidate_syllabus_topics(concurso_cargo=cargo, limit=200)
		if row.get("name")
	}
	explicit_syllabus = [name for name in (syllabus_topic_names or []) if name in valid_candidates]
	inferred_syllabus = match_syllabus_topics_by_names(cleaned_topics + ([topic_name] if topic_name else []), concurso_cargo=cargo)
	target_syllabus = list(dict.fromkeys(explicit_syllabus + inferred_syllabus))

	existing_links = {
		getattr(row, "conteudo_programatico", None)
		for row in (getattr(question, "trivia_syllabus_topics", None) or [])
		if getattr(row, "conteudo_programatico", None)
	}
	added_syllabus = []
	for syllabus_name in target_syllabus:
		if syllabus_name not in existing_links and hasattr(question, "append"):
			question.append("trivia_syllabus_topics", {"conteudo_programatico": syllabus_name})
			existing_links.add(syllabus_name)
			added_syllabus.append(syllabus_name)

	tags_added = []
	q_name = getattr(question, "name", None)
	if q_name:
		for tag in cleaned_topics:
			added = _add_frappe_tag("LMS Question", q_name, tag, doc=question)
			if added:
				tags_added.append(added)

	return {
		"trivia_subject_link": getattr(question, "trivia_subject_link", None),
		"trivia_topic_link": getattr(question, "trivia_topic_link", None),
		"syllabus_topics_added": added_syllabus,
		"tags_added": tags_added,
	}
