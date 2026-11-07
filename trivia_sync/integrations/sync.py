import hashlib
import json
import frappe
from trivia_sync.integrations.normalization import normalize_question, normalize_resource
from trivia_sync.integrations.ownership import update_source_owned_fields
from trivia_sync.integrations.qapi_client import QAPIBudgetError, QAPI_METHOD_COSTS
from trivia_sync.integrations.source_adapters import QAPIAdapter
from trivia_sync.integrations.reconciliation import (
	reconcile_question_classification,
	resolve_resource_links,
	sync_syllabus_tree,
)

RESOURCE_MAP = {
	"bancas": ("Trivia Exam Board", "bancas"),
	"orgaos": ("Trivia Organization", "orgaos"),
	"cargos": ("Trivia Position", "cargos"),
	"materias": ("Trivia Subject", "materias"),
	"assuntos": ("Trivia Topic", "assuntos"),
	"concursos": ("Trivia Contest", "concursos"),
	"provas": ("Trivia Exam", "provas"),
	"disciplinas": ("Trivia Discipline", "disciplinas"),
	"conteudos": ("Trivia Syllabus Topic", "conteudos"),
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


def _find_existing(doctype, data, legacy_key):
	matches = set()
	if data.get("source_key"):
		name = frappe.db.get_value(doctype, {"source_key": data["source_key"]}, "name")
		if name:
			matches.add(name)
	if data.get(legacy_key):
		name = frappe.db.get_value(doctype, {legacy_key: data[legacy_key]}, "name")
		if name:
			matches.add(name)
	if len(matches) > 1:
		frappe.throw(f"Ambiguous identity for {doctype}; import stopped without selecting a record.")
	return next(iter(matches), None)


def _upsert(doctype, data, key="qapi_id"):
	data = resolve_resource_links(doctype, data)
	value = data.get(key)
	if not value:
		return "skipped"
	if not data.get("source_key"):
		data = {**data, "source_type": "QAPI", "source_id": str(value), "source_key": f"qapi:{value}"}
	name = _find_existing(doctype, data, key)
	if name:
		doc = frappe.get_doc(doctype, name)
		if (
			getattr(doc, "sync_hash", None) == data.get("sync_hash")
			and getattr(doc, "source_key", None) == data.get("source_key")
		):
			return "skipped"
		update_source_owned_fields(doc, data, doctype)
		doc.last_synced_at = frappe.utils.now_datetime()
		doc.save(ignore_permissions=True)
		return "updated"
	doc = frappe.get_doc({"doctype": doctype, **data, "last_synced_at": frappe.utils.now_datetime()})
	doc.insert(ignore_permissions=True)
	return "created"


def _sync_text(adapter, codigo):
	if not codigo:
		return None
	payload = adapter.fetch_text(codigo)
	row = payload.get("data", payload) if isinstance(payload, dict) else payload
	data = normalize_resource(row if isinstance(row, dict) else {"codigo": codigo, "conteudo": row}, "texto")
	data["codigo"] = data.get("codigo") or codigo
	data["source_id"] = str(codigo)
	data["source_key"] = f"qapi:{codigo}"
	_upsert("Trivia Supporting Text", data, "codigo")
	return frappe.db.get_value("Trivia Supporting Text", {"codigo": data["codigo"]}, "name")


def _save_question(adapter, row, settings_doc):
	data = normalize_question(row)
	if not data["source_id"] or not data["enunciado"]:
		return "skipped"
	texto_name = _sync_text(adapter, data["texto_codigo"]) if settings_doc.sync_support_texts else None
	if texto_name:
		texto_hash = frappe.db.get_value("Trivia Supporting Text", texto_name, "sync_hash") or ""
		data["content_hash"] = hashlib.sha256(f"{data['content_hash']}:{texto_hash}".encode()).hexdigest()
	data["texto_apoio"] = texto_name
	name = _find_existing("Trivia Question", data, "qcode")
	if name:
		doc = frappe.get_doc("Trivia Question", name)
		if (
			doc.sync_hash == data["sync_hash"]
			and doc.texto_apoio == texto_name
			and doc.source_key == data["source_key"]
		):
			return "skipped"
		update_source_owned_fields(doc, data, "Trivia Question")
		reconcile_question_classification(doc)
		doc.last_synced_at = frappe.utils.now_datetime()
		doc.save(ignore_permissions=True)
		return "updated"
	doc = frappe.get_doc({"doctype": "Trivia Question", **data, "last_synced_at": frappe.utils.now_datetime()})
	reconcile_question_classification(doc)
	doc.insert(ignore_permissions=True)
	return "created"


def _sync_paginated(
	adapter, method_name, doctype, kind, settings_doc, max_pages, filters, start_page=1, run=None,
	request_offset=0, credit_offset=0
):
	created = updated = skipped = errors = 0
	for page in range(start_page, max_pages + 1):
		if run:
			run.current_operation = method_name
			run.page = page
			run.resume_operation = method_name
			run.resume_page = page
		payload = adapter.fetch_resource(method_name, page=page, size=min(10, max(1, int(settings_doc.qapi_page_size or 10))))
		for row in _rows(payload):
			try:
				result = _upsert(doctype, normalize_resource(row, kind))
				if result == "created":
					created += 1
				elif result == "updated":
					updated += 1
				else:
					skipped += 1
			except Exception as exc:
				errors += 1
				if run:
					run.error_log = _append_error(run.error_log, doctype, row.get("id") or row.get("codigo"), exc)
			frappe.db.commit()
		if run:
			run.requests_made = request_offset + adapter.requests_made
			run.credits_used = credit_offset + adapter.credits_used
			run.save(ignore_permissions=True)
		frappe.db.commit()
		if page >= _pages(payload):
			break
	return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}


