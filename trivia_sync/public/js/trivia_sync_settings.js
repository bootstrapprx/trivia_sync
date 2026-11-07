frappe.ui.form.on("Trivia Sync Settings", {
  refresh(frm) {
    if (!frappe.user.has_role("System Manager")) return;
    frm.add_custom_button("Test QAPI", () => {
      frappe.call({ method: "trivia_sync.api.qapi_status" }).then(({ message }) => {
        frappe.msgprint(message?.ok ? `QAPI OK: ${message.total ?? "connection successful"}` : (message?.error || "Could not validate QAPI."));
      });
    }, "Sync");
    frm.add_custom_button("Sync QAPI questions", () => {
      frappe.call({ method: "trivia_sync.api.enqueue_qapi_sync" }).then(() => frappe.show_alert({ message: "QAPI sync queued.", indicator: "green" }));
    }, "Sync");
    frm.add_custom_button("Sync LMS → Trivia", () => {
      frappe.call({ method: "trivia_sync.api.enqueue_lms_sync" }).then(() => frappe.show_alert({ message: "Frappe LMS sync queued.", indicator: "green" }));
    }, "Sync");
    frm.add_custom_button("Enrich questions with AI", () => {
      frappe.call({ method: "trivia_sync.api.enqueue_ai_enrichment" }).then(() => frappe.show_alert({ message: "AI enrichment queued.", indicator: "green" }));
    }, "IA");
  },
});
