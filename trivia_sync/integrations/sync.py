import json
import frappe
from trivia_sync.integrations.normalization import normalize_question, normalize_resource, first
from trivia_sync.integrations.qapi_client import QAPIClient
from trivia_sync.integrations.lms_questions import sync_lms_question

RESOURCE_MAP = {
	"bancas": ("Banca", "bancas"),
	"orgaos": ("Órgão", "orgaos"),
	"cargos": ("Cargo", "cargos"),
	"materias": ("Matéria", "materias"),
	"assuntos": ("Assunto", "assuntos"),
	"concursos": ("Concurso", "concursos"),
	"provas": ("Prova", "provas"),
	"disciplinas": ("Disciplina", "disciplinas"),
	"conteudos": ("Conteúdo Programático", "conteudos"),
	"flashcards": ("Flashcard", "flashcards"),
}


def _rows(payload):
	if isinstance(payload, list):
		return payload
	for key in (
		"data",
		"items",
		"results",
		"questoes",
		"bancas",
		"orgaos",
		"cargos",
		"materias",
		"assuntos",
		"concursos",
		"provas",
		"disciplinas",
		"conteudos",
		"flashcards",
	):
		if isinstance(payload.get(key), list):
			return payload[key]
	return []


def _pages(payload):
	if not isinstance(payload, dict):
		return 1
	return int(payload.get("pages") or payload.get("totalPages") or payload.get("last_page") or 1)


def _tree_rows(payload, parent_id="", level=0):
	if isinstance(payload, dict):
		is_node = any(
			payload.get(key) not in (None, "")
			for key in ("id", "_id", "codigo", "code", "uuid", "titulo", "title", "nome", "name")
		)
		nodes = (
			next(
				(
					value
					for key, value in payload.items()
					if key in {"data", "items", "results", "conteudos"} and isinstance(value, list)
				),
				None,
			)
			if not is_node
			else None
		)
		if nodes is not None:
			for node in nodes:
				yield from _tree_rows(node, parent_id, level)
			return
		row = dict(payload)
		if parent_id and not row.get("parent_id") and not row.get("parentId"):
			row["parent_id"] = parent_id
		row.setdefault("nivel", level)
		yield row
		current = str(row.get("id") or row.get("_id") or row.get("codigo") or "")
		for key in ("children", "filhos", "items"):
			if isinstance(row.get(key), list):
				for child in row[key]:
					yield from _tree_rows(child, current, level + 1)
	elif isinstance(payload, list):
		for node in payload:
			yield from _tree_rows(node, parent_id, level)


def _upsert(doctype, data, key="qapi_id"):
	value = data.get(key)
	if not value:
		return "skipped"
	name = frappe.db.exists(doctype, {key: value})
	if name:
		doc = frappe.get_doc(doctype, name)
		if getattr(doc, "sync_hash", None) == data.get("sync_hash"):
			return "skipped"
		for k, v in data.items():
			if k not in {"qapi_id"}:
				setattr(doc, k, v)
		doc.last_synced_at = frappe.utils.now_datetime()
		doc.save(ignore_permissions=True)
		return "updated"
	doc = frappe.get_doc({"doctype": doctype, **data, "last_synced_at": frappe.utils.now_datetime()})
	doc.insert(ignore_permissions=True)
	return "created"


def _sync_text(client, codigo):
	if not codigo:
		return None
	payload = client.texto(codigo)
	row = payload.get("data", payload) if isinstance(payload, dict) else payload
	data = normalize_resource(row if isinstance(row, dict) else {"codigo": codigo, "conteudo": row}, "texto")
	_upsert("Texto de Apoio", data, "codigo")
	return frappe.db.get_value("Texto de Apoio", {"codigo": data["codigo"]}, "name")


