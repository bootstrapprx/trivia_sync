frappe.pages["trivia-sync-onboarding"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Contest Setup"),
		single_column: true,
	});
	const main = page.main.addClass("trivia-onboarding-page").empty();

	main.html(`
		<div class="trivia-onboarding-header">
			<div class="trivia-onboarding-eyebrow">TRIVIA SYNC</div>
			<h2>Prepare your question bank</h2>
			<p>Configure the source and credit budget, then send questions for editorial review before they reach the LMS.</p>
		</div>
		<div class="trivia-onboarding-grid">
			<section class="frappe-card trivia-onboarding-step">
				<div class="trivia-onboarding-step-title"><span>1</span><div><h3>Connect to QAPI</h3><p>Enter the URL and your API key.</p></div></div>
				<div data-field="qapi_base_url"></div>
				<div data-field="qapi_api_key"></div>
				<div data-field="qapi_enabled"></div>
				<div data-field="qapi_sync_frequency"></div>
				<div data-field="qapi_max_requests_per_run"></div>
				<div data-field="qapi_min_credit_reserve"></div>
				<button class="btn btn-primary" data-action="save">Save settings</button>
			</section>
			<section class="frappe-card trivia-onboarding-step">
				<div class="trivia-onboarding-step-title"><span>2</span><div><h3>Test connection</h3><p>Confirm that the key can access QAPI.</p></div></div>
			<div class="trivia-onboarding-status text-muted" data-status></div>
			<button class="btn btn-default" data-action="test">Test QAPI</button>
			</section>
			<section class="frappe-card trivia-onboarding-step">
			<div class="trivia-onboarding-step-title"><span>3</span><div><h3>Preview and import</h3><p>Imports create questions in the editorial review queue. Only approved and cleared items are projected to the LMS.</p></div></div>
			<button class="btn btn-default" data-action="dry-run">Estimate cost</button>
			<button class="btn btn-primary" data-action="sync">Import questions for review</button>
			</section>
		</div>`);

	const fields = {
		qapi_base_url: {
			fieldname: "qapi_base_url",
			fieldtype: "Data",
			label: __("Base URL"),
			reqd: 1,
		},
		qapi_api_key: {
			fieldname: "qapi_api_key",
			fieldtype: "Password",
			label: __("Q-Api-Key"),
			placeholder: __("Paste your QAPI key"),
		},
		qapi_enabled: {
			fieldname: "qapi_enabled",
			fieldtype: "Check",
			label: __("Enable automatic sync"),
		},
		qapi_sync_frequency: {
			fieldname: "qapi_sync_frequency",
			fieldtype: "Select",
			label: __("Frequency"),
			options: "Hourly\nEvery scheduler tick",
		},
		qapi_max_requests_per_run: {
			fieldname: "qapi_max_requests_per_run",
			fieldtype: "Int",
			label: __("QAPI credit limit per run (0 disables sync; exams cost 200)"),
			default: 0,
		},
		qapi_min_credit_reserve: {
			fieldname: "qapi_min_credit_reserve",
			fieldtype: "Int",
			label: __("Credits to keep in reserve"),
			default: 1,
		},
	};
	const controls = {};
	for (const [name, df] of Object.entries(fields)) {
		controls[name] = frappe.ui.form.make_control({
			df,
			parent: main.find(`[data-field="${name}"]`),
			render_input: true,
		});
		controls[name].refresh();
	}

	const showStatus = (message, indicator = "blue") => frappe.show_alert({ message, indicator });
	const loadStatus = () =>
		frappe.call("trivia_sync.api.onboarding_status").then(({ message }) => {
			if (!message) return;
			controls.qapi_base_url.set_value(message.base_url || "https://qapi.otunac.com/api");
			controls.qapi_enabled.set_value(message.enabled);
			controls.qapi_sync_frequency.set_value(message.frequency);
			controls.qapi_max_requests_per_run.set_value(message.request_budget || 0);
			controls.qapi_min_credit_reserve.set_value(message.credit_reserve || 0);
			main.find("[data-status]").text(
				`${message.configured ? __("Key configured") : __("Key missing")} · ${__("Effective limit")}: ${message.paid_sync_available ? message.request_budget - message.credit_reserve : 0} ${__("credits")} · ${__("Last sync")}: ${message.last_sync || __("never")}`
			);
		});

	main.find('[data-action="save"]').on("click", () =>
		frappe
			.call({
				method: "trivia_sync.api.save_onboarding",
				args: {
					qapi_base_url: controls.qapi_base_url.get_value(),
					qapi_api_key: controls.qapi_api_key.get_value(),
					qapi_enabled: controls.qapi_enabled.get_value() ? 1 : 0,
					qapi_sync_frequency: controls.qapi_sync_frequency.get_value(),
					qapi_max_requests_per_run: controls.qapi_max_requests_per_run.get_value(),
					qapi_min_credit_reserve: controls.qapi_min_credit_reserve.get_value(),
				},
			})
			.then(({ message }) => {
				controls.qapi_api_key.set_value("");
				showStatus(__("Settings saved."), "green");
				loadStatus();
			})
	);

	main.find('[data-action="test"]').on("click", () =>
		frappe.call("trivia_sync.api.qapi_status").then(({ message }) => {
			const text = message?.ok
				? `${__("Connection successful")} · ${message.total ?? __("QAPI is reachable")}`
				: message?.error || __("QAPI connection test failed");
			main.find("[data-status]").text(text);
			showStatus(text, message?.ok ? "green" : "red");
		})
	);

	main.find('[data-action="sync"]').on("click", () =>
		frappe.call("trivia_sync.api.enqueue_qapi_sync").then(() =>
			showStatus(__("Import queued."), "green")
		)
	);

	main.find('[data-action="dry-run"]').on("click", () =>
		frappe.call({ method: "trivia_sync.api.run_qapi_sync_now", args: { dry_run: 1 } }).then(({ message }) => {
			const text = `${__("Estimated maximum cost")}: ${message?.projected_request_cost ?? 0} ${__("credits")} · ${__("No data will be written")}`;
			main.find("[data-status]").text(text);
			showStatus(text, "blue");
		})
	);

	loadStatus();
};
