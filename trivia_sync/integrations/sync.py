import hashlib
import json
import copy
import frappe
from trivia_sync.integrations.normalization import normalize_question, normalize_resource
from trivia_sync.integrations.ownership import source_fields_changed, update_source_owned_fields
from trivia_sync.integrations.qapi_client import QAPIBudgetError, QAPIError, QAPI_METHOD_COSTS
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

DETAIL_ENDPOINTS = {
	"provas": ("prova", 200),
	"concursos": ("concurso", 1),
	"disciplinas": ("disciplina", 1),
}

RESOURCE_SWITCHES = {
	"bancas": "sync_bancas",
	"orgaos": "sync_orgaos",
	"cargos": "sync_cargos",
	"materias": "sync_materias",
	"assuntos": "sync_assuntos",
	"concursos": "sync_concursos",
	"provas": "sync_exams",
	"disciplinas": "sync_disciplinas",
	"conteudos": "sync_conteudos",
	"flashcards": "sync_flashcards",
}


def _resource_enabled(settings_doc, kind):
	return bool(getattr(settings_doc, RESOURCE_SWITCHES.get(kind, ""), 1))


def _metric(metrics, endpoint):
	return metrics.setdefault(endpoint, {"received": 0, "created": 0, "updated": 0, "failed": 0})


def _record_metric(metrics, endpoint, result=None, received=0, failed=0):
	bucket = _metric(metrics, endpoint)
	bucket["received"] += int(received or 0)
	bucket["failed"] += int(failed or 0)
	if result == "created":
		bucket["created"] += 1
	elif result == "updated":
		bucket["updated"] += 1


def _payload_record(payload):
	if isinstance(payload, dict):
		for key in ("data", "item", "result"):
			value = payload.get(key)
			if isinstance(value, dict):
				return value
		return payload
	return {}


def _estimated_request_cost(settings_doc, max_pages, include_catalogs, local_flashcard_count=0):
	page_size = min(10, max(1, int(settings_doc.qapi_page_size or 10)))
	cost_multiplier = 2 if getattr(settings_doc, "mcp_enabled", 0) else 1
	question_records = max_pages * page_size
	cost = max_pages * cost_multiplier if getattr(settings_doc, "sync_questions", 1) else 0  # get_questoes
	cost += question_records * cost_multiplier if getattr(settings_doc, "sync_questions", 1) and settings_doc.sync_support_texts else 0
	if not include_catalogs or not settings_doc.sync_catalogs:
		return cost + (local_flashcard_count if getattr(settings_doc, "push_flashcards", 0) else 0)
	for method, (_, kind) in RESOURCE_MAP.items():
		if not _resource_enabled(settings_doc, kind):
			continue
		cost += max_pages * QAPI_METHOD_COSTS.get(method, 1) * cost_multiplier
		if method in DETAIL_ENDPOINTS:
			detail_method, detail_cost = DETAIL_ENDPOINTS[method]
			cost += max_pages * page_size * detail_cost * cost_multiplier
	if settings_doc.sync_catalogs and _resource_enabled(settings_doc, "conteudos"):
		cost += cost_multiplier  # get_conteudos_arvore
	if settings_doc.sync_catalogs and _resource_enabled(settings_doc, "concursos"):
		cost += cost_multiplier  # get_status_concurso
	if getattr(settings_doc, "push_flashcards", 0):
		cost += local_flashcard_count * QAPI_METHOD_COSTS["criar_flashcard"] * cost_multiplier
	return cost


def _rows(payload):
	if isinstance(payload, list):
		return payload
	if not isinstance(payload, dict):
		raise QAPIError("Unexpected QAPI page response; expected a list or object envelope.")
	list_keys = (
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
		"rows",
	)
	queue = [payload]
	while queue:
		current = queue.pop(0)
		if isinstance(current, list):
			return current
		if not isinstance(current, dict):
			continue
		for key in list_keys:
			value = current.get(key)
			if isinstance(value, list):
				return value
		for key in ("data", "result", "results", "payload", "response"):
			value = current.get(key)
			if isinstance(value, dict):
				queue.append(value)
	raise QAPIError("Unexpected QAPI page response; no question/resource list was found.")


