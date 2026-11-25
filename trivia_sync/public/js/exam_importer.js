(() => {
	window.trivia_sync = window.trivia_sync || {};

	const escapeHtml = (value) => frappe.utils.escape_html(String(value ?? ""));

	const readLocalFile = (accept, onText) => {
		const input = document.createElement("input");
		input.type = "file";
		input.accept = accept;
		input.onchange = () => {
			const file = input.files?.[0];
			if (!file) return;
			const reader = new FileReader();
			reader.onload = () => onText(String(reader.result || ""), file.name);
			reader.readAsText(file, "utf-8");
		};
		input.click();
	};

	window.trivia_sync.openExamImporterDialog = (options = {}) => {
		const dialog = new frappe.ui.Dialog({
			title: __("Import Ready Exam (YAML / JSON → LMS Questions + LMS Quiz)"),
			size: "extra-large",
			fields: [
				{
					fieldname: "help_html",
					fieldtype: "HTML",
					options: `<div class="text-muted small mb-2">
						${__("Paste or upload a structured exam (YAML or JSON with <code>prova</code>, <code>textos_apoio</code>, and <code>questoes</code>). All questions enter the standard LMS Question flow (AI enrichment, Cockpit, Knowledge Pages) and an LMS Quiz is created automatically.")}
					</div>`,
				},
				{
					fieldname: "upload_bar",
					fieldtype: "HTML",
					options: `<div class="d-flex flex-wrap gap-2 mb-2" style="gap:8px;">
						<button type="button" class="btn btn-xs btn-default" data-action="load-exam-file">${__("Upload exam file (.yaml / .yml / .json)")}</button>
						<button type="button" class="btn btn-xs btn-default" data-action="load-key-file">${__("Upload answer key file (.txt / .csv / .json / .yaml)")}</button>
						<button type="button" class="btn btn-xs btn-default" data-action="preview-exam">${__("Preview parsed exam")}</button>
					</div>`,
				},
				{
					fieldname: "payload",
					fieldtype: "Code",
					options: "YAML",
					label: __("Exam payload (YAML or JSON)"),
					reqd: 1,
				},
				{
					fieldname: "answer_key",
					fieldtype: "Small Text",
					label: __("Answer key / Gabarito (optional — leave blank to enter manually on the Quiz)"),
					description: __("Examples: <code>1-A 2-C 3-E</code> · <code>01:A, 02:C</code> · <code>ACDBE...</code> · JSON/YAML map. Questions without an answer key are marked 'Answer key pending' until confirmed."),
				},
				{ fieldname: "sec_opts", fieldtype: "Section Break", label: __("Quiz & Contest Options") },
				{
					fieldname: "quiz_title",
					fieldtype: "Data",
					label: __("LMS Quiz title (optional override)"),
				},
				{
					fieldname: "passing_percentage",
					fieldtype: "Int",
					label: __("Passing percentage (%)"),
					default: 60,
				},
				{ fieldname: "col_opts", fieldtype: "Column Break" },
				{
					fieldname: "contest",
					fieldtype: "Link",
					options: "Trivia Contest",
					label: __("Contest (optional)"),
				},
				{
					fieldname: "contest_position",
					fieldtype: "Link",
					options: "Trivia Contest Position",
					label: __("Contest position (optional)"),
				},
				{
					fieldname: "update_existing",
					fieldtype: "Check",
					label: __("Update previously imported questions from this same exam (idempotent)"),
					default: 1,
				},
				{ fieldname: "sec_preview", fieldtype: "Section Break", label: __("Preview") },
				{
					fieldname: "preview_html",
					fieldtype: "HTML",
					options: `<div class="text-muted small">${__("Click 'Preview parsed exam' to validate questions, supporting texts, disciplines, and answer key before importing.")}</div>`,
				},
			],
			primary_action_label: __("Import Exam & Create LMS Quiz"),
			primary_action(values) {
				if (!(values.payload || "").trim()) {
					frappe.msgprint(__("Paste or upload the exam YAML/JSON first."));
					return;
				}
				frappe.call({
					method: "trivia_sync.api.import_ready_exam",
					freeze: true,
					freeze_message: __("Importing supporting texts, LMS Questions, and creating LMS Quiz..."),
					args: {
						payload: values.payload,
						answer_key: values.answer_key || null,
						quiz_title: values.quiz_title || null,
						passing_percentage: values.passing_percentage ?? 60,
						contest: values.contest || null,
						contest_position: values.contest_position || null,
						update_existing: values.update_existing ? 1 : 0,
					},
				}).then(({ message }) => {
					dialog.hide();
					if (!message) return;
					const pendingNote = message.pending_count
						? `<p class="mt-2"><strong>${__("{0} question(s) have a pending answer key.", [message.pending_count])}</strong> ${__("Open the created LMS Quiz and click <em>Answer Key (Manual / Import)</em> to fill or import the gabarito in seconds.")}</p>`
						: `<p class="mt-2 text-success">${__("All {0} questions imported with confirmed answer keys.", [message.answered_count])}</p>`;
					frappe.msgprint({
						title: __("Exam Imported Successfully"),
						indicator: message.pending_count ? "orange" : "green",
						message: `
							<p><strong>${escapeHtml(message.quiz_title)}</strong></p>
							<ul>
								<li>${__("Questions created")}: <strong>${message.questions_created || 0}</strong></li>
								<li>${__("Questions updated")}: <strong>${message.questions_updated || 0}</strong></li>
								<li>${__("Supporting texts linked")}: <strong>${message.supporting_texts || 0}</strong></li>
								<li>${__("Total questions in LMS Quiz")}: <strong>${message.total_questions || 0}</strong></li>
							</ul>
							${pendingNote}
							<div class="mt-3">
								<a class="btn btn-primary btn-sm" href="/app/lms-quiz/${encodeURIComponent(message.quiz_name)}">${__("Open LMS Quiz")}</a>
								<a class="btn btn-default btn-sm ml-2" href="/app/lms-question">${__("Open LMS Question Bank")}</a>
							</div>`,
					});
					if (typeof options.onImported === "function") options.onImported(message);
				});
			},
		});

		const renderPreview = (data) => {
			const p = data.prova || {};
			const discs = Object.entries(data.disciplines || {})
				.map(([name, count]) => `<span class="indicator-pill blue" style="margin:2px 4px 2px 0;">${escapeHtml(name)} (${count})</span>`)
				.join("");
			const samples = (data.sample_questions || [])
				.map((q) => `<li><strong>#${q.numero}</strong> [${escapeHtml(q.disciplina || "—")}] ${escapeHtml(q.enunciado)} <span class="text-muted">(${(q.alternativas || []).join("/")}${q.gabarito?.length ? ` · Gabarito: ${q.gabarito.join(",")}` : " · Gabarito pendente"})</span></li>`)
				.join("");
			dialog.fields_dict.preview_html.$wrapper.html(`
				<div class="frappe-card p-3">
					<div class="mb-2"><strong>${escapeHtml(data.quiz_title)}</strong> <span class="text-muted">(${escapeHtml(data.exam_code)})</span></div>
					<div class="small text-muted mb-2">
						${escapeHtml(p.banca || "—")} · ${escapeHtml(p.orgao || "—")} · ${escapeHtml(p.ano || "—")}${p.duracao_minutos ? ` · ${p.duracao_minutos} min` : ""}
					</div>
					<div class="mb-2">
						<span class="indicator-pill green">${data.total_questions} ${__("questions")}</span>
						<span class="indicator-pill blue">${data.supporting_texts} ${__("supporting texts")}</span>
						<span class="indicator-pill ${data.pending_count ? "orange" : "green"}">${data.answered_count} ${__("answered")} / ${data.pending_count} ${__("pending")}</span>
					</div>
					${discs ? `<div class="mb-2">${discs}</div>` : ""}
					${samples ? `<div class="small"><strong>${__("Sample questions")}:</strong><ul class="mt-1 mb-0 pl-3">${samples}</ul></div>` : ""}
				</div>
			`);
			if (!dialog.get_value("quiz_title") && data.quiz_title) {
				dialog.set_value("quiz_title", data.quiz_title);
			}
		};

		dialog.$wrapper.on("click", '[data-action="load-exam-file"]', () => {
			readLocalFile(".yaml,.yml,.json,.txt", (text, filename) => {
				dialog.set_value("payload", text);
				frappe.show_alert({ message: __("Loaded {0}", [filename]), indicator: "green" });
			});
		});

		dialog.$wrapper.on("click", '[data-action="load-key-file"]', () => {
			readLocalFile(".txt,.csv,.json,.yaml,.yml", (text, filename) => {
				dialog.set_value("answer_key", text);
				frappe.show_alert({ message: __("Loaded answer key from {0}", [filename]), indicator: "green" });
			});
		});

		dialog.$wrapper.on("click", '[data-action="preview-exam"]', () => {
			const payload = dialog.get_value("payload");
			if (!(payload || "").trim()) {
				frappe.msgprint(__("Paste or upload the exam YAML/JSON first."));
				return;
			}
			frappe.call({
				method: "trivia_sync.api.preview_ready_exam",
				freeze: true,
				freeze_message: __("Parsing exam..."),
				args: { payload, answer_key: dialog.get_value("answer_key") || null },
			}).then(({ message }) => {
				if (message) renderPreview(message);
			});
		});

		dialog.show();
	};
})();
