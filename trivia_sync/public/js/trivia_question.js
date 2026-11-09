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
	const rich = (value) => {
		const raw = String(value ?? "").trim();
		if (!raw) return `<span class="text-muted">${__("Not provided")}</span>`;
		return safe(raw.includes("<") ? raw : raw.replace(/\r?\n/g, "<br>"));
	};
	const parseOptions = (value) => {
		try {
			const parsed = typeof value === "string" ? JSON.parse(value || "{}") : value || {};
			return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
		} catch (error) {
			return {};
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
		const options = parseOptions(d.options);
		const optionRows = Object.entries(options).map(([letter, value]) => {
			const correct = letter === d.correct_option;
			return `<div class="trivia-option-row ${correct ? "is-correct" : ""}"><span class="trivia-option-letter">${safe(letter)}</span><div class="trivia-option-content">${rich(value)}</div>${correct ? `<span class="indicator-pill green">${__("Answer key")}</span>` : ""}</div>`;
		}).join("") || `<p class="text-muted">${__("No alternatives were normalized.")}</p>`;
		const starValue = Number(d.ai_difficulty_stars || 0);
		const stars = "★".repeat(Math.max(0, Math.min(5, starValue))) + "☆".repeat(Math.max(0, 5 - starValue));
		root.html(`
			<div class="trivia-cockpit-header"><div><div class="text-muted small">${__("EDITORIAL COCKPIT")}</div><h3>${safe(d.qcode || d.name)}</h3></div><div class="trivia-cockpit-status"><span class="indicator-pill ${d.review_status === "Approved" ? "green" : d.review_status === "Rejected" ? "red" : "orange"}">${safe(d.review_status || "Pending")}</span><span class="indicator-pill blue">${safe(d.projection_status || "Not Projected")}</span></div></div>
			<div class="trivia-cockpit-meta"><span>${safe(d.banca || "—")}</span><span>${safe(d.materia || "—")}</span><span>${safe(d.assunto || "—")}</span><span>${safe(d.ano || "—")}</span><span class="trivia-stars">${stars}</span></div>
			<div class="trivia-cockpit-block"><h4>${__("Question preview")}</h4><div class="trivia-rich-content">${rich(d.enunciado)}</div></div>
			${d.texto_apoio ? `<div class="trivia-cockpit-block"><h4>${__("Supporting text")}</h4><p><a class="text-muted" data-action="supporting-text">${safe(d.texto_apoio)}</a></p><p class="text-muted">${__("The linked text is included during LMS projection.")}</p></div>` : ""}
			<div class="trivia-cockpit-block"><h4>${__("Alternatives")}</h4><div class="trivia-options-list">${optionRows}</div></div>
			${d.explanation ? `<div class="trivia-cockpit-block"><h4>${__("Explanation")}</h4><div class="trivia-rich-content">${rich(d.explanation)}</div></div>` : ""}
			<div class="trivia-cockpit-actions" data-actions></div>`);
		const actions = root.find("[data-actions]");
		const call = (method, args, message) => frappe.call({ method, args }).then(() => { frappe.show_alert({ message, indicator: "green" }); frm.reload_doc(); });
		actions.append(`<button class="btn btn-default btn-sm" data-cockpit="reformat">${__("Repair rich formatting")}</button>`);
		if (d.review_status !== "Approved") actions.append(`<button class="btn btn-primary btn-sm" data-cockpit="approve">${__("Approve question")}</button>`);
		if (d.review_status !== "Rejected") actions.append(`<button class="btn btn-default btn-sm" data-cockpit="reject">${__("Reject")}</button>`);
		if (d.review_status === "Approved" && d.redistribution_status !== "Approved") actions.append(`<button class="btn btn-default btn-sm" data-cockpit="rights">${__("Authorize redistribution")}</button>`);
		if (d.review_status === "Approved" && d.redistribution_status === "Approved") actions.append(`<button class="btn btn-primary btn-sm" data-cockpit="project">${__("Project to LMS")}</button>`);
		actions.find('[data-cockpit="approve"]').on("click", () => call("trivia_sync.api.review_question", { question_name: d.name, decision: "approved" }, __("Question approved.")));
		actions.find('[data-cockpit="reformat"]').on("click", () => call("trivia_sync.api.repair_qapi_question", { question_name: d.name }, __("Rich content reparsed from the stored QAPI payload.")));
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
	});
})();
