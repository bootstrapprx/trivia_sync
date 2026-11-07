#!/usr/bin/env python3
"""Ensure existing app DocTypes, fields, and controllers remain present."""

import json
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
BASELINE = APP_ROOT / "docs/superpowers/fixtures/schema_baseline.json"
DOCTYPE_ROOT = APP_ROOT / "trivia_sync/trivia_sync/doctype"
DECLARED_RENAMES = {
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


def current_schema():
    schema = {}
    for path in sorted(DOCTYPE_ROOT.glob("*/**/*.json")):
        data = json.loads(path.read_text())
        if data.get("doctype") != "DocType":
            continue
        name = data["name"]
        slug = name.lower().replace(" ", "_")
        controller = APP_ROOT / "trivia_sync/trivia_sync/doctype" / slug / f"{slug}.py"
        schema[name] = {
            "fields": sorted(field["fieldname"] for field in data.get("fields", []) if field.get("fieldname")),
            "controller": controller.exists(),
        }
    return schema


def link_errors():
    names = set()
    files = list(DOCTYPE_ROOT.glob("*/**/*.json"))
    for path in files:
        data = json.loads(path.read_text())
        if data.get("doctype") == "DocType":
            names.add(data["name"])
    external = {"User", "LMS Question", "LMS Course", "Course Lesson", "LMS Quiz"}
    errors = []
    for path in files:
        data = json.loads(path.read_text())
        if data.get("doctype") != "DocType":
            continue
        for field in data.get("fields", []):
            if field.get("fieldtype") != "Link":
                continue
            target = field.get("options")
            if target not in names | external:
                errors.append(f"invalid Link target: {data['name']}.{field.get('fieldname')} -> {target or '(empty)'}")
    return errors


def main():
    actual = current_schema()
    if "--write" in sys.argv:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(actual, ensure_ascii=False, indent=2) + "\n")
        print(f"Wrote {BASELINE.relative_to(APP_ROOT)}")
        return 0

    baseline = json.loads(BASELINE.read_text())
    errors = link_errors()
    for doctype, previous in baseline.items():
        if doctype not in actual:
            if doctype in DECLARED_RENAMES and DECLARED_RENAMES[doctype] in actual:
                continue
            errors.append(f"removed DocType: {doctype}")
            continue
        removed = sorted(set(previous["fields"]) - set(actual[doctype]["fields"]))
        errors.extend(f"removed field: {doctype}.{field}" for field in removed)
        if not actual[doctype]["controller"]:
            errors.append(f"missing controller: {doctype}")
    if errors:
        print("Schema compatibility check failed:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print(f"Schema compatibility OK ({len(baseline)} existing DocTypes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
