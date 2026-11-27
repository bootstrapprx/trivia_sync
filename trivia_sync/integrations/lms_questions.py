import hashlib
import html
import json
import re
from urllib.parse import quote

import frappe

from trivia_sync.integrations.reconciliation import reconcile_question_classification

OPTION_LETTERS = "ABCDEFGHIJ"

_DEPRECATED_BANNER_RE = re.compile(r'<div class="trivia-deprecated-banner">[\s\S]*?</div>\s*', re.IGNORECASE)
_PASSAGE_RE = re.compile(r'<div class="trivia-supporting-passage">[\s\S]*?</div>\s*<hr\s*/?>\s*', re.IGNORECASE)
_KNOWLEDGE_RE = re.compile(r'<div class="trivia-knowledge-refs">[\s\S]*?</div>\s*$', re.IGNORECASE)
_DEEP_DIVE_RE = re.compile(r'\s*<details class="trivia-deep-dive">[\s\S]*?</details>\s*$', re.IGNORECASE)


MAX_TITLE_CHARS = 135


def strip_question_embeds(question_html: str) -> str:
	text = _DEPRECATED_BANNER_RE.sub("", str(question_html or ""))
	text = _PASSAGE_RE.sub("", text)
	text = _KNOWLEDGE_RE.sub("", text)
	return text.strip()


def build_deprecated_banner_html(
	deprecated_law: str | None = None,
	replacement_law: str | None = None,
	deprecation_note: str | None = None,
) -> str:
	old_law = str(deprecated_law or "").strip()
	new_law = str(replacement_law or "").strip()
	note = str(deprecation_note or "").strip()
	parts = [
		"<strong>Questão depreciada · estudo opcional (não obrigatória)</strong>"
	]
	if old_law and new_law:
		parts.append(f"<span>Baseada em <em>{html.escape(old_law)}</em> → substituída por <em>{html.escape(new_law)}</em>.</span>")
	elif old_law:
		parts.append(f"<span>Baseada em norma revogada/superada: <em>{html.escape(old_law)}</em>.</span>")
	elif new_law:
		parts.append(f"<span>Substituída pela legislação vigente: <em>{html.escape(new_law)}</em>.</span>")
	if note:
		parts.append(f"<span>{html.escape(note)}</span>")
	return f'<div class="trivia-deprecated-banner">{" ".join(parts)}</div>'


def strip_teacher_comment_embed(explanation_html: str) -> str:
	return _DEEP_DIVE_RE.sub("", str(explanation_html or "")).strip()


def _sanitize_portal_html(raw_html: str) -> str:
	text = str(raw_html or "").strip()
	if not text:
		return ""
	try:
		if hasattr(frappe, "utils") and hasattr(frappe.utils, "sanitize_html"):
			return frappe.utils.sanitize_html(text)
	except Exception:
		pass
	return text


def _has_meaningful_html(raw_html: str) -> bool:
	plain = html.unescape(re.sub(r"<[^>]+>", " ", str(raw_html or "")))
	return bool(re.sub(r"\s+", " ", plain).strip())


def compose_correct_explanation_html(
	base_explanation: str,
	question_name: str | None,
	teacher_comment: str | None,
) -> str:
	clean_base = strip_teacher_comment_embed(base_explanation)
	if not question_name or not _has_meaningful_html(teacher_comment or ""):
		return clean_base
	safe_comment = _sanitize_portal_html(teacher_comment or "")
	deep_dive_url = f"/aprofundar?q={quote(str(question_name), safe='')}"
	block = (
		'<details class="trivia-deep-dive">'
		"<summary>Aprofunde seu conhecimento</summary>"
		f'<div class="trivia-deep-dive-body">{safe_comment}</div>'
		'<div class="trivia-deep-dive-cta">'
		f'<a href="{deep_dive_url}" target="_blank" rel="noopener">'
		"Responder desafio com a Athena / Abrir página completa ↗"
		"</a>"
		"</div>"
		"</details>"
	)
	return f"{clean_base}\n{block}" if clean_base else block


def sync_lms_question_deep_dive_embeds(doc) -> None:
	"""Keep the collapsible 'Aprofunde seu conhecimento' block synced exclusively on correct option(s)."""
	teacher_comment = getattr(doc, "trivia_general_explanation", None) or ""
	question_name = getattr(doc, "name", None)
	answer_key_pending = bool(getattr(doc, "trivia_answer_key_pending", 0))
	should_embed = bool(question_name and not answer_key_pending and _has_meaningful_html(teacher_comment))

	for idx in range(1, len(OPTION_LETTERS) + 1):
		raw_exp = getattr(doc, f"explanation_{idx}", None) or ""
		clean_exp = strip_teacher_comment_embed(raw_exp)
		opt_text = str(getattr(doc, f"option_{idx}", None) or "").strip()
		is_correct = bool(int(getattr(doc, f"is_correct_{idx}", 0) or 0))
		if should_embed and opt_text and is_correct:
			new_exp = compose_correct_explanation_html(clean_exp, question_name, teacher_comment)
		else:
			new_exp = clean_exp
		if new_exp != raw_exp:
			doc.set(f"explanation_{idx}", new_exp)


