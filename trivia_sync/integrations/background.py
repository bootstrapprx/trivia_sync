import importlib
import json
import os
import socket
import threading
import traceback
import uuid
from collections.abc import Callable
from typing import Any

import frappe


def set_ignore_validate(doc) -> None:
	flags = getattr(doc, "flags", None)
	if flags is not None:
		flags.ignore_validate = True


def create_sync_run(
	source: str,
	operation: str,
	status: str = "Queued",
	current_operation: str = "",
	parameters: dict[str, Any] | None = None,
	records_received: int = 0,
) -> str:
	"""Create and immediately commit a Trivia Sync Run so the Dashboard reflects queued/running work right away."""
	run = frappe.new_doc("Trivia Sync Run")
	run.source = source
	run.operation = str(operation or "")[:140]
	run.status = status
	user = getattr(getattr(frappe, "session", None), "user", None)
	if user:
		run.operator = user
	if status == "Running" and hasattr(frappe, "utils") and hasattr(frappe.utils, "now_datetime"):
		run.started_at = frappe.utils.now_datetime()
	if current_operation:
		run.current_operation = str(current_operation)[:140]
	if records_received:
		run.records_received = int(records_received)
	if parameters is not None:
		run.parameters_json = json.dumps(parameters, ensure_ascii=False, default=str)
	set_ignore_validate(run)
	run.insert(ignore_permissions=True)
	if hasattr(frappe, "db") and hasattr(frappe.db, "commit"):
		frappe.db.commit()
	return run.name


def has_active_rq_worker(queue: str = "long") -> bool:
	"""Return True iff at least one live RQ worker process is actively listening on `queue`."""
	try:
		from frappe.utils.background_jobs import generate_qname, get_redis_conn
		from rq import Worker
	except Exception:
		return False

	try:
		conn = get_redis_conn()
		target_qnames = {queue, generate_qname(queue)}
		local_host = socket.gethostname()
		for worker in Worker.all(connection=conn):
			state = getattr(worker, "get_state", lambda: getattr(worker, "state", ""))()
			if state == "suspended":
				continue
			worker_queues = set(worker.queue_names() or [])
			if not (worker_queues & target_qnames):
				continue
			w_host = getattr(worker, "hostname", None)
			w_pid = getattr(worker, "pid", None)
			if w_host and w_pid and w_host == local_host:
				try:
					os.kill(int(w_pid), 0)
				except OSError:
					continue
			return True
	except Exception:
		return False
	return False


def _resolve_callable(target: str | Callable) -> Callable:
	if callable(target):
		return target
	if hasattr(frappe, "get_attr"):
		try:
			return frappe.get_attr(target)
		except Exception:
			pass
	mod_name, _, attr_name = str(target).rpartition(".")
	mod = importlib.import_module(mod_name)
	return getattr(mod, attr_name)


def _mark_run_failed_safely(run_name: str | None, tb: str) -> None:
	if not run_name or not hasattr(frappe, "db"):
		return
	try:
		current_status = frappe.db.get_value("Trivia Sync Run", run_name, "status")
		if current_status in ("Queued", "Running", None):
			now = frappe.utils.now_datetime() if hasattr(frappe, "utils") else None
			frappe.db.set_value(
				"Trivia Sync Run",
				run_name,
				{
					"status": "Failed",
					"error_log": tb,
					"current_operation": "Falhou durante execução em segundo plano",
					"finished_at": now,
				},
				update_modified=False,
			)
			frappe.db.commit()
	except Exception:
		pass


def dispatch_background_job(
	target: str | Callable,
	*,
	kwargs: dict[str, Any] | None = None,
	queue: str = "long",
	timeout: int = 3600,
	job_name: str | None = None,
	run_name: str | None = None,
) -> dict[str, Any]:
	"""Dispatch via Frappe RQ if a worker is online on `queue`; otherwise execute in an isolated daemon thread."""
	call_kwargs = dict(kwargs or {})
	final_job_name = job_name or f"trivia_sync_{uuid.uuid4().hex[:10]}"

	if has_active_rq_worker(queue):
		job = frappe.enqueue(
			target,
			queue=queue,
			timeout=timeout,
			job_name=final_job_name,
			enqueue_after_commit=False,
			**call_kwargs,
		)
		return {
			"queued": True,
			"executor": "rq",
			"queue": queue,
			"job": final_job_name,
			"job_id": getattr(job, "id", None),
			"run": run_name,
		}

	site = getattr(getattr(frappe, "local", None), "site", None)
	user = getattr(getattr(frappe, "session", None), "user", None) or "Administrator"

	def _thread_entry() -> None:
		initialized_site = False
		try:
			if site and hasattr(frappe, "init") and hasattr(frappe, "connect"):
				frappe.init(site=site)
				frappe.connect()
				initialized_site = True
				if hasattr(frappe, "set_user"):
					frappe.set_user(user)
			fn = _resolve_callable(target)
			fn(**call_kwargs)
			if hasattr(frappe, "db") and hasattr(frappe.db, "commit"):
				frappe.db.commit()
		except Exception:
			tb = traceback.format_exc()
			try:
				if hasattr(frappe, "db") and hasattr(frappe.db, "rollback"):
					frappe.db.rollback()
				if hasattr(frappe, "log_error"):
					frappe.log_error(tb, f"Trivia Sync · background thread · {final_job_name}")
				_mark_run_failed_safely(run_name, tb)
			except Exception:
				pass
		finally:
			if initialized_site and hasattr(frappe, "destroy"):
				try:
					frappe.destroy()
				except Exception:
					pass

	worker_thread = threading.Thread(target=_thread_entry, name=final_job_name[:60], daemon=True)
	worker_thread.start()
	return {
		"queued": True,
		"executor": "local_thread",
		"queue": queue,
		"job": final_job_name,
		"job_id": final_job_name,
		"run": run_name,
	}
