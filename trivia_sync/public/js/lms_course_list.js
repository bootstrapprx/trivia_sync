(() => {
	const canManage = () =>
		frappe.user.has_role("System Manager") ||
		frappe.user.has_role("Trivia Editor") ||
		frappe.user.has_role("Trivia Reviewer") ||
		frappe.user.has_role("Trivia Integrator");

	const existing = frappe.listview_settings["LMS Course"] || {};
	const previousOnload = existing.onload;
	frappe.listview_settings["LMS Course"] = {
		...existing,
		onload(listview) {
			if (typeof previousOnload === "function") previousOnload(listview);
			if (!canManage()) return;
			listview.page.add_inner_button(__("Athena · Criar Curso"), () => {
				window.trivia_sync?.openAthenaCourseBuilder?.({
					onCreated: (res) => {
						listview.refresh();
						if (res?.course_name) {
							frappe.set_route("Form", "LMS Course", res.course_name);
						}
					},
				});
			});
		},
	};
})();
