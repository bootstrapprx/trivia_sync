from types import SimpleNamespace


def question(**overrides):
    values = {
        "name": "TRIVIA-QUESTION-1",
        "qcode": "Q-1",
        "enunciado": "Enunciado de teste?",
        "options": '{"A":"Opção A","B":"Opção B"}',
        "correct_option": "A",
        "materia": "Matemática",
        "assunto": "Aritmética",
        "banca": "Banca de teste",
        "ano": 2024,
    }
    return SimpleNamespace(**(values | overrides))


def sync_run(**overrides):
    values = {
        "source": "QAPI", "operation": "Question sync", "status": "Running", "records_created": 0,
        "records_updated": 0, "records_skipped": 0, "records_errors": 0,
    }
    return SimpleNamespace(**(values | overrides))


def catalog_record(**overrides):
    return {"name": "CATALOG-1", "external_id": "source-1", "title": "Catalog test", **overrides}


def fake_lms_question(**overrides):
    return SimpleNamespace(name="LMS-QUESTION-1", question="Question?", **overrides)
