(() => {
	frappe.ui.form.on("Trivia Contest", {
		refresh(frm) {
			if (frm.is_new()) return;
			if (frm.doc.publication_status === "Published" && frm.doc.public_slug) {
				frm.add_custom_button(__("Open public page"), () => {
					window.open(`/concursos?slug=${encodeURIComponent(frm.doc.public_slug)}`, "_blank");
				}, __("Publication"));
			}
			if (!frappe.user.has_role("System Manager")) return;

			const setStatus = (status, label) => {
				frappe.call({
					method: "trivia_sync.api.set_contest_publication",
					args: { concurso_name: frm.doc.name, status },
				}).then(() => {
					frappe.show_alert({ message: label, indicator: "green" });
					frm.reload_doc();
				});
			};

			if (frm.doc.publication_status !== "Published") {
				frm.add_custom_button(__("Publish contest"), () => setStatus("Published", __("Contest published.")), __("Publication"));
			}
			if (frm.doc.publication_status !== "Draft") {
				frm.add_custom_button(__("Move to draft"), () => setStatus("Draft", __("Contest moved to draft.")), __("Publication"));
			}
			if (frm.doc.publication_status !== "Archived") {
				frm.add_custom_button(__("Archive contest"), () => {
					frappe.confirm(
						__("Archive this contest and hide it from the public catalog?"),
						() => setStatus("Archived", __("Contest archived."))
					);
				}, __("Publication"));
			}
		},
	});
})();
