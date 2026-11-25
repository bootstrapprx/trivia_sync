"""Lightweight compatibility module; LMS Question is now the single question entity."""

from trivia_sync.integrations.lms_questions import OPTION_LETTERS, extract_lms_question_options

__all__ = ["OPTION_LETTERS", "extract_lms_question_options"]
