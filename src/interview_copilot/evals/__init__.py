"""Answer-quality evals: run a question set through the engine, judge it and write a report.

Entry point: :func:`interview_copilot.evals.runner.main` (``python -m interview_copilot eval``).
"""

from .judge import CRITERIA, TAGS
from .runner import keyword_check, main, parse_cases

__all__ = ["CRITERIA", "TAGS", "keyword_check", "main", "parse_cases"]
