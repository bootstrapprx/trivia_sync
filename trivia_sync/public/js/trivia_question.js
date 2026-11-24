(() => {
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
	const parseJsonObject = (value) => {
		try {
			const parsed = typeof value === "string" ? JSON.parse(value || "{}") : value || {};
			return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
		} catch (error) {
			return {};
		}
	};
	const parseCorrectOptions = (doc) => {
		try {
			const parsed = typeof doc.correct_options === "string" ? JSON.parse(doc.correct_options || "[]") : doc.correct_options || [];
			return new Set(Array.isArray(parsed) && parsed.length ? parsed : doc.correct_option ? [doc.correct_option] : []);
		} catch (error) {
			return new Set(doc.correct_option ? [doc.correct_option] : []);
		}
	};

	const renderCockpit = (frm) => {
		const field = frm.fields_dict.enunciado?.$wrapper;
		if (!field) return;
		let root = frm.$wrapper.find(".trivia-question-cockpit");
		if (!root.length) {
			root = $("<section class='trivia-question-cockpit frappe-card'></section>");
			field.after(root);
		}
		const d = frm.doc;
		const options = parseJsonObject(d.options);
		const correctOptions = parseCorrectOptions(d);
		const explanations = parseJsonObject(d.option_explanations);
		const generalExplanation = String(d.explanation || "").trim();
		const letters = Object.keys(options).sort();

		const effectiveExplanation = (letter) => {
			const own = String(explanations[letter] || explanations[letter.toLowerCase()] || "").trim();
			if (own) return own;
			return correctOptions.has(letter) ? generalExplanation : "";
		};

		const missingLetters = letters.filter((letter) => !effectiveExplanation(letter));
		const explainedCount = letters.length - missingLetters.length;

		const optionRows = letters.map((letter) => {
			const value = options[letter];
			const correct = correctOptions.has(letter);
			const text = effectiveExplanation(letter);
			const hasText = Boolean(text);
			const label = correct
				? __("Why this answer is correct")
				: __("Why this alternative is wrong (do not reveal the correct answer)");
			const placeholder = correct
				? __("Explain why this alternative satisfies the question...")
				: __("Explain the flaw in this alternative without giving away the answer key...");
			return `
				<div class="trivia-option-card ${correct ? "is-correct" : ""} ${hasText ? "" : "is-missing-explanation"}" data-option-card="${escapeAttr(letter)}">
					<div class="trivia-option-top">
						<span class="trivia-option-letter">${safe(letter)}</span>
						<div class="trivia-option-content">${rich(value)}</div>
						<div class="trivia-option-badges">
							${correct ? `<span class="indicator-pill green">${__("Answer key")}</span>` : ""}
							<span class="indicator-pill ${hasText ? "green" : "orange"}" data-option-pill="${escapeAttr(letter)}">${hasText ? __("Explained") : __("Explanation missing")}</span>
						</div>
					</div>
					<div class="trivia-option-explanation-wrap" style="display:block;width:100%;">
						<div class="trivia-option-explanation-label">${label}</div>
						<textarea
							id="trivia-exp-${escapeAttr(letter)}"
							rows="2"
							class="form-control trivia-option-explanation-input"
							style="display:block;width:100%;"
							data-explanation-letter="${escapeAttr(letter)}"
							placeholder="${escapeAttr(placeholder)}"
						>${escapeAttr(text)}</textarea>
					</div>
				</div>`;
		}).join("") || `<p class="text-muted">${__("No alternatives were normalized.")}</p>`;

		const toStars = (value) => {
			const n = Number(value || 0);
			if (n <= 0) return 0;
			return n <= 1 ? Math.round(n * 5) : Math.min(5, Math.round(n));
		};
		const starValue = toStars(d.editorial_difficulty || d.ai_difficulty_stars || 0);
		const stars = "★".repeat(Math.max(0, Math.min(5, starValue))) + "☆".repeat(Math.max(0, 5 - starValue));
		let aiTopics = [];
		try {
			const parsedTopics = typeof d.ai_topics === "string" ? JSON.parse(d.ai_topics || "[]") : d.ai_topics || [];
			if (Array.isArray(parsedTopics)) aiTopics = parsedTopics.filter(Boolean);
		} catch (error) {
			aiTopics = [];
		}
		const hasAiEnrichment = Boolean(d.ai_enriched_at || d.ai_difficulty_stars || d.ai_learning_objective || d.ai_difficulty_reason);
		const aiSummaryHtml = hasAiEnrichment
			? `<div class="trivia-cockpit-block">
				<div class="trivia-cockpit-block-head">
					<h4>${__("AI pedagogical analysis")}</h4>
					<span class="text-muted small">${safe(d.ai_model || "")}${d.ai_difficulty_label ? ` · ${safe(d.ai_difficulty_label)}` : ""}</span>
				</div>
				<div class="trivia-question-surface trivia-ai-summary">
					${d.ai_learning_objective ? `<div class="trivia-ai-row"><strong>${__("Learning objective")}:</strong> ${safe(d.ai_learning_objective)}</div>` : ""}
					${d.ai_difficulty_reason ? `<div class="trivia-ai-row"><strong>${__("Difficulty rationale")}:</strong> ${safe(d.ai_difficulty_reason)}</div>` : ""}
					${aiTopics.length ? `<div class="trivia-ai-topics">${aiTopics.map((topic) => `<span class="trivia-ai-topic-tag">${safe(topic)}</span>`).join("")}</div>` : ""}
				</div>
			</div>`
			: "";
		const status = d.editorial_status || d.review_status || "Imported";
		const statusColor = ["Approved", "Published"].includes(status) ? "green" : ["Rejected", "Archived"].includes(status) ? "red" : "orange";
		const coveragePillColor = letters.length && !missingLetters.length ? "green" : "orange";
		const coverageLabel = letters.length
			? (missingLetters.length
				? __("{0}/{1} explanations · missing: {2}", [explainedCount, letters.length, missingLetters.join(", ")])
				: __("{0}/{1} explanations complete", [explainedCount, letters.length]))
			: __("No alternatives");

		root.html(`
			<div class="trivia-cockpit-header">
				<div>
					<div class="text-muted small">${__("EDITORIAL COCKPIT")}</div>
					<h3>${safe(d.qcode || d.name)}</h3>
				</div>
				<div class="trivia-cockpit-status">
					<span class="indicator-pill ${statusColor}">${safe(status)}</span>
					<span class="indicator-pill blue">${safe(d.projection_status || "Not Projected")}</span>
					<span class="indicator-pill ${coveragePillColor}" data-coverage-pill>${safe(coverageLabel)}</span>
				</div>
			</div>
			<div class="trivia-cockpit-meta">
				<span>${safe(d.banca || "—")}</span>
				<span>${safe(d.materia || "—")}</span>
				<span>${safe(d.assunto || "—")}</span>
				<span>${safe(d.ano || "—")}</span>
				<span>${letters.length} ${__("alternatives")}</span>
				<span class="trivia-stars">${stars}</span>
			</div>
			<div class="trivia-cockpit-block">
				<div class="trivia-cockpit-block-head"><h4>${__("Question preview")}</h4></div>
				<div class="trivia-question-surface trivia-rich-content">${rich(d.enunciado)}</div>
			</div>
			${d.texto_apoio ? `<div class="trivia-cockpit-block"><div class="trivia-cockpit-block-head"><h4>${__("Supporting text")}</h4></div><p><a class="text-muted" data-action="supporting-text">${safe(d.texto_apoio)}</a></p><p class="text-muted">${__("The linked text is included during LMS projection.")}</p></div>` : ""}
			${d.allow_variable_options ? `<div class="alert alert-warning">${__("Variable alternative count authorized")}: ${safe(d.exception_reason || __("Reason required"))}</div>` : ""}
			<div class="trivia-cockpit-block">
				<div class="trivia-cockpit-block-head">
					<h4>${__("Alternatives & per-option explanations")}</h4>
					<span class="text-muted small">${__("Wrong options explain the error without revealing the answer key.")}</span>
				</div>
				<div class="trivia-options-list">${optionRows}</div>
			</div>
			${aiSummaryHtml}
			${d.explanation ? `<div class="trivia-cockpit-block"><div class="trivia-cockpit-block-head"><h4>${__("General comment")}</h4></div><div class="trivia-question-surface trivia-rich-content">${rich(d.explanation)}</div></div>` : ""}
			<div class="trivia-cockpit-actions">
				<div class="trivia-cockpit-actions-group" data-tools></div>
				<div class="trivia-cockpit-actions-group" data-actions></div>
			</div>`);

		const syncExplanationsFromInputs = () => {
			const updated = {};
			const stillMissing = [];
			root.find("[data-explanation-letter]").each((_, el) => {
				const letter = el.getAttribute("data-explanation-letter");
				const val = (el.value || "").trim();
				if (val) {
					updated[letter] = val;
				} else {
					stillMissing.push(letter);
				}
				const card = root.find(`[data-option-card="${letter}"]`);
				const pill = root.find(`[data-option-pill="${letter}"]`);
				card.toggleClass("is-missing-explanation", !val);
				pill.toggleClass("green", Boolean(val)).toggleClass("orange", !val).text(val ? __("Explained") : __("Explanation missing"));
			});
			const done = letters.length - stillMissing.length;
			root.find("[data-coverage-pill]")
				.toggleClass("green", letters.length > 0 && !stillMissing.length)
				.toggleClass("orange", stillMissing.length > 0)
				.text(
					stillMissing.length
						? __("{0}/{1} explanations · missing: {2}", [done, letters.length, stillMissing.join(", ")])
						: __("{0}/{1} explanations complete", [done, letters.length])
				);
			frm._trivia_syncing_explanations = true;
			frm.set_value("option_explanations", JSON.stringify(updated, null, 2));
			frm._trivia_syncing_explanations = false;
		};

		root.find("[data-explanation-letter]").on("input change", syncExplanationsFromInputs);

		const tools = root.find("[data-tools]");
		const actions = root.find("[data-actions]");
		const call = (method, args, message) => frappe.call({ method, args }).then(() => { frappe.show_alert({ message, indicator: "green" }); frm.reload_doc(); });
		const transition = (target, message) => call("trivia_sync.api.transition_editorial_status", { question_name: d.name, status: target }, message);

		if (!frm.is_new()) {
			tools.append(`<button class="btn btn-primary btn-sm" data-cockpit="enrich-all">${__("Enrich all (AI)")}</button>`);
			tools.append(`<button class="btn btn-default btn-sm" data-cockpit="classify-difficulty">${__("Classify difficulty (AI)")}</button>`);
			tools.append(`<button class="btn btn-default btn-sm" data-cockpit="draft-explanations">${__("Draft explanations (AI)")}</button>`);
			if (aiTopics.length) {
				tools.append(`<button class="btn btn-default btn-sm" data-cockpit="apply-topics">${__("Apply AI topics")}</button>`);
			}
			tools.append(`<button class="btn btn-default btn-sm" data-cockpit="reformat">${__("Repair rich formatting")}</button>`);
			if (status === "Imported") actions.append(`<button class="btn btn-primary btn-sm" data-cockpit="queue">${__("Queue for review")}</button>`);
			if (status === "Pending Review") actions.append(`<button class="btn btn-primary btn-sm" data-cockpit="start">${__("Start review")}</button>`);
			if (status === "In Review") actions.append(`<button class="btn btn-primary btn-sm" data-cockpit="pending-approval">${__("Submit for approval")}</button>`);
			if (status === "Pending Approval") actions.append(`<button class="btn btn-primary btn-sm" data-cockpit="approve">${__("Approve question")}</button><button class="btn btn-default btn-sm" data-cockpit="reject">${__("Reject")}</button>`);
			if (["Approved", "Published"].includes(status) && d.redistribution_status !== "Approved") actions.append(`<button class="btn btn-default btn-sm" data-cockpit="rights">${__("Authorize redistribution")}</button>`);
			if (["Approved", "Published"].includes(status) && d.redistribution_status === "Approved") actions.append(`<button class="btn btn-primary btn-sm" data-cockpit="project">${__("Project to LMS")}</button>`);
		}

		tools.find('[data-cockpit="enrich-all"]').on("click", () => {
			frappe.confirm(
				__("Run full AI enrichment for this question (difficulty, learning objective, topics, and explanations for every alternative without revealing the answer key on wrong options)?"),
				() => call("trivia_sync.api.enrich_question_all", { question_name: d.name }, __("Full AI enrichment completed. Review before approving."))
			);
		});
		tools.find('[data-cockpit="classify-difficulty"]').on("click", () => {
			call("trivia_sync.api.enrich_question_difficulty", { question_name: d.name }, __("AI difficulty, objective, and topics updated."));
		});
		tools.find('[data-cockpit="apply-topics"]').on("click", () => {
			call("trivia_sync.api.apply_question_ai_topics", { question_name: d.name }, __("AI topics linked to catalogs, syllabus, and Tags."));
		});
		tools.find('[data-cockpit="draft-explanations"]').on("click", () => {
			frappe.confirm(
				__("Generate AI draft explanations for all alternatives (without revealing the answer key on wrong options)? Existing draft explanations will be replaced for review."),
				() => call("trivia_sync.api.draft_question_option_explanations", { question_name: d.name }, __("AI explanation drafts generated. Review before approving."))
			);
		});
		tools.find('[data-cockpit="reformat"]').on("click", () => call("trivia_sync.api.repair_qapi_question", { question_name: d.name }, __("Rich content reparsed from the stored QAPI payload.")));
		actions.find('[data-cockpit="queue"]').on("click", () => transition("Pending Review", __("Question queued for review.")));
		actions.find('[data-cockpit="start"]').on("click", () => transition("In Review", __("Review started.")));
		actions.find('[data-cockpit="pending-approval"]').on("click", () => transition("Pending Approval", __("Question submitted for approval.")));
		actions.find('[data-cockpit="approve"]').on("click", () => call("trivia_sync.api.review_question", { question_name: d.name, decision: "approved" }, __("Question approved.")));
		actions.find('[data-cockpit="reject"]').on("click", () => {
			const reason = window.prompt(__("Reason for rejection"));
			if (reason !== null) call("trivia_sync.api.review_question", { question_name: d.name, decision: "rejected", reason }, __("Question rejected."));
		});
		actions.find('[data-cockpit="rights"]').on("click", () => {
			const reason = window.prompt(__("License or redistribution reference"), d.redistribution_reference || "");
			if (reason !== null) call("trivia_sync.api.decide_question_redistribution", { question_name: d.name, decision: "approved", reason }, __("Redistribution authorized."));
		});
		actions.find('[data-cockpit="project"]').on("click", () => call("trivia_sync.api.project_question", { question_name: d.name }, __("Question projected to LMS.")));
		root.find('[data-action="supporting-text"]').on("click", () => frappe.set_route("Form", "Trivia Supporting Text", d.texto_apoio));
		ensureMathJax().then((math) => math?.typesetPromise?.([root[0]])).catch(() => {});
	};

	frappe.ui.form.on("Trivia Question", {
		refresh(frm) { renderCockpit(frm); },
		enunciado(frm) { renderCockpit(frm); },
		options(frm) { renderCockpit(frm); },
		correct_option(frm) { renderCockpit(frm); },
		option_explanations(frm) {
			if (!frm._trivia_syncing_explanations) renderCockpit(frm);
		},
	});
})();
