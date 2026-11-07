frappe.pages["trivia-sync-dashboard"].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Trivia Sync Dashboard"), single_column: true });
  const main = page.main.addClass("trivia-dashboard-page");
  main.html(`
    <div class="trivia-dashboard-header">
      <div><div class="trivia-onboarding-eyebrow">TRIVIA SYNC</div><h2>${__("Editorial e concursos")}</h2><p>${__("Acompanhe revisão, licenças, projeção LMS, orçamento e cobertura por cargo.")}</p></div>
      <button class="btn btn-default" data-action="refresh">${__("Atualizar")}</button>
    </div>
    <div class="trivia-dashboard-grid" data-cards></div>
    <div class="trivia-dashboard-columns">
      <section class="frappe-card trivia-dashboard-card"><h3>${__("Fila editorial")}</h3><div data-editorial></div></section>
      <section class="frappe-card trivia-dashboard-card"><h3>${__("Sincronização QAPI")}</h3><div data-source></div></section>
    </div>
    <section class="frappe-card trivia-dashboard-card"><h3>${__("Cobertura por cargo")}</h3><div class="trivia-dashboard-table-wrap"><table class="table table-sm"><thead><tr><th>${__("Concurso")}</th><th>${__("Cargo")}</th><th>${__("Banco")}</th><th>${__("Elegíveis")}</th><th>${__("Revisão pendente")}</th></tr></thead><tbody data-coverage></tbody></table></div></section>
    <div class="trivia-dashboard-columns">
      <section class="frappe-card trivia-dashboard-card"><h3>${__("Dificuldade IA")}</h3><div data-difficulty></div></section>
      <section class="frappe-card trivia-dashboard-card"><h3>${__("Workers recentes")}</h3><div class="trivia-dashboard-table-wrap"><table class="table table-sm"><thead><tr><th>${__("Fonte")}</th><th>${__("Operação")}</th><th>${__("Status")}</th><th>${__("Erros")}</th><th>${__("Chamadas · créditos / limite · reserva")}</th><th>${__("Retomada")}</th><th>${__("Fim")}</th></tr></thead><tbody data-runs></tbody></table></div></section>
    </div>
    <div class="text-muted trivia-dashboard-updated" data-updated></div>`);

  const escape = (value) => frappe.utils.escape_html(String(value ?? ""));
  const card = (label, value, detail, tone = "blue") => `<div class="frappe-card trivia-dashboard-metric"><div class="trivia-dashboard-metric-label">${escape(label)}</div><div class="trivia-dashboard-metric-value text-${tone}">${escape(value)}</div><div class="trivia-dashboard-metric-detail">${escape(detail)}</div></div>`;

  const render = (data) => {
    const q = data.questions || {}, w = data.workers || {}, c = data.catalogs || {}, e = data.editorial || {}, s = data.source_sync || {};
    main.find("[data-cards]").html([
      card(__("Workers ativos"), w.running, __("Execuções em andamento"), w.running ? "orange" : "green"),
      card(__("Questões"), q.total, `${q.enriched} ${__("enriquecidas")} · ${q.coverage_percent}%`, "blue"),
      card(__("Pendentes IA"), q.pending, __("Aguardando classificação"), q.pending ? "orange" : "green"),
      card(__("Média de dificuldade"), `${q.average || 0} ★`, __("Escala de 1 a 5 estrelas"), "purple"),
      card(__("Falhas recentes"), w.failed_recent, __("Workers parciais ou falhos"), w.failed_recent ? "red" : "green"),
      card(__("Revisão pendente"), e.pending_review, `${e.oldest_pending_days || 0} ${__("dias na fila mais antiga")}`, e.pending_review ? "orange" : "green"),
      card(__("Falha de projeção LMS"), e.projection_failed, __("Projeções que podem ser retomadas"), e.projection_failed ? "red" : "green"),
      card(__("Catálogos"), Object.values(c).reduce((a, b) => a + (Number(b) || 0), 0), __("Registros catalogados"), "blue"),
    ].join(""));
    const dist = q.distribution || {};
    main.find("[data-difficulty]").html(Object.keys(dist).map((stars) => `<div class="trivia-dashboard-bar-row"><span>${stars} ★</span><div class="trivia-dashboard-bar"><i style="width:${q.enriched ? Math.min(100, (dist[stars] / q.enriched) * 100) : 0}%"></i></div><strong>${dist[stars]}</strong></div>`).join("") || `<p class="text-muted">${__("Ainda não há classificações IA.")}</p>`);
    main.find("[data-runs]").html((w.recent_runs || []).map((run) => `<tr><td>${escape(run.source)}</td><td>${escape(run.operation)} · ${escape(run.current_operation || "")}</td><td><span class="indicator-pill ${run.status === "Completed" ? "green" : run.status === "Running" ? "orange" : "red"}">${escape(run.status)}</span></td><td>${escape(run.records_errors || 0)}</td><td>${escape(run.requests_made || 0)} · ${escape(run.credits_used || 0)} / ${escape(run.request_budget || 0)} · ${escape(run.credit_reserve || 0)}</td><td>${escape(run.resume_operation || "—")} ${escape(run.resume_page || "")}</td><td>${escape(run.finished_at || "—")}</td></tr>`).join("") || `<tr><td colspan="7" class="text-muted">${__("Nenhuma execução registrada.")}</td></tr>`);
    main.find("[data-editorial]").html([
      card(__("Aguardando revisão"), e.pending_review || 0, `${e.oldest_pending_days || 0} ${__("dias mais antiga")}`, e.pending_review ? "orange" : "green"),
      card(__("Projeções pendentes"), e.projection_pending || 0, __("Aguardando projeção LMS"), "blue"),
      card(__("Projeções com falha"), e.projection_failed || 0, __("Retomáveis sem perder aprovação"), e.projection_failed ? "red" : "green"),
    ].join(""));
    main.find("[data-source]").html([
      card(__("Agendamento"), s.enabled ? __("Ativo") : __("Desativado"), `${__("Última sync")}: ${s.last_sync || __("nunca")}`, s.enabled ? "green" : "orange"),
      card(__("Créditos / reserva"), `${s.request_budget || 0} / ${s.credit_reserve || 0}`, s.paid_sync_available ? __("Chamadas pagas disponíveis") : __("Configure orçamento acima da reserva"), s.paid_sync_available ? "blue" : "orange"),
      card(__("Execução QAPI"), s.last_run?.status || __("Sem execução"), `${s.last_run?.current_operation || "—"} · ${s.last_run?.requests_made || 0} ${__("chamadas")} / ${s.last_run?.credits_used || 0} ${__("créditos")}`, "blue"),
    ].join(""));
    main.find("[data-coverage]").html((data.syllabus_coverage || []).map((row) => `<tr><td>${escape(row.concurso || "—")}</td><td>${escape(row.cargo || row.concurso_cargo)}</td><td>${escape(row.questions || 0)}</td><td>${escape(row.eligible || 0)}</td><td>${escape(row.review?.Pending || 0)}</td></tr>`).join("") || `<tr><td colspan="5" class="text-muted">${__("Sem vínculos de cargo configurados.")}</td></tr>`);
    main.find("[data-updated]").text(`${__("Atualizado em")} ${data.generated_at || "—"}`);
  };
  const load = () => frappe.call("trivia_sync.dashboard.metrics").then(({ message }) => render(message || {}));
  main.find('[data-action="refresh"]').on("click", load);
  load();
  setInterval(load, 30000);
};
