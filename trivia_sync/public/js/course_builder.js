(() => {
	window.trivia_sync = window.trivia_sync || {};

	const OWL_SVG = `<svg class="trivia-svg-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.85" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
		<path d="M5 4l3.5 3A7.5 7.5 0 0 1 12 6.2c1.25 0 2.45.28 3.5.8L19 4l-.8 4.4A7.2 7.2 0 0 1 19.5 12.5c0 4.2-3.2 7.5-7.5 7.5s-7.5-3.3-7.5-7.5c0-1.5.45-2.9 1.3-4.1L5 4z"/>
		<circle cx="9.2" cy="11.6" r="1.8"/>
		<circle cx="14.8" cy="11.6" r="1.8"/>
		<path d="M12 13.4l-1.1 1.6L12 16.5l1.1-1.5L12 13.4z"/>
		<path d="M8.5 19.2c1 .5 2.2.8 3.5.8s2.5-.3 3.5-.8"/>
	</svg>`;

	const esc = (v) => frappe.utils.escape_html(String(v ?? ""));

	window.trivia_sync.openAthenaCourseBuilder = (options = {}) => {
		let currentPlan = null;

		const dialog = new frappe.ui.Dialog({
			title: options.targetCourse
				? __("Athena · Gerar Capítulos no Curso ({0})", [options.targetCourse])
				: __("Athena · Criar Curso no LMS"),
			size: "extra-large",
			fields: [
				{
					fieldname: "intro_html",
					fieldtype: "HTML",
					options: `<div class="trivia-athena-dialog-intro">
						<span class="trivia-athena-emblem">${OWL_SVG}</span>
						<div class="text-muted small">
							${__("Escolha uma questão do banco (engenharia reversa) e/ou escreva uma pergunta norteadora. Primeiro a Athena monta a ementa e seleciona questões reais do banco para você revisar; depois redige todas as aulas e o Quiz em rascunho.")}
						</div>
					</div>`,
				},
				{
					fieldname: "seed_question",
					fieldtype: "Link",
					options: "LMS Question",
					label: __("Questão-base do banco (opcional se informar pergunta abaixo)"),
					default: options.seedQuestion || "",
				},
				{
					fieldname: "col_break_1",
					fieldtype: "Column Break",
				},
				{
					fieldname: "target_course",
					fieldtype: "Link",
					options: "LMS Course",
					label: __("Adicionar em curso existente (em branco = criar novo curso)"),
					default: options.targetCourse || "",
				},
				{
					fieldname: "sec_prompt",
					fieldtype: "Section Break",
				},
				{
					fieldname: "prompt",
					fieldtype: "Small Text",
					label: __("Pergunta norteadora, tema ou instruções para a Athena"),
					default: options.defaultPrompt || "",
					description: __("Ex.: 'Como funcionam os créditos adicionais na Lei 4.320/64?' ou orientações específicas sobre o foco didático."),
				},
				{
					fieldname: "sec_controls",
					fieldtype: "Section Break",
					label: __("Controles Didáticos"),
				},
				{
					fieldname: "level",
					fieldtype: "Select",
					label: __("Profundidade do curso"),
					options: [
						{ label: __("mais · Enxuto (1 capítulo, 2–3 aulas)"), value: "mais" },
						{ label: __("180 · Intermediário (1–2 capítulos, 3–5 aulas)"), value: "180" },
						{ label: __("360 · Completo (2–3 capítulos, 5–8 aulas)"), value: "360" },
					],
					default: "180",
					reqd: 1,
				},
				{
					fieldname: "methodology",
					fieldtype: "Link",
					options: "Trivia Methodology",
					label: __("Metodologia (opcional)"),
				},
				{
					fieldname: "col_break_2",
					fieldtype: "Column Break",
				},
				{
					fieldname: "use_teacher_materials",
					fieldtype: "Check",
					label: __("Usar meu Comentário do Professor e Páginas de Conhecimento como base didática"),
					default: 1,
				},
				{
					fieldname: "include_quiz",
					fieldtype: "Check",
					label: __("Criar aula prática final com LMS Quiz usando questões Prontas do banco"),
					default: 1,
				},
				{
					fieldname: "sec_blueprint",
					fieldtype: "Section Break",
					label: __("Ementa Planejada pela Athena"),
				},
				{
					fieldname: "blueprint_html",
					fieldtype: "HTML",
					options: `<div class="text-muted small">${__("Clique em '1. Planejar Ementa com a Athena' para visualizar e editar os capítulos, aulas e questões sugeridas antes de criar o curso.")}</div>`,
				},
			],
			primary_action_label: __("1. Planejar Ementa com a Athena"),
			primary_action(values) {
				const seed = (values.seed_question || "").trim();
				const promptText = (values.prompt || "").trim();
				if (!seed && !promptText) {
					frappe.msgprint(__("Selecione uma questão-base ou digite uma pergunta/tema norteador."));
					return;
				}
				frappe.call({
					method: "trivia_sync.api.plan_athena_course",
					freeze: true,
					freeze_message: __("Athena está estruturando a ementa e buscando questões correlatas..."),
					args: {
						seed_question: seed || null,
						prompt: promptText,
						level: values.level || "180",
						methodology: values.methodology || null,
						use_teacher_materials: values.use_teacher_materials ? 1 : 0,
					},
				}).then(({ message }) => {
					if (!message?.blueprint) return;
					currentPlan = {
						blueprint: JSON.parse(JSON.stringify(message.blueprint)),
						bank_candidates: message.bank_candidates || [],
						model: message.model || "",
					};
					renderBlueprintEditor();
				});
			},
		});

		const countLessons = (bp) =>
			(bp?.chapters || []).reduce((acc, ch) => acc + ((ch.lessons || []).length), 0);

		const renderBlueprintEditor = () => {
			if (!currentPlan) return;
			const bp = currentPlan.blueprint;
			const candidates = currentPlan.bank_candidates || [];
			const selectedSet = new Set(bp.recommended_question_names || []);
			const totalLessons = countLessons(bp);
			const targetCourse = (dialog.get_value("target_course") || "").trim();

			const chaptersHtml = (bp.chapters || []).map((ch, cIdx) => {
				const lessonsHtml = (ch.lessons || []).map((les, lIdx) => `
					<div class="p-2 mb-2 rounded border" style="background: var(--card-bg);" data-chapter="${cIdx}" data-lesson="${lIdx}">
						<div class="d-flex align-items-center justify-content-between mb-1" style="gap: 8px;">
							<input type="text" class="form-control form-control-sm font-weight-bold" data-edit="lesson-title" data-chapter="${cIdx}" data-lesson="${lIdx}" value="${esc(les.title)}" placeholder="${esc(__("Título da aula"))}">
							<button type="button" class="btn btn-xs btn-default text-danger" data-action="remove-lesson" data-chapter="${cIdx}" data-lesson="${lIdx}" title="${esc(__("Remover aula"))}">✕</button>
						</div>
						<input type="text" class="form-control form-control-sm text-muted" data-edit="lesson-objective" data-chapter="${cIdx}" data-lesson="${lIdx}" value="${esc(les.objective || "")}" placeholder="${esc(__("Objetivo da aula"))}">
					</div>
				`).join("");

				return `
					<div class="frappe-card p-3 mb-3" data-chapter-card="${cIdx}">
						<div class="d-flex align-items-center justify-content-between mb-2" style="gap: 8px;">
							<div class="d-flex align-items-center flex-grow-1" style="gap: 8px;">
								<span class="badge badge-secondary">${__("Cap. {0}", [cIdx + 1])}</span>
								<input type="text" class="form-control form-control-sm font-weight-bold" data-edit="chapter-title" data-chapter="${cIdx}" value="${esc(ch.title)}" placeholder="${esc(__("Título do capítulo"))}">
							</div>
							<button type="button" class="btn btn-xs btn-default text-danger" data-action="remove-chapter" data-chapter="${cIdx}">${__("Remover capítulo")}</button>
						</div>
						<div class="pl-2">${lessonsHtml}</div>
						<button type="button" class="btn btn-xs btn-default mt-1" data-action="add-lesson" data-chapter="${cIdx}">${__("+ Adicionar aula")}</button>
					</div>
				`;
			}).join("");

			const questionsHtml = candidates.length
				? candidates.map((q) => {
					const checked = selectedSet.has(q.name) ? "checked" : "";
					return `
						<label class="d-flex align-items-start p-2 mb-1 rounded border small" style="gap: 8px; cursor: pointer; margin: 0;">
							<input type="checkbox" class="mt-1" data-question-check="${esc(q.name)}" ${checked}>
							<div>
								<strong>${esc(q.qcode)}</strong> · ${esc(q.title)}
								<div class="text-muted">${esc([q.banca, q.materia, q.assunto, q.ano].filter(Boolean).join(" · "))}</div>
							</div>
						</label>
					`;
				}).join("")
				: `<div class="text-muted small">${__("Nenhuma questão Pronta correlata encontrada no banco para o Quiz.")}</div>`;

			const defaultBg = totalLessons >= 5 ? "checked" : "";

			dialog.fields_dict.blueprint_html.$wrapper.html(`
				<div class="p-3 rounded border" style="background: var(--control-bg);">
					<div class="d-flex flex-wrap justify-content-between align-items-center mb-3" style="gap: 8px;">
						<span class="indicator-pill blue">${__("Ementa gerada pela Athena")} (${esc(currentPlan.model)})</span>
						<span class="text-muted small">${__("{0} capítulo(s) · {1} aula(s) teórica(s)", [(bp.chapters || []).length, totalLessons])}</span>
					</div>

					${!targetCourse ? `
					<div class="row mb-3">
						<div class="col-md-6 mb-2">
							<label class="small font-weight-bold">${__("Título do Curso")}</label>
							<input type="text" class="form-control form-control-sm" data-edit="course-title" value="${esc(bp.course_title || "")}">
						</div>
						<div class="col-md-6 mb-2">
							<label class="small font-weight-bold">${__("Introdução curta")}</label>
							<input type="text" class="form-control form-control-sm" data-edit="short-intro" value="${esc(bp.short_introduction || "")}">
						</div>
					</div>` : `<div class="alert alert-info py-2 small mb-3">${__("Os capítulos abaixo serão adicionados ao curso existente:")} <strong>${esc(targetCourse)}</strong></div>`}

					<div class="mb-2 d-flex justify-content-between align-items-center">
						<strong class="small text-uppercase text-muted">${__("Capítulos & Aulas")}</strong>
						<button type="button" class="btn btn-xs btn-default" data-action="add-chapter">${__("+ Adicionar capítulo")}</button>
					</div>
					<div>${chaptersHtml}</div>

					<div class="mt-3 mb-3">
						<div class="row mb-2">
							<div class="col-md-7">
								<strong class="small text-uppercase text-muted">${__("Questões do Banco para o LMS Quiz")} (${selectedSet.size}/${candidates.length})</strong>
							</div>
							<div class="col-md-5">
								<input type="text" class="form-control form-control-sm" data-edit="quiz-title" value="${esc(bp.quiz_title || "")}" placeholder="${esc(__("Título do Quiz"))}">
							</div>
						</div>
						<div style="max-height: 210px; overflow-y: auto; display: flex; flex-direction: column; gap: 4px;">
							${questionsHtml}
						</div>
					</div>

					<div class="pt-3 border-top d-flex flex-wrap justify-content-between align-items-center" style="gap: 12px;">
						<label class="d-flex align-items-center small mb-0" style="gap: 6px; cursor: pointer;">
							<input type="checkbox" data-edit="run-in-background" ${defaultBg}>
							<span>${__("Gerar em segundo plano (recomendado para 5+ aulas para evitar timeout)")}</span>
						</label>
						<button type="button" class="btn btn-primary btn-sm font-weight-bold" data-action="materialize-course">
							${targetCourse ? __("2. Gerar e Anexar Capítulos no LMS") : __("2. Gerar Curso Completo em Rascunho")}
						</button>
					</div>
				</div>
			`);
		};

		const wrap = dialog.$wrapper;

		wrap.on("input change", "[data-edit]", (ev) => {
			if (!currentPlan) return;
			const el = ev.currentTarget;
			const kind = el.getAttribute("data-edit");
			const bp = currentPlan.blueprint;
			if (kind === "course-title") bp.course_title = el.value;
			else if (kind === "short-intro") bp.short_introduction = el.value;
			else if (kind === "quiz-title") bp.quiz_title = el.value;
			else if (kind === "chapter-title") {
				const cIdx = Number(el.getAttribute("data-chapter"));
				if (bp.chapters[cIdx]) bp.chapters[cIdx].title = el.value;
			} else if (kind === "lesson-title") {
				const cIdx = Number(el.getAttribute("data-chapter"));
				const lIdx = Number(el.getAttribute("data-lesson"));
				if (bp.chapters[cIdx]?.lessons?.[lIdx]) bp.chapters[cIdx].lessons[lIdx].title = el.value;
			} else if (kind === "lesson-objective") {
				const cIdx = Number(el.getAttribute("data-chapter"));
				const lIdx = Number(el.getAttribute("data-lesson"));
				if (bp.chapters[cIdx]?.lessons?.[lIdx]) bp.chapters[cIdx].lessons[lIdx].objective = el.value;
			}
		});

		wrap.on("change", "[data-question-check]", () => {
			if (!currentPlan) return;
			const checked = [];
			wrap.find("[data-question-check]:checked").each((_, node) => {
				checked.push(node.getAttribute("data-question-check"));
			});
			currentPlan.blueprint.recommended_question_names = checked;
		});

		wrap.on("click", '[data-action="add-chapter"]', () => {
			if (!currentPlan) return;
			currentPlan.blueprint.chapters.push({
				title: __("Novo Capítulo"),
				description: "",
				lessons: [{ title: __("Nova Aula"), objective: "", key_points: [__("Conceito central"), __("Aplicação em prova")] }],
			});
			renderBlueprintEditor();
		});

		wrap.on("click", '[data-action="remove-chapter"]', (ev) => {
			if (!currentPlan) return;
			const cIdx = Number(ev.currentTarget.getAttribute("data-chapter"));
			if (currentPlan.blueprint.chapters.length <= 1) {
				frappe.msgprint(__("O curso precisa ter ao menos um capítulo."));
				return;
			}
			currentPlan.blueprint.chapters.splice(cIdx, 1);
			renderBlueprintEditor();
		});

		wrap.on("click", '[data-action="add-lesson"]', (ev) => {
			if (!currentPlan) return;
			const cIdx = Number(ev.currentTarget.getAttribute("data-chapter"));
			currentPlan.blueprint.chapters[cIdx]?.lessons.push({
				title: __("Nova Aula"),
				objective: "",
				key_points: [__("Fundamentação"), __("Pegadinhas da banca")],
			});
			renderBlueprintEditor();
		});

		wrap.on("click", '[data-action="remove-lesson"]', (ev) => {
			if (!currentPlan) return;
			const cIdx = Number(ev.currentTarget.getAttribute("data-chapter"));
			const lIdx = Number(ev.currentTarget.getAttribute("data-lesson"));
			const lessons = currentPlan.blueprint.chapters[cIdx]?.lessons || [];
			if (lessons.length <= 1) {
				frappe.msgprint(__("Cada capítulo precisa ter ao menos uma aula."));
				return;
			}
			lessons.splice(lIdx, 1);
			renderBlueprintEditor();
		});

		wrap.on("click", '[data-action="materialize-course"]', () => {
			if (!currentPlan) return;
			const values = dialog.get_values() || {};
			const runBg = wrap.find('[data-edit="run-in-background"]').is(":checked");
			const args = {
				blueprint: JSON.stringify(currentPlan.blueprint),
				target_course: values.target_course || null,
				seed_question: values.seed_question || null,
				prompt: values.prompt || "",
				level: values.level || "180",
				methodology: values.methodology || null,
				use_teacher_materials: values.use_teacher_materials ? 1 : 0,
				include_quiz: values.include_quiz ? 1 : 0,
			};

			if (runBg) {
				dialog.hide();
				frappe.call({
					method: "trivia_sync.api.enqueue_athena_course",
					args,
				}).then(({ message }) => {
					frappe.show_alert({
						message: __("Geração do curso enfileirada na fila {0}. Acompanhe em Trivia Sync Run ou no Dashboard!", [message?.queue || "long"]),
						indicator: "green",
					});
					if (typeof options.onCreated === "function") options.onCreated(message);
				});
				return;
			}

			frappe.call({
				method: "trivia_sync.api.create_athena_course",
				freeze: true,
				freeze_message: __("Athena está redigindo as aulas completas e montando o Quiz no LMS..."),
				args,
			}).then(({ message }) => {
				if (!message) return;
				dialog.hide();
				frappe.show_alert({
					message: __("Curso '{0}' pronto ({1} capítulo(s), {2} aula(s))!", [
						message.course_title || message.course_name,
						message.chapters_created || 0,
						message.lessons_created || 0,
					]),
					indicator: "green",
				});
				if (typeof options.onCreated === "function") {
					options.onCreated(message);
				} else if (message.course_name) {
					frappe.set_route("Form", "LMS Course", message.course_name);
				}
			});
		});

		dialog.show();
	};
})();
