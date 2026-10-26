"""对话信号埋点（RL 前置：奖励的前提是数据）。

每轮对话结束后向 ``data/runtime/dialogue_signals/<companion_id>.jsonl``
追加一条记录，包含可自动判定的质量信号：

- **玩家否定反馈**（``negative_feedback``）：规则检测玩家指出角色记错 /
  编造 / 复读的文本模式（「你幻视了」「我没说过」「你是不是又……」）——
  实测日志里出现过的真实负面信号形态。
- **复读度**（``repetition_score``）：本条回复与同会话近期回复的字符
  二元组 Jaccard 相似度最大值——句式复读（「……不过……吧」反复出现）
  的量化代理。
- **话题延续**（``topic_continued``）：玩家本轮与上轮文本的主题重叠——
  engagement 的粗代理（玩家愿意接着聊 = 回应有效）。

外加当轮注入的印象主题（``injected_topics``）与情绪/手势/表情选择，供
日后把「记忆调度 / 表现选择」的手调超参换成学出来的策略（bandit/RL）。

T083 风格校验结果（``style_violations``）也落入本埋点，供运行期验收指标
统计。``None`` 表示该轮未走 LLM 路径（mock/fallback），空列表表示 LLM 路径
通过校验。

埋点是观测而非流程：任何写盘/检测故障一律静默吞掉（同 FR-011 纪律，
绝不因埋点阻塞对话主流程）。

v0.4 作用域请求的日志写入失败向外传播，由请求协调器记录未知提交结果。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.scoped.context import current_scope
from app.scoped.storage import (
    append_jsonl, signal_directory, signal_metadata, guarded_commit, unavailable,
)

# 玩家负面反馈模式（记错/编造/复读的玩家侧表述——实测日志出现过的形态）。
_NEGATIVE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"幻视",
        r"记[岔错混]",
        r"胡说",
        r"瞎说",
        r"胡编",
        r"编造",
        r"乱讲",
        r"说谎",
        r"没说过",
        r"没答应",
        r"我没说",
        r"不是这样",
        r"根本没有",
        r"你怎么知道",
        r"又模糊",
        r"又忘了",
        r"经常返回相同",
        r"重复的?话",
    )
)

# 复读判定阈值：字符二元组 Jaccard 超过该值视为句式复读（经验值）。
_REPETITION_FLAG_THRESHOLD = 0.6


def detect_negative_feedback(text: str) -> str | None:
    """玩家是否在指出角色记错/编造/复读；命中返回首个模式串。"""
    for pattern in _NEGATIVE_PATTERNS:
        if pattern.search(text):
            return pattern.pattern
    return None


def _char_bigrams(text: str) -> set[str]:
    normalized = re.sub(r"\s+", "", text)
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {normalized[i : i + 2] for i in range(len(normalized) - 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def repetition_score(reply: str, previous_replies: list[str]) -> float:
    """本条回复与近期回复的相似度最大值（0~1，越高越像复读）。"""
    reply_grams = _char_bigrams(reply)
    return max(
        (_jaccard(reply_grams, _char_bigrams(prev)) for prev in previous_replies),
        default=0.0,
    )


def topic_continued(current_text: str, previous_text: str | None) -> bool | None:
    """玩家是否延续同一话题（主题重叠或文本高度相似）。

    ``None`` 表示无上轮文本可比较（会话第一轮）。
    """
    if not previous_text:
        return None
    from app.services.memory.topics import extract_topics

    current_topics = set(extract_topics(current_text))
    previous_topics = set(extract_topics(previous_text))
    # 主题词长度不一（「钓鱼」vs「一起去钓鱼」），包含关系也算同一话题。
    if any(
        a == b or a in b or b in a for a in current_topics for b in previous_topics
    ):
        return True
    return _jaccard(_char_bigrams(current_text), _char_bigrams(previous_text)) >= 0.3


_DEFAULT_GAME_ID = "aesir"


@guarded_commit
def record_turn_signal(
    companion_id: str,
    session_id: str | None,
    *,
    player_text: str,
    reply_text: str,
    source: str,
    emotion_id: str,
    gesture_id: str,
    facial_expression_id: str,
    game_state: str,
    injected_topics: list[str] | None = None,
    previous_player_texts: list[str] = (),
    previous_reply_texts: list[str] = (),
    style_violations: list[str] | None = None,
    game_id: str = _DEFAULT_GAME_ID,
    memory_cited: bool | None = None,
    relationship_stage: str = "",
    latency_ms: int | None = None,
    sentiment: str | None = None,
    relationship_delta: int | None = None,
    relationship_reason: str | None = None,
    lore_lookup: dict | None = None,
    facts_rejected: int | None = None,
) -> None:
    """追加一条本轮对话信号记录（JSONL）；任何故障静默吞掉。

    ``previous_*`` 为本轮记录**之前**的会话历史（旧→新），供复读度与
    话题延续比较；调用方在写入会话记忆前采集。

    新增可选字段（T32 判定层列明的 N/A 项所需数据源，缺省不落盘）：
    - ``memory_cited``：本轮回复是否引用了具体记忆（SC-001 记忆引用正确率）；
    - ``relationship_stage``：本轮关系阶段机器名（SC-003 语气区分）；
    - ``latency_ms``：本轮服务端耗时毫秒（SC-011 时延统计，样本 ≥30）；
    - ``sentiment``：LLM 判定的玩家发言情感质量（warm/deep/cold/hurtful；
      FIX-13 新增，SC-004 防刷与关系驱动判定的数据源）；
    - ``relationship_delta``：本轮关系层实际增减（冷却/日上限吃掉为 0；
      FIX-13 新增，与 ``sentiment`` 配对落盘便于核对「判定 vs 实收」）；
    - ``relationship_reason``：关系层拦截原因（T38 / SC-004：scored /
      cooldown_blocked / daily_cap / no_signal / store_error……四种 delta=0
      从此可区分）；
    - ``lore_lookup``：本轮查证结果 ``{tool, found, reason_codes}``
      （T38 / SC-008；未索取查证的轮次为 None 不落盘）；
    - ``facts_rejected``：本轮被接地校验丢弃的事实条数（T38 / SC-008，
      LLM 倾向编造的直接证据；仅 >0 时落盘）。
    """
    try:
        signals = {
            "negative_feedback": detect_negative_feedback(player_text),
            "repetition_score": round(
                repetition_score(reply_text, list(previous_reply_texts)), 4
            ),
            "topic_continued": topic_continued(
                player_text, previous_player_texts[-1] if previous_player_texts else None
            ),
        }
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "companion_id": companion_id,
            "session_id": session_id,
            "game_state": game_state,
            "source": source,
            "player_text": player_text,
            "reply_text": reply_text,
            "emotion_id": emotion_id,
            "gesture_id": gesture_id,
            "facial_expression_id": facial_expression_id,
            "injected_topics": list(injected_topics or []),
            "signals": signals,
            "repetitive": signals["repetition_score"] >= _REPETITION_FLAG_THRESHOLD,
            "style_violations": style_violations,
        }
        # 可选埋点仅在显式传入时落盘（保持旧记录结构稳定，缺省字段缺失不报错）。
        if memory_cited is not None:
            record["memory_cited"] = memory_cited
        if relationship_stage:
            record["relationship_stage"] = relationship_stage
        if latency_ms is not None:
            record["latency_ms"] = latency_ms
        if sentiment is not None:
            record["sentiment"] = sentiment
        if relationship_delta is not None:
            record["relationship_delta"] = relationship_delta
        if relationship_reason:
            record["relationship_reason"] = relationship_reason
        if lore_lookup is not None:
            record["lore_lookup"] = lore_lookup
        if facts_rejected is not None:
            record["facts_rejected"] = facts_rejected
        root = signal_directory(get_settings().dialogue_signals_dir, game_id)
        record.update(signal_metadata())
        append_jsonl(root, f"{companion_id}.jsonl", json.dumps(record, ensure_ascii=False))
    except Exception as error:  # noqa: BLE001 - 埋点绝不阻塞对话主流程
        if current_scope():
            raise unavailable() from error
        pass
