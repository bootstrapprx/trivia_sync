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
        return str(first(value, "nome", "name", "titulo", "title", "descricao", "description", default=""))
    return str(value or "").strip()


def identifier(row: dict[str, Any]) -> str:
    return text(first(row, "qCode", "qcode", "codigo", "code", "_id", "id", "uuid"))


def answer_letter(value: Any) -> str:
    value = first(value, "letra", "letter", "resposta", default=value)
    normalized = text(value).upper()
    if normalized in {"A", "B", "C", "D", "E"}: return normalized
    if normalized.isdigit() and 1 <= int(normalized) <= 5: return "ABCDE"[int(normalized) - 1]
    return ""


def raw_hash(row: dict[str, Any]) -> tuple[str, str]:
    raw = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_question(row: dict[str, Any]) -> dict[str, Any]:
    raw, digest = raw_hash(row)
    options = {letter: text(first(row, field, letter.lower(), letter, default="")) for letter, field in OPTION_KEYS}
    options = {key: value for key, value in options.items() if value}
    qcode = identifier(row)
    return {"qcode": qcode, "source": "QAPI", "enunciado": text(first(row, "enunciado", "question", "pergunta", "texto")),
            "banca": text(first(row, "banca", "siglaBanca", "organizadora")), "orgao": text(first(row, "orgao", "entidade")),
            "cargo": text(first(row, "cargo", "posto")), "ano": int(first(row, "ano", "year", default=0) or 0),
            "materia": text(first(row, "materia", "disciplina")), "assunto": text(first(row, "assunto", "topic")),
            "options": json.dumps(options, ensure_ascii=False), "correct_option": answer_letter(first(row, "gabarito", "resposta", "correct_answer")),
            "explanation": text(first(row, "comentario", "explicacao", "explanation", "justificativa")),
            "texto_codigo": text(first(row, "textoCodigo", "texto_codigo", "codigoTexto", "texto_id", "textoId")),
            "source_url": f"https://qapi.otunac.com/api/questoes?qCode={qcode}" if qcode else "", "raw_payload": raw, "sync_hash": digest}


def normalize_resource(row: dict[str, Any], kind: str) -> dict[str, Any]:
    raw, digest = raw_hash(row)
    rid = text(first(row, "id", "_id", "codigo", "code", "uuid", "qCode"))
    if kind == "texto": return {"codigo": rid, "titulo": text(first(row, "titulo", "title", "nome")), "conteudo": text(first(row, "conteudo", "texto", "body", "descricao")), "source_url": text(first(row, "url", "link")), "raw_payload": raw, "sync_hash": digest}
    if kind == "flashcard": return {"qapi_id": rid, "frente": text(first(row, "frente", "front", "pergunta", "question")), "verso": text(first(row, "verso", "back", "resposta", "answer")), "conteudo": text(first(row, "conteudo_id", "conteudoId")), "materia": text(first(row, "materia", "disciplina")), "assunto": text(first(row, "assunto", "topic")), "raw_payload": raw, "sync_hash": digest}
    result = {"qapi_id": rid, "raw_payload": raw, "sync_hash": digest}
    name = text(first(row, "nome", "name", "titulo", "title", "descricao", "description"))
    result.update({"nome": name, "titulo": name, "sigla": text(first(row, "sigla", "abbreviation")), "uf": text(first(row, "uf", "estado")), "materia": text(first(row, "materia", "disciplina")), "status": text(first(row, "status")), "ano": int(first(row, "ano", "year", default=0) or 0), "orgao": text(first(row, "orgao", "orgao_id")), "banca": text(first(row, "banca", "banca_id")), "cargo": text(first(row, "cargo", "cargo_id")), "regiao": text(first(row, "regiao", "region")), "estado": text(first(row, "estado", "uf")), "pdf_url": text(first(row, "pdf", "pdf_url", "link_pdf")), "concurso": text(first(row, "concurso_id", "concursoId")), "disciplina": text(first(row, "disciplina_id", "disciplinaId")), "parent_conteudo": text(first(row, "parent_id", "parentId", "pai")), "is_group": int(bool(first(row, "is_group", "grupo", default=False))), "ordem": int(first(row, "ordem", "order", "position", default=0) or 0), "nivel": int(first(row, "nivel", "level", default=0) or 0)})
    return result
