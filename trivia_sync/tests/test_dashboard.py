import importlib
import json
import sys
import types
import unittest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch


class TestDashboard(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		sys.modules.setdefault("frappe", types.SimpleNamespace())
		cls.module = importlib.import_module("trivia_sync.dashboard")

	def test_metrics_are_role_gated_and_return_operational_aggregates(self):
		frappe = self.module.frappe
		now = datetime(2026, 11, 6, 12)
		run = types.SimpleNamespace(
			name="RUN-1", source="QAPI", operation="full", status="Partial", started_at=now,
			finished_at=None, page=2, records_created=4, records_updated=1, records_skipped=0,
			records_errors=1, requests_made=5, request_budget=10, credit_reserve=2,
			current_operation="questions", resume_operation="questions", resume_page=3,
		)
		old_pending = types.SimpleNamespace(creation=now - timedelta(days=3, hours=2))
		latest = types.SimpleNamespace(**{key: getattr(run, key) for key in (
			"name", "status", "started_at", "finished_at", "requests_made", "request_budget",
			"credit_reserve", "current_operation", "resume_operation", "resume_page",
		)})
		cargo = types.SimpleNamespace(name="CC-1", concurso="CON-1", cargo="Cargo A", lms_course="COURSE-1")
		with patch.object(frappe, "only_for") as only_for, patch.object(
			frappe.db, "count", side_effect=[10, 6, 3, 2, 1, 4, 5, 6, 7, 8]
		), patch.object(frappe.db, "sql", side_effect=[[], [types.SimpleNamespace(average=3.5)], [[8]]]), patch.object(
			frappe, "get_all", side_effect=[[run], [old_pending], [latest], [cargo]]
		), patch.object(
			frappe, "get_single", return_value=types.SimpleNamespace(
				qapi_enabled=1, last_qapi_sync_at=now, qapi_max_requests_per_run=10,
				qapi_min_credit_reserve=2,
			)
		), patch.object(frappe.utils, "now_datetime", return_value=now), patch.object(
			self.module, "question_coverage", return_value={
				"total": 8, "eligible": 3, "subject": {}, "topic": {}, "review": {"Pending": 2},
				"license": {}, "source": {},
			}
		):
			result = self.module.metrics()

		only_for.assert_called_once_with(("System Manager", "Trivia Reviewer", "Trivia Integrator", "Trivia Editor"))
		self.assertEqual(result["editorial"]["oldest_pending_days"], 3)
		self.assertEqual(result["editorial"]["projection_failed"], 1)
		self.assertEqual(result["source_sync"]["last_run"].resume_page, 3)
		self.assertEqual(result["source_sync"]["request_budget"], 10)
		self.assertEqual(result["syllabus_coverage"][0]["eligible"], 3)
		self.assertNotIn("raw_payload", repr(result))
		self.assertNotIn("api_key", repr(result))

	def test_workspace_roles_can_read_each_linked_doctype(self):
		root = Path(__file__).resolve().parents[1] / "trivia_sync"
		workspace = json.loads((root / "workspace/concursos/concursos.json").read_text())
		roles = {row["role"] for row in workspace["roles"]}
		doctypes = {
			data["name"]: data
			for path in (root / "doctype").glob("*/**/*.json")
			for data in [json.loads(path.read_text())]
			if data.get("doctype") == "DocType"
		}
		for link in (row for row in workspace["links"] if row["type"] == "Link" and row["link_type"] == "DocType"):
			permissions = {row["role"]: row.get("read", 0) for row in doctypes[link["link_to"]].get("permissions", [])}
			for role in roles:
				self.assertTrue(permissions.get(role), f"{role} cannot read {link['link_to']}")


if __name__ == "__main__":
	unittest.main()
