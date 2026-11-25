import hashlib
import html
import json
import re
import unicodedata

import frappe

from trivia_sync.integrations.lms_questions import (
	OPTION_LETTERS,
	build_question_title,
	compose_lms_question_html,
	disambiguate_option_pairs,
	extract_lms_question_options,
	is_lms_question_treated,
)
from trivia_sync.integrations.reconciliation import resolve_or_create_catalog

try:
	import yaml as _yaml
except ImportError:  # pragma: no cover - fallback when PyYAML is absent outside bench venv
	_yaml = None

ANNULLED_MARKERS = {"X", "*", "ANULADA", "ANULADO", "NULA", "CANCELADA", "-"}


def _slugify(value: str, max_len: int = 48) -> str:
	text = unicodedata.normalize("NFKD", str(value or "").casefold())
	text = "".join(ch for ch in text if not unicodedata.combining(ch))
	text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
	return (text or "prova")[:max_len].strip("-")


def _strip_quotes(val: str) -> str:
	s = val.strip()
	if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
		if s[0] == "'":
			return s[1:-1].replace("''", "'")
		try:
			return json.loads(s)
		except ValueError:
			return s[1:-1]
	return s


def _coerce_scalar(val: str):
	s = val.strip()
	if not s:
		return ""
	if s[0] in ("'", '"') and len(s) >= 2 and s[-1] == s[0]:
		return _strip_quotes(s)
	low = s.lower()
	if low in ("null", "none", "~"):
		return None
	if low == "true":
		return True
	if low == "false":
		return False
	if re.fullmatch(r"-?\d+", s):
		return int(s)
	return s


