import hashlib
import json
from typing import Any

OPTION_KEYS = [("A", "opcaoA"), ("B", "opcaoB"), ("C", "opcaoC"), ("D", "opcaoD"), ("E", "opcaoE")]


def answer_letter(value):
    text = str(value or "").strip().upper()
    if text in {"A", "B", "C", "D", "E"}:
        return text
    if text.isdigit() and 1 <= int(text) <= 5:
        return "ABCDE"[int(text) - 1]
    return ""


def normalize_question(row: dict[str, Any]) -> dict[str, Any]:
    qcode = str(row.get("qCode") or row.get("_id") or "").strip()
    options = {letter: str(row.get(field) or "").strip() for letter, field in OPTION_KEYS}
    options = {key: value for key, value in options.items() if value}
    raw = json.dumps(row, ensure_ascii=False, sort_keys=True)
    return {
        "qcode": qcode,
        "source": "QAPI",
        "enunciado": str(row.get("enunciado") or "").strip(),
        "banca": str(row.get("banca") or row.get("siglaBanca") or "").strip(),
        "orgao": str(row.get("orgao") or "").strip(),
        "cargo": str(row.get("cargo") or "").strip(),
        "ano": int(row.get("ano") or 0),
        "materia": str(row.get("materia") or "").strip(),
        "assunto": str(row.get("assunto") or "").strip(),
        "options": json.dumps(options, ensure_ascii=False),
        "correct_option": answer_letter(row.get("gabarito")),
        "explanation": str(row.get("comentario") or "").strip(),
        "source_url": f"https://qapi.otunac.com/api/questoes?qCode={qcode}" if qcode else "",
        "raw_payload": raw,
        "sync_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    }
