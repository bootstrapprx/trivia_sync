import frappe


RENAMES = {
    "Órgão": "Trivia Organization",
    "Matéria": "Trivia Subject",
    "Conteúdo Programático": "Trivia Syllabus Topic",
    "Concurso": "Trivia Contest",
    "Assunto": "Trivia Topic",
    "Prova": "Trivia Exam",
    "Banca": "Trivia Exam Board",
    "Concurso Cargo": "Trivia Contest Position",
    "Disciplina": "Trivia Discipline",
    "Texto de Apoio": "Trivia Supporting Text",
    "Cargo": "Trivia Position",
    "Trivia Apostila Recipe": "Trivia Study Guide Recipe",
}


def execute():
    for old, new in RENAMES.items():
        if not frappe.db.exists("DocType", old):
            continue
        if frappe.db.exists("DocType", new):
            frappe.throw(f"Cannot rename {old}: {new} already exists.")

        # Exclude self-links from rename_doc's value update; only the DocType option changes.
        frappe.db.set_value("DocField", {"parent": old, "options": old}, "options", new)
        frappe.rename_doc("DocType", old, new, force=True)
