frappe.pages["trivia-sync-onboarding"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Configuração de Concursos"),
		single_column: true,
	});
	const main = page.main.addClass("trivia-onboarding-page").empty();

	main.html(`
		<div class="trivia-onboarding-header">
			<div class="trivia-onboarding-eyebrow">TRIVIA SYNC</div>
			<h2>Prepare seu banco de questões</h2>
			<p>Conecte a QAPI e importe questões diretamente para o Frappe LMS.</p>
		</div>
		<div class="trivia-onboarding-grid">
			<section class="frappe-card trivia-onboarding-step">
				<div class="trivia-onboarding-step-title"><span>1</span><div><h3>Conectar à QAPI</h3><p>Informe a URL e sua chave de acesso.</p></div></div>
				<div data-field="qapi_base_url"></div>
				<div data-field="qapi_api_key"></div>
				<div data-field="qapi_enabled"></div>
				<div data-field="qapi_sync_frequency"></div>
				<button class="btn btn-primary" data-action="save">Salvar configuração</button>
			</section>
			<section class="frappe-card trivia-onboarding-step">
				<div class="trivia-onboarding-step-title"><span>2</span><div><h3>Testar conexão</h3><p>Confirme que a chave permite acessar a QAPI.</p></div></div>
			<div class="trivia-onboarding-status text-muted" data-status></div>
			<button class="btn btn-default" data-action="test">Testar QAPI</button>
			</section>
			<section class="frappe-card trivia-onboarding-step">
				<div class="trivia-onboarding-step-title"><span>3</span><div><h3>Importar questões</h3><p>As questões válidas entrarão no banco do LMS, prontas para serem usadas em quizzes.</p></div></div>
			<button class="btn btn-primary" data-action="sync">Sincronizar questões agora</button>
			</section>
		</div>`);

	const fields = {
		qapi_base_url: {
			fieldname: "qapi_base_url",
			fieldtype: "Data",
			label: __("URL base"),
			reqd: 1,
		},
		qapi_api_key: {
			fieldname: "qapi_api_key",
			fieldtype: "Password",
			label: __("Chave Q-Api-Key"),
			placeholder: __("Cole sua chave da QAPI"),
		},
		qapi_enabled: {
			fieldname: "qapi_enabled",
			fieldtype: "Check",
			label: __("Habilitar sincronização automática"),
		},
		qapi_sync_frequency: {
			fieldname: "qapi_sync_frequency",
			fieldtype: "Select",
			label: __("Frequência"),
			options: "Hourly\nEvery scheduler tick",
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
			main.find("[data-status]").text(
				`${message.configured ? __("Chave configurada") : __("Chave pendente")} · ${__("Última sincronização")}: ${message.last_sync || __("nunca")}`
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
				},
			})
			.then(({ message }) => {
				controls.qapi_api_key.set_value("");
				showStatus(__("Configuração salva."), "green");
				loadStatus();
			})
	);

	main.find('[data-action="test"]').on("click", () =>
		frappe.call("trivia_sync.api.qapi_status").then(({ message }) => {
			const text = message?.ok
				? `${__("Conexão OK")} · ${message.total ?? __("QAPI acessível")}`
				: message?.error || __("Falha ao testar QAPI");
			main.find("[data-status]").text(text);
			showStatus(text, message?.ok ? "green" : "red");
		})
	);

	main.find('[data-action="sync"]').on("click", () =>
		frappe.call("trivia_sync.api.enqueue_qapi_sync").then(() =>
			showStatus(__("Importação enfileirada."), "green")
		)
	);

	loadStatus();
};
