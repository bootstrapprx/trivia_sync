frappe.ui.form.on("Trivia Sync Settings", {
	setup(frm) {
		frm.set_query("ai_flow_model", () => ({
			filters: { enabled: 1, embedding: 0 },
		}));
	},
	refresh(frm) {
		if (!frappe.user.has_role("System Manager")) return;
		frm.add_custom_button("Test QAPI", () => {
			frappe.call({ method: "trivia_sync.api.qapi_status" }).then(({ message }) => {
				frappe.msgprint(message?.ok ? `QAPI OK: ${message.total ?? "connection successful"}` : (message?.error || "Could not validate QAPI."));
			});
		}, "Sync");
		frm.add_custom_button("Sync QAPI questions", () => {
			frappe.call({ method: "trivia_sync.api.enqueue_qapi_sync" }).then(() => frappe.show_alert({ message: "QAPI sync queued.", indicator: "green" }));
		}, "Sync");
		frm.add_custom_button("Sync LMS → Trivia", () => {
			frappe.call({ method: "trivia_sync.api.enqueue_lms_sync" }).then(() => frappe.show_alert({ message: "Frappe LMS sync queued.", indicator: "green" }));
		}, "Sync");
		frm.add_custom_button("Repair imported rich content", () => {
			frappe.call({ method: "trivia_sync.api.enqueue_qapi_reformat" }).then(({ message }) => {
				frappe.show_alert({ message: `Reformat queued on ${message?.queue || "long"}${message?.job_id ? ` · ${message.job_id}` : ""}.`, indicator: "green" });
			});
		}, "Sync");
		frm.add_custom_button("Test AI connection", () => {
			frappe.call({ method: "trivia_sync.api.ai_status" }).then(({ message }) => {
				frappe.msgprint(
					message?.ok
						? `AI OK (${message.backend}): ${message.model}${message.flow_model ? ` · Flow Model: ${message.flow_model}` : ""}`
						: (message?.error || "Could not validate AI connection.")
				);
			});
		}, "IA");
		frm.add_custom_button("Enrich questions with AI", () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Queue AI Batch Enrichment"),
				fields: [
					{
						fieldname: "mode",
						fieldtype: "Select",
						label: __("Enrichment scope"),
						options: "full\ndifficulty\nexplanations\nknowledge",
						default: "full",
						reqd: 1,
					},
					{
						fieldname: "limit",
						fieldtype: "Int",
						label: __("Max questions in batch (1–200)"),
						default: frm.doc.ai_batch_size || 20,
						reqd: 1,
					},
					{
						fieldname: "include_knowledge",
						fieldtype: "Check",
						label: __("Extract & link Knowledge Pages"),
						default: 1,
						depends_on: "eval:doc.mode=='full'",
					},
					{
						fieldname: "force",
						fieldtype: "Check",
						label: __("Re-process already enriched questions"),
						default: 0,
					},
				],
				primary_action_label: __("Queue Batch"),
				primary_action(values) {
					dialog.hide();
					frappe.call({
						method: "trivia_sync.api.enqueue_ai_batch",
						args: {
							mode: values.mode,
							limit: values.limit,
							include_knowledge: values.include_knowledge ? 1 : 0,
							force: values.force ? 1 : 0,
						},
					}).then(({ message }) => {
						frappe.show_alert({
							message: `AI batch (${message?.mode || values.mode}) queued on ${message?.queue || "long"} for up to ${message?.limit || values.limit} question(s).`,
							indicator: "green",
						});
					});
				},
			});
			dialog.show();
		}, "IA");
		frm.add_custom_button("Setup Flow Knowledge & Skill", () => {
			frappe.call({ method: "trivia_sync.api.setup_flow_knowledge_and_skill" }).then(({ message }) => {
				const parts = [];
				if (message?.knowledge_base) parts.push(`Knowledge Base: ${message.knowledge_base}`);
				if (message?.knowledge_source) parts.push(`Source: ${message.knowledge_source}`);
				if (message?.skill) parts.push(`Skill: ${message.skill}`);
				if (message?.warnings?.length) parts.push(`Warnings: ${message.warnings.join(" | ")}`);
				frappe.msgprint(parts.join("<br>") || "Flow Knowledge & Skill synchronized.");
			});
		}, "IA");
	},
});
