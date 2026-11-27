import importlib
import sys
import time
import types
import unittest
from unittest.mock import patch


class TestBackgroundDispatcher(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe = sys.modules.setdefault("frappe", types.SimpleNamespace())
		frappe.session = types.SimpleNamespace(user="admin@example.com")
		frappe.local = types.SimpleNamespace(site=None)
		frappe.utils = types.SimpleNamespace(now_datetime=lambda: "2026-11-27 19:20:00")
		frappe.log_error = lambda *a, **k: None
		cls.module = importlib.import_module("trivia_sync.integrations.background")

	def test_create_sync_run_inserts_queued_run_with_ignore_validate(self):
		inserted = []

		class FakeRun:
			def __init__(self):
				self.name = "RUN-QUEUED-1"
				self.flags = types.SimpleNamespace(ignore_validate=False)

			def insert(self, ignore_permissions=False):
				inserted.append(self)

		frappe = self.module.frappe
		frappe.new_doc = lambda dt: FakeRun()
		frappe.db = types.SimpleNamespace(commit=lambda: None)

		name = self.module.create_sync_run(
			source="Athena",
			operation="Create LMS Course",
			status="Queued",
			current_operation="Na fila: Direito Administrativo",
		)
		self.assertEqual(name, "RUN-QUEUED-1")
		self.assertEqual(len(inserted), 1)
		self.assertTrue(inserted[0].flags.ignore_validate)
		self.assertEqual(inserted[0].status, "Queued")
		self.assertEqual(inserted[0].source, "Athena")

	def test_dispatch_uses_rq_when_worker_is_online(self):
		enqueued = {}

		def fake_enqueue(target, **kwargs):
			enqueued["target"] = target
			enqueued["kwargs"] = kwargs
			return types.SimpleNamespace(id="rq-123")

		frappe = self.module.frappe
		frappe.enqueue = fake_enqueue

		with patch.object(self.module, "has_active_rq_worker", return_value=True):
			res = self.module.dispatch_background_job(
				"some.module.fn",
				kwargs={"x": 42},
				queue="long",
				job_name="job-1",
				run_name="RUN-1",
			)
		self.assertEqual(res["executor"], "rq")
		self.assertEqual(res["run"], "RUN-1")
		self.assertEqual(enqueued["kwargs"]["x"], 42)

	def test_dispatch_falls_back_to_local_thread_when_no_rq_worker_and_marks_failed_on_error(self):
		executed = []
		failed_updates = []

		def sample_job(val):
			executed.append(val)

		def failing_job():
			raise RuntimeError("boom in thread")

		frappe = self.module.frappe
		frappe.local = types.SimpleNamespace(site=None)
		frappe.db = types.SimpleNamespace(
			commit=lambda: None,
			rollback=lambda: None,
			get_value=lambda dt, name, field: "Running",
			set_value=lambda dt, name, values, **kw: failed_updates.append((name, values)),
		)

		with patch.object(self.module, "has_active_rq_worker", return_value=False):
			res = self.module.dispatch_background_job(
				sample_job,
				kwargs={"val": "done-in-thread"},
				run_name="RUN-OK",
			)
			for _ in range(40):
				if executed:
					break
				time.sleep(0.01)
			self.assertEqual(res["executor"], "local_thread")
			self.assertEqual(executed, ["done-in-thread"])

			self.module.dispatch_background_job(
				failing_job,
				run_name="RUN-FAIL",
			)
			for _ in range(40):
				if failed_updates:
					break
				time.sleep(0.01)
			self.assertEqual(failed_updates[0][0], "RUN-FAIL")
			self.assertEqual(failed_updates[0][1]["status"], "Failed")
			self.assertIn("boom in thread", failed_updates[0][1]["error_log"])


if __name__ == "__main__":
	unittest.main()
