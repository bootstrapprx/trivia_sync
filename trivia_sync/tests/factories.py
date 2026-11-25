from types import SimpleNamespace


def lms_question(**overrides):
	values = {
		"name": "LMS-QUESTION-1",
		"type": "Choices",
		"question": "Enunciado de teste?",
		"option_1": "Opção A",
		"is_correct_1": 1,
		"explanation_1": "",
		"option_2": "Opção B",
		"is_correct_2": 0,
		"explanation_2": "",
		"trivia_qcode": "Q-1",
		"trivia_status": "In Preparation",
		"trivia_materia": "Matemática",
		"trivia_assunto": "Aritmética",
		"trivia_banca": "Banca de teste",
		"trivia_ano": 2024,
	}
	return SimpleNamespace(**(values | overrides))


def sync_run(**overrides):
	values = {
		"source": "QAPI",
		"operation": "Question sync",
		"status": "Running",
		"records_created": 0,
		"records_updated": 0,
		"records_skipped": 0,
		"records_errors": 0,
	}
	return SimpleNamespace(**(values | overrides))


def catalog_record(**overrides):
	return {"name": "CATALOG-1", "external_id": "source-1", "title": "Catalog test", **overrides}


def fake_lms_question(**overrides):
	return lms_question(**overrides)