def _fallback_parse_yaml(text: str):
	"""Minimal indentation-based YAML parser used only when PyYAML is not installed."""
	raw_lines = text.splitlines()

	def _next_non_empty(idx: int):
		while idx < len(raw_lines):
			stripped = raw_lines[idx].strip()
			if stripped and not stripped.startswith("#"):
				return idx
			idx += 1
		return len(raw_lines)

	def _indent(line: str) -> int:
		return len(line) - len(line.lstrip(" "))

	def _read_block_scalar(start_idx: int, parent_indent: int, folded: bool) -> tuple[str, int]:
		lines = []
		block_indent = None
		i = start_idx
		while i < len(raw_lines):
			line = raw_lines[i]
			if not line.strip():
				lines.append("")
				i += 1
				continue
			ind = _indent(line)
			if ind <= parent_indent:
				break
			if block_indent is None:
				block_indent = ind
			lines.append(line[block_indent:])
			i += 1
		while lines and lines[-1] == "":
			lines.pop()
		if folded:
			out = []
			for ln in lines:
				if ln == "":
					out.append("\n\n")
				elif out and out[-1] != "\n\n":
					out.append(" " + ln)
				else:
					out.append(ln)
			return "".join(out), i
		return "\n".join(lines), i

	def _read_wrapped_scalar(first_val: str, start_idx: int, key_indent: int) -> tuple[str, int]:
		parts = [first_val]
		i = start_idx
		is_quoted = first_val.startswith("'") or first_val.startswith('"')
		quote_char = first_val[0] if is_quoted else ""
		if is_quoted and len(first_val) >= 2 and first_val.endswith(quote_char):
			return _strip_quotes(first_val), i
		while i < len(raw_lines):
			line = raw_lines[i]
			if not line.strip():
				break
			ind = _indent(line)
			if ind <= key_indent:
				break
			stripped = line.strip()
			if not is_quoted and (stripped.startswith("- ") or re.match(r"^[A-Za-z0-9_]+\s*:", stripped)):
				break
			parts.append(stripped)
			i += 1
			if is_quoted and stripped.endswith(quote_char):
				break
		joined = " ".join(parts)
		return (_strip_quotes(joined) if is_quoted else _coerce_scalar(joined)), i

	def _parse_block(start_idx: int, min_indent: int):
		i = _next_non_empty(start_idx)
		if i >= len(raw_lines) or _indent(raw_lines[i]) < min_indent:
			return None, i
		base_indent = _indent(raw_lines[i])
		if raw_lines[i].lstrip(" ").startswith("- ") or raw_lines[i].lstrip(" ") == "-":
			items = []
			while i < len(raw_lines):
				i = _next_non_empty(i)
				if i >= len(raw_lines) or _indent(raw_lines[i]) != base_indent:
					break
				content = raw_lines[i][base_indent:]
				if not (content.startswith("- ") or content == "-"):
					break
				after_dash = content[2:] if content.startswith("- ") else ""
				if not after_dash.strip():
					val, i = _parse_block(i + 1, base_indent + 1)
					items.append(val)
				elif ":" in after_dash and not after_dash.lstrip().startswith(("'", '"')):
					k, rest = after_dash.split(":", 1)
					k = k.strip()
					rest_s = rest.strip()
					obj = {}
					item_indent = base_indent + 2
					if rest_s in ("|", "|-", ">", ">-"):
						obj[k], i = _read_block_scalar(i + 1, base_indent, rest_s.startswith(">"))
					elif rest_s == "":
						obj[k], i = _parse_block(i + 1, item_indent + 1)
					else:
						obj[k], i = _read_wrapped_scalar(rest_s, i + 1, base_indent)
					# Parse remaining keys of this mapping item
					while i < len(raw_lines):
						ni = _next_non_empty(i)
						if ni >= len(raw_lines) or _indent(raw_lines[ni]) < item_indent:
							i = ni
							break
						if _indent(raw_lines[ni]) > item_indent:
							i = ni
							break
						m_line = raw_lines[ni][item_indent:]
						if ":" not in m_line:
							i = ni
							break
						mk, mrest = m_line.split(":", 1)
						mk = mk.strip()
						mrest_s = mrest.strip()
						if mrest_s in ("|", "|-", ">", ">-"):
							obj[mk], i = _read_block_scalar(ni + 1, item_indent, mrest_s.startswith(">"))
						elif mrest_s == "":
							obj[mk], i = _parse_block(ni + 1, item_indent + 1)
						else:
							obj[mk], i = _read_wrapped_scalar(mrest_s, ni + 1, item_indent)
					items.append(obj)
				else:
					val, i = _read_wrapped_scalar(after_dash.strip(), i + 1, base_indent)
					items.append(val)
			return items, i

		mapping = {}
		while i < len(raw_lines):
			i = _next_non_empty(i)
			if i >= len(raw_lines) or _indent(raw_lines[i]) != base_indent:
				break
			line_content = raw_lines[i][base_indent:]
			if line_content.startswith("- ") or ":" not in line_content:
				break
			k, rest = line_content.split(":", 1)
			k = k.strip()
			rest_s = rest.strip()
			if rest_s in ("|", "|-", ">", ">-"):
				mapping[k], i = _read_block_scalar(i + 1, base_indent, rest_s.startswith(">"))
			elif rest_s == "":
				nxt = _next_non_empty(i + 1)
				if nxt < len(raw_lines) and _indent(raw_lines[nxt]) >= base_indent and (
					_indent(raw_lines[nxt]) > base_indent or raw_lines[nxt].lstrip(" ").startswith("- ")
				):
					mapping[k], i = _parse_block(nxt, base_indent)
				else:
					mapping[k] = ""
					i += 1
			else:
				mapping[k], i = _read_wrapped_scalar(rest_s, i + 1, base_indent)
		return mapping, i

	parsed, _ = _parse_block(0, 0)
	return parsed


def parse_structured_text(raw_text: str):
	text = str(raw_text or "").strip()
	if not text:
		frappe.throw("Exam payload is empty.")
	if text[0] in ("{", "["):
		try:
			return json.loads(text)
		except ValueError:
			pass
	if _yaml is not None:
		try:
			data = _yaml.safe_load(text)
			if data is not None:
				return data
		except Exception as exc:
			frappe.throw(f"Invalid YAML/JSON exam payload: {exc}")
	data = _fallback_parse_yaml(text)
	if not isinstance(data, dict):
		frappe.throw("Exam payload must be a YAML or JSON object with 'prova' and 'questoes'.")
	return data


