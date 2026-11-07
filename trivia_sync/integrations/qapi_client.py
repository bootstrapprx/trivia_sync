import requests
import frappe

BASE_DEFAULT = "https://qapi.otunac.com/api"
MCP_DEFAULT = "https://qapi.otunac.com/mcp"
QAPI_METHOD_COSTS = {"provas": 200, "prova": 200}


class QAPIError(RuntimeError):
	pass


class QAPIBudgetError(QAPIError):
	pass


class QAPIClient:
	def __init__(self, settings_doc=None, max_requests=None):
		self.settings = settings_doc or frappe.get_single("Trivia Sync Settings")
		configured = int(getattr(self.settings, "qapi_max_requests_per_run", 0) or 0)
		reserve = max(1, int(getattr(self.settings, "qapi_min_credit_reserve", 1) or 1))
		self.max_requests = max(0, configured - reserve) if max_requests is None else max(0, int(max_requests))
		self.requests_made = 0
		self.credits_used = 0
		self.base_url = (self.settings.qapi_base_url or BASE_DEFAULT).rstrip("/")
		self.mcp_url = (self.settings.mcp_base_url or MCP_DEFAULT).rstrip("/")
		self.api_key = self.settings.get_password("qapi_api_key") if self.settings.qapi_api_key else ""
		if not self.api_key:
			raise QAPIError("Configure the Q-Api-Key before syncing.")
		self.timeout = max(10, int(self.settings.qapi_timeout or 60))
		self.session = requests.Session()
		self.session.headers.update({"Accept": "application/json", "Q-Api-Key": self.api_key})

	def _reserve_request(self, cost=1):
		cost = max(1, int(cost))
		if self.credits_used + cost > self.max_requests:
			raise QAPIBudgetError("Local QAPI credit limit reached; no further request was sent.")
		self.requests_made += 1
		self.credits_used += cost

	def get(self, path, params=None, cost=1):
		self._reserve_request(cost)
		response = self.session.get(
			f"{self.base_url}/{path.lstrip('/')}", params=params or {}, timeout=self.timeout
		)
		try:
			response.raise_for_status()
		except requests.HTTPError as exc:
			raise QAPIError(f"QAPI {response.status_code}: {response.text[:500]}") from exc
		return response.json()

	def post(self, path, payload=None, cost=1):
		self._reserve_request(cost)
		response = self.session.post(
			f"{self.base_url}/{path.lstrip('/')}", json=payload or {}, timeout=self.timeout
		)
		try:
			response.raise_for_status()
		except requests.HTTPError as exc:
			raise QAPIError(f"QAPI {response.status_code}: {response.text[:500]}") from exc
		return response.json()

	def mcp_call(self, tool, arguments=None, cost=1):
		self._reserve_request(cost)
		response = requests.post(
			self.mcp_url,
			headers={
				"Accept": "application/json",
				"Content-Type": "application/json",
				"x-api-key": self.api_key,
			},
			json={
				"jsonrpc": "2.0",
				"id": 1,
				"method": "tools/call",
				"params": {"name": tool, "arguments": arguments or {}},
			},
			timeout=self.timeout,
		)
		response.raise_for_status()
		payload = response.json()
		if payload.get("error"):
			raise QAPIError(str(payload["error"]))
		return payload.get("result", payload)

	def call(self, path, params=None, tool=None, cost=1):
		if getattr(self.settings, "mcp_enabled", 0) and tool:
			return self.mcp_call(tool, params, cost=cost)
		return self.get(path, params, cost=cost)

	def page(self, path, params=None, tool=None, cost=1):
		params = dict(params or {})
		params["page"] = max(1, int(params.get("page", 1)))
		params["size"] = min(10, max(1, int(params.get("size", 10))))
		return self.call(path, params, tool, cost=cost)

	def questoes(self, **params):
		return self.page("questoes", params, "get_questoes")

	def texto(self, codigo):
		return self.call(f"textos/{codigo}", {"codigo": codigo}, tool="get_texto")

	def bancas(self, **params):
		return self.page("bancas", params, "get_bancas")

	def orgaos(self, **params):
		return self.page("orgaos", params, "get_orgaos")

	def cargos(self, **params):
		return self.page("cargos", params, "get_cargos")

	def materias(self, **params):
		return self.page("materias", params, "get_materias")

	def assuntos(self, materia=None, **params):
		if materia:
			params["materia"] = materia
		return self.page("assuntos", params, "get_assuntos")

	def provas(self, **params):
		return self.page("provas", params, "get_provas", cost=QAPI_METHOD_COSTS["provas"])

	def prova(self, rid):
		return self.call(f"provas/{rid}", {"id": rid}, tool="get_prova_por_id", cost=QAPI_METHOD_COSTS["prova"])

	def concursos(self, **params):
		return self.page("concursos", params, "get_concursos")

	def concurso(self, rid):
		return self.call(f"concursos/{rid}", {"id": rid}, tool="get_concurso_por_id")

	def status_concurso(self):
		return self.call("concursos/status", tool="get_status_concurso")

	def disciplinas(self, **params):
		return self.page("disciplinas", params, "get_disciplinas")

	def disciplina(self, rid):
		return self.call(f"disciplinas/{rid}", {"id": rid}, tool="get_disciplina_por_id")

	def conteudos(self, **params):
		return self.page("conteudos", params, "get_conteudos")

	def conteudos_arvore(self, **params):
		return self.call("conteudos/arvore", params, "get_conteudos_arvore")

	def flashcards(self, **params):
		return self.page("flashcards", params, "get_flashcards")

	def criar_flashcard(self, payload):
		if getattr(self.settings, "mcp_enabled", 0):
			return self.mcp_call("criar_flashcard", payload)
		return self.post("flashcards", payload)