def build_question_title(question_html: str, fallback: str = "") -> str:
	"""Build a clean <=135-char plain-text title for LMS Question (safe for Tag Link, ToDo, List View)."""
	clean = strip_question_embeds(question_html)
	plain = html.unescape(re.sub(r"<[^>]+>", " ", clean))
	plain = re.sub(r"\s+", " ", plain).strip()
	if not plain:
		plain = re.sub(r"\s+", " ", str(fallback or "Questão")).strip()
	if len(plain) > MAX_TITLE_CHARS:
		return plain[: MAX_TITLE_CHARS - 1].rstrip() + "…"
	return plain


def sync_lms_question_title(doc, method=None):
	"""doc_events hook (`before_validate`) keeping `LMS Question.trivia_title` concise, clearing pending key, and syncing deep-dive embeds."""
	fallback = getattr(doc, "trivia_qcode", None) or getattr(doc, "name", None) or "Questão"
	doc.trivia_title = build_question_title(getattr(doc, "question", "") or "", fallback=fallback)
	if (
		getattr(doc, "trivia_answer_key_pending", 0)
		and hasattr(doc, "is_new")
		and not doc.is_new()
		and hasattr(doc, "has_value_changed")
		and any(doc.has_value_changed(f"is_correct_{i}") for i in range(1, 11))
	):
		doc.trivia_answer_key_pending = 0
	sync_lms_question_deep_dive_embeds(doc)
	if hasattr(doc, "question") and doc.question is not None:
		without_banner = _DEPRECATED_BANNER_RE.sub("", str(doc.question or "")).strip()
		if int(getattr(doc, "trivia_deprecated", 0) or 0):
			banner = build_deprecated_banner_html(
				deprecated_law=getattr(doc, "trivia_deprecated_law", None),
				replacement_law=getattr(doc, "trivia_replacement_law", None),
				deprecation_note=getattr(doc, "trivia_deprecation_note", None),
			)
			doc.question = f"{banner}{without_banner}"
		elif without_banner != str(doc.question or "").strip():
			doc.question = without_banner


def sync_deprecated_quiz_marks(doc, method=None):
	"""When a question is marked deprecated, zero its weight (marks=0) in linked LMS Quizzes so it never penalizes scores."""
	if not int(getattr(doc, "trivia_deprecated", 0) or 0) or not getattr(doc, "name", None):
		return
	if not hasattr(frappe, "db") or not frappe.db.exists("DocType", "LMS Quiz Question"):
		return
	rows = frappe.get_all(
		"LMS Quiz Question",
		filters={"question": doc.name, "marks": ["!=", 0]},
		fields=["name", "parent"],
	) or []
	if not rows:
		return
	affected_quizzes = set()
	for row in rows:
		frappe.db.set_value("LMS Quiz Question", row["name"], "marks", 0, update_modified=False)
		if row.get("parent"):
			affected_quizzes.add(row["parent"])
	for quiz_name in affected_quizzes:
		try:
			quiz_rows = frappe.get_all("LMS Quiz Question", filters={"parent": quiz_name}, pluck="marks") or []
			total_marks = sum(int(m or 0) for m in quiz_rows)
			frappe.db.set_value("LMS Quiz", quiz_name, "total_marks", total_marks, update_modified=False)
		except Exception:
			pass


def compose_lms_question_html(
	base_html: str,
	texto_apoio: str | None = None,
	knowledge_rows=None,
	deprecated: bool = False,
	deprecated_law: str | None = None,
	replacement_law: str | None = None,
	deprecation_note: str | None = None,
) -> str:
	clean = strip_question_embeds(base_html)
	if texto_apoio and hasattr(frappe, "db") and frappe.db.exists("Trivia Supporting Text", texto_apoio):
		passage = frappe.db.get_value("Trivia Supporting Text", texto_apoio, "conteudo")
		if passage:
			clean = f'<div class="trivia-supporting-passage"><p><strong>Texto de apoio</strong></p>{passage}</div><hr>{clean}'
	if deprecated:
		banner = build_deprecated_banner_html(
			deprecated_law=deprecated_law,
			replacement_law=replacement_law,
			deprecation_note=deprecation_note,
		)
		clean = f"{banner}{clean}"

	names = [
		getattr(row, "knowledge_page", None) if not isinstance(row, dict) else row.get("knowledge_page")
		for row in (knowledge_rows or [])
	]
	names = [n for n in names if n]
	if names and hasattr(frappe, "get_all"):
		pages = frappe.get_all(
			"Trivia Knowledge Page",
			filters={"name": ["in", names], "status": "Published"},
			fields=["name", "title", "slug"],
		) or []
		by_name = {p.get("name"): p for p in pages}
		ordered = [by_name[n] for n in names if n in by_name and by_name[n].get("slug")]
		if ordered:
			anchors = " · ".join(
				f'<a href="/conhecimento?slug={html.escape(p["slug"])}" target="_blank" rel="noopener">{html.escape(p["title"])}</a>'
				for p in ordered
			)
			clean = f'{clean}<div class="trivia-knowledge-refs"><small><strong>Conceitos relacionados:</strong> {anchors}</small></div>'
	return clean