def parse_duration_minutes(raw_duration) -> str:
	if raw_duration in (None, ""):
		return ""
	if isinstance(raw_duration, (int, float)):
		return str(max(1, int(raw_duration)))
	text = str(raw_duration).strip().lower()
	if re.fullmatch(r"\d+", text):
		return text
	hours = 0
	minutes = 0
	hm = re.search(r"(\d+)\s*(?:h|hora|horas)", text)
	if hm:
		hours = int(hm.group(1))
	mm = re.search(r"(\d+)\s*(?:min|minuto|minutos|m\b)", text)
	if mm:
		minutes = int(mm.group(1))
	total = hours * 60 + minutes
	return str(total) if total > 0 else ""


def parse_year(raw_year=None, raw_date=None) -> int | None:
	for candidate in (raw_year, raw_date):
		if candidate in (None, ""):
			continue
		match = re.search(r"\b(19\d{2}|20\d{2}|21\d{2})\b", str(candidate))
		if match:
			return int(match.group(1))
	return None


def _normalize_answer_value(val) -> list[str]:
	if val is None:
		return []
	if isinstance(val, list):
		letters = []
		for item in val:
			letters.extend(_normalize_answer_value(item))
		return list(dict.fromkeys(letters))
	token = str(val).strip().upper()
	if not token or token in ANNULLED_MARKERS:
		return []
	if len(token) == 1 and token in OPTION_LETTERS:
		return [token]
	# Multi-letter like "A,C" or "A/C"
	parts = [p.strip() for p in re.split(r"[,;/+\s]+", token) if p.strip()]
	if parts and all(len(p) == 1 and p in OPTION_LETTERS for p in parts):
		return list(dict.fromkeys(parts))
	return []


def parse_answer_key(raw_key, total_questions: int | None = None) -> dict[int, list[str]]:
	"""Parse an answer key from dict, list, JSON/YAML, numbered pairs ('1-A 2-C'), or compact string ('ACDBE...')."""
	if raw_key in (None, ""):
		return {}

	if isinstance(raw_key, dict):
		out: dict[int, list[str]] = {}
		for k, v in raw_key.items():
			m = re.search(r"\d+", str(k))
			if not m:
				continue
			num = int(m.group(0))
			letters = _normalize_answer_value(v)
			if letters:
				out[num] = letters
		return out

	if isinstance(raw_key, list):
		out = {}
		for idx, item in enumerate(raw_key, start=1):
			letters = _normalize_answer_value(item)
			if letters:
				out[idx] = letters
		return out

	text = str(raw_key).strip()
	if not text:
		return {}

	# Ignore prose disclaimers like "Não informado no PDF enviado."
	if re.search(r"n[aã]o\s+informad|sem\s+gabarito|indispon[ií]vel", text, re.IGNORECASE):
		return {}

	# Try JSON / YAML dict or list first
	if text[0] in ("{", "["):
		try:
			parsed = json.loads(text)
			if isinstance(parsed, (dict, list)):
				return parse_answer_key(parsed, total_questions=total_questions)
		except ValueError:
			pass

	# Numbered pairs: "1-A", "01: B", "1. C", "1) D", "1 E", "1=A", "Q1: A"
	pairs = re.findall(
		r"(?:^|[\s,;|])(?:Q|QUEST[AÃ]O)?\s*0*(\d{1,3})\s*[-:=.)\s]\s*(ANULAD[AO]|NULA|CANCELADA|[A-J](?:\s*[,/+]\s*[A-J])*|[X*])(?=$|[\s,;|])",
		text.upper(),
	)
	if pairs:
		out = {}
		for num_str, ans_str in pairs:
			num = int(num_str)
			letters = _normalize_answer_value(ans_str)
			if letters:
				out[num] = letters
		return out

	# Compact sequence of letters/annulled markers (e.g. "ACDBEA..." or "A C D B E")
	compact = re.sub(r"[\s,;|/-]+", "", text.upper())
	if compact and re.fullmatch(r"[A-JX*]+", compact):
		if total_questions is None or len(compact) <= max(total_questions, 200):
			out = {}
			for idx, ch in enumerate(compact, start=1):
				if ch in OPTION_LETTERS:
					out[idx] = [ch]
			return out

	# Last resort: YAML mapping if PyYAML is installed
	if _yaml is not None and ":" in text:
		try:
			parsed = _yaml.safe_load(text)
			if isinstance(parsed, (dict, list)):
				return parse_answer_key(parsed, total_questions=total_questions)
		except Exception:
			pass

	return {}


