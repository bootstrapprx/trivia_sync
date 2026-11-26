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
		frm.add_custom_button(__("Testar conexão da Athena"), () => {
			frappe.call({ method: "trivia_sync.api.ai_status" }).then(({ message }) => {
				frappe.msgprint(
					message?.ok
						? `Athena OK (${message.backend}): ${message.model}${message.flow_model ? ` · Flow Model: ${message.flow_model}` : ""}`
						: (message?.error || "Não foi possível validar a conexão da Athena.")
				);
			});
		}, "Athena");
		frm.add_custom_button(__("Analisar questões em lote"), () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Enfileirar lote da Athena"),
				fields: [
					{
						fieldname: "mode",
						fieldtype: "Select",
						label: __("Escopo da análise"),
						options: "full\ndifficulty\nexplanations\nknowledge",
						default: "full",
						reqd: 1,
					},
					{
						fieldname: "limit",
						fieldtype: "Int",
						label: __("Máximo de questões no lote (1–200)"),
						default: frm.doc.ai_batch_size || 20,
						reqd: 1,
					},
					{
						fieldname: "include_knowledge",
						fieldtype: "Check",
						label: __("Extrair e vincular páginas de conhecimento"),
						default: 1,
						depends_on: "eval:doc.mode=='full'",
					},
					{
						fieldname: "force",
						fieldtype: "Check",
						label: __("Reprocessar questões já analisadas"),
						default: 0,
					},
				],
				primary_action_label: __("Enfileirar lote"),
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
							message: `Lote da Athena (${message?.mode || values.mode}) enfileirado em ${message?.queue || "long"} para até ${message?.limit || values.limit} questão(ões).`,
							indicator: "green",
						});
					});
				},
			});
			dialog.show();
		}, "Athena");
		frm.add_custom_button(__("Configurar Knowledge & Skill (Flow)"), () => {
			frappe.call({ method: "trivia_sync.api.setup_flow_knowledge_and_skill" }).then(({ message }) => {
				const parts = [];
				if (message?.knowledge_base) parts.push(`Knowledge Base: ${message.knowledge_base}`);
				if (message?.knowledge_source) parts.push(`Source: ${message.knowledge_source}`);
				if (message?.skill) parts.push(`Skill: ${message.skill}`);
				if (message?.warnings?.length) parts.push(`Avisos: ${message.warnings.join(" | ")}`);
				frappe.msgprint(parts.join("<br>") || "Flow Knowledge & Skill sincronizados.");
			});
		}, "Athena");
	},
});
