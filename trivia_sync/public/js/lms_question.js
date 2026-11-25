(() => {
	const LETTERS = "ABCDEFGHIJ";
	const mathScriptUrl = "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js";

	const ensureMathJax = () => {
		if (window.MathJax?.typesetPromise) return Promise.resolve(window.MathJax);
		window.MathJax = window.MathJax || {
			tex: {
				inlineMath: [["\\(", "\\)"], ["$", "$"], ["\\$", "\\$"]],
				displayMath: [["\\[", "\\]"], ["$$", "$$"]],
				processEscapes: true,
			},
			options: { skipHtmlTags: ["script", "noscript", "style", "textarea", "pre", "code"] },
		};
		return new Promise((resolve) => {
			if (document.querySelector(`script[src="${mathScriptUrl}"]`)) {
				const wait = setInterval(() => {
					if (window.MathJax?.typesetPromise) { clearInterval(wait); resolve(window.MathJax); }
				}, 100);
				return;
			}
			const script = document.createElement("script");
			script.src = mathScriptUrl;
			script.async = true;
			script.onload = () => resolve(window.MathJax);
			document.head.appendChild(script);
		});
	};

	const safe = (value) => {
		const raw = String(value ?? "");
		return frappe.utils.sanitize_html ? frappe.utils.sanitize_html(raw) : raw;
	};
	const escapeAttr = (value) => frappe.utils.escape_html(String(value ?? ""));
	const rich = (value) => {
		const raw = String(value ?? "").trim();
		if (!raw) return `<span class="text-muted">${__("Not provided")}</span>`;
		return safe(raw.includes("<") ? raw : raw.replace(/\r?\n/g, "<br>"));
	};

	const readOptions = (doc) => {
		const rows = [];
		for (let i = 1; i <= 10; i += 1) {
			const text = String(doc[`option_${i}`] || "").trim();
			if (!text) continue;
			rows.push({
				index: i,
				letter: LETTERS[i - 1],
				text,
				correct: Boolean(Number(doc[`is_correct_${i}`] || 0)),
				explanation: String(doc[`explanation_${i}`] || "").trim(),
			});
		}
		return rows;
	};

	const renderCockpit = (frm) => {
		const field = frm.fields_dict.question?.$wrapper;
		if (!field) return;
		let root = frm.$wrapper.find(".trivia-question-cockpit");
		if (!root.length) {
			root = $("<section class='trivia-question-cockpit frappe-card'></section>");
			field.after(root);
		}
		const d = frm.doc;
		if (d.type && d.type !== "Choices") {
			root.empty().hide();
			return;
		}
		root.show();

		const optionItems = readOptions(d);
		const missingLetters = optionItems.filter((item) => !item.explanation).map((item) => item.letter);
		const explainedCount = optionItems.length - missingLetters.length;

		const optionRows = optionItems.map((item) => {
			const hasText = Boolean(item.explanation);
			const label = item.correct
				? __("Why this answer is correct")
				: __("Why this alternative is wrong (do not reveal the correct answer)");
			const placeholder = item.correct
				? __("Explain why this alternative satisfies the question...")
				: __("Explain the flaw in this alternative without giving away the answer key...");
			return `
				<div class="trivia-option-card ${item.correct ? "is-correct" : ""} ${hasText ? "" : "is-missing-explanation"}" data-option-card="${item.index}">
					<div class="trivia-option-top">
						<span class="trivia-option-letter">${safe(item.letter)}</span>
						<div class="trivia-option-content">${rich(item.text)}</div>
						<div class="trivia-option-badges">
							${item.correct ? `<span class="indicator-pill green">${__("Answer key")}</span>` : ""}
							<span class="indicator-pill ${hasText ? "green" : "orange"}" data-option-pill="${item.index}">${hasText ? __("Explained") : __("Explanation missing")}</span>
						</div>
					</div>
					<div class="trivia-option-explanation-wrap" style="display:block;width:100%;">
						<div class="trivia-option-explanation-label">${label}</div>
						<textarea
							rows="2"
							class="form-control trivia-option-explanation-input"
							style="display:block;width:100%;"
							data-explanation-index="${item.index}"
							data-explanation-letter="${escapeAttr(item.letter)}"
							placeholder="${escapeAttr(placeholder)}"
						>${escapeAttr(item.explanation)}</textarea>
					</div>
				</div>`;
		}).join("") || `<p class="text-muted">${__("Fill Option 1, Option 2... below to preview and explain alternatives.")}</p>`;

		const toStars = (value) => {
			const n = Number(value || 0);
			if (n <= 0) return 0;
			return n <= 1 ? Math.round(n * 5) : Math.min(5, Math.round(n));
		};
		const starValue = toStars(d.trivia_editorial_difficulty || d.trivia_ai_difficulty_stars || 0);
		const stars = "★".repeat(Math.max(0, Math.min(5, starValue))) + "☆".repeat(Math.max(0, 5 - starValue));

		let aiTopics = [];
		try {
			const parsedTopics = typeof d.trivia_ai_topics === "string" ? JSON.parse(d.trivia_ai_topics || "[]") : d.trivia_ai_topics || [];
			if (Array.isArray(parsedTopics)) aiTopics = parsedTopics.filter(Boolean);
		} catch (error) {
			aiTopics = [];
		}

		const hasAiEnrichment = Boolean(d.trivia_ai_enriched_at || d.trivia_ai_difficulty_stars || d.trivia_ai_learning_objective || d.trivia_ai_difficulty_reason);
		const aiSummaryHtml = hasAiEnrichment
			? `<div class="trivia-cockpit-block">
				<div class="trivia-cockpit-block-head">
					<h4>${__("AI pedagogical analysis")}</h4>
					<span class="text-muted small">${safe(d.trivia_ai_model || "")}${d.trivia_ai_difficulty_label ? ` · ${safe(d.trivia_ai_difficulty_label)}` : ""}</span>
				</div>
				<div class="trivia-question-surface trivia-ai-summary">
					${d.trivia_ai_learning_objective ? `<div class="trivia-ai-row"><strong>${__("Learning objective")}:</strong> ${safe(d.trivia_ai_learning_objective)}</div>` : ""}
					${d.trivia_ai_difficulty_reason ? `<div class="trivia-ai-row"><strong>${__("Difficulty rationale")}:</strong> ${safe(d.trivia_ai_difficulty_reason)}</div>` : ""}
					${aiTopics.length ? `<div class="trivia-ai-topics">${aiTopics.map((topic) => `<span class="trivia-ai-topic-tag">${safe(topic)}</span>`).join("")}</div>` : ""}
				</div>
			</div>`
			: "";

		const status = d.trivia_status || "In Preparation";
		const statusColor = status === "Ready" ? "green" : "orange";
		const coveragePillColor = optionItems.length >= 2 && !missingLetters.length ? "green" : "orange";
		const coverageLabel = optionItems.length
			? (missingLetters.length
				? __("{0}/{1} explanations · missing: {2}", [explainedCount, optionItems.length, missingLetters.join(", ")])
				: __("{0}/{1} explanations complete", [explainedCount, optionItems.length]))
			: __("No alternatives");

		root.html(`
			<div class="trivia-cockpit-header">
				<div>
					<div class="text-muted small">${__("LMS QUESTION COCKPIT")}</div>
					<h3>${safe(d.trivia_qcode || d.name || __("New Question"))}</h3>
				</div>
				<div class="trivia-cockpit-status">
					<span class="indicator-pill ${statusColor}">${safe(status)}</span>
					<span class="indicator-pill ${coveragePillColor}" data-coverage-pill>${safe(coverageLabel)}</span>
				</div>
			</div>
			<div class="trivia-cockpit-meta">
				<span>${safe(d.trivia_banca || "—")}</span>
				<span>${safe(d.trivia_materia || "—")}</span>
				<span>${safe(d.trivia_assunto || "—")}</span>
				<span>${safe(d.trivia_ano || "—")}</span>
				<span>${optionItems.length} ${__("alternatives")}</span>
				<span class="trivia-stars">${stars}</span>
			</div>
			<div class="trivia-cockpit-block" data-supporting-text-block>
				<div class="trivia-cockpit-block-head">
					<h4>${__("Supporting text")}</h4>
					<div class="trivia-cockpit-actions-group">
						${d.trivia_texto_apoio
							? `<a class="btn btn-xs btn-default" data-action="supporting-text">${__("Open / edit")}</a>`
							: (!frm.is_new() ? `<button class="btn btn-xs btn-default" data-action="create-supporting-text">${__("+ Create & link supporting text")}</button>` : "")}
					</div>
				</div>
				<div class="trivia-question-surface trivia-supporting-text-body" data-supporting-text-body>
					${d.trivia_texto_apoio
						? `<span class="text-muted">${__("Loading supporting text")} (${safe(d.trivia_texto_apoio)})...</span>`
						: `<span class="text-muted">${__("No supporting text linked. Select one in the Supporting text field or create a new reusable passage.")}</span>`}
				</div>
			</div>
			<div class="trivia-cockpit-block">
				<div class="trivia-cockpit-block-head"><h4>${__("Question preview")}</h4></div>
				<div class="trivia-question-surface trivia-rich-content">${rich(d.question)}</div>
			</div>
			<div class="trivia-cockpit-block">
				<div class="trivia-cockpit-block-head">
					<h4>${__("Alternatives & per-option explanations")}</h4>
					<span class="text-muted small">${__("Supports 2 to 10 options. Wrong options explain the error without revealing the answer key.")}</span>
				</div>
				<div class="trivia-options-list">${optionRows}</div>
			</div>
			${aiSummaryHtml}
			<div class="trivia-cockpit-block" data-knowledge-block style="display:none;">
				<div class="trivia-cockpit-block-head">
					<h4>${__("Linked knowledge pages (concepts & sub-concepts)")}</h4>
					<span class="text-muted small">${__("Click to open the concept page in Desk")}</span>
				</div>
				<div class="trivia-ai-topics" data-knowledge-chips></div>
			</div>
			${d.trivia_general_explanation ? `<div class="trivia-cockpit-block"><div class="trivia-cockpit-block-head"><h4>${__("General comment")}</h4></div><div class="trivia-question-surface trivia-rich-content">${rich(d.trivia_general_explanation)}</div></div>` : ""}
			<div class="trivia-cockpit-actions">
				<div class="trivia-cockpit-actions-group" data-tools></div>
				<div class="trivia-cockpit-actions-group" data-actions></div>
			</div>`);

		root.find("[data-explanation-index]").on("input change", (ev) => {
			const el = ev.currentTarget;
			const idx = Number(el.getAttribute("data-explanation-index"));
			const val = (el.value || "").trim();
			frm._trivia_syncing_explanations = true;
			frm.set_value(`explanation_${idx}`, val);
			frm._trivia_syncing_explanations = false;

			const card = root.find(`[data-option-card="${idx}"]`);
			const pill = root.find(`[data-option-pill="${idx}"]`);
			card.toggleClass("is-missing-explanation", !val);
			pill.toggleClass("green", Boolean(val)).toggleClass("orange", !val).text(val ? __("Explained") : __("Explanation missing"));

			const stillMissing = [];
			root.find("[data-explanation-index]").each((_, node) => {
				if (!(node.value || "").trim()) stillMissing.push(node.getAttribute("data-explanation-letter"));
			});
			const done = optionItems.length - stillMissing.length;
			root.find("[data-coverage-pill]")
				.toggleClass("green", optionItems.length >= 2 && !stillMissing.length)
				.toggleClass("orange", stillMissing.length > 0)
				.text(
					stillMissing.length
						? __("{0}/{1} explanations · missing: {2}", [done, optionItems.length, stillMissing.join(", ")])
						: __("{0}/{1} explanations complete", [done, optionItems.length])
				);
		});

		const tools = root.find("[data-tools]");
		const actions = root.find("[data-actions]");
		const call = (method, args, message) =>
			frappe.call({ method, args, freeze: true, freeze_message: __("Processing...") }).then(() => {
				frappe.show_alert({ message, indicator: "green" });
				frm.reload_doc();
			});

		if (!frm.is_new()) {
			tools.append(`<button class="btn btn-primary btn-sm" data-cockpit="enrich-all">${__("Enrich all (AI)")}</button>`);
			tools.append(`<button class="btn btn-default btn-sm" data-cockpit="classify-difficulty">${__("Classify difficulty (AI)")}</button>`);
			tools.append(`<button class="btn btn-default btn-sm" data-cockpit="draft-explanations">${__("Draft explanations (AI)")}</button>`);
			tools.append(`<button class="btn btn-default btn-sm" data-cockpit="extract-knowledge">${__("Extract knowledge (AI)")}</button>`);
			if (aiTopics.length) {
				tools.append(`<button class="btn btn-default btn-sm" data-cockpit="apply-topics">${__("Apply AI topics")}</button>`);
			}
			if (d.trivia_raw_payload) {
				tools.append(`<button class="btn btn-default btn-sm" data-cockpit="reformat">${__("Repair rich formatting")}</button>`);
			}

			if (status !== "Ready") {
				actions.append(`<button class="btn btn-primary btn-sm" data-cockpit="mark-ready">${__("Mark Ready")}</button>`);
			} else {
				actions.append(`<button class="btn btn-default btn-sm" data-cockpit="mark-prep">${__("Move to In Preparation")}</button>`);
			}

			frappe.call({
				method: "trivia_sync.api.question_knowledge_pages",
				args: { question_name: d.name },
			}).then(({ message }) => {
				const pages = message || [];
				if (!pages.length) return;
				const block = root.find("[data-knowledge-block]").show();
				block.find("[data-knowledge-chips]").html(
					pages.map((p) => {
						const pillColor = p.status === "Published" ? "green" : p.status === "Archived" ? "red" : "orange";
						return `<a class="trivia-knowledge-chip" href="/app/trivia-knowledge-page/${encodeURIComponent(p.name)}" title="${escapeAttr(p.summary || p.title)}">
							<span>${safe(p.title)}</span>
							<span class="indicator-pill ${pillColor}">${safe(p.status)}</span>
						</a>`;
					}).join("")
				);
			});
		}

		tools.find('[data-cockpit="enrich-all"]').on("click", () => {
			call("trivia_sync.api.enrich_question_all", { question_name: d.name }, __("Full AI enrichment completed."));
		});
		tools.find('[data-cockpit="classify-difficulty"]').on("click", () => {
			call("trivia_sync.api.enrich_question_difficulty", { question_name: d.name }, __("AI difficulty, objective, and topics updated."));
		});
		tools.find('[data-cockpit="draft-explanations"]').on("click", () => {
			call("trivia_sync.api.draft_question_option_explanations", { question_name: d.name }, __("Per-option explanations drafted."));
		});
		tools.find('[data-cockpit="extract-knowledge"]').on("click", () => {
			call("trivia_sync.api.extract_question_knowledge", { question_name: d.name }, __("Concept & sub-concept knowledge pages extracted and linked."));
		});
		tools.find('[data-cockpit="apply-topics"]').on("click", () => {
			call("trivia_sync.api.apply_question_ai_topics", { question_name: d.name }, __("AI topics linked to catalogs, syllabus, and Tags."));
		});
		tools.find('[data-cockpit="reformat"]').on("click", () => {
			call("trivia_sync.api.repair_qapi_question", { question_name: d.name }, __("Rich content reparsed from stored QAPI payload."));
		});
		actions.find('[data-cockpit="mark-ready"]').on("click", () => {
			call("trivia_sync.api.update_lms_question_status", { question_name: d.name, status: "Ready" }, __("Question marked Ready."));
		});
		actions.find('[data-cockpit="mark-prep"]').on("click", () => {
			call("trivia_sync.api.update_lms_question_status", { question_name: d.name, status: "In Preparation" }, __("Question moved to In Preparation."));
		});

		root.find('[data-action="supporting-text"]').on("click", () => frappe.set_route("Form", "Trivia Supporting Text", d.trivia_texto_apoio));
		root.find('[data-action="create-supporting-text"]').on("click", () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Create & Link Supporting Text"),
				fields: [
					{ fieldname: "titulo", fieldtype: "Data", label: __("Title"), reqd: 1 },
					{ fieldname: "conteudo", fieldtype: "Text Editor", label: __("Passage content"), reqd: 1 },
				],
				primary_action_label: __("Create & Link"),
				primary_action(values) {
					dialog.hide();
					call(
						"trivia_sync.api.create_and_link_supporting_text",
						{ question_name: d.name, titulo: values.titulo, conteudo: values.conteudo },
						__("Supporting text created and linked.")
					);
				},
			});
			dialog.show();
		});

		if (d.trivia_texto_apoio) {
			frappe.call({
				method: "trivia_sync.api.supporting_text_preview",
				args: { name: d.trivia_texto_apoio },
			}).then(({ message }) => {
				const container = root.find("[data-supporting-text-body]");
				if (!message) {
					container.html(`<span class="text-muted">${__("Linked supporting text not found")}: ${safe(d.trivia_texto_apoio)}</span>`);
					return;
				}
				container.html(`
					<div class="trivia-supporting-text-title"><strong>${safe(message.titulo || message.name)}</strong></div>
					<div class="trivia-rich-content">${rich(message.conteudo)}</div>
				`);
				ensureMathJax().then((math) => math?.typesetPromise?.([container[0]])).catch(() => {});
			});
		}

		ensureMathJax().then((math) => math?.typesetPromise?.([root[0]])).catch(() => {});
	};

	const handlers = {
		refresh(frm) { renderCockpit(frm); },
		question(frm) { renderCockpit(frm); },
		type(frm) { renderCockpit(frm); },
		trivia_texto_apoio(frm) { renderCockpit(frm); },
	};
	for (let i = 1; i <= 10; i += 1) {
		handlers[`option_${i}`] = (frm) => renderCockpit(frm);
		handlers[`is_correct_${i}`] = (frm) => renderCockpit(frm);
		handlers[`explanation_${i}`] = (frm) => {
			if (!frm._trivia_syncing_explanations) renderCockpit(frm);
		};
	}
	frappe.ui.form.on("LMS Question", handlers);
})();
