(() => {
	const canBuild = () =>
		frappe.user.has_role("System Manager") ||
		frappe.user.has_role("Trivia Editor") ||
		frappe.user.has_role("Trivia Reviewer") ||
		frappe.user.has_role("Trivia Integrator");

	frappe.ui.form.on("LMS Quiz", {
		refresh(frm) {
			if (frm.is_new() || !canBuild()) return;
			frm.add_custom_button(__("Build from Question Bank"), () => {
				const dialog = new frappe.ui.Dialog({
					title: __("Build Quiz from LMS Question Bank"),
					fields: [
						{ fieldname: "count", fieldtype: "Int", label: __("Number of questions"), default: 10, reqd: 1 },
						{ fieldname: "subject", fieldtype: "Link", options: "Trivia Subject", label: __("Subject (optional)") },
						{ fieldname: "topic", fieldtype: "Link", options: "Trivia Topic", label: __("Topic (optional)") },
						{ fieldname: "board", fieldtype: "Data", label: __("Exam board contains (optional)") },
						{ fieldname: "concurso_cargo", fieldtype: "Link", options: "Trivia Contest Position", label: __("Contest position (optional)") },
						{ fieldname: "syllabus_topic", fieldtype: "Link", options: "Trivia Syllabus Topic", label: __("Syllabus topic (optional)") },
						{ fieldname: "marks", fieldtype: "Int", label: __("Marks per question (optional override)") },
						{ fieldname: "only_ready", fieldtype: "Check", label: __("Include Ready questions only"), default: 1 },
						{ fieldname: "append_existing", fieldtype: "Check", label: __("Append to existing quiz questions (instead of replacing)"), default: 0 },
					],
					primary_action_label: __("Populate Quiz"),
					primary_action(values) {
						dialog.hide();
						frappe.call({
							method: "trivia_sync.api.build_lms_quiz",
							freeze: true,
							freeze_message: __("Selecting questions..."),
							args: {
								quiz_name: frm.doc.name,
								count: values.count,
								subject: values.subject || null,
								topic: values.topic || null,
								board: values.board || null,
								concurso_cargo: values.concurso_cargo || null,
								syllabus_topic: values.syllabus_topic || null,
								only_ready: values.only_ready ? 1 : 0,
								append_existing: values.append_existing ? 1 : 0,
								marks: values.marks || null,
							},
						}).then(({ message }) => {
							frappe.show_alert({
								message: __("Added {0} question(s) to quiz ({1} total).", [message?.added || 0, message?.total_questions || 0]),
								indicator: "green",
							});
							frm.reload_doc();
						});
					},
				});
				dialog.show();
			}, __("Trivia Sync"));
		},
	});
})();
