(() => {
	const canRunAI = () =>
		frappe.user.has_role("System Manager") ||
		frappe.user.has_role("Trivia Editor") ||
		frappe.user.has_role("Trivia Reviewer") ||
		frappe.user.has_role("Trivia Integrator");

	const openBatchDialog = (listview, selectedNames = []) => {
		const isSelection = selectedNames.length > 0;
		const fields = [
			{
				fieldname: "mode",
				fieldtype: "Select",
				label: __("Enrichment scope"),
				options: [
					{ label: __("Full enrichment (difficulty + topics/Tags + per-option explanations + knowledge)"), value: "full" },
					{ label: __("Difficulty, objective & topics/Tags only"), value: "difficulty" },
					{ label: __("Per-option explanations only"), value: "explanations" },
					{ label: __("Knowledge pages (concepts & sub-concepts) only"), value: "knowledge" },
				],
				default: "full",
				reqd: 1,
			},
			{
				fieldname: "include_knowledge",
				fieldtype: "Check",
				label: __("Extract & link Knowledge Pages (concepts/sub-concepts)"),
				default: 1,
				depends_on: "eval:doc.mode=='full'",
			},
			{
				fieldname: "force",
				fieldtype: "Check",
				label: __("Re-process questions that are already Ready/enriched"),
				default: 0,
			},
			{
				fieldname: "run_now",
				fieldtype: "Check",
				label: __("Run immediately (synchronous, up to 15 questions — no background worker needed)"),
				default: isSelection && selectedNames.length <= 5 ? 1 : 0,
			},
		];
		if (!isSelection) {
			fields.splice(1, 0, {
				fieldname: "limit",
				fieldtype: "Int",
				label: __("Max questions in this batch (1–200)"),
				default: 20,
				reqd: 1,
			});
			fields.splice(2, 0, {
				fieldname: "use_list_filters",
				fieldtype: "Check",
				label: __("Respect active list filters (subject, board, status, etc.)"),
				default: 1,
			});
		}

		const dialog = new frappe.ui.Dialog({
			title: isSelection
				? __("Batch AI Enrichment · {0} selected LMS question(s)", [selectedNames.length])
				: __("Batch AI Enrichment · In Preparation Questions"),
			fields,
			primary_action_label: __("Start AI Batch"),
			primary_action(values) {
				const activeFilters = {};
				if (!isSelection && values.use_list_filters && listview.filter_area) {
					const rawFilters = listview.filter_area.get() || [];
					rawFilters.forEach((entry) => {
						if (Array.isArray(entry) && entry.length >= 4 && entry[0] === "LMS Question") {
							activeFilters[entry[1]] = [entry[2], entry[3]];
						}
					});
				}
				dialog.hide();
				const method = values.run_now ? "trivia_sync.api.run_ai_batch_now" : "trivia_sync.api.enqueue_ai_batch";
				frappe.call({
					method,
					freeze: Boolean(values.run_now),
					freeze_message: values.run_now ? __("Running AI enrichment batch...") : undefined,
					args: {
						question_names: isSelection ? JSON.stringify(selectedNames) : null,
						mode: values.mode,
						limit: isSelection ? selectedNames.length : values.limit,
						include_knowledge: values.include_knowledge ? 1 : 0,
						force: values.force ? 1 : 0,
						filters: Object.keys(activeFilters).length ? JSON.stringify(activeFilters) : null,
					},
				}).then(({ message }) => {
					if (values.run_now) {
						frappe.show_alert({
							message: __("AI batch finished: {0} enriched, {1} skipped, {2} errors.", [
								message?.enriched || 0,
								message?.skipped || 0,
								message?.errors || 0,
							]),
							indicator: message?.errors ? "orange" : "green",
						});
						listview.refresh();
						return;
					}
					const scopeLabel = isSelection
						? __("{0} selected question(s)", [selectedNames.length])
						: __("up to {0} question(s)", [message?.limit || values.limit]);
					frappe.show_alert({
						message: __("AI batch ({0}) queued on {1} for {2}. Track progress in Trivia Sync Run or Dashboard.", [
							message?.mode || values.mode,
							message?.queue || "long",
							scopeLabel,
						]),
						indicator: "green",
					});
				});
			},
		});
		dialog.show();
	};

	const existing = frappe.listview_settings["LMS Question"] || {};
	const previousOnload = existing.onload;
	frappe.listview_settings["LMS Question"] = {
		...existing,
		onload(listview) {
			if (typeof previousOnload === "function") previousOnload(listview);
			if (!canRunAI()) return;

			listview.page.add_action_item(__("Enrich selected with AI"), () => {
				const selected = (listview.get_checked_items() || []).map((row) => row.name);
				if (!selected.length) {
					frappe.msgprint(__("Select at least one question first."));
					return;
				}
				openBatchDialog(listview, selected);
			});

			listview.page.add_inner_button(__("Enrich pending batch (AI)"), () => {
				openBatchDialog(listview, []);
			});

			listview.page.add_inner_button(__("Import Ready Exam"), () => {
				window.trivia_sync?.openExamImporterDialog?.({
					onImported: () => listview.refresh(),
				});
			});
		},
	};
})();