def extract_lms_question_options(doc) -> tuple[dict[str, str], list[str], dict[str, str]]:
	options: dict[str, str] = {}
	correct: list[str] = []
	explanations: dict[str, str] = {}
	for idx, letter in enumerate(OPTION_LETTERS, start=1):
		val = str(getattr(doc, f"option_{idx}", None) or "").strip()
		if not val:
			continue
		options[letter] = val
		if int(getattr(doc, f"is_correct_{idx}", 0) or 0):
			correct.append(letter)
		exp = strip_teacher_comment_embed(getattr(doc, f"explanation_{idx}", None) or "")
		if exp:
			explanations[letter] = exp
	return options, correct, explanations


def apply_explanations_to_lms_question(doc, explanations_by_letter: dict[str, str]) -> int:
	filled = 0
	total = 0
	for idx, letter in enumerate(OPTION_LETTERS, start=1):
		opt_val = str(getattr(doc, f"option_{idx}", None) or "").strip()
		if not opt_val:
			continue
		total += 1
		text = str(
			explanations_by_letter.get(letter)
			or explanations_by_letter.get(letter.lower())
			or strip_teacher_comment_embed(getattr(doc, f"explanation_{idx}", None) or "")
			or ""
		).strip()
		doc.set(f"explanation_{idx}", text)
		if text:
			filled += 1
	if total >= 2 and filled == total and not getattr(doc, "trivia_answer_key_pending", 0):
		doc.trivia_status = "Ready"
	return filled


def is_lms_question_treated(doc) -> bool:
	if getattr(doc, "trivia_status", None) == "Ready":
		return True
	if getattr(doc, "trivia_ai_enriched_at", None):
		return True
	_, correct, explanations = extract_lms_question_options(doc)
	wrong_explained = [k for k, v in explanations.items() if k not in set(correct) and v]
	if wrong_explained:
		return True
	if getattr(doc, "name", None) and hasattr(frappe, "db") and frappe.db.exists("LMS Quiz Question", {"question": doc.name}):
		return True
	return False


def disambiguate_option_pairs(ordered: list[tuple[str, str]]) -> list[tuple[str, str]]:
	seen: set[str] = set()
	result: list[tuple[str, str]] = []
	for letter, text in ordered:
		candidate = text
		if candidate in seen:
			candidate = f"{text} ({letter})"
		seen.add(candidate)
		result.append((letter, candidate))
	return result


def _parse_normalized_options(data: dict) -> tuple[list[tuple[str, str]], set[str]]:
	raw_opts = data.get("options") or "{}"
	opts = json.loads(raw_opts) if isinstance(raw_opts, str) else raw_opts
	if not isinstance(opts, dict):
		frappe.throw("Invalid question options payload.")
	ordered = [
		(str(k).upper(), str(v).strip())
		for k, v in sorted(opts.items())
		if str(k).upper() in OPTION_LETTERS and str(v or "").strip()
	]
	if not 2 <= len(ordered) <= 10:
		frappe.throw("Choice questions must have between 2 and 10 non-empty options.")
	ordered = disambiguate_option_pairs(ordered)
	raw_corr = data.get("correct_options") or "[]"
	corr_list = json.loads(raw_corr) if isinstance(raw_corr, str) else raw_corr
	correct = {str(x).upper() for x in (corr_list or []) if x}
	if not correct and data.get("correct_option"):
		correct = {str(data["correct_option"]).upper()}
	valid_letters = {k for k, _ in ordered}
	if not correct or not correct.issubset(valid_letters):
		frappe.throw("Question answer key does not match available options.")
	return ordered, correct


