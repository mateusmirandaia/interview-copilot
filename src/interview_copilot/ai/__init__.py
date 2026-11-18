"""AI layer: prompts, output parsing and the streaming engine."""

from .engine import CopilotEngine, EngineStats, Source, Turn, extract_sources, merge_sources, search_error
from .parsing import Suggestion, parse_suggestion

__all__ = [
    "CopilotEngine",
    "EngineStats",
    "Source",
    "Suggestion",
    "Turn",
    "extract_sources",
    "merge_sources",
    "parse_suggestion",
    "search_error",
]
