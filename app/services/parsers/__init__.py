"""Pluggable command-parser backends (rule-based default, LLM slot)."""

from app.services.parsers.base import CommandParser
from app.services.parsers.rule import RuleCommandParser

__all__ = ["CommandParser", "RuleCommandParser"]