def upsert_qapi_lms_question(data: dict, texto_name: str | None = None, force_reformat: bool = False) -> str:
	ordered_options, correct_letters = _parse_normalized_options(data)
	source_key = data.get("source_key")
	qcode = data.get("qcode")

	existing_name = None
	if source_key:
		existing_name = frappe.db.get_value("LMS Question", {"trivia_source_key": source_key}, "name")
	if not existing_name and qcode:
		existing_name = frappe.db.get_value("LMS Question", {"trivia_qcode": qcode}, "name")

	sync_signature = hashlib.sha256(
		json.dumps(
			{
				"enunciado": data.get("enunciado"),
				"options": ordered_options,
				"correct": sorted(correct_letters),
				"texto_apoio": texto_name,
				"banca": data.get("banca"),
				"orgao": data.get("orgao"),
				"cargo": data.get("cargo"),
				"ano": data.get("ano"),
				"materia": data.get("materia"),
				"assunto": data.get("assunto"),
			},
			ensure_ascii=False,
			sort_keys=True,
		).encode("utf-8")
	).hexdigest()

	if existing_name:
		doc = frappe.get_doc("LMS Question", existing_name)
		if getattr(doc, "trivia_sync_hash", None) == sync_signature and not force_reformat:
			return "skipped"
		if is_lms_question_treated(doc) and not force_reformat:
			# Preserve all human/AI-treated content; only fill missing metadata
			meta_updated = False
			for attr, val in (
				("trivia_qcode", qcode),
				("trivia_source_key", source_key),
				("trivia_texto_apoio", texto_name),
				("trivia_banca", data.get("banca")),
				("trivia_orgao", data.get("orgao")),
				("trivia_cargo", data.get("cargo")),
				("trivia_ano", data.get("ano") or None),
				("trivia_materia", data.get("materia")),
				("trivia_assunto", data.get("assunto")),
				("trivia_source_url", data.get("source_url")),
				("trivia_raw_payload", data.get("raw_payload")),
			):
				if val and not getattr(doc, attr, None):
					setattr(doc, attr, val)
					meta_updated = True
			if meta_updated:
				reconcile_question_classification(doc)
				doc.save(ignore_permissions=True)
				return "updated"
			return "skipped"
	else:
		doc = frappe.new_doc("LMS Question")
		doc.trivia_status = "In Preparation"

	is_new = doc.is_new()
	doc.type = "Choices"
	doc.marks = max(1, int(data.get("marks") or 1))
	doc.multiple = int(len(correct_letters) > 1)
	doc.trivia_source_type = data.get("source_type") or "QAPI"
	doc.trivia_qcode = qcode
	doc.trivia_source_key = source_key
	doc.trivia_texto_apoio = texto_name or getattr(doc, "trivia_texto_apoio", None)
	doc.trivia_banca = data.get("banca")
	doc.trivia_orgao = data.get("orgao")
	doc.trivia_cargo = data.get("cargo")
	doc.trivia_ano = data.get("ano") or None
	doc.trivia_materia = data.get("materia")
	doc.trivia_assunto = data.get("assunto")
	doc.trivia_source_url = data.get("source_url")
	doc.trivia_source_license = data.get("source_license")
	doc.trivia_source_attribution = data.get("source_attribution")
	doc.trivia_source_authors = data.get("source_authors")
	doc.trivia_detected_option_count = len(ordered_options)
	doc.trivia_raw_payload = data.get("raw_payload")
	doc.trivia_sync_hash = sync_signature

	general_exp = str(data.get("explanation") or "").strip()
	if general_exp and not getattr(doc, "trivia_general_explanation", None):
		doc.trivia_general_explanation = general_exp

	doc.question = compose_lms_question_html(
		data.get("enunciado") or "",
		texto_apoio=doc.trivia_texto_apoio,
		knowledge_rows=getattr(doc, "trivia_knowledge_pages", None),
	)
	doc.trivia_title = build_question_title(doc.question, fallback=qcode or getattr(doc, "name", "") or "Questão")

	for idx in range(1, 11):
		if idx <= len(ordered_options):
			letter, opt_text = ordered_options[idx - 1]
			is_corr = int(letter in correct_letters)
			existing_exp = str(getattr(doc, f"explanation_{idx}", None) or "").strip()
			doc.set(f"option_{idx}", opt_text)
			doc.set(f"is_correct_{idx}", is_corr)
			doc.set(f"explanation_{idx}", existing_exp or (general_exp if is_corr else ""))
		else:
			doc.set(f"option_{idx}", "")
			doc.set(f"is_correct_{idx}", 0)
			doc.set(f"explanation_{idx}", "")

	reconcile_question_classification(doc)
	if is_new:
		doc.insert(ignore_permissions=True)
		return "created"
	doc.save(ignore_permissions=True)
	return "updated"


def set_lms_question_status(question_name: str, status: str) -> dict:
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	if status not in ("In Preparation", "Ready"):
		frappe.throw("Invalid question preparation status.")
	doc = frappe.get_doc("LMS Question", question_name)
	doc.trivia_status = status
	doc.question = compose_lms_question_html(
		doc.question,
		texto_apoio=getattr(doc, "trivia_texto_apoio", None),
		knowledge_rows=getattr(doc, "trivia_knowledge_pages", None),
	)
	sync_lms_question_title(doc)
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "trivia_status": doc.trivia_status}
