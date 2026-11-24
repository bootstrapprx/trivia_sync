from frappe.model.document import Document

from trivia_sync.integrations.learning_content import validate_material_recipe


class TriviaLessonRecipe(Document):
	def validate(self):
		validate_material_recipe(self)
