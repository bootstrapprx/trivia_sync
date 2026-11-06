frappe.pages["trivia-sync-dashboard"].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Trivia Sync Dashboard"), single_column: true });
  const main = page.main.addClass("trivia-dashboard-page");
  main.html(`
    <div class="trivia-dashboard-header">
      <div><div class="trivia-onboarding-eyebrow">TRIVIA SYNC</div><h2>${__("Operação e enriquecimento")}</h2><p>${__("Acompanhe workers, sincronização QAPI e classificação IA das questões.")}</p></div>
      <button class="btn btn-default" data-action="refresh">${__("Atualizar")}</button>
    </div>
    <div class="trivia-dashboard-grid" data-cards></div>
    <div class="trivia-dashboard-columns">
      <section class="frappe-card trivia-dashboard-card"><h3>${__("Dificuldade IA")}</h3><div data-difficulty></div></section>
      <section class="frappe-card trivia-dashboard-card"><h3>${__("Workers recentes")}</h3><div class="trivia-dashboard-table-wrap"><table class="table table-sm"><thead><tr><th>${__("Fonte")}</th><th>${__("Operação")}</th><th>${__("Status")}</th><th>${__("Erros")}</th><th>${__("Fim")}</th></tr></thead><tbody data-runs></tbody></table></div></section>
    </div>
    <div class="text-muted trivia-dashboard-updated" data-updated></div>`);

  const escape = (value) => frappe.utils.escape_html(String(value ?? ""));
  const card = (label, value, detail, tone = "blue") => `<div class="frappe-card trivia-dashboard-metric"><div class="trivia-dashboard-metric-label">${escape(label)}</div><div class="trivia-dashboard-metric-value text-${tone}">${escape(value)}</div><div class="trivia-dashboard-metric-detail">${escape(detail)}</div></div>`;

  const render = (data) => {
    const q = data.questions || {}, w = data.workers || {}, c = data.catalogs || {};
    main.find("[data-cards]").html([
      card(__("Workers ativos"), w.running, __("Execuções em andamento"), w.running ? "orange" : "green"),
      card(__("Questões"), q.total, `${q.enriched} ${__("enriquecidas")} · ${q.coverage_percent}%`, "blue"),
      card(__("Pendentes IA"), q.pending, __("Aguardando classificação"), q.pending ? "orange" : "green"),
      card(__("Média de dificuldade"), `${q.average || 0} ★`, __("Escala de 1 a 5 estrelas"), "purple"),
      card(__("Falhas recentes"), w.failed_recent, __("Workers parciais ou falhos"), w.failed_recent ? "red" : "green"),
      card(__("Catálogos"), Object.values(c).reduce((a, b) => a + (Number(b) || 0), 0), __("Registros catalogados"), "blue"),
    ].join(""));
    const dist = q.distribution || {};
    main.find("[data-difficulty]").html(Object.keys(dist).map((stars) => `<div class="trivia-dashboard-bar-row"><span>${stars} ★</span><div class="trivia-dashboard-bar"><i style="width:${q.enriched ? Math.min(100, (dist[stars] / q.enriched) * 100) : 0}%"></i></div><strong>${dist[stars]}</strong></div>`).join("") || `<p class="text-muted">${__("Ainda não há classificações IA.")}</p>`);
    main.find("[data-runs]").html((w.recent_runs || []).map((run) => `<tr><td>${escape(run.source)}</td><td>${escape(run.operation)}</td><td><span class="indicator-pill ${run.status === "Completed" ? "green" : run.status === "Running" ? "orange" : "red"}">${escape(run.status)}</span></td><td>${escape(run.records_errors || 0)}</td><td>${escape(run.finished_at || "—")}</td></tr>`).join("") || `<tr><td colspan="5" class="text-muted">${__("Nenhuma execução registrada.")}</td></tr>`);
    main.find("[data-updated]").text(`${__("Atualizado em")} ${data.generated_at || "—"}`);
  };
  const load = () => frappe.call("trivia_sync.dashboard.metrics").then(({ message }) => render(message || {}));
  main.find('[data-action="refresh"]').on("click", load);
  load();
  setInterval(load, 30000);
};
