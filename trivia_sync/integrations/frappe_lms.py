import json
from typing import Any

import frappe
import requests


def settings():
	return frappe.get_single("Trivia Sync Settings")


def _published_filter(doc):
	return {"published": 1} if doc.only_published else {}


def build_lms_payload():
	doc = settings()
	tracks = []
	subjects = {}
	courses = frappe.get_all(
		"LMS Course",
		filters=_published_filter(doc),
		fields=["name", "title", "description", "short_introduction"],
		order_by="modified asc",
	)
	for course in courses:
		course_doc = frappe.get_doc("LMS Course", course.name)
		modules = []
		chapters = sorted(course_doc.chapters or [], key=lambda row: row.idx or 0)
		for chapter_ref in chapters:
			chapter = frappe.get_doc("Course Chapter", chapter_ref.chapter)
			subject = chapter.title or "Conhecimentos gerais"
			subjects[subject] = {"name": subject}
			lessons = sorted(chapter.lessons or [], key=lambda row: row.idx or 0)
			for index, lesson_ref in enumerate(lessons, start=1):
				lesson = frappe.get_doc("Course Lesson", lesson_ref.lesson)
				modules.append(
					{
						"title": lesson.title,
						"subject": subject,
						"type": "questoes" if lesson.quiz_id else ("video" if lesson.youtube else "aula"),
						"durationMinutes": 25,
						"orderIndex": index,
						"url": lesson.youtube or None,
						"source": "frappe-lms",
						"sourceId": lesson.name,
					}
				)
		tracks.append(
			{
				"title": course_doc.title,
				"exam": "Frappe LMS",
				"layer": "trivia",
				"description": course_doc.short_introduction
				or course_doc.description
				or "Conteúdo do Frappe LMS.",
				"source": "frappe-lms",
				"sourceId": course_doc.name,
				"modules": modules,
			}
		)
	return {"subjects": list(subjects.values()), "tracks": tracks, "questions": []}


def sync_existing_lms_to_trivia():
	doc = settings()
	payload = build_lms_payload()
	run = frappe.new_doc("Trivia Sync Run")
	run.source, run.operation, run.status, run.started_at = (
		"Frappe LMS",
		"Push LMS content",
		"Running",
		frappe.utils.now_datetime(),
	)
	run.insert(ignore_permissions=True)
	try:
		if doc.trivia_sync_mode == "Dry run":
			result = {
				"dry_run": True,
				"tracks": len(payload["tracks"]),
				"modules": sum(len(t.get("modules", [])) for t in payload["tracks"]),
			}
		else:
			if not doc.trivia_api_url:
				raise frappe.ValidationError("Configure a URL da API da trivia360.")
			token = doc.get_password("trivia_api_token") if doc.trivia_api_token else ""
			response = requests.post(
				doc.trivia_api_url.rstrip("/"),
				json=payload,
				headers={
					"Accept": "application/json",
					"Content-Type": "application/json",
					"X-Trivia-Sync-Token": token,
				},
				timeout=60,
			)
			response.raise_for_status()
			result = response.json()
		run.status = "Completed"
		run.records_created = len(payload["tracks"])
		run.records_updated = sum(len(track.get("modules", [])) for track in payload["tracks"])
		doc.last_lms_sync_at = frappe.utils.now_datetime()
		doc.save(ignore_permissions=True)
		return result
	except Exception:
		run.status = "Failed"
		run.error_log = frappe.get_traceback()
		frappe.log_error(frappe.get_traceback(), "Trivia Sync · LMS sync")
		raise
	finally:
		run.finished_at = frappe.utils.now_datetime()
		run.save(ignore_permissions=True)
		frappe.db.commit()
