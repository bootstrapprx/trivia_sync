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

	frappe.ui.form.on("Trivia Lesson Recipe", {
		refresh(frm) {
			if (frm.is_new()) return;
			const rows = frm.doc.material_versions || [];
			const staleCount = rows.filter((row) => row.status === "Stale").length;
			const pendingCount = rows.filter((row) => row.status === "Pending Approval").length;
			if (staleCount) {
				frm.dashboard.set_headline_alert(
					__("{0} material version(s) are Stale because source questions or methodology changed.", [staleCount]),
					"orange"
				);
			} else if (pendingCount) {
				frm.dashboard.set_headline_alert(
					__("{0} material version(s) awaiting reviewer approval.", [pendingCount]),
					"blue"
				);
			}

			const isArchived = frm.doc.status === "Archived";

			if (!isArchived && hasAnyRole("Trivia Editor")) {
				frm.add_custom_button(__("Create manual draft"), () => {
					const dialog = new frappe.ui.Dialog({
						title: __("Create Manual Lesson Draft"),
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
								"trivia_sync.api.create_manual_lesson_material",
								{ recipe_name: frm.doc.name, level: values.level, content: values.content, summary: values.summary || "" },
								__("Manual draft created.")
							);
						},
					});
					dialog.show();
				}, __("Material"));
			}

			if (!isArchived && hasAnyRole("Trivia Integrator")) {
				frm.add_custom_button(__("Generate AI draft"), () => {
					const dialog = new frappe.ui.Dialog({
						title: __("Generate AI Lesson Draft"),
						fields: [
							{ fieldname: "level", fieldtype: "Select", label: __("Level"), options: "mais\n180\n360", default: "mais", reqd: 1 },
						],
						primary_action_label: __("Generate"),
						primary_action(values) {
							dialog.hide();
							runAction(
								frm,
								"trivia_sync.api.generate_lesson_material",
								{ recipe_name: frm.doc.name, level: values.level },
								__("AI draft generated.")
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
								"trivia_sync.api.submit_lesson_recipe_material",
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
						title: __("Approve Lesson Version"),
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
								"trivia_sync.api.approve_lesson_recipe_material",
								{ recipe_name: frm.doc.name, level, version, reason: values.reason || "" },
								__("Version approved.")
							);
						},
					});
					dialog.show();
				}, __("Review"));

				frm.add_custom_button(__("Reject version"), () => {
					const dialog = new frappe.ui.Dialog({
						title: __("Reject Lesson Version"),
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
								"trivia_sync.api.reject_lesson_recipe_material",
								{ recipe_name: frm.doc.name, level, version, reason: values.reason },
								__("Version rejected.")
							);
						},
					});
					dialog.show();
				}, __("Review"));
			}

			if (hasAnyRole("Trivia Integrator")) {
				const publishableLevels = [...new Set(rows.filter((row) => row.status === "Approved").map((row) => row.level))];
				if (!isArchived && publishableLevels.length) {
					frm.add_custom_button(__("Publish to LMS lesson"), () => {
						const dialog = new frappe.ui.Dialog({
							title: __("Publish Approved Material to LMS Lesson"),
							fields: [
								{ fieldname: "level", fieldtype: "Select", label: __("Level"), options: publishableLevels.join("\n"), default: publishableLevels[0], reqd: 1 },
							],
							primary_action_label: __("Publish"),
							primary_action(values) {
								dialog.hide();
								runAction(
									frm,
									"trivia_sync.api.publish_lesson_material",
									{ recipe_name: frm.doc.name, level: values.level },
									__("Material published to LMS lesson.")
								);
							},
						});
						dialog.show();
					}, __("LMS"));
				}

				const publishedLevels = [...new Set(rows.filter((row) => row.status === "Published").map((row) => row.level))];
				if (publishedLevels.length) {
					frm.add_custom_button(__("Unpublish from LMS lesson"), () => {
						const dialog = new frappe.ui.Dialog({
							title: __("Unpublish Material from LMS Lesson"),
							fields: [
								{ fieldname: "level", fieldtype: "Select", label: __("Level"), options: ["All", ...publishedLevels].join("\n"), default: "All", reqd: 1 },
							],
							primary_action_label: __("Unpublish"),
							primary_action(values) {
								dialog.hide();
								runAction(
									frm,
									"trivia_sync.api.unpublish_lesson_recipe_material",
									{ recipe_name: frm.doc.name, level: values.level === "All" ? null : values.level },
									__("Material removed from LMS lesson.")
								);
							},
						});
						dialog.show();
					}, __("LMS"));
				}

				if (!isArchived) {
					frm.add_custom_button(__("Archive recipe"), () => {
						frappe.confirm(
							__("Archive this recipe and remove any published blocks from the LMS lesson?"),
							() => runAction(frm, "trivia_sync.api.archive_lesson_recipe", { recipe_name: frm.doc.name }, __("Recipe archived."))
						);
					}, __("LMS"));
				}
			}

			if (!isArchived && hasAnyRole("Trivia Editor", "Trivia Reviewer", "Trivia Integrator")) {
				frm.add_custom_button(__("Check freshness"), () => {
					frappe.call({
						method: "trivia_sync.api.check_lesson_recipe_freshness",
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