def _pages(payload):
	if not isinstance(payload, dict):
		return 1
	queue = [payload]
	while queue:
		current = queue.pop(0)
		if not isinstance(current, dict):
			continue
		for key in ("pages", "totalPages", "total_pages", "last_page", "page_count"):
			if current.get(key) not in (None, "", 0, "0"):
				return max(1, int(current[key]))
		if current.get("total") not in (None, "") and current.get("size") not in (None, "", 0, "0"):
			return max(1, (int(current["total"]) + int(current["size"]) - 1) // int(current["size"]))
		for key in ("meta", "metadata", "pagination", "data", "result"):
			if isinstance(current.get(key), dict):
				queue.append(current[key])
	return 1


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


def _sync_text(adapter, codigo, metrics=None):
	if not codigo:
		return None
	try:
		payload = adapter.fetch_text(codigo)
		if metrics is not None:
			_record_metric(metrics, "get_texto", received=1)
	except Exception:
		if metrics is not None:
			_record_metric(metrics, "get_texto", received=1, failed=1)
		raise
	row = payload.get("data", payload) if isinstance(payload, dict) else payload
	data = normalize_resource(row if isinstance(row, dict) else {"codigo": codigo, "conteudo": row}, "texto")
	data["codigo"] = data.get("codigo") or codigo
	data["source_id"] = str(codigo)
	data["source_key"] = f"qapi:{codigo}"
	result = _upsert("Trivia Supporting Text", data, "codigo")
	if metrics is not None:
		_record_metric(metrics, "get_texto", result=result)
	return frappe.db.get_value("Trivia Supporting Text", {"codigo": data["codigo"]}, "name")


def _save_question(adapter, row, settings_doc, metrics=None):
	data = normalize_question(row)
	if not data["source_id"] or not data["enunciado"]:
		return "skipped"
	texto_name = _sync_text(adapter, data["texto_codigo"], metrics) if settings_doc.sync_support_texts else None
	if texto_name:
		texto_hash = frappe.db.get_value("Trivia Supporting Text", texto_name, "sync_hash") or ""
		data["content_hash"] = hashlib.sha256(f"{data['content_hash']}:{texto_hash}".encode()).hexdigest()
	data["texto_apoio"] = texto_name
	name = _find_existing("Trivia Question", data, "qcode")
	if name:
		doc = frappe.get_doc("Trivia Question", name)
		if (
			doc.sync_hash == data["sync_hash"]
			and doc.content_hash == data["content_hash"]
			and doc.texto_apoio == texto_name
			and doc.source_key == data["source_key"]
			and not source_fields_changed(doc, data, "Trivia Question")
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
	request_offset=0, credit_offset=0, metrics=None
):
	created = updated = skipped = errors = 0
	for page in range(start_page, max_pages + 1):
		if run:
			run.current_operation = method_name
			run.page = page
			run.resume_operation = method_name
			run.resume_page = page
		payload = adapter.fetch_resource(
			method_name,
			page=page,
			size=min(10, max(1, int(settings_doc.qapi_page_size or 10))),
			filters=filters,
		)
		for row in _rows(payload):
			if metrics is not None:
				_record_metric(metrics, method_name, received=1)
			try:
				result = _upsert(doctype, normalize_resource(row, kind))
				if metrics is not None:
					_record_metric(metrics, method_name, result=result)
				if result == "created":
					created += 1
				elif result == "updated":
					updated += 1
				else:
					skipped += 1
			except Exception as exc:
				errors += 1
				if metrics is not None:
					_record_metric(metrics, method_name, failed=1)
				if run:
					run.error_log = _append_error(run.error_log, doctype, row.get("id") or row.get("codigo"), exc)
			if method_name in DETAIL_ENDPOINTS:
				detail_method, _ = DETAIL_ENDPOINTS[method_name]
				row_id = str(row.get("id") or row.get("_id") or row.get("codigo") or row.get("qCode") or "")
				if row_id:
					try:
						detail = getattr(adapter.client, detail_method)(row_id)
						if metrics is not None:
							_record_metric(metrics, f"get_{detail_method}", received=1)
						detail_row = _payload_record(detail)
						if detail_row:
							detail_data = normalize_resource({**row, **detail_row}, kind)
							detail_result = _upsert(doctype, detail_data)
							if metrics is not None:
								_record_metric(metrics, f"get_{detail_method}", result=detail_result)
					except Exception as exc:
						if metrics is not None:
							_record_metric(metrics, f"get_{detail_method}", failed=1)
						if run:
							run.error_log = _append_error(run.error_log, doctype, row_id, exc)
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


def reformat_qapi_questions(question_name=None, limit=10000):
	"""Reparse stored QAPI payloads after a normalizer/renderer upgrade; no QAPI calls."""
	filters = {"source_type": "QAPI"}
	if question_name:
		filters["name"] = question_name
	rows = frappe.get_all("Trivia Question", filters=filters, fields=["name", "raw_payload"], limit_page_length=limit)
	updated = skipped = failed = 0
	for row in rows:
		try:
			payload = json.loads(row.raw_payload or "{}")
			data = normalize_question(payload)
			doc = frappe.get_doc("Trivia Question", row.name)
			if doc.texto_apoio:
				text_hash = frappe.db.get_value("Trivia Supporting Text", doc.texto_apoio, "sync_hash") or ""
				data["content_hash"] = hashlib.sha256(f"{data['content_hash']}:{text_hash}".encode()).hexdigest()
				data["texto_apoio"] = doc.texto_apoio
			changed = source_fields_changed(doc, data, "Trivia Question")
			update_source_owned_fields(doc, data, "Trivia Question")
			if changed:
				doc.last_synced_at = frappe.utils.now_datetime()
				doc.save(ignore_permissions=True)
				updated += 1
			else:
				skipped += 1
		except Exception as exc:
			failed += 1
			frappe.log_error(f"{type(exc).__name__}: {str(exc)[:500]}", "Trivia Sync · reformat question")
	frappe.db.commit()
	return {"processed": len(rows), "updated": updated, "skipped": skipped, "failed": failed}


def _validate_filters(filters):
	allowed = {"concurso", "cargo", "banca", "orgao", "materia", "ano"}
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
	local_flashcard_count = 0
	if getattr(settings_doc, "push_flashcards", 0):
		local_flashcard_count = frappe.db.count("Flashcard", {"source_type": "LOCAL"})
	projected = _estimated_request_cost(settings_doc, max_pages, include_catalogs, local_flashcard_count)
	return {
		"dry_run": True,
		"filters": filters,
		"max_pages": max_pages,
		"page_size": page_size,
		"request_budget": request_budget,
		"credit_reserve": reserve,
		"spend_limit": spend_limit,
		"projected_request_cost": projected,
		"required_upper_bound": projected,
		"budget_sufficient_for_upper_bound": spend_limit >= projected,
		"projection_is_upper_bound": True,
		"strict_full_utilization": True,
		"writes": 0,
	}


def _sync_concurso_status(adapter, metrics):
	try:
		payload = adapter.client.status_concurso()
		_record_metric(metrics, "get_status_concurso", received=1)
		return payload
	except Exception:
		_record_metric(metrics, "get_status_concurso", received=1, failed=1)
		raise


def _push_local_flashcards(adapter, metrics):
	created = updated = failed = 0
	rows = frappe.get_all(
		"Flashcard",
		filters={"source_type": "LOCAL"},
		fields=["name", "qapi_id", "frente", "verso", "conteudo", "materia", "assunto"],
		limit_page_length=10000,
	)
	for row in rows:
		_record_metric(metrics, "criar_flashcard", received=1)
		try:
			payload = {
				"front": row.frente,
				"back": row.verso,
				"conteudo_id": row.conteudo,
				"materia": row.materia,
				"assunto": row.assunto,
			}
			response = adapter.client.criar_flashcard(payload)
			result = _payload_record(response)
			remote_id = str(result.get("id") or result.get("_id") or result.get("codigo") or "")
			if not remote_id:
				raise ValueError("QAPI did not return a flashcard ID")
			doc = frappe.get_doc("Flashcard", row.name)
			doc.qapi_id = remote_id
			doc.source_type = "QAPI"
			doc.source_id = remote_id
			doc.source_key = f"qapi:{remote_id}"
			doc.raw_payload = json.dumps(result, ensure_ascii=False)
			doc.save(ignore_permissions=True)
			_record_metric(metrics, "criar_flashcard", result="created")
			updated += 1
		except Exception as exc:
			failed += 1
			_record_metric(metrics, "criar_flashcard", failed=1)
			frappe.log_error(f"{type(exc).__name__}: {str(exc)[:300]}", "Trivia Sync · flashcard")
	return {"created": created, "updated": updated, "failed": failed}


def ingest_source(
	source_name="QAPI", filters=None, dry_run=False, max_pages=0, budget=None, resume_run=None, include_catalogs=True,
	force_full_upgrade=False,
):
	if source_name != "QAPI":
		frappe.throw(f"Source not implemented: {source_name}.")
	settings = frappe.get_single("Trivia Sync Settings")
	if force_full_upgrade:
		settings = copy.copy(settings)
		settings.sync_catalogs = 1
		for field in (
			"sync_questions", "sync_support_texts", "sync_bancas", "sync_orgaos", "sync_cargos", "sync_materias",
			"sync_assuntos", "sync_concursos", "sync_exams", "sync_disciplinas", "sync_conteudos", "sync_flashcards",
		):
			setattr(settings, field, 1)
		settings.push_flashcards = 0
	filters = _validate_filters(filters)
	include_catalogs = bool(include_catalogs and settings.sync_catalogs)
	request_budget, reserve, spend_limit, max_pages = _limits(settings, budget, max_pages)
	if dry_run:
		return _dry_run_result(settings, filters, request_budget, reserve, spend_limit, max_pages, include_catalogs)
	local_flashcard_count = 0
	if getattr(settings, "push_flashcards", 0):
		local_flashcard_count = frappe.db.count("Flashcard", {"source_type": "LOCAL"})
	required_upper_bound = _estimated_request_cost(settings, max_pages, include_catalogs, local_flashcard_count)
	run = frappe.get_doc("Trivia Sync Run", resume_run) if resume_run else frappe.new_doc("Trivia Sync Run")
	if not resume_run:
		run.source = "QAPI"
		run.operation = "QAPI ingestion"
		run.operator = frappe.session.user
		run.started_at = frappe.utils.now_datetime()
		run.records_created = run.records_updated = run.records_skipped = run.records_errors = 0
		run.records_received = 0
		run.endpoint_metrics = "{}"
		run.insert(ignore_permissions=True)
	prior_requests = int(run.requests_made or 0) if resume_run else 0
	prior_credits = int(run.credits_used or 0) if resume_run else 0
	run.status = "Running"
	run.request_budget = int(run.request_budget or 0) + spend_limit if resume_run else spend_limit
	run.credit_reserve = reserve
	run.parameters_json = json.dumps(
		{"source": source_name, "filters": filters, "max_pages": max_pages, "include_catalogs": include_catalogs,
		 "required_upper_bound": required_upper_bound, "strict_full_utilization": True}, ensure_ascii=False
	)
	totals = {
		"created": int(run.records_created or 0) if resume_run else 0,
		"updated": int(run.records_updated or 0) if resume_run else 0,
		"skipped": int(run.records_skipped or 0) if resume_run else 0,
		"errors": int(run.records_errors or 0) if resume_run else 0,
	}
	metrics = json.loads(run.endpoint_metrics or "{}") if resume_run and run.endpoint_metrics else {}
	if spend_limit < required_upper_bound:
		run.status = "Blocked"
		run.error_log = (
			f"Budget preflight blocked the run: {spend_limit} spendable credits available, "
			f"{required_upper_bound} required for the configured worst-case plan."
		)
		run.finished_at = frappe.utils.now_datetime()
		run.save(ignore_permissions=True)
		frappe.db.commit()
		return {**totals, "blocked": True, "required_upper_bound": required_upper_bound,
				"spend_limit": spend_limit, "requests_made": 0}
	if spend_limit <= 0:
		run.status = "Blocked"
		run.error_log = "Paid budget unavailable: set a credit limit above the reserve."
		run.finished_at = frappe.utils.now_datetime()
		run.save(ignore_permissions=True)
		frappe.db.commit()
		return {**totals, "blocked": True, "requests_made": 0}
	adapter = None
	try:
		adapter = QAPIAdapter(settings, max_requests=spend_limit)
		if not adapter.is_available():
			frappe.throw("QAPI is unavailable: configure an API key and a positive local budget.")
		page_size = min(10, max(1, int(settings.qapi_page_size or 10)))
		resume_operation = run.resume_operation if resume_run else ""
		resume_page = int(run.resume_page or 1) if resume_run else 1
		tasks = [("questions", None, None)] if getattr(settings, "sync_questions", 1) else []
		if include_catalogs:
			for method, (doctype, kind) in RESOURCE_MAP.items():
				if not _resource_enabled(settings, kind):
					continue
				tasks.append((method, doctype, kind))
			if _resource_enabled(settings, "conteudos"):
				tasks.append(("syllabus_tree", "Trivia Syllabus Topic", "conteudos"))
			if _resource_enabled(settings, "concursos"):
				tasks.append(("contest_status", None, None))
		if getattr(settings, "push_flashcards", 0):
			tasks.append(("create_flashcards", "Flashcard", "flashcards_out"))
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
			if operation == "questions":
				for page in range(start_page, max_pages + 1):
					run.page = page
					payload = adapter.fetch_questions(filters, page=page, size=page_size)
					for row in _rows(payload):
						_record_metric(metrics, "get_questoes", received=1)
						try:
							result = _save_question(adapter, row, settings, metrics)
							_record_metric(metrics, "get_questoes", result=result)
							totals[{"created": "created", "updated": "updated"}.get(result, "skipped")] += 1
						except QAPIBudgetError:
							raise
						except Exception as exc:
							totals["errors"] += 1
							_record_metric(metrics, "get_questoes", failed=1)
							run.error_log = _append_error(run.error_log, "Trivia Question", row.get("qCode") or row.get("qcode"), exc)
					if page >= _pages(payload):
						break
			else:
				if operation == "syllabus_tree":
					payload = adapter.fetch_syllabus_tree(filters)
					_record_metric(metrics, "get_conteudos_arvore", received=1)
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
								_record_metric(metrics, "get_conteudos_arvore", failed=1)
								run.error_log = _append_error(run.error_log, doctype, row.get("id") or row.get("codigo"), exc)
				elif operation == "contest_status":
					_sync_concurso_status(adapter, metrics)
				elif operation == "create_flashcards":
					result = _push_local_flashcards(adapter, metrics)
					totals["created"] += result["created"]
					totals["updated"] += result["updated"]
					totals["errors"] += result["failed"]
				else:
					result = _sync_paginated(
						adapter, operation, doctype, kind, settings, max_pages, filters, start_page=start_page, run=run,
						request_offset=prior_requests, credit_offset=prior_credits, metrics=metrics,
					)
					for key in totals:
						totals[key] += result[key]
			run.requests_made = prior_requests + adapter.requests_made
			run.credits_used = prior_credits + adapter.credits_used
			run.records_received = sum(item.get("received", 0) for item in metrics.values())
			run.endpoint_metrics = json.dumps(metrics, ensure_ascii=False)
		run.records_created = totals["created"]
		run.records_updated = totals["updated"]
		run.records_skipped = totals["skipped"]
		run.records_errors = totals["errors"]
		run.save(ignore_permissions=True)
		frappe.db.commit()
		if not resume_reached:
			frappe.throw("The saved resume step is no longer enabled in the current settings.")
		run.status = "Partial" if totals["errors"] else "Completed"
		run.resume_operation = None
		run.resume_page = 0
		settings.last_qapi_sync_at = frappe.utils.now_datetime()
		settings.save(ignore_permissions=True)
		return {**totals, "requests_made": run.requests_made, "requests_this_attempt": adapter.requests_made,
				"endpoint_metrics": metrics}
	except QAPIBudgetError as exc:
		run.status = "Partial" if prior_requests + adapter.requests_made else "Blocked"
		run.error_log = _append_error(run.error_log, run.current_operation, run.page, exc)
		return {**totals, "partial": bool(run.requests_made), "blocked": not bool(run.requests_made),
				"requests_made": prior_requests + adapter.requests_made, "endpoint_metrics": metrics}
	except Exception as exc:
		run.status = "Failed"
		run.error_log = _append_error(run.error_log, run.current_operation, run.page, exc)
		frappe.log_error(f"{type(exc).__name__}: {str(exc)[:300]}", "Trivia Sync · QAPI ingestion")
		raise
	finally:
		run.finished_at = frappe.utils.now_datetime()
		if adapter:
			run.requests_made = prior_requests + adapter.requests_made
			run.credits_used = prior_credits + adapter.credits_used
		run.records_received = sum(item.get("received", 0) for item in metrics.values())
		run.endpoint_metrics = json.dumps(metrics, ensure_ascii=False)
		run.records_created = totals["created"]
		run.records_updated = totals["updated"]
		run.records_skipped = totals["skipped"]
		run.records_errors = totals["errors"]
		run.save(ignore_permissions=True)
		frappe.db.commit()

def sync_qapi_full():
	return ingest_source("QAPI")