def _text_to_html(text: str, source: str = "") -> str:
	raw = str(text or "").strip()
	if not raw:
		return ""
	if "<p" in raw.lower() or "<div" in raw.lower() or "<br" in raw.lower():
		body = raw
	else:
		paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
		body = "".join(
			f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>"
			for p in paragraphs
		)
	if source:
		body += f"<p><small><em>{html.escape(str(source).strip())}</em></small></p>"
	return body


def parse_exam_payload(raw_payload, answer_key=None) -> dict:
	"""Parse and normalize a ready-made exam payload (YAML/JSON dict or string) + optional answer key."""
	data = raw_payload if isinstance(raw_payload, dict) else parse_structured_text(raw_payload)
	if not isinstance(data, dict):
		frappe.throw("Invalid exam payload format.")

	prova = data.get("prova") if isinstance(data.get("prova"), dict) else {}
	raw_questions = data.get("questoes") or data.get("questions") or []
	if not isinstance(raw_questions, list) or not raw_questions:
		frappe.throw("Exam payload must contain a non-empty 'questoes' list.")

	raw_texts = data.get("textos_apoio") or data.get("supporting_texts") or []
	texts_by_id: dict[str, dict] = {}
	for idx, entry in enumerate(raw_texts, start=1):
		if not isinstance(entry, dict):
			continue
		tid = str(entry.get("id") or entry.get("codigo") or f"texto_{idx}").strip()
		content = str(entry.get("texto") or entry.get("conteudo") or "").strip()
		if not tid or not content:
			continue
		texts_by_id[tid] = {
			"id": tid,
			"questoes": str(entry.get("questoes") or "").strip(),
			"fonte": str(entry.get("fonte") or "").strip(),
			"texto": content,
		}

	title = str(prova.get("titulo") or data.get("titulo") or "Prova Importada").strip()
	specialty = str(prova.get("especialidade") or prova.get("cargo") or "").strip()
	caderno = str(prova.get("caderno") or "").strip()
	orgao = str(prova.get("orgao") or "").strip()
	banca = str(prova.get("banca") or "").strip()
	ano = parse_year(prova.get("ano"), prova.get("data"))
	duration_minutes = parse_duration_minutes(prova.get("duracao"))

	exam_seed = "|".join(filter(None, [title, specialty, banca, str(ano or ""), caderno]))
	exam_slug = _slugify(f"{title}-{specialty}-{ano or ''}", max_len=36)
	exam_hash = hashlib.sha1(exam_seed.encode("utf-8")).hexdigest()[:6].upper()
	exam_code = f"EX-{exam_hash}"

	# Merge answer keys: embedded prova.gabarito -> per-question gabarito -> explicit answer_key argument
	merged_answers: dict[int, list[str]] = {}
	if prova.get("gabarito") not in (None, ""):
		merged_answers.update(parse_answer_key(prova.get("gabarito"), total_questions=len(raw_questions)))

	questions: list[dict] = []
	disciplines: dict[str, int] = {}
	for idx, item in enumerate(raw_questions, start=1):
		if not isinstance(item, dict):
			continue
		numero = int(item.get("numero") or idx)
		enunciado = str(item.get("enunciado") or item.get("question") or "").strip()
		if not enunciado:
			continue
		raw_alts = item.get("alternativas") or item.get("options") or {}
		ordered_alts: list[tuple[str, str]] = []
		if isinstance(raw_alts, dict):
			for k, v in sorted(raw_alts.items()):
				letter = str(k).strip().upper()
				val = str(v if v is not None else "").strip()
				if letter in OPTION_LETTERS and val:
					ordered_alts.append((letter, val))
		elif isinstance(raw_alts, list):
			for opt_idx, v in enumerate(raw_alts[:10]):
				val = str(v.get("texto") if isinstance(v, dict) else (v if v is not None else "")).strip()
				if val:
					ordered_alts.append((OPTION_LETTERS[opt_idx], val))
		if len(ordered_alts) < 2:
			continue
		ordered_alts = disambiguate_option_pairs(ordered_alts)

		disciplina = str(item.get("disciplina") or item.get("materia") or "").strip()
		if disciplina:
			disciplines[disciplina] = disciplines.get(disciplina, 0) + 1

		q_inline_key = _normalize_answer_value(item.get("gabarito") or item.get("correta") or item.get("correct_option"))
		if q_inline_key:
			merged_answers[numero] = q_inline_key

		questions.append(
			{
				"numero": numero,
				"disciplina": disciplina,
				"assunto": str(item.get("assunto") or "").strip(),
				"texto_ou_contexto": str(item.get("texto_ou_contexto") or item.get("texto_id") or "").strip(),
				"enunciado": enunciado,
				"alternativas": ordered_alts,
				"comentario": str(item.get("comentario") or item.get("explanation") or "").strip(),
			}
		)

	if not questions:
		frappe.throw("No valid questions with at least 2 alternatives were found in the exam payload.")

	if answer_key not in (None, ""):
		explicit = parse_answer_key(answer_key, total_questions=len(questions))
		merged_answers.update(explicit)

	for q in questions:
		valid_letters = {letter for letter, _ in q["alternativas"]}
		ans = [l for l in merged_answers.get(q["numero"], []) if l in valid_letters]
		q["gabarito"] = ans
		q["answer_key_pending"] = int(not bool(ans))

	default_quiz_title = title
	if specialty and specialty.lower() not in title.lower():
		default_quiz_title = f"{title} ({specialty})"
	if ano and str(ano) not in default_quiz_title:
		default_quiz_title = f"{default_quiz_title} · {ano}"

	return {
		"exam_slug": exam_slug,
		"exam_code": exam_code,
		"quiz_title": default_quiz_title[:135],
		"prova": {
			"titulo": title,
			"especialidade": specialty,
			"orgao": orgao,
			"banca": banca,
			"ano": ano,
			"caderno": caderno,
			"duracao_minutos": duration_minutes,
		},
		"textos_apoio": texts_by_id,
		"questions": questions,
		"disciplines": disciplines,
		"answered_count": sum(1 for q in questions if not q["answer_key_pending"]),
		"pending_count": sum(1 for q in questions if q["answer_key_pending"]),
	}


