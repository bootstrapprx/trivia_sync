(() => {
	const canImport = () =>
		frappe.user.has_role("System Manager") ||
		frappe.user.has_role("Trivia Editor") ||
		frappe.user.has_role("Trivia Reviewer") ||
		frappe.user.has_role("Trivia Integrator");

	const existing = frappe.listview_settings["LMS Quiz"] || {};
	const previousOnload = existing.onload;
	frappe.listview_settings["LMS Quiz"] = {
		...existing,
		onload(listview) {
			if (typeof previousOnload === "function") previousOnload(listview);
			if (!canImport()) return;
			listview.page.add_inner_button(__("Import Ready Exam"), () => {
				window.trivia_sync?.openExamImporterDialog?.({
					onImported: () => listview.refresh(),
				});
			});
		},
	};
})();
