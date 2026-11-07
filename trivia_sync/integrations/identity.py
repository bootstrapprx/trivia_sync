import frappe


def source_identity(source_type, source_id=None, qcode=None):
    source_id = str(source_id or qcode or "").strip()
    if not source_id:
        frappe.throw("Informe o ID da fonte para criar uma identidade estável.")
    source_key = f"{source_type.strip().lower().replace(' ', '-')}:" + source_id
    return source_id, source_key


def ensure_unique_source_key(doctype, source_key, current_name=None):
    existing = frappe.db.get_value(doctype, {"source_key": source_key}, "name")
    if existing and existing != current_name:
        frappe.throw(f"A identidade de fonte {source_key} já está vinculada a {existing}.")