def preview_ready_exam(raw_payload, answer_key=None) -> dict:
	parsed = parse_exam_payload(raw_payload, answer_key=answer_key)
	return {
		"quiz_title": parsed["quiz_title"],
		"exam_code": parsed["exam_code"],
		"prova": parsed["prova"],
		"total_questions": len(parsed["questions"]),
		"supporting_texts": len(parsed["textos_apoio"]),
		"disciplines": parsed["disciplines"],
		"answered_count": parsed["answered_count"],
		"pending_count": parsed["pending_count"],
		"sample_questions": [
			{
				"numero": q["numero"],
				"disciplina": q["disciplina"],
				"enunciado": build_question_title(q["enunciado"]),
				"alternativas": [letter for letter, _ in q["alternativas"]],
				"gabarito": q["gabarito"],
				"texto_ou_contexto": q["texto_ou_contexto"],
			}
			for q in parsed["questions"][:5]
		],
	}


def _upsert_supporting_text(exam_slug: str, exam_title: str, entry: dict) -> str:
	codigo = f"EX-{_slugify(exam_slug, 20)}-{_slugify(entry['id'], 24)}"[:80]
	source_key = f"exam:{exam_slug}:text:{entry['id']}"
	existing = frappe.db.get_value("Trivia Supporting Text", {"source_key": source_key}, "name")
	if not existing:
		existing = frappe.db.get_value("Trivia Supporting Text", {"codigo": codigo}, "name")

	label_title = f"{entry['id'].replace('_', ' ').title()}"
	if entry.get("questoes"):
		label_title = f"{label_title} (Q. {entry['questoes']})"
	if exam_title:
		label_title = f"{label_title} · {exam_title}"
	label_title = label_title[:135]

	content_html = _text_to_html(entry["texto"], source=entry.get("fonte") or "")
	if existing:
		doc = frappe.get_doc("Trivia Supporting Text", existing)
		if doc.conteudo != content_html or doc.titulo != label_title:
			doc.titulo = label_title
			doc.conteudo = content_html
			doc.save(ignore_permissions=True)
		return doc.name

	doc = frappe.new_doc("Trivia Supporting Text")
	doc.codigo = codigo
	doc.titulo = label_title
	doc.conteudo = content_html
	doc.source_type = "External"
	doc.source_id = codigo
	doc.source_key = source_key
	doc.insert(ignore_permissions=True)
	return doc.name


