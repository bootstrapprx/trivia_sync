from typing import Protocol

from trivia_sync.integrations.qapi_client import QAPIClient, QAPI_METHOD_COSTS


class SourceAdapter(Protocol):
	source_type: str

	def request_cost(self, operation: str) -> int: ...

	def is_available(self) -> bool: ...

	def fetch_questions(self, filters=None, page=1, size=10): ...


class QAPIAdapter:
	source_type = "QAPI"

	def __init__(self, settings, max_requests):
		self.client = QAPIClient(settings, max_requests=max_requests)

	def is_available(self):
		return bool(self.client.api_key) and self.client.max_requests > 0

	def request_cost(self, operation):
		return QAPI_METHOD_COSTS.get(operation, 1)

	def fetch_questions(self, filters=None, page=1, size=10):
		return self.client.questoes(page=page, size=size, **(filters or {}))

	def fetch_resource(self, method, page=1, size=10, filters=None):
		return getattr(self.client, method)(page=page, size=size, **(filters or {}))

	def fetch_text(self, source_id):
		return self.client.texto(source_id)

	def fetch_syllabus_tree(self, filters=None):
		return self.client.conteudos_arvore(**(filters or {}))

	@property
	def requests_made(self):
		return self.client.requests_made

	@property
	def credits_used(self):
		return self.client.credits_used
