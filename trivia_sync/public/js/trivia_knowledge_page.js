(() => {
	const hasAnyRole = (...roles) =>
		frappe.user.has_role("System Manager") || roles.some((role) => frappe.user.has_role(role));

	frappe.ui.form.on("Trivia Knowledge Page", {
		refresh(frm) {
			if (frm.is_new()) return;

			if (frm.doc.status === "Published" && frm.doc.slug) {
				frm.add_custom_button(__("Open public page"), () => {
					window.open(`/conhecimento?slug=${encodeURIComponent(frm.doc.slug)}`, "_blank");
				}, __("Publication"));
			}

			const setStatus = (status, label) =>
				frappe.call({
					method: "trivia_sync.api.update_knowledge_page_status",
					args: { page_name: frm.doc.name, status },
				}).then(() => {
					frappe.show_alert({ message: label, indicator: "green" });
					frm.reload_doc();
				});

			if (hasAnyRole("Trivia Reviewer", "Trivia Integrator")) {
				if (frm.doc.status !== "Published") {
					frm.add_custom_button(__("Publish page"), () => setStatus("Published", __("Knowledge page published.")), __("Publication"));
				}
				if (frm.doc.status !== "Archived") {
					frm.add_custom_button(__("Archive page"), () => {
						frappe.confirm(
							__("Archive this knowledge page and hide it from /conhecimento and LMS links?"),
							() => setStatus("Archived", __("Knowledge page archived."))
						);
					}, __("Publication"));
				}
			}
			if (frm.doc.status !== "Draft" && hasAnyRole("Trivia Editor", "Trivia Reviewer", "Trivia Integrator")) {
				frm.add_custom_button(__("Move to draft"), () => setStatus("Draft", __("Knowledge page moved to draft.")), __("Publication"));
			}

			// Show sub-concepts and linked questions panel
			frappe.call({
				method: "trivia_sync.api.knowledge_page_backlinks",
				args: { page_name: frm.doc.name },
			}).then(({ message }) => {
				if (!message) return;
				const subs = message.sub_concepts || [];
				const questions = message.questions || [];
				if (!subs.length && !questions.length) return;
				const escape = (v) => frappe.utils.escape_html(String(v ?? ""));
				const subHtml = subs.length
					? `<div class="mb-2"><strong>${__("Sub-concepts")}:</strong> ${subs.map((s) => `<a class="badge badge-secondary mr-1" href="/app/trivia-knowledge-page/${encodeURIComponent(s.name)}">${escape(s.title)} (${escape(s.status)})</a>`).join(" ")}</div>`
					: "";
				const qHtml = questions.length
					? `<div><strong>${__("Linked questions")} (${questions.length}):</strong> ${questions.slice(0, 10).map((q) => `<a class="badge badge-light mr-1" href="/app/trivia-question/${encodeURIComponent(q.name)}">${escape(q.qcode || q.name)}</a>`).join(" ")}</div>`
					: "";
				frm.dashboard.set_headline_alert(`${subHtml}${qHtml}`, "blue");
			});
		},
	});
})();
