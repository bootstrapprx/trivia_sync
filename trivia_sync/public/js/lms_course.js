(() => {
	const canManage = () =>
		frappe.user.has_role("System Manager") ||
		frappe.user.has_role("Trivia Editor") ||
		frappe.user.has_role("Trivia Reviewer") ||
		frappe.user.has_role("Trivia Integrator");

	frappe.ui.form.on("LMS Course", {
		refresh(frm) {
			if (frm.is_new() || !canManage()) return;
			frm.add_custom_button(
				__("Athena · Gerar Capítulos"),
				() => {
					window.trivia_sync?.openAthenaCourseBuilder?.({
						targetCourse: frm.doc.name,
						onCreated: () => frm.reload_doc(),
					});
				},
				__("Trivia Concursos")
			);
		},
	});
})();
