import frappe


CONTEST_FIELDS = ["name", "public_slug", "titulo", "public_summary", "ano", "regiao", "estado"]


def _public_courses(contest_names):
	links = frappe.get_all(
		"Concurso Cargo",
		filters={"concurso": ["in", contest_names]},
		fields=["concurso", "lms_course"],
	)
	if not links:
		return {}
	course_names = list({link.get("lms_course") for link in links if link.get("lms_course")})
	if not course_names:
		return {}
	courses = frappe.get_all(
		"LMS Course",
		filters={"name": ["in", course_names], "published": 1},
		fields=["name", "title"],
	)
	titles = {course.get("name"): course.get("title") for course in courses}
	result = {}
	for link in links:
		if link.get("lms_course") in titles:
			result.setdefault(link.get("concurso"), []).append({"title": titles[link["lms_course"]]})
	return result


def _dto(contest, courses):
	return {
		"slug": contest.get("public_slug"),
		"title": contest.get("titulo"),
		"summary": contest.get("public_summary"),
		"year": contest.get("ano"),
		"region": contest.get("regiao"),
		"state": contest.get("estado"),
		"courses": courses,
	}


def list_public_contests():
	contests = frappe.get_all(
		"Concurso",
		filters={"publication_status": "Published", "published_at": ["<=", frappe.utils.now_datetime()]},
		fields=CONTEST_FIELDS,
		order_by="published_at desc",
	)
	if not contests:
		return []
	courses = _public_courses([contest.get("name") for contest in contests])
	return [_dto(contest, courses[contest["name"]]) for contest in contests if courses.get(contest["name"])]


def get_public_contest(slug):
	contests = frappe.get_all(
		"Concurso",
		filters={
			"public_slug": slug,
			"publication_status": "Published",
			"published_at": ["<=", frappe.utils.now_datetime()],
		},
		fields=CONTEST_FIELDS,
		page_length=1,
	)
	if not contests:
		frappe.throw("Concurso não encontrado.", frappe.DoesNotExistError)
	contest = contests[0]
	courses = _public_courses([contest.get("name")]).get(contest.get("name"))
	if not courses:
		frappe.throw("Concurso não encontrado.", frappe.DoesNotExistError)
	return _dto(contest, courses)


@frappe.whitelist(allow_guest=True)
def public_contest_catalog():
	return list_public_contests()


@frappe.whitelist(allow_guest=True)
def public_contest(slug):
	return get_public_contest(slug)
