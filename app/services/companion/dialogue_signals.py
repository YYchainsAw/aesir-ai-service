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
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings

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
) -> None:
    """追加一条本轮对话信号记录（JSONL）；任何故障静默吞掉。

    ``previous_*`` 为本轮记录**之前**的会话历史（旧→新），供复读度与
    话题延续比较；调用方在写入会话记忆前采集。
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
        root = Path(get_settings().dialogue_signals_dir) / game_id
        root.mkdir(parents=True, exist_ok=True)
        with (root / f"{companion_id}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - 埋点绝不阻塞对话主流程
        pass
