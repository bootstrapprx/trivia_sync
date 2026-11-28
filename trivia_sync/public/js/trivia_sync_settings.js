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
			frappe.call({ method: "trivia_sync.api.enqueue_lms_sync" }).then(() => frappe.show_alert({ message: "Sincronização Trivia Concursos enfileirada.", indicator: "green" }));
		}, "Sync");
		frm.add_custom_button(__("Reaplicar Whitelabel Agora"), () => {
			frappe.call({
				method: "trivia_sync.api.apply_whitelabel_now",
				type: "POST",
				freeze: true,
				freeze_message: __("Aplicando identidade visual Trivia Concursos..."),
			}).then(({ message }) => {
				const count = (message?.updated_doctypes || []).length;
				frappe.show_alert({
					message: count
						? __("Whitelabel Trivia Concursos atualizado ({0} configuração(ões)).", [count])
						: __("Whitelabel Trivia Concursos já está sincronizado."),
					indicator: "green",
				});
			});
		}, __("Identidade Visual"));
		frm.add_custom_button("Repair imported rich content", () => {
			frappe.call({ method: "trivia_sync.api.enqueue_qapi_reformat" }).then(({ message }) => {
				frappe.show_alert({ message: `Reformat queued on ${message?.queue || "long"}${message?.job_id ? ` · ${message.job_id}` : ""}.`, indicator: "green" });
			});
		}, "Sync");
		frm.add_custom_button(__("Testar conexão da Athena"), () => {
			frappe.call({ method: "trivia_sync.api.ai_status" }).then(({ message }) => {
				if (message?.backend === "Codex CLI (OAuth)") {
					frappe.msgprint(
						message?.ok
							? `Athena OK (Codex CLI OAuth · ${message.model})<br><small class="text-muted">${frappe.utils.escape_html(message.status_text || "")}</small>`
							: `Codex CLI ainda não autenticado via OAuth.<br><small class="text-muted">${frappe.utils.escape_html(message?.status_text || message?.error || "")}</small><br><br>Use <b>Athena → Conectar Codex (OAuth)</b>.`
					);
					return;
				}
				frappe.msgprint(
					message?.ok
						? `Athena OK (${message.backend}): ${message.model}${message.flow_model ? ` · Flow Model: ${message.flow_model}` : ""}`
						: (message?.error || "Não foi possível validar a conexão da Athena.")
				);
			});
		}, "Athena");
		frm.add_custom_button(__("Conectar Codex (OAuth)"), () => {
			frappe.call({
				method: "trivia_sync.api.start_codex_oauth",
				freeze: true,
				freeze_message: __("Iniciando autenticação OAuth do Codex..."),
			}).then(({ message }) => {
				if (!message) return;
				if (message.already_authenticated) {
					frappe.show_alert({ message: __("Codex já está conectado via OAuth!"), indicator: "green" });
					frappe.msgprint(`<strong>Codex OAuth ativo</strong><br><small class="text-muted">${frappe.utils.escape_html(message.status_text || "")}</small>`);
					return;
				}
				const url = frappe.utils.escape_html(message.verification_url || "https://auth.openai.com/codex/device");
				const code = frappe.utils.escape_html(message.user_code || "");
				const raw = frappe.utils.escape_html(message.raw_output || "");
				const dialog = new frappe.ui.Dialog({
					title: __("Conectar Codex via OAuth (sem chave de API)"),
					fields: [
						{
							fieldname: "oauth_html",
							fieldtype: "HTML",
							options: `
								<div class="mb-3">
									<p class="text-muted small mb-2">1. Clique no botão abaixo para abrir a página oficial de autorização da OpenAI e entre com sua conta ChatGPT.</p>
									<a href="${url}" target="_blank" rel="noopener" class="btn btn-primary btn-sm">Abrir página de autorização OpenAI ↗</a>
								</div>
								${code ? `
								<div class="mb-3 p-3 rounded border" style="background: var(--control-bg);">
									<div class="small text-muted mb-1">2. Digite este código único no navegador:</div>
									<div style="font-size: 1.5rem; font-weight: 700; letter-spacing: 0.14em; font-family: monospace;">${code}</div>
								</div>` : `<pre class="small p-2 rounded border" style="white-space: pre-wrap;">${raw}</pre>`}
								<p class="text-muted small mb-0">3. Após autorizar no navegador, clique em <strong>Verificar conexão</strong> abaixo.</p>
								<div class="mt-2 small" data-codex-status></div>
							`,
						},
					],
					primary_action_label: __("Verificar conexão"),
					primary_action() {
						frappe.call({
							method: "trivia_sync.api.get_codex_oauth_status",
						}).then(({ message: st }) => {
							const box = dialog.$wrapper.find("[data-codex-status]");
							if (st?.authenticated) {
								box.html(`<span class="indicator-pill green">${__("Conectado via OAuth!")}</span> <span class="text-muted">${frappe.utils.escape_html(st.status_text || "")}</span>`);
								frappe.show_alert({ message: __("Codex conectado com sucesso via OAuth!"), indicator: "green" });
							} else {
								box.html(`<span class="indicator-pill orange">${__("Aguardando autorização no navegador...")}</span>`);
							}
						});
					},
				});
				dialog.show();
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
