frappe.ui.form.on("Trivia Sync Settings", {
  refresh(frm) {
    if (!frappe.user.has_role("System Manager")) return;
    frm.add_custom_button("Testar QAPI", () => {
      frappe.call({ method: "trivia_sync.api.qapi_status" }).then(({ message }) => {
        frappe.msgprint(message?.ok ? `QAPI OK: ${message.total ?? "conexão válida"}` : (message?.error || "Não foi possível validar a QAPI."));
      });
    }, "Sincronização");
    frm.add_custom_button("Sincronizar questões QAPI", () => {
      frappe.call({ method: "trivia_sync.api.enqueue_qapi_sync" }).then(() => frappe.show_alert({ message: "Sincronização QAPI enfileirada.", indicator: "green" }));
    }, "Sincronização");
    frm.add_custom_button("Sincronizar LMS → Trivia", () => {
      frappe.call({ method: "trivia_sync.api.enqueue_lms_sync" }).then(() => frappe.show_alert({ message: "Sincronização do Frappe LMS enfileirada.", indicator: "green" }));
    }, "Sincronização");
    frm.add_custom_button("Enriquecer questões com IA", () => {
      frappe.call({ method: "trivia_sync.api.enqueue_ai_enrichment" }).then(() => frappe.show_alert({ message: "Enriquecimento IA enfileirado.", indicator: "green" }));
    }, "IA");
  },
});