def _append_error(current, doctype, source_id, error):
	message = f"{doctype} [{source_id or 'unknown'}]: {type(error).__name__}: {str(error)[:300]}"
	return "\n".join(filter(None, [current, message]))[-12000:]


def _validate_filters(filters):
	allowed = {"concurso", "cargo", "banca", "materia", "ano"}
	filters = filters or {}
	if not isinstance(filters, dict) or set(filters) - allowed:
		frappe.throw("Supported filters: contest, position, exam board, subject, and year.")
	return {key: value for key, value in filters.items() if value not in (None, "")}


def _limits(settings_doc, budget, max_pages):
	configured = max(0, int(settings_doc.qapi_max_requests_per_run or 0))
	requested = configured if budget is None else max(0, int(budget))
	request_budget = min(configured, requested)
	reserve = max(1, int(settings_doc.qapi_min_credit_reserve or 1))
	spend_limit = max(0, request_budget - reserve)
	pages = max(1, min(int(max_pages or settings_doc.qapi_max_pages or 10), 100000))
	return request_budget, reserve, spend_limit, pages


def _dry_run_result(settings_doc, filters, request_budget, reserve, spend_limit, max_pages, include_catalogs):
	page_size = min(10, max(1, int(settings_doc.qapi_page_size or 10)))
	resource_cost = 0
	if include_catalogs and settings_doc.sync_catalogs:
		resource_cost = sum(
			max_pages * QAPI_METHOD_COSTS.get(method, 1)
			for method, (_, kind) in RESOURCE_MAP.items()
			if (kind != "provas" or settings_doc.sync_exams)
			and (kind != "flashcards" or settings_doc.sync_flashcards)
		)
		resource_cost += 1  # Árvore de conteúdo programático.
	text_upper_bound = max_pages * page_size if settings_doc.sync_support_texts else 0
	projected = max_pages + resource_cost + text_upper_bound
	return {
		"dry_run": True,
		"filters": filters,
		"max_pages": max_pages,
		"page_size": page_size,
		"request_budget": request_budget,
		"credit_reserve": reserve,
		"spend_limit": spend_limit,
		"projected_request_cost": projected,
		"budget_sufficient_for_upper_bound": spend_limit >= projected,
		"projection_is_upper_bound": True,
		"writes": 0,
	}


