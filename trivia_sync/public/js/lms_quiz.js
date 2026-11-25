(() => {
	const canBuild = () =>
		frappe.user.has_role("System Manager") ||
		frappe.user.has_role("Trivia Editor") ||
		frappe.user.has_role("Trivia Reviewer") ||
		frappe.user.has_role("Trivia Integrator");

	const escapeHtml = (value) => frappe.utils.escape_html(String(value ?? ""));

	const parseBulkKeyClient = (rawText) => {
		const text = String(rawText || "").trim();
		if (!text) return {};
		const out = {};
		if (text[0] === "{" || text[0] === "[") {
			try {
				const parsed = JSON.parse(text);
				if (Array.isArray(parsed)) {
					parsed.forEach((v, idx) => {
						const l = String(v || "").trim().toUpperCase();
						if (/^[A-J]$/.test(l)) out[idx + 1] = l;
					});
					return out;
				}
				if (parsed && typeof parsed === "object") {
					Object.entries(parsed).forEach(([k, v]) => {
						const num = Number(String(k).replace(/\D/g, ""));
						const l = Array.isArray(v) ? String(v[0] || "").trim().toUpperCase() : String(v || "").trim().toUpperCase();
						if (num && /^[A-J]$/.test(l)) out[num] = l;
					});
					return out;
				}
			} catch (e) {
				// fall through to regex parsing
			}
		}
		const pairRegex = /(?:^|[\s,;|])(?:Q|QUEST[AÃ]O)?\s*0*(\d{1,3})\s*[-:=.)\s]\s*([A-J])(?=$|[\s,;|])/gi;
		let match;
		while ((match = pairRegex.exec(text)) !== null) {
			out[Number(match[1])] = match[2].toUpperCase();
		}
		if (Object.keys(out).length) return out;

		const compact = text.toUpperCase().replace(/[\s,;|/-]+/g, "");
		if (/^[A-JX*]+$/.test(compact)) {
			for (let i = 0; i < compact.length; i += 1) {
				if (/^[A-J]$/.test(compact[i])) out[i + 1] = compact[i];
			}
		}
		return out;
	};

	const openAnswerKeyDialog = (frm) => {
		frappe.call({
			method: "trivia_sync.api.get_quiz_answer_key_state",
			args: { quiz_name: frm.doc.name },
			freeze: true,
			freeze_message: __("Loading quiz questions..."),
		}).then(({ message }) => {
			const state = message || {};
			const questions = state.questions || [];
			if (!questions.length) {
				frappe.msgprint(__("Add questions to this quiz first."));
				return;
			}

			const selections = {};
			questions.forEach((q) => {
				if (!q.answer_key_pending && q.correct?.length) {
					selections[q.numero] = q.correct[0];
				}
			});

			const dialog = new frappe.ui.Dialog({
				title: __("Answer Key (Manual / Import) · {0}", [state.quiz_title || frm.doc.title]),
				size: "extra-large",
				fields: [
					{
						fieldname: "bulk_key",
						fieldtype: "Small Text",
						label: __("Optional bulk import (paste 1-A 2-C... or ACDBE... or JSON)"),
					},
					{
						fieldname: "bulk_actions",
						fieldtype: "HTML",
						options: `<div class="d-flex flex-wrap align-items-center mb-3" style="gap:8px;">
							<button type="button" class="btn btn-xs btn-default" data-action="apply-bulk-to-grid">${__("Fill grid from pasted answer key")}</button>
							<button type="button" class="btn btn-xs btn-default" data-action="upload-key-file">${__("Upload answer key file")}</button>
							<span class="text-muted small" data-progress-label></span>
						</div>`,
					},
					{
						fieldname: "grid_html",
						fieldtype: "HTML",
					},
				],
				primary_action_label: __("Save Answer Key to Questions"),
				primary_action() {
					if (!Object.keys(selections).length) {
						frappe.msgprint(__("Select at least one answer in the grid or paste an answer key."));
						return;
					}
					frappe.call({
						method: "trivia_sync.api.apply_quiz_answer_key",
						freeze: true,
						freeze_message: __("Updating answer keys on LMS Questions..."),
						args: {
							quiz_name: frm.doc.name,
							answer_key: JSON.stringify(selections),
						},
					}).then(({ message: res }) => {
						dialog.hide();
						frappe.show_alert({
							message: __("Answer key saved for {0}/{1} question(s).", [res?.updated || 0, res?.total || questions.length]),
							indicator: "green",
						});
						frm.reload_doc();
					});
				},
			});

			const updateProgress = () => {
				const answered = Object.keys(selections).length;
				dialog.$wrapper.find("[data-progress-label]").text(
					__("{0}/{1} marked in grid ({2} originally pending)", [answered, questions.length, state.pending_count || 0])
				);
			};

			const renderGrid = () => {
				const rowsHtml = questions.map((q) => {
					const chosen = selections[q.numero] || "";
					const buttons = (q.letters || ["A", "B", "C", "D", "E"]).map((letter) => {
						const active = chosen === letter;
						return `<button type="button" class="btn btn-xs ${active ? "btn-primary" : "btn-default"}" data-qnum="${q.numero}" data-letter="${letter}" style="min-width:28px;">${letter}</button>`;
					}).join(" ");
					const statusBadge = chosen
						? `<span class="indicator-pill green">${chosen}</span>`
						: `<span class="indicator-pill orange">${__("Pending")}</span>`;
					return `<div class="d-flex align-items-center justify-content-between py-2" style="border-bottom:1px solid var(--border-color);gap:10px;">
						<div style="min-width:0;flex:1;">
							<div class="d-flex align-items-center" style="gap:6px;">
								<strong>#${q.numero}</strong>
								${q.subject ? `<span class="text-muted small">· ${escapeHtml(q.subject)}</span>` : ""}
								${statusBadge}
							</div>
							<div class="text-muted small text-truncate" title="${escapeHtml(q.title)}">${escapeHtml(q.title)}</div>
						</div>
						<div class="d-flex flex-shrink-0" style="gap:4px;">${buttons}</div>
					</div>`;
				}).join("");

				dialog.fields_dict.grid_html.$wrapper.html(`
					<div style="max-height:460px;overflow-y:auto;padding-right:6px;">${rowsHtml}</div>
				`);
				updateProgress();
			};

			dialog.$wrapper.on("click", "[data-qnum][data-letter]", (ev) => {
				const btn = ev.currentTarget;
				const qnum = Number(btn.getAttribute("data-qnum"));
				const letter = btn.getAttribute("data-letter");
				selections[qnum] = letter;
				renderGrid();
			});

			dialog.$wrapper.on("click", '[data-action="apply-bulk-to-grid"]', () => {
				const parsed = parseBulkKeyClient(dialog.get_value("bulk_key"));
				const keys = Object.keys(parsed);
				if (!keys.length) {
					frappe.msgprint(__("Could not detect any answers. Try formats like '1-A 2-C 3-E' or 'ACDBE'."));
					return;
				}
				keys.forEach((k) => { selections[Number(k)] = parsed[k]; });
				renderGrid();
				frappe.show_alert({ message: __("Filled {0} answer(s) into the grid.", [keys.length]), indicator: "green" });
			});

			dialog.$wrapper.on("click", '[data-action="upload-key-file"]', () => {
				const input = document.createElement("input");
				input.type = "file";
				input.accept = ".txt,.csv,.json,.yaml,.yml";
				input.onchange = () => {
					const file = input.files?.[0];
					if (!file) return;
					const reader = new FileReader();
					reader.onload = () => {
						dialog.set_value("bulk_key", String(reader.result || ""));
						const parsed = parseBulkKeyClient(reader.result);
						Object.entries(parsed).forEach(([k, v]) => { selections[Number(k)] = v; });
						renderGrid();
						frappe.show_alert({ message: __("Loaded {0} answer(s) from {1}.", [Object.keys(parsed).length, file.name]), indicator: "green" });
					};
					reader.readAsText(file, "utf-8");
				};
				input.click();
			});

			renderGrid();
			dialog.show();
		});
	};

	frappe.ui.form.on("LMS Quiz", {
		refresh(frm) {
			if (frm.is_new() || !canBuild()) return;

			if ((frm.doc.questions || []).length) {
				frm.add_custom_button(__("Answer Key (Manual / Import)"), () => {
					openAnswerKeyDialog(frm);
				});
			}

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
