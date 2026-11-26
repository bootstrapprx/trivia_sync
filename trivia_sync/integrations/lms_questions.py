import hashlib
import html
import json
import re

import frappe

from trivia_sync.integrations.reconciliation import reconcile_question_classification

OPTION_LETTERS = "ABCDEFGHIJ"

_PASSAGE_RE = re.compile(r'<div class="trivia-supporting-passage">[\s\S]*?</div>\s*<hr\s*/?>\s*', re.IGNORECASE)
_KNOWLEDGE_RE = re.compile(r'<div class="trivia-knowledge-refs">[\s\S]*?</div>\s*$', re.IGNORECASE)


MAX_TITLE_CHARS = 135


def strip_question_embeds(question_html: str) -> str:
	text = _PASSAGE_RE.sub("", str(question_html or ""))
	text = _KNOWLEDGE_RE.sub("", text)
	return text.strip()


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
	"""doc_events hook (`before_validate`) keeping `LMS Question.trivia_title` concise and clearing pending key on manual edit."""
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


def compose_lms_question_html(base_html: str, texto_apoio: str | None = None, knowledge_rows=None) -> str:
	clean = strip_question_embeds(base_html)
	if texto_apoio and hasattr(frappe, "db") and frappe.db.exists("Trivia Supporting Text", texto_apoio):
		passage = frappe.db.get_value("Trivia Supporting Text", texto_apoio, "conteudo")
		if passage:
			clean = f'<div class="trivia-supporting-passage"><p><strong>Texto de apoio</strong></p>{passage}</div><hr>{clean}'

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
		exp = str(getattr(doc, f"explanation_{idx}", None) or "").strip()
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
			or getattr(doc, f"explanation_{idx}", None)
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
