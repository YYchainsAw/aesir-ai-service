"""Aesir AI 服务的运行时配置。

若项目根目录存在 ``.env``，会在 import 时自动加载（依赖 ``python-dotenv``）。
所有配置项都有安全默认值，因此即使没有 ``.env`` 也能直接运行。
"""

import os

from dotenv import load_dotenv

load_dotenv()


def get_parser_backend() -> str:
    """返回当前生效的命令解析后端。

    每次调用时读取（而非在 import 时读取），方便在运行时切换，也便于测试时
    覆盖环境变量。取值：``rule``（默认）或 ``llm``。
    """
    return os.environ.get("AESIR_PARSER_BACKEND", "rule")