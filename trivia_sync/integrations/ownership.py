RESOURCE_SOURCE_FIELDS = {
	"Trivia Exam Board": {"qapi_id", "nome", "sigla", "raw_payload", "sync_hash", "last_synced_at", "source_type", "source_id", "source_key"},
	"Trivia Organization": {"qapi_id", "nome", "sigla", "uf", "raw_payload", "sync_hash", "last_synced_at", "source_type", "source_id", "source_key"},
	"Trivia Position": {"qapi_id", "nome", "raw_payload", "sync_hash", "last_synced_at", "source_type", "source_id", "source_key", "is_obsolete"},
	"Trivia Subject": {"qapi_id", "nome", "raw_payload", "sync_hash", "last_synced_at", "source_type", "source_id", "source_key"},
	"Trivia Topic": {"qapi_id", "nome", "materia", "raw_payload", "sync_hash", "last_synced_at", "source_type", "source_id", "source_key"},
	"Trivia Contest": {"qapi_id", "titulo", "orgao", "banca", "status", "ano", "regiao", "estado", "raw_payload", "sync_hash", "last_synced_at", "source_type", "source_id", "source_key", "is_obsolete"},
	"Trivia Discipline": {"qapi_id", "titulo", "concurso", "cargo", "materia", "raw_payload", "sync_hash", "last_synced_at", "source_type", "source_id", "source_key"},
	"Trivia Syllabus Topic": {"qapi_id", "titulo", "disciplina", "parent_conteudo", "is_group", "ordem", "nivel", "raw_payload", "sync_hash", "last_synced_at", "source_type", "source_id", "source_key", "source_path", "source_text", "source_version", "source_hash", "concurso_cargo", "is_obsolete"},
	"Flashcard": {"qapi_id", "frente", "verso", "conteudo", "materia", "assunto", "raw_payload", "sync_hash", "source_type", "source_id", "source_key"},
	"Trivia Supporting Text": {"codigo", "titulo", "conteudo", "source_url", "raw_payload", "sync_hash", "last_synced_at", "source_type", "source_id", "source_key"},
}


def source_fields_changed(doc, data, doctype):
	fields = RESOURCE_SOURCE_FIELDS[doctype]
	return any(getattr(doc, field, None) != data[field] for field in fields if field in data)


def update_source_owned_fields(doc, data, doctype):
	fields = RESOURCE_SOURCE_FIELDS[doctype]
	for field in fields:
		if field in data:
			setattr(doc, field, data[field])
	return False
