import hashlib
import json
from typing import Any

OPTION_KEYS = [("A", "opcaoA"), ("B", "opcaoB"), ("C", "opcaoC"), ("D", "opcaoD"), ("E", "opcaoE")]


def first(row: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return default


def text(value: Any) -> str:
    if isinstance(value, dict):
        return str(first(value, "nome", "name", "titulo", "title", "sigla", "descricao", "description", default=""))
    return str(value or "").strip()


def rich_text(value: Any) -> str:
    """Preserve QAPI rich content instead of stringifying it to a dict label."""
    if isinstance(value, dict):
        value = first(value, "html", "content", "conteudo", "texto", "text", "body", "value", "valor", "descricao", "description", default="")
    if isinstance(value, list):
        value = "<br>".join(rich_text(item) for item in value)
    return str(value or "").strip()


def identifier(row: dict[str, Any]) -> str:
    return text(first(row, "qCode", "qcode", "codigo", "code", "_id", "id", "uuid"))


def answer_letter(value: Any) -> str:
    if isinstance(value, dict):
        value = first(value, "letra", "letter", "alternativa", "option", "resposta", "answer", default=value)
    normalized = text(value).upper().strip().rstrip(".")
    if normalized in {"A", "B", "C", "D", "E"}:
        return normalized
    if normalized.isdigit() and 1 <= int(normalized) <= 5:
        return "ABCDE"[int(normalized) - 1]
    return ""


def raw_hash(row: dict[str, Any]) -> tuple[str, str]:
    raw = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def evaluable_hash(question: dict[str, Any]) -> str:
    content = {key: question.get(key) for key in ("enunciado", "options", "correct_option", "explanation", "texto_codigo")}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _option_value(value: Any) -> str:
    if isinstance(value, dict):
        value = first(value, "html", "content", "texto", "text", "descricao", "description", "valor", "value", default="")
    return rich_text(value)


def _extract_options(row: dict[str, Any]) -> dict[str, str]:
    """Accept legacy opcaoA fields and QAPI arrays/maps such as alternativas/opcoes."""
    values: dict[str, Any] = {}
    for letter, field in OPTION_KEYS:
        value = first(row, field, letter.lower(), letter, default="")
        if value not in (None, ""):
            values[letter] = value

    grouped = first(row, "alternativas", "alternatives", "opcoes", "options", "respostas", default=None)
    if isinstance(grouped, dict):
        for key, value in grouped.items():
            letter = answer_letter(key)
            if letter:
                values[letter] = value
    elif isinstance(grouped, list):
        for index, value in enumerate(grouped[:5]):
            letter = answer_letter(value) if isinstance(value, dict) else "ABCDE"[index]
            if not letter:
                letter = "ABCDE"[index]
            values[letter] = value

    return {letter: _option_value(values[letter]) for letter in "ABCDE" if values.get(letter) not in (None, "")}


def normalize_question(row: dict[str, Any]) -> dict[str, Any]:
    raw, digest = raw_hash(row)
    options = _extract_options(row)
    qcode = identifier(row)
    result = {
        "qcode": qcode,
        "source": "QAPI",
        "source_type": "QAPI",
        "source_id": qcode,
        "source_key": f"qapi:{qcode}" if qcode else "",
        "enunciado": rich_text(first(row, "enunciado", "question", "pergunta", "texto", "statement", default="")),
        "banca": text(first(row, "banca", "siglaBanca", "organizadora")),
        "orgao": text(first(row, "orgao", "entidade")),
        "cargo": text(first(row, "cargo", "posto")),
        "ano": int(first(row, "ano", "year", default=0) or 0),
        "materia": text(first(row, "materia", "disciplina")),
        "assunto": text(first(row, "assunto", "topic")),
        "options": json.dumps(options, ensure_ascii=False),
        "correct_option": answer_letter(first(row, "gabarito", "resposta", "correct_answer", "answer_key")),
        "explanation": rich_text(first(row, "comentario", "explicacao", "explanation", "justificativa", default="")),
        "texto_codigo": text(first(row, "textoCodigo", "texto_codigo", "codigoTexto", "texto_id", "textoId")),
        "source_url": f"https://qapi.otunac.com/api/questoes?qCode={qcode}" if qcode else "",
        "raw_payload": raw,
        "sync_hash": digest,
        "source_license": text(first(row, "licenca", "license")),
        "source_attribution": text(first(row, "atribuicao", "attribution")),
    }
    result["content_hash"] = evaluable_hash(result)
    return result


def normalize_resource(row: dict[str, Any], kind: str) -> dict[str, Any]:
    raw, digest = raw_hash(row)
    rid = text(first(row, "id", "_id", "codigo", "code", "uuid", "qCode"))
    if kind == "texto":
        return {
            "codigo": rid,
            "source_type": "QAPI",
            "source_id": rid,
            "source_key": f"qapi:{rid}" if rid else "",
            "titulo": text(first(row, "titulo", "title", "nome")),
            "conteudo": rich_text(first(row, "conteudo", "texto", "body", "html", "descricao")),
            "source_url": text(first(row, "url", "link")),
            "raw_payload": raw,
            "sync_hash": digest,
        }
    if kind in {"flashcard", "flashcards"}:
        return {
            "qapi_id": rid,
            "source_type": "QAPI",
            "source_id": rid,
            "source_key": f"qapi:{rid}" if rid else "",
            "frente": rich_text(first(row, "frente", "front", "pergunta", "question")),
            "verso": rich_text(first(row, "verso", "back", "resposta", "answer")),
            "conteudo": text(first(row, "conteudo_id", "conteudoId")),
            "materia": text(first(row, "materia", "disciplina")),
            "assunto": text(first(row, "assunto", "topic")),
            "raw_payload": raw,
            "sync_hash": digest,
        }
    result = {"qapi_id": rid, "source_type": "QAPI", "source_id": rid,
              "source_key": f"qapi:{rid}" if rid else "", "raw_payload": raw, "sync_hash": digest}
    name = text(first(row, "nome", "name", "titulo", "title", "descricao", "description"))
    result.update(
        {
            "nome": name,
            "titulo": name,
            "sigla": text(first(row, "sigla", "abbreviation")),
            "uf": text(first(row, "uf", "estado")),
            "materia": text(first(row, "materia", "disciplina")),
            "status": text(first(row, "status")),
            "ano": int(first(row, "ano", "year", default=0) or 0),
            "orgao": text(first(row, "orgao", "orgao_id")),
            "banca": text(first(row, "banca", "banca_id")),
            "cargo": text(first(row, "cargo", "cargo_id")),
            "regiao": text(first(row, "regiao", "region")),
            "estado": text(first(row, "estado", "uf")),
            "pdf_url": text(first(row, "pdf", "pdf_url", "link_pdf")),
            "concurso": text(first(row, "concurso_id", "concursoId")),
            "disciplina": text(first(row, "disciplina_id", "disciplinaId")),
            "parent_conteudo": text(first(row, "parent_id", "parentId", "pai")),
            "is_group": int(bool(first(row, "is_group", "grupo", default=False))),
            "ordem": int(first(row, "ordem", "order", "position", default=0) or 0),
            "nivel": int(first(row, "nivel", "level", default=0) or 0),
        }
    )
    return result
