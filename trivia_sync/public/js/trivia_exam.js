(() => {
	const canIntegrate = () =>
		frappe.user.has_role("System Manager") || frappe.user.has_role("Trivia Integrator");

	frappe.ui.form.on("Trivia Exam", {
		refresh(frm) {
			if (frm.is_new()) return;
			if (frm.doc.lms_quiz) {
				frm.add_custom_button(__("Open LMS Quiz"), () => {
					frappe.set_route("Form", "LMS Quiz", frm.doc.lms_quiz);
				}, __("LMS"));
			}
			if (!canIntegrate()) return;

			if (!["Superseded", "Archived"].includes(frm.doc.status)) {
				frm.add_custom_button(__("Build mock exam"), () => {
					frappe.call({
						method: "trivia_sync.api.build_simulado",
						args: { prova_name: frm.doc.name },
					}).then(({ message }) => {
						frappe.show_alert({
							message: message?.reused
								? __("Existing quiz {0} (v{1}) is already up to date.", [message.quiz, message.version])
								: __("Quiz {0} (v{1}) built with {2} questions.", [message?.quiz, message?.version, message?.questions]),
							indicator: "green",
						});
						frm.reload_doc();
					});
				}, __("LMS"));
			}

			if (frm.doc.lms_quiz && ["Ready", "Published"].includes(frm.doc.status)) {
				frm.add_custom_button(__("Publish to LMS lesson"), () => {
					frappe.call({
						method: "trivia_sync.api.publish_prova",
						args: { prova_name: frm.doc.name, lesson_name: frm.doc.lms_lesson || null },
					}).then(({ message }) => {
						frappe.show_alert({
							message: message?.reused
								? __("Quiz {0} is already published in this lesson.", [message.quiz])
								: __("Quiz {0} published to LMS lesson.", [message?.quiz]),
							indicator: "green",
						});
						frm.reload_doc();
					});
				}, __("LMS"));
			}

			if (frm.doc.status !== "Archived") {
				frm.add_custom_button(__("Archive exam"), () => {
					frappe.confirm(
						__("Archive this exam and remove its active quiz from the LMS lesson? Existing attempts are preserved."),
						() => frappe.call({
							method: "trivia_sync.api.archive_prova",
							args: { prova_name: frm.doc.name },
						}).then(() => {
							frappe.show_alert({ message: __("Exam archived."), indicator: "green" });
							frm.reload_doc();
						})
					);
				}, __("LMS"));
			}
		},
	});
})();