def ingest_source(
	source_name="QAPI", filters=None, dry_run=False, max_pages=0, budget=None, resume_run=None, include_catalogs=True
):
	if source_name != "QAPI":
		frappe.throw(f"Source not implemented: {source_name}.")
	settings = frappe.get_single("Trivia Sync Settings")
	filters = _validate_filters(filters)
	include_catalogs = bool(include_catalogs and settings.sync_catalogs)
	request_budget, reserve, spend_limit, max_pages = _limits(settings, budget, max_pages)
	if dry_run:
		return _dry_run_result(settings, filters, request_budget, reserve, spend_limit, max_pages, include_catalogs)

	run = frappe.get_doc("Trivia Sync Run", resume_run) if resume_run else frappe.new_doc("Trivia Sync Run")
	if not resume_run:
		run.source = "QAPI"
		run.operation = "QAPI ingestion"
		run.operator = frappe.session.user
		run.started_at = frappe.utils.now_datetime()
		run.records_created = run.records_updated = run.records_skipped = run.records_errors = 0
		run.insert(ignore_permissions=True)
	prior_requests = int(run.requests_made or 0) if resume_run else 0
	prior_credits = int(run.credits_used or 0) if resume_run else 0
	run.status = "Running"
	run.parameters_json = json.dumps(
		{"source": source_name, "filters": filters, "max_pages": max_pages, "include_catalogs": include_catalogs},
		ensure_ascii=False,
	)
	run.request_budget = int(run.request_budget or 0) + spend_limit if resume_run else spend_limit
	run.credit_reserve = reserve
	run.save(ignore_permissions=True)
	frappe.db.commit()
	totals = {
		"created": int(run.records_created or 0) if resume_run else 0,
		"updated": int(run.records_updated or 0) if resume_run else 0,
		"skipped": int(run.records_skipped or 0) if resume_run else 0,
		"errors": int(run.records_errors or 0) if resume_run else 0,
	}
	if spend_limit <= 0:
		run.status = "Blocked"
		run.error_log = "Paid budget unavailable: set a credit limit above the reserve."
		run.finished_at = frappe.utils.now_datetime()
		run.save(ignore_permissions=True)
		frappe.db.commit()
		return {**totals, "blocked": True, "requests_made": 0}

	try:
		adapter = QAPIAdapter(settings, max_requests=spend_limit)
		if not adapter.is_available():
			frappe.throw("QAPI is unavailable: configure an API key and a positive local budget.")
		page_size = min(10, max(1, int(settings.qapi_page_size or 10)))
		resume_operation = run.resume_operation if resume_run else ""
		resume_page = int(run.resume_page or 1) if resume_run else 1
		tasks = [("questions", None, None)]
		if include_catalogs:
			for method, (doctype, kind) in RESOURCE_MAP.items():
				if kind == "provas" and not settings.sync_exams:
					continue
				if kind == "flashcards" and not settings.sync_flashcards:
					continue
				tasks.append((method, doctype, kind))
			tasks.append(("syllabus_tree", "Trivia Syllabus Topic", "conteudos"))
		resume_reached = not resume_operation
		for operation, doctype, kind in tasks:
			if not resume_reached:
				if operation != resume_operation:
					continue
				resume_reached = True
			start_page = resume_page if operation == resume_operation else 1
			run.current_operation = operation
			run.resume_operation = operation
			run.resume_page = start_page
			run.save(ignore_permissions=True)
			if operation == "questions":
				for page in range(start_page, max_pages + 1):
					run.page = page
					run.resume_page = page
					payload = adapter.fetch_questions(filters, page=page, size=page_size)
					for row in _rows(payload):
						try:
							result = _save_question(adapter, row, settings)
							totals[{"created": "created", "updated": "updated"}.get(result, "skipped")] += 1
						except QAPIBudgetError:
							raise
						except Exception as exc:
							totals["errors"] += 1
							run.error_log = _append_error(run.error_log, "Trivia Question", row.get("qCode") or row.get("qcode"), exc)
						run.requests_made = prior_requests + adapter.requests_made
						run.credits_used = prior_credits + adapter.credits_used
						run.records_created = totals["created"]
						run.records_updated = totals["updated"]
						run.records_skipped = totals["skipped"]
						run.records_errors = totals["errors"]
						frappe.db.commit()
					if page >= _pages(payload):
						break
					run.save(ignore_permissions=True)
					frappe.db.commit()
			else:
				if operation == "syllabus_tree":
					run.page = 1
					payload = adapter.fetch_syllabus_tree(filters)
					cargo_id = filters.get("cargo")
					cargo_name = frappe.db.get_value("Trivia Contest Position", {"source_id": str(cargo_id)}, "name") if cargo_id else None
					if cargo_name:
						rows = payload.get("data", payload) if isinstance(payload, dict) else payload
						version = str(payload.get("version") or payload.get("updated_at") or "") if isinstance(payload, dict) else ""
						result = sync_syllabus_tree(cargo_name, rows, version)
						totals["created"] += result["created"]
						totals["updated"] += result["updated"]
						totals["skipped"] += result["unchanged"]
					else:
						for row in _tree_rows(payload):
							try:
								result = _upsert(doctype, normalize_resource(row, kind))
								totals[{"created": "created", "updated": "updated"}.get(result, "skipped")] += 1
							except Exception as exc:
								totals["errors"] += 1
								run.error_log = _append_error(run.error_log, doctype, row.get("id") or row.get("codigo"), exc)
				else:
					result = _sync_paginated(
						adapter, operation, doctype, kind, settings, max_pages, {}, start_page=start_page, run=run,
						request_offset=prior_requests, credit_offset=prior_credits,
					)
					for key in totals:
						totals[key] += result[key]
			run.requests_made = prior_requests + adapter.requests_made
			run.credits_used = prior_credits + adapter.credits_used
			run.records_created = totals["created"]
			run.records_updated = totals["updated"]
			run.records_skipped = totals["skipped"]
			run.records_errors = totals["errors"]
			frappe.db.commit()
		if not resume_reached:
			frappe.throw("The saved resume step is no longer enabled in the current settings.")
		run.status = "Partial" if totals["errors"] else "Completed"
		run.resume_operation = None
		run.resume_page = 0
		settings.last_qapi_sync_at = frappe.utils.now_datetime()
		settings.save(ignore_permissions=True)
		return {**totals, "requests_made": run.requests_made, "requests_this_attempt": adapter.requests_made}
	except QAPIBudgetError as exc:
		run.status = "Partial" if prior_requests + adapter.requests_made else "Blocked"
		run.error_log = _append_error(run.error_log, run.current_operation, run.page, exc)
		run.requests_made = prior_requests + adapter.requests_made
		run.credits_used = prior_credits + getattr(locals().get("adapter"), "credits_used", 0)
		return {**totals, "partial": bool(run.requests_made), "blocked": not bool(run.requests_made), "requests_made": run.requests_made}
	except Exception as exc:
		run.status = "Failed"
		run.error_log = _append_error(run.error_log, run.current_operation, run.page, exc)
		frappe.log_error(f"{type(exc).__name__}: {str(exc)[:300]}", "Trivia Sync · QAPI ingestion")
		raise
	finally:
		run.finished_at = frappe.utils.now_datetime()
		run.requests_made = prior_requests + getattr(locals().get("adapter"), "requests_made", 0)
		run.credits_used = prior_credits + getattr(locals().get("adapter"), "credits_used", 0)
		run.records_created = totals["created"]
		run.records_updated = totals["updated"]
		run.records_skipped = totals["skipped"]
		run.records_errors = totals["errors"]
		run.save(ignore_permissions=True)
		frappe.db.commit()


def sync_qapi_full():
	return ingest_source("QAPI")
