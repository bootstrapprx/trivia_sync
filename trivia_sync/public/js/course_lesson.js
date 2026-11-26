(() => {
	const canGenerate = () =>
		frappe.user.has_role("System Manager") ||
		frappe.user.has_role("Trivia Editor") ||
		frappe.user.has_role("Trivia Reviewer") ||
		frappe.user.has_role("Trivia Integrator");

	frappe.ui.form.on("Course Lesson", {
		refresh(frm) {
			if (frm.is_new() || !canGenerate()) return;
			frm.add_custom_button(__("Gerar rascunho da aula (Athena)"), () => {
				const dialog = new frappe.ui.Dialog({
					title: __("Gerar material de estudo com a Athena"),
					fields: [
						{ fieldname: "level", fieldtype: "Select", label: __("Nível de profundidade"), options: "mais\n180\n360", default: "180", reqd: 1 },
						{ fieldname: "trivia_subject", fieldtype: "Link", options: "Trivia Subject", label: __("Filtro de matéria (opcional)") },
						{ fieldname: "trivia_topic", fieldtype: "Link", options: "Trivia Topic", label: __("Filtro de tópico (opcional)") },
						{ fieldname: "syllabus_topic", fieldtype: "Link", options: "Trivia Syllabus Topic", label: __("Filtro de item do edital (opcional)") },
						{ fieldname: "methodology", fieldtype: "Link", options: "Trivia Methodology", label: __("Metodologia (opcional)") },
						{ fieldname: "prompt", fieldtype: "Small Text", label: __("Instruções adicionais para a Athena") },
					],
					primary_action_label: __("Gerar na aula"),
					primary_action(values) {
						dialog.hide();
						frappe.call({
							method: "trivia_sync.api.generate_course_lesson_material",
							freeze: true,
							freeze_message: __("Athena está gerando o material da aula..."),
							args: {
								lesson_name: frm.doc.name,
								level: values.level,
								trivia_subject: values.trivia_subject || null,
								trivia_topic: values.trivia_topic || null,
								syllabus_topic: values.syllabus_topic || null,
								methodology: values.methodology || null,
								prompt: values.prompt || "",
							},
						}).then(({ message }) => {
							frappe.show_alert({
								message: __("Lesson material (level {0}) generated from {1} question(s).", [
									message?.level || values.level,
									message?.source_questions || 0,
								]),
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