def import_ready_exam(
	raw_payload,
	answer_key=None,
	quiz_title: str | None = None,
	passing_percentage: int = 60,
	contest: str | None = None,
	contest_position: str | None = None,
	update_existing: bool = True,
) -> dict:
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	parsed = parse_exam_payload(raw_payload, answer_key=answer_key)
	prova = parsed["prova"]
	exam_slug = parsed["exam_slug"]
	exam_code = parsed["exam_code"]

	# 1. Create / reuse supporting texts
	supporting_text_map: dict[str, str] = {}
	for tid, entry in parsed["textos_apoio"].items():
		supporting_text_map[tid] = _upsert_supporting_text(exam_slug, prova["titulo"], entry)

	# 2. Resolve / create Trivia Subject links per discipline
	subject_link_map: dict[str, str | None] = {}
	for disc in parsed["disciplines"]:
		subject_link_map[disc] = resolve_or_create_catalog("Trivia Subject", disc)

	# 3. Create / update LMS Question records in exact exam order
	created = updated = skipped = 0
	ordered_lms_questions: list[dict] = []

	for q in parsed["questions"]:
		num = q["numero"]
		qcode = f"{exam_code}-Q{num:02d}"
		source_key = f"exam:{exam_slug}:q{num:02d}"

		existing_name = frappe.db.get_value("LMS Question", {"trivia_source_key": source_key}, "name")
		if not existing_name:
			existing_name = frappe.db.get_value("LMS Question", {"trivia_qcode": qcode}, "name")

		texto_name = supporting_text_map.get(q["texto_ou_contexto"]) if q["texto_ou_contexto"] else None
		has_answer = not q["answer_key_pending"]
		# Frappe LMS requires at least one is_correct_i == 1; use option A as placeholder only while pending
		correct_letters = set(q["gabarito"]) if has_answer else {q["alternativas"][0][0]}

		if existing_name:
			doc = frappe.get_doc("LMS Question", existing_name)
			if not update_existing or (is_lms_question_treated(doc) and not has_answer):
				skipped += 1
				ordered_lms_questions.append({"name": doc.name, "question": doc.question, "marks": int(doc.marks or 1), "type": doc.type})
				continue
			is_new = False
		else:
			doc = frappe.new_doc("LMS Question")
			doc.trivia_status = "In Preparation"
			is_new = True

		if is_new or not is_lms_question_treated(doc):
			doc.type = "Choices"
			doc.marks = 1
			doc.trivia_source_type = "External"
			doc.trivia_qcode = qcode
			doc.trivia_source_key = source_key
			doc.trivia_texto_apoio = texto_name
			doc.trivia_banca = prova["banca"]
			doc.trivia_orgao = prova["orgao"]
			doc.trivia_cargo = prova["especialidade"]
			doc.trivia_ano = prova["ano"]
			doc.trivia_materia = q["disciplina"]
			doc.trivia_subject_link = subject_link_map.get(q["disciplina"])
			if q["assunto"]:
				doc.trivia_assunto = q["assunto"]
			if contest:
				doc.trivia_concurso = contest
			if contest_position:
				doc.trivia_concurso_cargo = contest_position
			if q["comentario"] and not getattr(doc, "trivia_general_explanation", None):
				doc.trivia_general_explanation = q["comentario"]
			doc.trivia_detected_option_count = len(q["alternativas"])

			prompt_html = _text_to_html(q["enunciado"])
			doc.question = compose_lms_question_html(
				prompt_html,
				texto_apoio=texto_name,
				knowledge_rows=getattr(doc, "trivia_knowledge_pages", None),
			)
			doc.trivia_title = build_question_title(doc.question, fallback=qcode)

			for idx in range(1, 11):
				if idx <= len(q["alternativas"]):
					letter, opt_text = q["alternativas"][idx - 1]
					doc.set(f"option_{idx}", opt_text)
					doc.set(f"is_correct_{idx}", int(letter in correct_letters))
					if is_new:
						doc.set(f"explanation_{idx}", "")
				else:
					doc.set(f"option_{idx}", "")
					doc.set(f"is_correct_{idx}", 0)
					doc.set(f"explanation_{idx}", "")
			doc.multiple = int(len(correct_letters) > 1)
			doc.trivia_answer_key_pending = int(not has_answer)
		elif has_answer:
			# Preserve treated text/explanations, only update the answer key if explicitly supplied now
			for idx in range(1, 11):
				opt_val = str(getattr(doc, f"option_{idx}", None) or "").strip()
				if opt_val:
					letter = OPTION_LETTERS[idx - 1]
					doc.set(f"is_correct_{idx}", int(letter in correct_letters))
			doc.multiple = int(len(correct_letters) > 1)
			doc.trivia_answer_key_pending = 0

		if is_new:
			doc.insert(ignore_permissions=True)
			created += 1
		else:
			doc.save(ignore_permissions=True)
			updated += 1

		ordered_lms_questions.append(
			{
				"name": doc.name,
				"question": doc.question,
				"marks": int(doc.marks or 1),
				"type": doc.type or "Choices",
			}
		)

	# 4. Create or update native LMS Quiz with all exam questions in order
	final_quiz_title = (str(quiz_title or "").strip() or parsed["quiz_title"])[:135]
	existing_quiz = frappe.db.get_value("LMS Quiz", {"title": final_quiz_title}, "name")
	if existing_quiz:
		quiz = frappe.get_doc("LMS Quiz", existing_quiz)
		quiz.set("questions", [])
		quiz_created = False
	else:
		quiz = frappe.new_doc("LMS Quiz")
		quiz.title = final_quiz_title
		quiz.show_answers = 1
		quiz.passing_percentage = max(0, min(100, int(passing_percentage or 60)))
		quiz_created = True

	if prova.get("duracao_minutos") and not getattr(quiz, "duration", None):
		quiz.duration = prova["duracao_minutos"]

	for item in ordered_lms_questions:
		quiz.append(
			"questions",
			{
				"question": item["name"],
				"question_detail": item["question"],
				"type": item["type"],
				"marks": item["marks"],
			},
		)

	if quiz_created:
		quiz.insert(ignore_permissions=True)
	else:
		quiz.save(ignore_permissions=True)

	if hasattr(frappe.db, "commit"):
		frappe.db.commit()

	return {
		"quiz_name": quiz.name,
		"quiz_title": quiz.title,
		"quiz_created": quiz_created,
		"exam_code": exam_code,
		"supporting_texts": len(supporting_text_map),
		"questions_created": created,
		"questions_updated": updated,
		"questions_skipped": skipped,
		"total_questions": len(ordered_lms_questions),
		"answered_count": parsed["answered_count"],
		"pending_count": parsed["pending_count"],
	}


