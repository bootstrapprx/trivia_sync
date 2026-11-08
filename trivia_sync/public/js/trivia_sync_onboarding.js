frappe.pages["trivia-sync-onboarding"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Contest Setup"), single_column: true });
	const main = page.main.addClass("trivia-onboarding-page").empty();
	const endpointFields = [
		["sync_questions", "Questions"], ["sync_support_texts", "Supporting texts → questions"],
		["sync_bancas", "Exam boards (bancas)"], ["sync_orgaos", "Organizations (órgãos)"],
		["sync_cargos", "Positions (cargos)"], ["sync_materias", "Subjects (matérias)"],
		["sync_assuntos", "Topics (assuntos)"], ["sync_concursos", "Contests + status"],
		["sync_exams", "Exams + details · 200 credits/call"], ["sync_disciplinas", "Disciplines + details"],
		["sync_conteudos", "Program-content tree"], ["sync_flashcards", "Flashcards (read)"],
	];
	main.html(`
		<div class="trivia-onboarding-header">
			<div class="trivia-onboarding-eyebrow">TRIVIA SYNC</div>
			<h2>${__("Prepare your question bank")}</h2>
			<p>${__("Choose individual endpoints or enable Full upgrade to consume every read endpoint in one resumable worker.")}</p>
		</div>
		<div class="trivia-onboarding-grid">
			<section class="frappe-card trivia-onboarding-step">
				<div class="trivia-onboarding-step-title"><span>1</span><div><h3>${__("Connect to QAPI")}</h3><p>${__("Enter the URL, key and credit budget.")}</p></div></div>
				<div data-field="qapi_base_url"></div><div data-field="qapi_api_key"></div><div data-field="qapi_enabled"></div>
				<div data-field="qapi_sync_frequency"></div><div data-field="qapi_page_size"></div><div data-field="qapi_max_pages"></div>
				<div data-field="qapi_max_requests_per_run"></div><div data-field="qapi_min_credit_reserve"></div>
				<button class="btn btn-primary" data-action="save">${__("Save settings")}</button>
			</section>
			<section class="frappe-card trivia-onboarding-step trivia-onboarding-options">
				<div class="trivia-onboarding-step-title"><span>2</span><div><h3>${__("Endpoints to synchronize")}</h3><p>${__("Select exactly what the worker should read. Full upgrade enables all read endpoints.")}</p></div></div>
				<div data-field="sync_catalogs"></div><div data-field="full_upgrade"></div>
				<div class="trivia-endpoint-grid">${endpointFields.map(([name]) => `<div data-field="${name}"></div>`).join("")}</div>
				<div data-field="push_flashcards"></div>
				<small class="text-muted">${__("Creating flashcards in QAPI is a separate write operation and remains opt-in.")}</small>
			</section>
			<section class="frappe-card trivia-onboarding-step">
				<div class="trivia-onboarding-step-title"><span>3</span><div><h3>${__("Test and preview")}</h3><p>${__("Dry-run calculates the worst-case credit cost; it never writes data or calls QAPI.")}</p></div></div>
				<div class="trivia-onboarding-status text-muted" data-status></div>
				<button class="btn btn-default" data-action="test">${__("Test QAPI")}</button>
				<button class="btn btn-default" data-action="dry-run">${__("Estimate full cost")}</button>
			</section>
			<section class="frappe-card trivia-onboarding-step">
				<div class="trivia-onboarding-step-title"><span>4</span><div><h3>${__("Run workers")}</h3><p>${__("The job is queued in the long worker and can be resumed after a budget block.")}</p></div></div>
				<button class="btn btn-primary" data-action="full-upgrade">${__("Full upgrade · all endpoints")}</button>
				<button class="btn btn-default" data-action="sync">${__("Run selected sync")}</button>
				<button class="btn btn-default" data-action="lms">${__("Sync LMS → Trivia")}</button>
			</section>
		</div>`);

	const fields = {
		qapi_base_url: { fieldname: "qapi_base_url", fieldtype: "Data", label: __("Base URL"), reqd: 1 },
		qapi_api_key: { fieldname: "qapi_api_key", fieldtype: "Password", label: __("Q-Api-Key"), placeholder: __("Paste your QAPI key") },
		qapi_enabled: { fieldname: "qapi_enabled", fieldtype: "Check", label: __("Enable automatic sync") },
		qapi_sync_frequency: { fieldname: "qapi_sync_frequency", fieldtype: "Select", label: __("Frequency"), options: "Hourly\nEvery scheduler tick" },
		qapi_page_size: { fieldname: "qapi_page_size", fieldtype: "Int", label: __("Items per page (max 10)"), default: 10 },
		qapi_max_pages: { fieldname: "qapi_max_pages", fieldtype: "Int", label: __("Max pages per endpoint"), default: 10 },
		qapi_max_requests_per_run: { fieldname: "qapi_max_requests_per_run", fieldtype: "Int", label: __("QAPI credit limit per run (exams cost 200)"), default: 0 },
		qapi_min_credit_reserve: { fieldname: "qapi_min_credit_reserve", fieldtype: "Int", label: __("Credits to keep in reserve"), default: 1 },
		sync_catalogs: { fieldname: "sync_catalogs", fieldtype: "Check", label: __("Enable catalog/resource sync"), default: 1 },
		full_upgrade: { fieldname: "full_upgrade", fieldtype: "Check", label: __("Full upgrade: enable all read endpoints") },
		push_flashcards: { fieldname: "push_flashcards", fieldtype: "Check", label: __("Create local flashcards in QAPI") },
	};
	endpointFields.forEach(([name, label]) => { fields[name] = { fieldname: name, fieldtype: "Check", label: __(label), default: name === "sync_exams" ? 0 : 1 }; });
	const controls = {};
	for (const [name, df] of Object.entries(fields)) {
		controls[name] = frappe.ui.form.make_control({ df, parent: main.find(`[data-field="${name}"]`), render_input: true });
		controls[name].refresh();
	}
	const readEndpointNames = endpointFields.map(([name]) => name);
	const setFullUpgrade = (value) => {
		controls.sync_catalogs.set_value(value ? 1 : 0);
		readEndpointNames.forEach((name) => controls[name].set_value(value ? 1 : 0));
		if (value) controls.push_flashcards.set_value(0);
	};
	controls.full_upgrade.$input?.on("change", () => setFullUpgrade(controls.full_upgrade.get_value()));
	const showStatus = (message, indicator = "blue") => { main.find("[data-status]").text(message); frappe.show_alert({ message, indicator }); };
	const optionValues = () => Object.fromEntries([...readEndpointNames, "push_flashcards", "sync_support_texts"].map((name) => [name, controls[name].get_value() ? 1 : 0]));
	const loadStatus = () => frappe.call("trivia_sync.api.onboarding_status").then(({ message }) => {
		if (!message) return;
		controls.qapi_base_url.set_value(message.base_url || "https://qapi.otunac.com/api");
		controls.qapi_enabled.set_value(message.enabled); controls.qapi_sync_frequency.set_value(message.frequency);
		controls.qapi_page_size.set_value(message.page_size || 10); controls.qapi_max_pages.set_value(message.max_pages || 10);
		controls.qapi_max_requests_per_run.set_value(message.request_budget || 0); controls.qapi_min_credit_reserve.set_value(message.credit_reserve || 0);
		controls.sync_catalogs.set_value(message.full_sync ? 1 : 0);
		Object.entries(message.sync_options || {}).forEach(([name, value]) => controls[name]?.set_value(value ? 1 : 0));
		main.find("[data-status]").text(`${message.configured ? __("Key configured") : __("Key missing")} · ${__("Effective limit")}: ${message.paid_sync_available ? message.request_budget - message.credit_reserve : 0} ${__("credits")} · ${__("Last sync")}: ${message.last_sync || __("never")}`);
	});
	main.find('[data-action="save"]').on("click", () => frappe.call({ method: "trivia_sync.api.save_onboarding", args: {
		qapi_base_url: controls.qapi_base_url.get_value(), qapi_api_key: controls.qapi_api_key.get_value(), qapi_enabled: controls.qapi_enabled.get_value() ? 1 : 0,
		qapi_sync_frequency: controls.qapi_sync_frequency.get_value(), qapi_page_size: controls.qapi_page_size.get_value(), qapi_max_pages: controls.qapi_max_pages.get_value(),
		qapi_max_requests_per_run: controls.qapi_max_requests_per_run.get_value(), qapi_min_credit_reserve: controls.qapi_min_credit_reserve.get_value(),
		sync_catalogs: controls.sync_catalogs.get_value() ? 1 : 0, sync_options: JSON.stringify(optionValues()),
	} }).then(() => { controls.qapi_api_key.set_value(""); showStatus(__("Settings saved."), "green"); loadStatus(); }));
	main.find('[data-action="test"]').on("click", () => frappe.call("trivia_sync.api.qapi_status").then(({ message }) => showStatus(message?.ok ? `${__("Connection successful")} · ${message.total ?? __("QAPI is reachable")}` : message?.error || __("QAPI connection test failed"), message?.ok ? "green" : "red")));
	main.find('[data-action="dry-run"]').on("click", () => frappe.call({ method: "trivia_sync.api.run_qapi_sync_now", args: { dry_run: 1, full_upgrade: 1, max_pages: controls.qapi_max_pages.get_value() } }).then(({ message }) => showStatus(`${__("Full upgrade upper bound")}: ${message?.required_upper_bound ?? message?.projected_request_cost ?? 0} ${__("credits")} · ${__("No data was written")}`, "blue")));
	main.find('[data-action="full-upgrade"]').on("click", () => frappe.call({ method: "trivia_sync.api.enqueue_qapi_full_upgrade", args: { max_pages: controls.qapi_max_pages.get_value() } }).then(() => showStatus(__("Full upgrade queued: all selected read endpoints will run."), "green")));
	main.find('[data-action="sync"]').on("click", () => frappe.call({ method: "trivia_sync.api.enqueue_qapi_sync", args: { full: 1, max_pages: controls.qapi_max_pages.get_value() } }).then(() => showStatus(__("Selected QAPI sync queued."), "green")));
	main.find('[data-action="lms"]').on("click", () => frappe.call("trivia_sync.api.enqueue_lms_sync").then(() => showStatus(__("Frappe LMS sync queued."), "green")));
	loadStatus();
};
