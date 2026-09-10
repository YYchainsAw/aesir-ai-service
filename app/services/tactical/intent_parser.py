"""文本 → ``TacticalIntent`` 的规则解析（组合端点 ``/v1/tactical/command`` 前半段）。

与 v0.1 规则解析器同一风格：确定性关键词匹配、更具体者优先、输出可验证的
白名单意图。区别在于本层只产出**语义意图**（玩家想做什么），具体技能由
resolver 结合战斗快照决定——这是 v0.2「指令理解与上下文战术落地」的分层原则。

多意图冲突按意图优先级降序判序（撤退 > 等眩晕爆发 > 治疗 > 保护 > 爆发 >
集火 > 跟随），保证「快撤退保命」不会误判成治疗/爆发。
"""

from app.schemas.tactical_intent import TacticalIntent

_WAKE_WORDS = ("艾莉", "艾琳", "alice", "eirin")

_BURST_WORDS = ("爆裂", "大招", "爆发", "开大", "explosion", "burst")
_STUN_WORDS = ("眩晕", "晕了", "出破绽", "破绽", "stun")


def _normalize(text: str) -> str:
    return (
        text.strip()
        .lower()
        .replace("，", ",")
        .replace("。", "")
        .replace(" ", "")
    )


def _has_any(text: str, *keywords: str) -> bool:
    return any(keyword in text for keyword in keywords)


def _intent(
    intent_id: str,
    target_id: str,
    timing: str = "immediate",
    strength: str = "unspecified",
    conservation: str = "normal",
    confidence: float = 0.9,
) -> TacticalIntent:
    return TacticalIntent(
        intent_id=intent_id,  # type: ignore[arg-type]
        target_id=target_id,
        timing=timing,  # type: ignore[arg-type]
        preferences={
            "strength": strength,  # type: ignore[dict-item]
            "resource_conservation": conservation,  # type: ignore[dict-item]
        },
        parse_confidence=confidence,
    )


def parse_text_to_intent(text: str) -> TacticalIntent | None:
    """识别文本中的语义意图；无法识别时返回 ``None``（调用方回复澄清）。

    wake 词（艾莉/艾琳/alice/eirin）与 v0.1 规则解析器保持一致，
    旧名 eirin 仅作向后兼容。
    """
    t = _normalize(text)
    if not t or not _has_any(t, *_WAKE_WORDS):
        return None

    # 1. 撤退（最高优先级）：别把「保命」误判成护盾/治疗。
    if _has_any(t, "撤退", "撤离", "先撤", "撤了", "保命", "逃跑", "retreat"):
        return _intent("retreat_and_survive", "party.player")

    # 2. 等眩晕爆发：stun 词 + burst 词同时出现（如「等它晕了放大招」）。
    if _has_any(t, *_STUN_WORDS) and _has_any(t, *_BURST_WORDS):
        return _intent("prepare_burst_on_stun", "encounter.primary_hostile",
                       timing="on_condition")

    # 3. 治疗：口语「奶我」「回一下血」都算。
    if _has_any(t, "奶", "回血", "回一下血", "治疗", "加血", "拉我", "heal"):
        strength = "major" if _has_any(t, "强效", "大", "满血") else (
            "minor" if _has_any(t, "小", "快速", "一口") else "unspecified"
        )
        return _intent("support_heal_player", "party.player", strength=strength)

    # 4. 保护：护盾/保我。
    if _has_any(t, "护盾", "开盾", "保我", "保护", "shield", "protect"):
        return _intent("support_protect_player", "party.player")

    # 5. 立即爆发。
    if _has_any(t, *_BURST_WORDS):
        return _intent("burst_boss", "encounter.primary_hostile",
                       conservation="aggressive")

    # 6. 集火。
    if _has_any(t, "集火", "全力输出", "集中", "focus"):
        return _intent("focus_fire_boss", "encounter.primary_hostile")

    # 7. 跟随。
    if _has_any(t, "跟随", "跟着", "跟上", "跟我", "follow"):
        return _intent("follow_player", "party.player")

    return None