def get_quiz_answer_key_state(quiz_name: str) -> dict:
	"""Return ordered questions of an LMS Quiz with current answer key and pending state for manual/bulk UI."""
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	quiz = frappe.get_doc("LMS Quiz", quiz_name)
	items = []
	for idx, row in enumerate(quiz.get("questions") or [], start=1):
		q_name = getattr(row, "question", None)
		if not q_name or not frappe.db.exists("LMS Question", q_name):
			continue
		q_doc = frappe.get_doc("LMS Question", q_name)
		options, correct, _ = extract_lms_question_options(q_doc)
		items.append(
			{
				"numero": idx,
				"question_name": q_doc.name,
				"qcode": getattr(q_doc, "trivia_qcode", None) or q_doc.name,
				"title": getattr(q_doc, "trivia_title", None) or build_question_title(q_doc.question, fallback=q_doc.name),
				"subject": getattr(q_doc, "trivia_materia", None) or "",
				"letters": list(options.keys()),
				"correct": correct,
				"answer_key_pending": int(bool(getattr(q_doc, "trivia_answer_key_pending", 0))),
			}
		)
	return {
		"quiz_name": quiz.name,
		"quiz_title": quiz.title,
		"total": len(items),
		"pending_count": sum(1 for item in items if item["answer_key_pending"]),
		"questions": items,
	}


