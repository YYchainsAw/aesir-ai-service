"""Aesir AI 服务的运行时配置。"""

import os


def get_parser_backend() -> str:
    """返回当前生效的命令解析后端。

    每次调用时读取（而非在 import 时读取），方便在运行时切换，也便于测试时
    覆盖环境变量。取值：``rule``（默认）或 ``llm``。
    """
    return os.environ.get("AESIR_PARSER_BACKEND", "rule")