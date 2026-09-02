"""可插拔的命令解析后端（默认规则解析，另有 LLM 槽位）。"""

from app.services.parsers.base import CommandParser
from app.services.parsers.rule import RuleCommandParser

__all__ = ["CommandParser", "RuleCommandParser"]