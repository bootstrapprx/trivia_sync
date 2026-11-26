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
				label: __("Escopo da análise da Athena"),
				options: [
					{ label: __("Análise completa (dificuldade + tópicos/Tags + explicações + conhecimento)"), value: "full" },
					{ label: __("Apenas dificuldade, objetivo e tópicos/Tags"), value: "difficulty" },
					{ label: __("Apenas explicações por alternativa"), value: "explanations" },
					{ label: __("Apenas páginas de conhecimento (conceitos e subconceitos)"), value: "knowledge" },
				],
				default: "full",
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
				label: __("Reprocessar questões já analisadas / Prontas"),
				default: 0,
			},
			{
				fieldname: "run_now",
				fieldtype: "Check",
				label: __("Executar agora (síncrono, até 15 questões — sem aguardar worker)"),
				default: isSelection && selectedNames.length <= 5 ? 1 : 0,
			},
		];
		if (!isSelection) {
			fields.splice(1, 0, {
				fieldname: "limit",
				fieldtype: "Int",
				label: __("Máximo de questões neste lote (1–200)"),
				default: 20,
				reqd: 1,
			});
			fields.splice(2, 0, {
				fieldname: "use_list_filters",
				fieldtype: "Check",
				label: __("Respeitar filtros ativos da lista (matéria, banca, status, etc.)"),
				default: 1,
			});
		}

		const dialog = new frappe.ui.Dialog({
			title: isSelection
				? __("Athena em lote · {0} questão(ões) selecionada(s)", [selectedNames.length])
				: __("Athena em lote · Questões em preparação"),
			fields,
			primary_action_label: __("Iniciar análise da Athena"),
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
					freeze_message: values.run_now ? __("Athena está analisando o lote...") : undefined,
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
							message: __("Athena concluiu o lote: {0} analisada(s), {1} ignorada(s), {2} erro(s).", [
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
						? __("{0} questão(ões) selecionada(s)", [selectedNames.length])
						: __("até {0} questão(ões)", [message?.limit || values.limit]);
					frappe.show_alert({
						message: __("Lote da Athena ({0}) enfileirado em {1} para {2}. Acompanhe no Trivia Sync Run ou Dashboard.", [
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

			listview.page.add_action_item(__("Analisar selecionadas com Athena"), () => {
				const selected = (listview.get_checked_items() || []).map((row) => row.name);
				if (!selected.length) {
					frappe.msgprint(__("Selecione ao menos uma questão primeiro."));
					return;
				}
				openBatchDialog(listview, selected);
			});

			listview.page.add_inner_button(__("Athena · Analisar pendentes"), () => {
				openBatchDialog(listview, []);
			});

			listview.page.add_inner_button(__("Importar Prova Pronta"), () => {
				window.trivia_sync?.openExamImporterDialog?.({
					onImported: () => listview.refresh(),
				});
			});
		},
	};
})();
