frappe.pages["trivia-sync-dashboard"].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Painel Trivia Concursos"), single_column: true });
  const main = page.main.addClass("trivia-dashboard-page");
  main.html(`
    <div class="trivia-dashboard-header">
      <div><div class="trivia-onboarding-eyebrow">TRIVIA CONCURSOS</div><h2>${__("Editorial and contests")}</h2><p>${__("Track reviews, licenses, LMS projections, budgets, and question coverage by position.")}</p></div>
      <div class="d-flex" style="gap:8px;">
        <button class="btn btn-primary" data-action="create-course">${__("Athena · Criar Curso")}</button>
        <button class="btn btn-default" data-action="import-exam">${__("Import Ready Exam")}</button>
        <button class="btn btn-default" data-action="refresh">${__("Refresh")}</button>
      </div>
    </div>
    <div class="trivia-dashboard-grid" data-cards></div>
    <div class="trivia-dashboard-columns">
      <section class="frappe-card trivia-dashboard-card"><h3>${__("Editorial queue")}</h3><div data-editorial></div></section>
      <section class="frappe-card trivia-dashboard-card"><h3>${__("QAPI sync")}</h3><div data-source></div></section>
    </div>
    <section class="frappe-card trivia-dashboard-card"><h3>${__("Materials lifecycle")}</h3><div class="trivia-dashboard-grid" data-materials></div></section>
    <section class="frappe-card trivia-dashboard-card"><h3>${__("Coverage by position")}</h3><div class="trivia-dashboard-table-wrap"><table class="table table-sm"><thead><tr><th>${__("Contest")}</th><th>${__("Position")}</th><th>${__("Bank")}</th><th>${__("Eligible")}</th><th>${__("Pending review")}</th></tr></thead><tbody data-coverage></tbody></table></div></section>
    <div class="trivia-dashboard-columns">
      <section class="frappe-card trivia-dashboard-card"><h3>${__("Dificuldade (Athena)")}</h3><div data-difficulty></div></section>
      <section class="frappe-card trivia-dashboard-card"><h3>${__("Recent workers")}</h3><div class="trivia-dashboard-table-wrap"><table class="table table-sm"><thead><tr><th>${__("Source")}</th><th>${__("Operation")}</th><th>${__("Status")}</th><th>${__("Errors")}</th><th>${__("Requests · credits / limit · reserve")}</th><th>${__("Resume")}</th><th>${__("Finished")}</th></tr></thead><tbody data-runs></tbody></table></div></section>
    </div>
    <section class="frappe-card trivia-dashboard-card"><h3>${__("Endpoint utilization")}</h3><div class="trivia-dashboard-table-wrap"><table class="table table-sm"><thead><tr><th>${__("Endpoint")}</th><th>${__("Received")}</th><th>${__("Created")}</th><th>${__("Updated")}</th><th>${__("Failed")}</th><th>${__("Utilization")}</th></tr></thead><tbody data-endpoints></tbody></table></div></section>
    <div class="text-muted trivia-dashboard-updated" data-updated></div>`);

  const escape = (value) => frappe.utils.escape_html(String(value ?? ""));
  const card = (label, value, detail, tone = "blue") => `<div class="frappe-card trivia-dashboard-metric"><div class="trivia-dashboard-metric-label">${escape(label)}</div><div class="trivia-dashboard-metric-value text-${tone}">${escape(value)}</div><div class="trivia-dashboard-metric-detail">${escape(detail)}</div></div>`;

  let pollTimer = null;
  const pillClass = (status) => {
    if (status === "Completed") return "green";
    if (status === "Queued") return "blue";
    if (status === "Running") return "orange";
    return "red";
  };

  const render = (data) => {
    const q = data.questions || {}, w = data.workers || {}, c = data.catalogs || {}, e = data.editorial || {}, s = data.source_sync || {}, m = data.materials || {};
    const activeCount = (w.running || 0) + (w.queued || 0);
    const workerNote = w.rq_worker_online
      ? `${w.running || 0} rodando · ${w.queued || 0} na fila (RQ online)`
      : `${w.running || 0} rodando · ${w.queued || 0} na fila (modo thread local)`;
    main.find("[data-cards]").html([
      card(__("Workers / Segundo plano"), activeCount, workerNote, activeCount ? "orange" : "green"),
      card(__("Questions"), q.total, `${q.enriched} ${__("enriched")} · ${q.coverage_percent}%`, "blue"),
      card(__("Pendentes para Athena"), q.pending, __("Aguardando análise"), q.pending ? "orange" : "green"),
      card(__("Average difficulty"), `${q.average || 0} ★`, __("Scale of 1 to 5 stars"), "purple"),
      card(__("Recent failures"), w.failed_recent, __("Partial or failed workers"), w.failed_recent ? "red" : "green"),
      card(__("In preparation"), e.pending_review, `${e.oldest_pending_days || 0} ${__("days in oldest item")}`, e.pending_review ? "orange" : "green"),
      card(__("Ready in LMS"), e.ready_questions || 0, __("Ready for LMS Quizzes"), "green"),
      card(__("Catalogs"), Object.values(c).reduce((a, b) => a + (Number(b) || 0), 0), __("Catalog records"), "blue"),
    ].join(""));
    const dist = q.distribution || {};
    main.find("[data-difficulty]").html(Object.keys(dist).map((stars) => `<div class="trivia-dashboard-bar-row"><span>${stars} ★</span><div class="trivia-dashboard-bar"><i style="width:${q.enriched ? Math.min(100, (dist[stars] / q.enriched) * 100) : 0}%"></i></div><strong>${dist[stars]}</strong></div>`).join("") || `<p class="text-muted">${__("Nenhuma classificação da Athena ainda.")}</p>`);
    main.find("[data-runs]").html((w.recent_runs || []).map((run) => `<tr style="cursor:pointer;" onclick="frappe.set_route('Form', 'Trivia Sync Run', '${escape(run.name)}')"><td><strong>${escape(run.source)}</strong></td><td>${escape(run.operation)}${run.current_operation ? ` · <span class="text-muted">${escape(run.current_operation)}</span>` : ""}${run.error_snippet ? `<div class="text-danger small mt-1">${escape(run.error_snippet)}</div>` : ""}</td><td><span class="indicator-pill ${pillClass(run.status)}">${escape(run.status)}</span></td><td>${escape(run.records_errors || 0)}</td><td>${escape(run.requests_made || 0)} · ${escape(run.credits_used || 0)} / ${escape(run.request_budget || 0)} · ${escape(run.credit_reserve || 0)}</td><td>${escape(run.resume_operation || "—")} ${escape(run.resume_page || "")}</td><td>${escape(run.finished_at || run.started_at || "—")}</td></tr>`).join("") || `<tr><td colspan="7" class="text-muted">${__("No runs recorded.")}</td></tr>`);
    main.find("[data-editorial]").html([
      card(__("In preparation"), e.pending_review || 0, `${e.oldest_pending_days || 0} ${__("days in oldest item")}`, e.pending_review ? "orange" : "green"),
      card(__("Ready in LMS"), e.ready_questions || 0, __("Available for quizzes & courses"), "green"),
    ].join(""));
    main.find("[data-source]").html([
      card(__("Schedule"), s.enabled ? __("Enabled") : __("Disabled"), `${__("Last sync")}: ${s.last_sync || __("never")}`, s.enabled ? "green" : "orange"),
      card(__("Credits / reserve"), `${s.request_budget || 0} / ${s.credit_reserve || 0}`, s.paid_sync_available ? __("Paid requests available") : __("Set a budget above the reserve"), s.paid_sync_available ? "blue" : "orange"),
      card(__("QAPI run"), s.last_run?.status || __("No runs"), `${s.last_run?.current_operation || "—"} · ${s.last_run?.requests_made || 0} ${__("requests")} / ${s.last_run?.credits_used || 0} ${__("credits")}`, "blue"),
    ].join(""));
    main.find("[data-materials]").html([
      card(__("Knowledge & Guides"), (m.knowledge_pages || 0) + (m.study_guides || 0), `${m.knowledge_pages || 0} ${__("knowledge pages")} · ${m.study_guides || 0} ${__("study guides")}`, "blue"),
      card(__("Draft"), m.draft || 0, __("Editable versions"), "blue"),
      card(__("Pending approval"), m.pending_approval || 0, __("Awaiting reviewer"), m.pending_approval ? "orange" : "green"),
      card(__("Stale"), m.stale || 0, __("Sources changed"), m.stale ? "red" : "green"),
      card(__("Published"), m.published || 0, `${m.approved || 0} ${__("approved ready")}`, "green"),
    ].join(""));
    const endpointRows = Object.entries(s.endpoint_metrics || {}).map(([endpoint, values]) => `<tr><td>${escape(endpoint)}</td><td>${escape(values.received || 0)}</td><td>${escape(values.created || 0)}</td><td>${escape(values.updated || 0)}</td><td>${escape(values.failed || 0)}</td><td>${escape(values.utilization_percent || 0)}%</td></tr>`).join("");
    main.find("[data-endpoints]").html(endpointRows || `<tr><td colspan="6" class="text-muted">${__("No endpoint metrics recorded yet.")}</td></tr>`);
    main.find("[data-coverage]").html((data.syllabus_coverage || []).map((row) => `<tr><td>${escape(row.concurso || "—")}</td><td>${escape(row.cargo || row.concurso_cargo)}</td><td>${escape(row.questions || 0)}</td><td>${escape(row.eligible || 0)}</td><td>${escape(row.review?.Pending || 0)}</td></tr>`).join("") || `<tr><td colspan="5" class="text-muted">${__("No contest positions are configured.")}</td></tr>`);
    main.find("[data-updated]").text(`${__("Updated at")} ${data.generated_at || "—"}`);
  };
  const scheduleNext = (active) => {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = setTimeout(load, active ? 5000 : 25000);
  };
  const load = () => frappe.call("trivia_sync.dashboard.metrics").then(({ message }) => {
    const data = message || {};
    render(data);
    const active = ((data.workers?.running || 0) + (data.workers?.queued || 0)) > 0;
    scheduleNext(active);
  });
  main.find('[data-action="create-course"]').on("click", () => {
    window.trivia_sync?.openAthenaCourseBuilder?.({ onCreated: load });
  });
  main.find('[data-action="import-exam"]').on("click", () => {
    window.trivia_sync?.openExamImporterDialog?.({ onImported: load });
  });
  main.find('[data-action="refresh"]').on("click", load);
  load();
};