def apply_quiz_answer_key(quiz_name: str, answer_key) -> dict:
	"""Apply a manual or bulk-imported answer key to the ordered LMS Questions of an LMS Quiz."""
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	quiz = frappe.get_doc("LMS Quiz", quiz_name)
	rows = [row for row in (quiz.get("questions") or []) if getattr(row, "question", None)]
	if not rows:
		frappe.throw("This quiz has no questions.")

	parsed_key = parse_answer_key(answer_key, total_questions=len(rows))
	if not parsed_key:
		frappe.throw("No valid answers were detected in the provided answer key.")

	updated = 0
	skipped = 0
	for idx, row in enumerate(rows, start=1):
		letters = parsed_key.get(idx)
		if not letters:
			skipped += 1
			continue
		q_doc = frappe.get_doc("LMS Question", row.question)
		options, _, _ = extract_lms_question_options(q_doc)
		valid_letters = set(options.keys())
		chosen = [l for l in letters if l in valid_letters]
		if not chosen:
			skipped += 1
			continue
		for opt_idx, letter in enumerate(OPTION_LETTERS, start=1):
			if letter in options:
				q_doc.set(f"is_correct_{opt_idx}", int(letter in chosen))
			else:
				q_doc.set(f"is_correct_{opt_idx}", 0)
		q_doc.multiple = int(len(chosen) > 1)
		q_doc.trivia_answer_key_pending = 0
		q_doc.save(ignore_permissions=True)
		updated += 1

	if hasattr(frappe.db, "commit"):
		frappe.db.commit()

	return {
		"quiz_name": quiz.name,
		"updated": updated,
		"skipped": skipped,
		"total": len(rows),
	}


def confirm_question_answer_key(question_name: str) -> dict:
	"""Mark an individual LMS Question's current answer key as confirmed (clear pending flag)."""
	frappe.only_for(("System Manager", "Trivia Editor", "Trivia Reviewer", "Trivia Integrator"))
	doc = frappe.get_doc("LMS Question", question_name)
	doc.trivia_answer_key_pending = 0
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "trivia_answer_key_pending": 0}
