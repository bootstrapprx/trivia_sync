QUESTION_SOURCE_FIELDS = {
	"qcode", "source", "source_type", "source_id", "source_key", "enunciado", "texto_apoio", "banca", "orgao",
	"cargo", "ano", "materia", "assunto", "options", "correct_option", "explanation", "source_url",
	"raw_payload", "sync_hash", "content_hash", "last_synced_at", "source_license", "source_attribution",
}

RESOURCE_SOURCE_FIELDS = {
	"Banca": {"qapi_id", "nome", "sigla", "raw_payload", "sync_hash", "last_synced_at", "source_type", "source_id", "source_key"},
	"Órgão": {"qapi_id", "nome", "sigla", "uf", "raw_payload", "sync_hash", "last_synced_at", "source_type", "source_id", "source_key"},
	"Cargo": {"qapi_id", "nome", "raw_payload", "sync_hash", "last_synced_at", "source_type", "source_id", "source_key", "is_obsolete"},
	"Matéria": {"qapi_id", "nome", "raw_payload", "sync_hash", "last_synced_at", "source_type", "source_id", "source_key"},
	"Assunto": {"qapi_id", "nome", "materia", "raw_payload", "sync_hash", "last_synced_at", "source_type", "source_id", "source_key"},
	"Concurso": {"qapi_id", "titulo", "orgao", "banca", "status", "ano", "regiao", "estado", "raw_payload", "sync_hash", "last_synced_at", "source_type", "source_id", "source_key", "is_obsolete"},
	"Prova": {"qapi_id", "titulo", "concurso", "banca", "orgao", "cargo", "ano", "pdf_url", "raw_payload", "sync_hash", "last_synced_at", "source_type", "source_id", "source_key"},
	"Disciplina": {"qapi_id", "titulo", "concurso", "cargo", "materia", "raw_payload", "sync_hash", "last_synced_at", "source_type", "source_id", "source_key"},
	"Conteúdo Programático": {"qapi_id", "titulo", "disciplina", "parent_conteudo", "is_group", "ordem", "nivel", "raw_payload", "sync_hash", "last_synced_at", "source_type", "source_id", "source_key", "source_path", "source_text", "source_version", "source_hash", "concurso_cargo", "is_obsolete"},
	"Flashcard": {"qapi_id", "frente", "verso", "conteudo", "materia", "assunto", "raw_payload", "sync_hash", "source_type", "source_id", "source_key"},
	"Texto de Apoio": {"codigo", "titulo", "conteudo", "source_url", "raw_payload", "sync_hash", "last_synced_at", "source_type", "source_id", "source_key"},
}


def update_source_owned_fields(doc, data, doctype):
	fields = QUESTION_SOURCE_FIELDS if doctype == "Trivia Question" else RESOURCE_SOURCE_FIELDS[doctype]
	previous_content_hash = getattr(doc, "content_hash", None) if doctype == "Trivia Question" else None
	previous_license = getattr(doc, "source_license", None) if doctype == "Trivia Question" else None
	previous_attribution = getattr(doc, "source_attribution", None) if doctype == "Trivia Question" else None
	for field in fields:
		if field in data:
			setattr(doc, field, data[field])
	if doctype == "Trivia Question" and (
		previous_license != data.get("source_license") or previous_attribution != data.get("source_attribution")
	):
		doc.redistribution_status = "Pending"
		doc.redistribution_decided_by = None
		doc.redistribution_decided_at = None
	if doctype == "Trivia Question" and previous_content_hash and previous_content_hash != data.get("content_hash"):
		doc.review_status = "Pending"
		doc.reviewed_by = None
		doc.reviewed_at = None
		doc.review_reason = None
		doc.ai_enrichment_status = "Stale"
	return previous_content_hash != data.get("content_hash")
