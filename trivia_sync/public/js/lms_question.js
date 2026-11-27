(() => {
	const LETTERS = "ABCDEFGHIJ";
	const mathScriptUrl = "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js";

	const svgIcon = (paths, extraClass = "") =>
		`<svg class="trivia-svg-icon ${extraClass}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.85" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;

	const ICONS = {
		athenaOwl: svgIcon(
			`<path d="M5 4l3.5 3A7.5 7.5 0 0 1 12 6.2c1.25 0 2.45.28 3.5.8L19 4l-.8 4.4A7.2 7.2 0 0 1 19.5 12.5c0 4.2-3.2 7.5-7.5 7.5s-7.5-3.3-7.5-7.5c0-1.5.45-2.9 1.3-4.1L5 4z"/>
			<circle cx="9.2" cy="11.6" r="1.8"/>
			<circle cx="14.8" cy="11.6" r="1.8"/>
			<path d="M12 13.4l-1.1 1.6L12 16.5l1.1-1.5L12 13.4z"/>
			<path d="M8.5 19.2c1 .5 2.2.8 3.5.8s2.5-.3 3.5-.8"/>`,
			"trivia-icon-athena"
		),
		teacherPen: svgIcon(
			`<path d="M12 20h9"/>
			<path d="M16.5 3.5a2.12 2.12 0 1 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/>`
		),
		debate: svgIcon(
			`<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
			<path d="M8 9h8"/>
			<path d="M8 13h5"/>`
		),
		star: svgIcon(
			`<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>`
		),
		listCheck: svgIcon(
			`<path d="M10 6h11"/>
			<path d="M10 12h11"/>
			<path d="M10 18h11"/>
			<path d="M3 6l1.5 1.5L7 5"/>
			<path d="M3 12l1.5 1.5L7 11"/>
			<path d="M3 18l1.5 1.5L7 17"/>`
		),
		bookOpen: svgIcon(
			`<path d="M2 4h6a4 4 0 0 1 4 4v12a3 3 0 0 0-3-3H2z"/>
			<path d="M22 4h-6a4 4 0 0 0-4 4v12a3 3 0 0 1 3-3h7z"/>`
		),
		tag: svgIcon(
			`<path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/>
			<circle cx="7" cy="7" r="1.2"/>`
		),
		wrench: svgIcon(
			`<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>`
		),
		keyCheck: svgIcon(
			`<circle cx="7.5" cy="15.5" r="4.5"/>
			<path d="M11 12l9-9"/>
			<path d="M18 5l2 2"/>
			<path d="M15 8l2 2"/>`
		),
		checkCircle: svgIcon(
			`<circle cx="12" cy="12" r="9"/>
			<path d="M8.5 12.5l2.3 2.3 4.7-5.3"/>`
		),
		edit: svgIcon(
			`<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
			<path d="M18.5 2.5a2.12 2.12 0 1 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>`
		),
		chevronDown: svgIcon(`<polyline points="6 9 12 15 18 9"/>`, "trivia-icon-chevron"),
	};

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
	const stripEmbeds = (htmlStr) =>
		String(htmlStr ?? "")
			.replace(/<div class="trivia-deprecated-banner">[\s\S]*?<\/div>\s*/gi, "")
			.replace(/<div class="trivia-supporting-passage">[\s\S]*?<\/div>\s*<hr\s*\/?>\s*/gi, "")
			.replace(/<div class="trivia-knowledge-refs">[\s\S]*?<\/div>\s*$/gi, "")
			.trim();
	const stripDeepDive = (htmlStr) =>
		String(htmlStr ?? "")
			.replace(/\s*<details class="trivia-deep-dive">[\s\S]*?<\/details>\s*$/gi, "")
			.trim();
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
				explanation: stripDeepDive(doc[`explanation_${i}`] || ""),
			});
		}
		return rows;
	};

	const styleCommentSections = (frm) => {
		const teacherWrapper = frm.fields_dict.trivia_general_explanation?.$wrapper;
		if (teacherWrapper) {
			teacherWrapper.closest(".form-section").addClass("trivia-teacher-section-card");
		}
		const aiWrapper = frm.fields_dict.trivia_ai_comment?.$wrapper;
		if (aiWrapper) {
			aiWrapper.closest(".form-section").addClass("trivia-ai-section-card");
		}
	};

	const renderCockpit = (frm) => {
		styleCommentSections(frm);
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

		const hasAiEnrichment = Boolean(
			d.trivia_ai_enriched_at ||
			d.trivia_ai_difficulty_stars ||
			d.trivia_ai_learning_objective ||
			d.trivia_ai_difficulty_reason ||
			d.trivia_ai_comment
		);
		const aiCommentHtml = d.trivia_ai_comment
			? `<div class="trivia-ai-comment-block">
				<div class="trivia-ai-comment-label">${__("Comentário da Athena")}</div>
				<div class="trivia-ai-comment-surface trivia-rich-content">${rich(d.trivia_ai_comment)}</div>
			</div>`
			: "";
		const aiSummaryHtml = hasAiEnrichment
			? `<div class="trivia-cockpit-block trivia-ai-block">
				<div class="trivia-cockpit-block-head">
					<h4 class="trivia-heading-with-icon"><span class="trivia-athena-emblem">${ICONS.athenaOwl}</span><span>${__("Análise pedagógica da Athena")}</span></h4>
					<div class="trivia-cockpit-actions-group">
						<span class="indicator-pill blue">${__("Athena")}</span>
						<span class="text-muted small">${safe(d.trivia_ai_model || "")}${d.trivia_ai_difficulty_label ? ` · ${safe(d.trivia_ai_difficulty_label)}` : ""}</span>
					</div>
				</div>
				<div class="trivia-question-surface trivia-ai-summary">
					${d.trivia_ai_learning_objective ? `<div class="trivia-ai-row"><strong>${__("Objetivo de aprendizagem")}:</strong> ${safe(d.trivia_ai_learning_objective)}</div>` : ""}
					${d.trivia_ai_difficulty_reason ? `<div class="trivia-ai-row"><strong>${__("Justificativa da dificuldade")}:</strong> ${safe(d.trivia_ai_difficulty_reason)}</div>` : ""}
					${aiCommentHtml}
					${aiTopics.length ? `<div class="trivia-ai-topics">${aiTopics.map((topic) => `<span class="trivia-ai-topic-tag">${safe(topic)}</span>`).join("")}</div>` : ""}
				</div>
			</div>`
			: "";
		const teacherCommentHtml = d.trivia_general_explanation
			? `<div class="trivia-cockpit-block trivia-teacher-comment-block">
				<div class="trivia-cockpit-block-head">
					<h4 class="trivia-heading-with-icon"><span class="trivia-teacher-emblem">${ICONS.teacherPen}</span><span>${__("Comentário do Professor")}</span></h4>
					<span class="indicator-pill green">${__("Exclusivo do Professor · Isolado da Athena")}</span>
				</div>
				<div class="trivia-question-surface trivia-teacher-comment-surface trivia-rich-content">${rich(d.trivia_general_explanation)}</div>
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

		const deprecatedBannerHtml = d.trivia_deprecated
			? `<div class="trivia-deprecated-banner">
				<strong>${__("Questão depreciada · estudo opcional (não obrigatória)")}</strong>
				${d.trivia_deprecated_law && d.trivia_replacement_law
					? `<span>${__("Baseada em")} <em>${safe(d.trivia_deprecated_law)}</em> → ${__("substituída por")} <em>${safe(d.trivia_replacement_law)}</em>.</span>`
					: (d.trivia_deprecated_law ? `<span>${__("Norma revogada")}: <em>${safe(d.trivia_deprecated_law)}</em>.</span>` : "")}
				${d.trivia_deprecation_note ? `<span>${safe(d.trivia_deprecation_note)}</span>` : ""}
			</div>`
			: "";

		root.html(`
			<div class="trivia-cockpit-header">
				<div>
					<div class="text-muted small">${__("LMS QUESTION COCKPIT")}</div>
					<h3>${safe(d.trivia_qcode || d.name || __("New Question"))}</h3>
				</div>
				<div class="trivia-cockpit-status">
					<span class="indicator-pill ${statusColor}">${safe(status)}</span>
					${d.trivia_deprecated ? `<span class="indicator-pill orange">${__("Depreciada · Estudo opcional")}</span>` : ""}
					${d.trivia_answer_key_pending ? `<span class="indicator-pill orange">${__("Answer key pending")}</span>` : ""}
					<span class="indicator-pill ${coveragePillColor}" data-coverage-pill>${safe(coverageLabel)}</span>
				</div>
			</div>
			${deprecatedBannerHtml}
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
				<div class="trivia-question-surface trivia-rich-content">${rich(stripEmbeds(d.question))}</div>
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
			${teacherCommentHtml}
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
			tools.append(
				`<button type="button" class="btn btn-primary btn-sm trivia-icon-btn" data-cockpit="enrich-all" title="${escapeAttr(__("Executa dificuldade, tópicos, explicações, comentário e conhecimento com a Athena"))}">${ICONS.athenaOwl}<span>${__("Athena · Analisar tudo")}</span></button>`
			);
			tools.append(
				`<button type="button" class="btn btn-default btn-sm trivia-icon-btn" data-cockpit="review-debate" title="${escapeAttr(__("Contestar gabarito ou explicações em debate com a Athena"))}">${ICONS.debate}<span>${__("Réplica")}</span></button>`
			);

			const menuItems = [
				`<li><a class="dropdown-item trivia-menu-item" href="#" data-cockpit="classify-difficulty">${ICONS.star}<span>${__("Classificar dificuldade")}</span></a></li>`,
				`<li><a class="dropdown-item trivia-menu-item" href="#" data-cockpit="draft-explanations">${ICONS.listCheck}<span>${__("Explicar alternativas")}</span></a></li>`,
				`<li><a class="dropdown-item trivia-menu-item" href="#" data-cockpit="extract-knowledge">${ICONS.bookOpen}<span>${__("Extrair conhecimento")}</span></a></li>`,
			];
			if (aiTopics.length) {
				menuItems.push(`<li><a class="dropdown-item trivia-menu-item" href="#" data-cockpit="apply-topics">${ICONS.tag}<span>${__("Aplicar tópicos sugeridos")}</span></a></li>`);
			}
			if (d.trivia_raw_payload) {
				menuItems.push(`<li class="dropdown-divider"></li>`);
				menuItems.push(`<li><a class="dropdown-item trivia-menu-item" href="#" data-cockpit="reformat">${ICONS.wrench}<span>${__("Reparar formatação QAPI")}</span></a></li>`);
			}

			tools.append(`
				<div class="btn-group trivia-athena-dropdown">
					<button type="button" class="btn btn-default btn-sm trivia-icon-btn" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">
						<span>${__("Mais ações da Athena")}</span>
						${ICONS.chevronDown}
					</button>
					<ul class="dropdown-menu trivia-athena-menu">${menuItems.join("")}</ul>
				</div>
			`);

			if (d.trivia_answer_key_pending) {
				actions.append(
					`<button type="button" class="btn btn-default btn-sm trivia-icon-btn" data-cockpit="confirm-key">${ICONS.keyCheck}<span>${__("Confirmar gabarito")}</span></button>`
				);
			}
			if (status !== "Ready") {
				actions.append(
					`<button type="button" class="btn btn-primary btn-sm trivia-icon-btn" data-cockpit="mark-ready">${ICONS.checkCircle}<span>${__("Marcar como Pronta")}</span></button>`
				);
			} else {
				actions.append(
					`<button type="button" class="btn btn-default btn-sm trivia-icon-btn" data-cockpit="mark-prep">${ICONS.edit}<span>${__("Em preparação")}</span></button>`
				);
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
			frappe.call({
				method: "trivia_sync.api.enrich_question_all",
				args: { question_name: d.name },
				freeze: true,
				freeze_message: __("Athena está analisando a questão..."),
			}).then(({ message }) => {
				if (message?.explanations_skipped_pending_key) {
					frappe.show_alert({
						message: __("Dificuldade, tópicos e conhecimento atualizados pela Athena. Explicações por alternativa foram puladas porque o gabarito está pendente."),
						indicator: "orange",
					});
				} else {
					frappe.show_alert({ message: __("Análise completa da Athena concluída."), indicator: "green" });
				}
				frm.reload_doc();
			});
		});
		tools.find('[data-cockpit="review-debate"]').on("click", () => {
			const availableLetters = optionItems.map((item) => item.letter);
			const history = [];
			let lastReview = null;

			const dialog = new frappe.ui.Dialog({
				title: __("Athena · Réplica & Tréplica ({0})", [d.trivia_qcode || d.name]),
				size: "extra-large",
				fields: [
					{
						fieldname: "intro",
						fieldtype: "HTML",
						options: `<div class="trivia-athena-dialog-intro">
							<span class="trivia-athena-emblem">${ICONS.athenaOwl}</span>
							<div class="text-muted small">${__("Conteste a análise ou o gabarito da Athena com seu argumento técnico/jurídico. A Athena avaliará de forma imparcial, responderá com sua tréplica e só atualizará a questão se você clicar em Aplicar.")}</div>
						</div>`,
					},
					{
						fieldname: "proposed_correct",
						fieldtype: "Select",
						label: __("Gabarito proposto (opcional)"),
						options: ["", ...availableLetters].join("\n"),
					},
					{
						fieldname: "include_general_comment",
						fieldtype: "Check",
						label: __("Incluir Comentário do Professor como referência para a Athena"),
						default: 1,
					},
					{
						fieldname: "feedback",
						fieldtype: "Small Text",
						label: __("Sua argumentação / Réplica"),
						reqd: 1,
						description: __("Explique por que o gabarito ou a explicação atual está incorreto (ex.: cite o artigo, norma ou raciocínio)."),
					},
					{
						fieldname: "debate_html",
						fieldtype: "HTML",
						options: `<div class="text-muted small mt-2">${__("Envie sua réplica para ver a tréplica da Athena e as correções sugeridas antes de aplicar qualquer alteração.")}</div>`,
					},
				],
				primary_action_label: __("Enviar réplica para Athena"),
				primary_action(values) {
					const feedbackText = (values.feedback || "").trim();
					if (!feedbackText) {
						frappe.msgprint(__("Escreva sua argumentação / réplica primeiro."));
						return;
					}
					frappe.call({
						method: "trivia_sync.api.review_question_with_feedback",
						freeze: true,
						freeze_message: __("Athena está reavaliando sua argumentação..."),
						args: {
							question_name: d.name,
							feedback: feedbackText,
							proposed_correct: values.proposed_correct || null,
							history: JSON.stringify(history),
							include_general_comment: values.include_general_comment ? 1 : 0,
						},
					}).then(({ message }) => {
						if (!message) return;
						lastReview = message;
						history.push({ role: "user", content: feedbackText });
						history.push({ role: "assistant", content: message.ai_reply || "" });
						dialog.set_value("feedback", "");
						const verdictColor = message.agrees_with_reviewer ? "green" : "orange";
						const verdictLabel = message.agrees_with_reviewer
							? __("Athena concordou com sua argumentação")
							: __("Athena manteve posição diferente");
						const expRows = Object.entries(message.option_explanations || {})
							.map(([letter, text]) => {
								const isCorr = (message.recommended_correct_options || []).includes(letter);
								return `<li class="mb-1"><strong>${safe(letter)}</strong> ${isCorr ? `<span class="indicator-pill green">${__("Correta")}</span>` : ""}: ${safe(text)}</li>`;
							})
							.join("");
						dialog.fields_dict.debate_html.$wrapper.html(`
							<div class="frappe-card p-3 mt-2">
								<div class="d-flex justify-content-between align-items-center mb-2">
									<strong class="trivia-heading-with-icon"><span class="trivia-athena-emblem">${ICONS.athenaOwl}</span><span>${__("Tréplica da Athena")} (${safe(message.model || "")})</span></strong>
									<span class="indicator-pill ${verdictColor}">${verdictLabel}</span>
								</div>
								<div class="mb-3" style="white-space:pre-wrap;">${safe(message.ai_reply)}</div>
								<div class="mb-2">
									<strong>${__("Gabarito recomendado")}:</strong>
									<span class="indicator-pill blue">${safe((message.recommended_correct_options || []).join(", "))}</span>
									<span class="text-muted small ml-2">${safe(message.difficulty_label || "")} (${message.difficulty_stars || 0}★)</span>
								</div>
								<div class="small"><strong>${__("Explicações sugeridas por alternativa")}:</strong><ul class="mt-1 pl-3">${expRows}</ul></div>
								<div class="mt-3">
									<button type="button" class="btn btn-primary btn-sm trivia-icon-btn" data-action="apply-ai-review">${ICONS.checkCircle}<span>${__("Aplicar revisão da Athena na questão")}</span></button>
									<span class="text-muted small ml-2">${__("Ou escreva outra réplica acima para continuar o debate.")}</span>
								</div>
							</div>
						`);
					});
				},
			});

			dialog.$wrapper.on("click", '[data-action="apply-ai-review"]', () => {
				if (!lastReview) return;
				frappe.call({
					method: "trivia_sync.api.apply_question_ai_review",
					freeze: true,
					freeze_message: __("Aplicando revisão aprovada..."),
					args: {
						question_name: d.name,
						correct_options: JSON.stringify(lastReview.recommended_correct_options || []),
						option_explanations: JSON.stringify(lastReview.option_explanations || {}),
						difficulty_stars: lastReview.difficulty_stars,
						difficulty_label: lastReview.difficulty_label,
						reason: lastReview.reason,
						model: lastReview.model,
					},
				}).then(() => {
					dialog.hide();
					frappe.show_alert({ message: __("Gabarito e explicações atualizados a partir da revisão com a Athena."), indicator: "green" });
					frm.reload_doc();
				});
			});

			dialog.show();
		});
		tools.find('[data-cockpit="classify-difficulty"]').on("click", (ev) => {
			ev.preventDefault();
			call("trivia_sync.api.enrich_question_difficulty", { question_name: d.name }, __("Dificuldade, objetivo e tópicos atualizados pela Athena."));
		});
		tools.find('[data-cockpit="draft-explanations"]').on("click", (ev) => {
			ev.preventDefault();
			call("trivia_sync.api.draft_question_option_explanations", { question_name: d.name }, __("Explicações por alternativa geradas pela Athena."));
		});
		tools.find('[data-cockpit="extract-knowledge"]').on("click", (ev) => {
			ev.preventDefault();
			call("trivia_sync.api.extract_question_knowledge", { question_name: d.name }, __("Páginas de conhecimento extraídas e vinculadas pela Athena."));
		});
		tools.find('[data-cockpit="apply-topics"]').on("click", (ev) => {
			ev.preventDefault();
			call("trivia_sync.api.apply_question_ai_topics", { question_name: d.name }, __("Tópicos da Athena vinculados aos catálogos, edital e Tags."));
		});
		tools.find('[data-cockpit="reformat"]').on("click", (ev) => {
			ev.preventDefault();
			call("trivia_sync.api.repair_qapi_question", { question_name: d.name }, __("Formatação rica reprocessada a partir do payload QAPI."));
		});
		actions.find('[data-cockpit="confirm-key"]').on("click", () => {
			call("trivia_sync.api.confirm_question_answer_key", { question_name: d.name }, __("Gabarito confirmado."));
		});
		actions.find('[data-cockpit="mark-ready"]').on("click", () => {
			call("trivia_sync.api.update_lms_question_status", { question_name: d.name, status: "Ready" }, __("Questão marcada como Pronta."));
		});
		actions.find('[data-cockpit="mark-prep"]').on("click", () => {
			call("trivia_sync.api.update_lms_question_status", { question_name: d.name, status: "In Preparation" }, __("Questão movida para Em preparação."));
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
		trivia_general_explanation(frm) { renderCockpit(frm); },
		trivia_ai_comment(frm) { renderCockpit(frm); },
		trivia_deprecated(frm) { renderCockpit(frm); },
		trivia_deprecated_law(frm) { renderCockpit(frm); },
		trivia_replacement_law(frm) { renderCockpit(frm); },
		trivia_deprecation_note(frm) { renderCockpit(frm); },
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