def _save_question(client, row, settings_doc):
	data = normalize_question(row)
	if not data["qcode"] or not data["enunciado"]:
		return "skipped"
	texto_name = _sync_text(client, data["texto_codigo"]) if settings_doc.sync_support_texts else None
	name = frappe.db.exists("Trivia Question", {"qcode": data["qcode"]})
	if name:
		doc = frappe.get_doc("Trivia Question", name)
		changed = doc.sync_hash != data["sync_hash"] or doc.texto_apoio != texto_name
	else:
		doc = frappe.new_doc("Trivia Question")
		changed = True
	if changed:
		for key, value in data.items():
			if key != "texto_codigo":
				setattr(doc, key, value)
		doc.texto_apoio = texto_name
		doc.last_synced_at = frappe.utils.now_datetime()
		doc.insert(ignore_permissions=True) if doc.is_new() else doc.save(ignore_permissions=True)
	return sync_lms_question(doc)


def _sync_paginated(client, method_name, doctype, kind, settings_doc, **params):
	created = updated = skipped = errors = 0
	max_pages = max(1, min(int(settings_doc.qapi_max_pages or 10), 100000))
	for page in range(1, max_pages + 1):
		payload = getattr(client, method_name)(
			page=page, size=min(10, int(settings_doc.qapi_page_size or 10)), **params
		)
		for row in _rows(payload):
			try:
				result = _upsert(doctype, normalize_resource(row, kind))
				if result == "created":
					created += 1
				elif result == "updated":
					updated += 1
				else:
					skipped += 1
			except Exception:
				errors += 1
				frappe.log_error(frappe.get_traceback(), f"Trivia Sync · {doctype}")
		frappe.db.commit()
		if page >= _pages(payload):
			break
	return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}


def sync_qapi_full():
	settings = frappe.get_single("Trivia Sync Settings")
	client = QAPIClient(settings)
	run = frappe.new_doc("Trivia Sync Run")
	run.source = "QAPI"
	run.operation = "Full QAPI sync"
	run.status = "Running"
	run.started_at = frappe.utils.now_datetime()
	run.insert(ignore_permissions=True)
	totals = {"created": 0, "updated": 0, "skipped": 0, "errors": 0}
	try:
		payload = client.questoes(page=1, size=min(10, int(settings.qapi_page_size or 10)))
		max_pages = max(1, min(int(settings.qapi_max_pages or 10), 100000))
		for page in range(1, max_pages + 1):
			if page > 1:
				payload = client.questoes(page=page, size=min(10, int(settings.qapi_page_size or 10)))
			for row in _rows(payload):
				try:
					result = _save_question(client, row, settings)
					totals[{"created": "created", "updated": "updated"}.get(result, "skipped")] += 1
				except Exception:
					totals["errors"] += 1
					frappe.log_error(frappe.get_traceback(), "Trivia Sync · question")
			frappe.db.commit()
			if page >= _pages(payload):
				break
		if settings.sync_catalogs:
			client.status_concurso()
			for method, (doctype, kind) in RESOURCE_MAP.items():
				if kind == "provas" and not settings.sync_exams:
					continue
				if kind == "flashcards" and not settings.sync_flashcards:
					continue
				result = _sync_paginated(client, method, doctype, kind, settings)
				for key in totals:
					totals[key] += result[key]
			tree = client.conteudos_arvore()
			for node in _tree_rows(tree):
				result = _upsert("Conteúdo Programático", normalize_resource(node, "conteudos"))
				totals[{"created": "created", "updated": "updated"}.get(result, "skipped")] += 1
		if settings.sync_support_texts:
			# Texts are fetched rigorously by qCode during question ingestion; no orphan scan is invented.
			pass
		run.status = "Partial" if totals["errors"] else "Completed"
		run.records_created = totals["created"]
		run.records_updated = totals["updated"]
		run.records_skipped = totals["skipped"]
		run.records_errors = totals["errors"]
		settings.last_qapi_sync_at = frappe.utils.now_datetime()
		settings.save(ignore_permissions=True)
		return totals
	except Exception:
		run.status = "Failed"
		run.error_log = frappe.get_traceback()
		frappe.log_error(frappe.get_traceback(), "Trivia Sync · full QAPI sync")
		raise
	finally:
		run.finished_at = frappe.utils.now_datetime()
		run.save(ignore_permissions=True)
		frappe.db.commit()
