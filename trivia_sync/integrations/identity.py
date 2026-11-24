import frappe


def source_identity(source_type, source_id=None, qcode=None):
	source_id = str(source_id or qcode or "").strip()
	if not source_id:
		frappe.throw("Provide a source ID to create a stable identity.")
	source_key = f"{source_type.strip().lower().replace(' ', '-')}:" + source_id
	return source_id, source_key


def ensure_unique_source_key(doctype, source_key, current_name=None):
	existing = frappe.db.get_value(doctype, {"source_key": source_key}, "name")
	if existing and existing != current_name:
		frappe.throw(f"Source identity {source_key} is already linked to {existing}.")


def autoname_optional_qapi(doc):
	qapi_id = str(getattr(doc, "qapi_id", None) or "").strip()
	if qapi_id:
		doc.qapi_id = qapi_id
		doc.name = qapi_id
		if not getattr(doc, "source_type", None):
			doc.source_type = "QAPI"
		return
	if not getattr(doc, "source_type", None):
		doc.source_type = "Manual"
	doc.name = frappe.generate_hash(length=16)
	if hasattr(doc, "source_id") and not getattr(doc, "source_id", None):
		doc.source_id = doc.name


def apply_optional_qapi_identity(doc, doctype=None):
	doctype = doctype or getattr(doc, "doctype", None)
	qapi_id = str(getattr(doc, "qapi_id", None) or "").strip()
	source_type = str(getattr(doc, "source_type", None) or "").strip()
	if not source_type:
		source_type = "QAPI" if qapi_id else "Manual"
	doc.source_type = source_type
	if qapi_id:
		doc.qapi_id = qapi_id
	elif source_type == "QAPI" and not getattr(doc, "source_id", None):
		frappe.throw("Provide a QAPI ID when Source type is QAPI.")

	has_source_key = any(hasattr(doc, field) for field in ("source_key", "source_id"))
	if has_source_key:
		source_id = getattr(doc, "source_id", None) or qapi_id or getattr(doc, "name", None) or frappe.generate_hash(length=16)
		doc.source_id, doc.source_key = source_identity(source_type, source_id, qapi_id or None)
		if doctype and hasattr(frappe, "db"):
			ensure_unique_source_key(doctype, doc.source_key, getattr(doc, "name", None))
