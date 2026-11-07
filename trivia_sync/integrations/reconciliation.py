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


CLASSIFICATION_FIELDS = {
	"banca": ("Trivia Exam Board", "trivia_banca"),
	"orgao": ("Trivia Organization", "trivia_orgao"),
	"cargo": ("Trivia Position", "trivia_cargo"),
	"materia": ("Trivia Subject", "trivia_materia"),
	"assunto": ("Trivia Topic", "trivia_assunto"),
	"concurso": ("Trivia Contest", "concurso"),
	"prova": ("Trivia Exam", "prova"),
	"concurso_cargo": ("Trivia Contest Position", "concurso_cargo"),
}


def reconcile_question_classification(question):
	try:
		raw = json.loads(question.raw_payload or "{}")
	except (TypeError, ValueError):
		raw = {}
	results = {}
	for field, (doctype, link_field) in CLASSIFICATION_FIELDS.items():
		value = raw.get(field) or raw.get(f"{field}Id") or raw.get(f"{field}_id")
		external_id = value.get("id") or value.get("_id") or value.get("codigo") if isinstance(value, dict) else value
		name = getattr(question, field, "")
		resolution = resolve_catalog(doctype, external_id, name)
		setattr(question, link_field, resolution["name"])
		results[field] = resolution
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
			{"title": row.get("titulo") or row.get("title") or row.get("nome") or row.get("name") or content,
			 "content": content, "order": row.get("ordem") or row.get("order") or position,
			 "group": bool(row.get("children") or row.get("filhos") or row.get("items"))},
			ensure_ascii=False, sort_keys=True,
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
		"Trivia Question",
		filters={"concurso_cargo": concurso_cargo},
		fields=["trivia_materia", "trivia_assunto", "review_status", "redistribution_status", "source_type", "lms_question", "source_license", "redistribution_reference"],
	)
	coverage = {key: {} for key in ("subject", "topic", "review", "license", "source")}
	for question in questions:
		for bucket, value in (
		("subject", question.get("trivia_materia")),
		("topic", question.get("trivia_assunto")),
			("review", question.get("review_status") or "Pending"),
			("license", question.get("redistribution_status") or "Pending"),
			("source", question.get("source_type") or "Unknown"),
		):
			key = value or "Unclassified"
			coverage[bucket][key] = coverage[bucket].get(key, 0) + 1
	eligible = sum(
		1 for question in questions
		if question.get("review_status") == "Approved"
		and question.get("redistribution_status") == "Approved"
		and question.get("lms_question")
		and (question.get("source_license") or question.get("redistribution_reference"))
	)
	return {"total": len(questions), "eligible": eligible, **coverage}


def resolve_resource_links(doctype, data):
	try:
		raw = json.loads(data.get("raw_payload") or "{}")
	except (TypeError, ValueError):
		raw = {}
	links = {
		"Trivia Syllabus Topic": {"disciplina": "Trivia Discipline", "parent_conteudo": "Trivia Syllabus Topic", "concurso_cargo": "Trivia Contest Position"},
		"Trivia Discipline": {"concurso": "Trivia Contest"},
		"Trivia Exam": {"concurso": "Trivia Contest", "concurso_cargo": "Trivia Contest Position"},
		"Flashcard": {"conteudo": "Trivia Syllabus Topic"},
	}.get(doctype, {})
	for field, target in links.items():
		value = raw.get(field) or raw.get(f"{field}Id") or raw.get(f"{field}_id") or data.get(field)
		external_id = (value.get("id") or value.get("_id") or value.get("codigo")) if isinstance(value, dict) else value
		name = value.get("nome") or value.get("name") or value.get("titulo") if isinstance(value, dict) else value
		resolved = resolve_catalog(target, external_id, name)
		data[field] = resolved["name"]
	return data
