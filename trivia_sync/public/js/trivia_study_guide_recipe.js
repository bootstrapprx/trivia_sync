(() => {
	const hasAnyRole = (...roles) =>
		frappe.user.has_role("System Manager") || roles.some((role) => frappe.user.has_role(role));

	const versionChoices = (frm, statuses) =>
		(frm.doc.material_versions || [])
			.filter((row) => statuses.includes(row.status))
			.map((row) => ({
				label: `${row.level} · v${row.version} (${row.status}${row.origin ? ` · ${row.origin}` : ""})`,
				value: `${row.level}::${row.version}`,
			}));

	const parseChoice = (value) => {
		const [level, version] = String(value || "").split("::");
		return { level, version: Number(version) };
	};

	const runAction = (frm, method, args, successMessage) =>
		frappe.call({ method, args }).then(({ message }) => {
			const indicator = message?.status === "Stale" ? "orange" : "green";
			const text = message?.status === "Stale"
				? __("Sources changed; version was marked Stale.")
				: successMessage;
			frappe.show_alert({ message: text, indicator });
			frm.reload_doc();
		});

	frappe.ui.form.on("Trivia Study Guide Recipe", {
		refresh(frm) {
			if (frm.is_new()) return;
			const rows = frm.doc.material_versions || [];
			const staleCount = rows.filter((row) => row.status === "Stale").length;
			const pendingCount = rows.filter((row) => row.status === "Pending Approval").length;
			if (staleCount) {
				frm.dashboard.set_headline_alert(
					__("{0} study guide version(s) are Stale because source questions or methodology changed.", [staleCount]),
					"orange"
				);
			} else if (pendingCount) {
				frm.dashboard.set_headline_alert(
					__("{0} study guide version(s) awaiting reviewer approval.", [pendingCount]),
					"blue"
				);
			}

			const isArchived = frm.doc.status === "Archived";

			if (!isArchived && hasAnyRole("Trivia Editor")) {
				frm.add_custom_button(__("Create manual draft"), () => {
					const dialog = new frappe.ui.Dialog({
						title: __("Create Manual Study Guide Draft"),
						fields: [
							{ fieldname: "level", fieldtype: "Select", label: __("Level"), options: "mais\n180\n360", default: "mais", reqd: 1 },
							{ fieldname: "summary", fieldtype: "Small Text", label: __("Summary") },
							{ fieldname: "content", fieldtype: "Text Editor", label: __("Content"), reqd: 1 },
						],
						primary_action_label: __("Create Draft"),
						primary_action(values) {
							dialog.hide();
							runAction(
								frm,
								"trivia_sync.api.create_manual_apostila_material",
								{ recipe_name: frm.doc.name, level: values.level, content: values.content, summary: values.summary || "" },
								__("Manual draft created.")
							);
						},
					});
					dialog.show();
				}, __("Material"));
			}

			if (!isArchived && hasAnyRole("Trivia Integrator")) {
				frm.add_custom_button(__("Gerar rascunho com Athena"), () => {
					const dialog = new frappe.ui.Dialog({
						title: __("Gerar rascunho de apostila · Athena"),
						fields: [
							{ fieldname: "level", fieldtype: "Select", label: __("Nível"), options: "mais\n180\n360", default: "mais", reqd: 1 },
						],
						primary_action_label: __("Gerar"),
						primary_action(values) {
							dialog.hide();
							runAction(
								frm,
								"trivia_sync.api.generate_apostila_recipe_material",
								{ recipe_name: frm.doc.name, level: values.level },
								__("Rascunho gerado pela Athena.")
							);
						},
					});
					dialog.show();
				}, __("Material"));
			}

			const submittable = versionChoices(frm, ["Draft", "Rejected"]);
			if (!isArchived && submittable.length && hasAnyRole("Trivia Editor")) {
				frm.add_custom_button(__("Submit for approval"), () => {
					const dialog = new frappe.ui.Dialog({
						title: __("Submit Version for Approval"),
						fields: [
							{ fieldname: "target", fieldtype: "Select", label: __("Version"), options: submittable, default: submittable[submittable.length - 1].value, reqd: 1 },
						],
						primary_action_label: __("Submit"),
						primary_action(values) {
							const { level, version } = parseChoice(values.target);
							dialog.hide();
							runAction(
								frm,
								"trivia_sync.api.submit_apostila_recipe_material",
								{ recipe_name: frm.doc.name, level, version },
								__("Version submitted for approval.")
							);
						},
					});
					dialog.show();
				}, __("Material"));
			}

			const reviewable = versionChoices(frm, ["Pending Approval"]);
			if (reviewable.length && hasAnyRole("Trivia Reviewer")) {
				frm.add_custom_button(__("Approve version"), () => {
					const dialog = new frappe.ui.Dialog({
						title: __("Approve Study Guide Version"),
						fields: [
							{ fieldname: "target", fieldtype: "Select", label: __("Version"), options: reviewable, default: reviewable[reviewable.length - 1].value, reqd: 1 },
							{ fieldname: "reason", fieldtype: "Small Text", label: __("Approval note") },
						],
						primary_action_label: __("Approve"),
						primary_action(values) {
							const { level, version } = parseChoice(values.target);
							dialog.hide();
							runAction(
								frm,
								"trivia_sync.api.approve_apostila_recipe_material",
								{ recipe_name: frm.doc.name, level, version, reason: values.reason || "" },
								__("Version approved.")
							);
						},
					});
					dialog.show();
				}, __("Review"));

				frm.add_custom_button(__("Reject version"), () => {
					const dialog = new frappe.ui.Dialog({
						title: __("Reject Study Guide Version"),
						fields: [
							{ fieldname: "target", fieldtype: "Select", label: __("Version"), options: reviewable, default: reviewable[reviewable.length - 1].value, reqd: 1 },
							{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason for rejection"), reqd: 1 },
						],
						primary_action_label: __("Reject"),
						primary_action(values) {
							const { level, version } = parseChoice(values.target);
							dialog.hide();
							runAction(
								frm,
								"trivia_sync.api.reject_apostila_recipe_material",
								{ recipe_name: frm.doc.name, level, version, reason: values.reason },
								__("Version rejected.")
							);
						},
					});
					dialog.show();
				}, __("Review"));
			}

			if (hasAnyRole("Trivia Integrator")) {
				const exportableLevels = [...new Set(rows.filter((row) => ["Approved", "Published"].includes(row.status)).map((row) => row.level))];
				if (!isArchived && exportableLevels.length) {
					frm.add_custom_button(__("Export PDF"), () => {
						const dialog = new frappe.ui.Dialog({
							title: __("Export Study Guide PDF"),
							fields: exportableLevels.map((level) => ({
								fieldname: `level_${level}`,
								fieldtype: "Check",
								label: __("Include level {0}", [level]),
								default: 1,
							})),
							primary_action_label: __("Export PDF"),
							primary_action(values) {
								const selected = exportableLevels.filter((level) => values[`level_${level}`]);
								if (!selected.length) {
									frappe.msgprint(__("Select at least one level to export."));
									return;
								}
								dialog.hide();
								frappe.call({
									method: "trivia_sync.api.export_apostila",
									args: { recipe_name: frm.doc.name, levels: JSON.stringify(selected) },
								}).then(({ message }) => {
									frappe.show_alert({ message: __("Study guide PDF exported and published."), indicator: "green" });
									frm.reload_doc();
									if (message?.file_url) window.open(message.file_url, "_blank");
								});
							},
						});
						dialog.show();
					}, __("Export"));
				}

				if (!isArchived) {
					frm.add_custom_button(__("Archive study guide"), () => {
						frappe.confirm(
							__("Archive this study guide recipe?"),
							() => runAction(frm, "trivia_sync.api.archive_apostila_recipe", { recipe_name: frm.doc.name }, __("Study guide archived."))
						);
					}, __("Export"));
				}
			}

			if (!isArchived && hasAnyRole("Trivia Editor", "Trivia Reviewer", "Trivia Integrator")) {
				frm.add_custom_button(__("Check freshness"), () => {
					frappe.call({
						method: "trivia_sync.api.check_apostila_recipe_freshness",
						args: { recipe_name: frm.doc.name },
					}).then(({ message }) => {
						const count = (message?.stale_versions || []).length;
						frappe.show_alert({
							message: count ? __("{0} version(s) marked Stale.", [count]) : __("All active versions are up to date."),
							indicator: count ? "orange" : "green",
						});
						if (count) frm.reload_doc();
					});
				}, __("Material"));
			}
		},
	});
})();
