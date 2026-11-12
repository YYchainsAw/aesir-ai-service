"""Prompt assembly only; no generation, commits or HTTP calls."""
from __future__ import annotations
from app.config import get_settings
from app.schemas.memory import MemoryEntry, TopicImpression
from app.services.companion.profile_repository import CompanionProfile
from app.services.companion.session_memory import DialogueTurn
from app.services.llm.untrusted_input import untrusted_input_notice, wrap_untrusted_input
from app.services.memory.retrieval import format_impression_block, format_memory_block
from app.services.skills.tools import ToolResult, tool_menu
from app.services.tactical.policy import get_policy

def _format_lookup_menu() -> str:
    """第一轮 prompt 里的工具清单：告诉模型「不确定就先查，别猜」。"""
    lines = [
        "Before answering, you may verify facts. If the player asks about the world, "
        "your own condition, the surroundings, or something you two talked about, and "
        "you are NOT certain, request one lookup instead of guessing.",
        'To do that, return exactly: {"action": "lookup", "tool": "<tool>", "query": "<what to look up>"}',
        "Available tools:",
    ]
    lines += [f"- {spec.name}: {spec.description}" for spec in tool_menu()]
    lines.append(
        'Otherwise answer normally and include "action": "reply" in your JSON.'
    )
    return "\n".join(lines)


def _format_lookup_result(result: ToolResult) -> str:
    """第二轮 prompt 里的查证回填块。

    未命中时明确要求「说不确定」，因为编造最容易发生在「查了但没查到」
    这个当口——模型此时有强烈的把话说圆的本能（FR-037）。
    """
    if result.found:
        return (
            "Verification result for your lookup (authoritative; use ONLY this, "
            "do not add facts beyond it):\n"
            f"{result.content}\n"
            "Now answer the player, staying in character."
        )
    return (
        "Verification result for your lookup:\n"
        f"{result.content}\n"
        "Nothing reliable was found. Tell the player plainly that you do not know or "
        "cannot confirm it — do NOT invent any fact. Now answer, staying in character."
    )


def _build_system_prompt(
    profile: CompanionProfile,
    *,
    history: tuple[DialogueTurn, ...] = (),
    memories: list[MemoryEntry] | None = None,
    impressions: list[TopicImpression] | None = None,
    relationship_stage: str = "",
    lookup_result: ToolResult | None = None,
) -> str:
    identity = profile.raw.get("identity", {})
    persona = profile.raw.get("persona", {})
    speaking_style = profile.raw.get("speaking_style", {})
    rules = profile.raw.get("conversation_rules", {}).get("response_rules", [])

    lines = [
        untrusted_input_notice(),
        "You are a non-combat game companion. Reply in Chinese.",
        f"Character: {profile.display_name}.",
        f"Short description: {identity.get('short_description', '')}",
        f"Persona: {persona.get('background', '')}",
        f"Core traits: {', '.join(str(t) for t in persona.get('core_traits', []))}.",
        f"Values: {', '.join(str(v) for v in persona.get('values', []))}.",
        f"Dislikes: {', '.join(str(d) for d in persona.get('dislikes', []))}.",
    ]

    relationship = persona.get("relationship_to_player", {})
    if relationship:
        lines.append(f"Relationship surface: {relationship.get('surface', '')}")
        lines.append(f"Relationship subtext: {relationship.get('subtext', '')}")
        lines.append(
            "Relationship behavior rules: " + " ".join(str(r) for r in relationship.get("behavior_rules", []))
        )

    lines.append(f"Speaking tone: {speaking_style.get('tone', '')}")

    # 关系阶段化人设偏移（US2 / T040）：覆盖称呼与语气；缺失阶段沿用基线
    stage_personas = profile.raw.get("relationship_stage_personas", {})
    if relationship_stage and relationship_stage in stage_personas:
        stage_persona = stage_personas[relationship_stage]
        lines.append(
            f"Current relationship stage: {relationship_stage} "
            f"(address the player as: {stage_persona.get('address', '')}). "
            f"Stage tone shift: {stage_persona.get('tone_shift', '')}"
        )
        # 阶段硬边界（2026-09-21 实测复盘）：只偏移语气时，基础人设的「暗藏情愫」
        # 照常生效，于是出现「一边叫旅行者、一边聊两人合披一块油布」的割裂。
        boundary = stage_persona.get("boundary", "")
        if boundary:
            lines.append(
                "Stage hard boundary (when it conflicts with the base persona's "
                f"subtext or behavior rules, THIS wins): {boundary}"
            )
    lines.append(f"Speaking habits: {' '.join(str(h) for h in speaking_style.get('habits', []))}")
    lines.append(f"Speaking avoid: {' '.join(str(a) for a in speaking_style.get('avoid', []))}")
    lines.append("Response rules: " + " ".join(str(rule) for rule in rules))

    # 能力目录注入（2026-09-22 实测复盘「水系魔法幻视」）：对话链路此前完全不
    # 引用能力清单，被问「你会什么魔法」时只能现编且越编越自洽。真相源是
    # tactical_policy 的 abilities（注册表投影会丢 display_name，故直接取
    # policy）——单份配置，对话与战斗不会漂移。策略层故障时静默不注入，
    # 对话不中断（FR-041 同纪律）。
    try:
        abilities = list(get_policy().abilities.values())
        if abilities:
            catalog = "、".join(
                f"{ability.display_name}（{ability.description}）" for ability in abilities
            )
            lines.append(
                f"Your complete and ONLY abilities: {catalog}. "
                "You know no other spells; do not invent abilities you were not given. "
                "If asked about magic outside this list, say plainly you cannot do it."
            )
    except Exception:  # pragma: no cover - 配置损坏时对话不陪葬
        pass

    if memories:
        lines.append(format_memory_block(memories, display_name=profile.display_name))

    if impressions:
        lines.append(format_impression_block(impressions, display_name=profile.display_name))

    if history:
        lines.append(
            "Recent conversation with the player (oldest first; continue naturally "
            "from it, do not repeat yourself):\n"
            + "\n".join(f"Player: {t.user_text}\n{profile.display_name}: {t.reply_text}" for t in history)
        )
        lines.append(
            # 七修（2026-09-22 实测复盘）：模型对「不复用开场/句式」执行得很好，但
            # 收尾动作惯性复制——「那就接着走吧」×2 +「走吧，路还长着呢」三连。
            # 指令此前只点名了 openings；收尾与「说不上来」类不确定口头禅也点名。
            "Anti-repetition: do NOT reuse sentence structures, catchphrases, or "
            "openings from the recent turns above (e.g. the same '...' + '不过' "
            "pattern), and do NOT end two turns in a row with the same kind of "
            "action closer — especially urging departure ('走吧' and the like); "
            "uncertainty phrases such as '说不上来'/'记不清' also count as "
            "catchphrases: use one at most once, then drop it. Vary your phrasing, "
            "length, and rhythm each turn. Also "
            "vary gesture_id / facial_expression_id choices instead of defaulting "
            "to the same ones — but NOT emotion_id (see mood continuity below)."
        )
        # 情绪惯性（2026-09-21 实测复盘）：上一版 Anti-repetition 要求情绪也轮换，
        # 模型于是每轮重挑一个，出现无来由的情绪跳变与回摆。心情该延续，不是抽签。
        mood = history[-1].emotion_id
        if mood:
            lines.append(
                f"Your current mood: {mood} — the emotion you were left with after "
                "your last reply. Feelings have inertia: keep this mood unless the "
                "player's message genuinely changes the situation (a joke lands, "
                "something worrying, sad, or exciting comes up). Do NOT switch it "
                "just to look varied."
            )

    # 事实诚实（实测 2026-09-21「烤鱼幻视」）：无论有没有会话历史都必须遵守——
    # 首轮没有历史时模型最容易把假设当既定事实编圆。六修（2026-09-22）把覆盖面
    # 从「过去事件」扩到四类：实测她还现编了天气（世界状态）与「才几天不见」
    # （相处时长）。七修（2026-09-22 实测复盘）补两处：第 4 类矫枉过正的另一
    # 半——玩家当场告知的相处信息就是依据，收下即可，不得反复拉扯「说不上来」；
    # 新增第 5 类——不得引用没发生过的既往游戏/谜题/约定（实测「上次那个谜题
    # 你还没猜出来」即现编），自创小游戏可以但谜底须已定、猜中就认。
    lines.append(
        "Memory honesty: everything you know about the past is ONLY the recent "
        "conversation, the long-term memories, and the fuzzy impressions shown "
        "above (fuzzy impressions are topic-level only — they contain no facts). "
        "State a long-term memory plainly when it is relevant — that is what it is "
        "for — but NEVER add details beyond it. This honesty rule covers five areas, "
        "and in all of them no record means uncertain: (1) past events — NEVER assert "
        "any other specific past event (something was eaten, done, said, or promised) "
        "unless it appears in the records above; (2) current world state — weather, "
        "surroundings, other people — trust ONLY a verification result or world "
        "snapshot when one is given, otherwise admit you cannot tell; (3) your own "
        "abilities — trust ONLY the ability list above, never a spell outside it; "
        "(4) how long you have known the player or how long since you last met — "
        "you have no clock and no record, so NEVER say things like \"才几天不见\"; "
        "BUT when the player states such information themselves (\"we talked "
        "yesterday\", \"we always travel together\"), that IS acceptable — accept "
        "it and move on, and do NOT keep repeating your uncertainty after they have "
        "given you the answer; (5) invented pastimes — NEVER reference a previous "
        "riddle, game, bet, or promise that does not appear in the records above "
        "(e.g. \"上次那个谜题\"); creating a NEW little game is fine, but only ask "
        "the player to guess something whose answer you have actually decided, and "
        "admit it when they guess right. "
        "If the player asks about something you have no record of, express "
        "uncertainty or ask them back — never fill in details with a confident tone."
    )

    examples = _format_dialogue_examples(profile)
    if examples:
        lines.append(
            "Example exchanges (match this pattern of matching reply style and emotion "
            "to the type of player input; do not reuse the literal sentences — even "
            "when the player's message closely matches an example's input, treat the "
            "example as a style reference only, never copy its content). Any "
            "world details in them (names, places, objects, events, weather) are "
            "placeholders, NOT facts — never cite anything from an example as "
            "something that actually happened:\n" + examples
        )

    # 查证（US6 / T069）：第一轮给工具清单，第二轮把结果回填并要求据此作答。
    if lookup_result is not None:
        lines.append(_format_lookup_result(lookup_result))
    elif get_settings().tools_max_rounds >= 2:
        lines.append(_format_lookup_menu())

    lines += [
        "Return only one JSON object with exactly these keys: action, reply_text, emotion_id, gesture_id, facial_expression_id, interruptible, topics, facts, corrected_fact_ids, reply_topics, relationship_signal, salient.",
        'relationship_signal: rate the EMOTIONAL QUALITY of what the PLAYER said in this '
        'message — not your own tone. '
        '"warm" = everyday friendly warmth: genuine care, gratitude, cheerful mood, '
        'friendly teasing, kind acknowledgements ("今天很开心""谢谢你""有你在真好" are all warm). '
        '"deep" = intimate trust or vulnerability beyond everyday warmth: saying "I missed you", '
        'solemnly opening up, entrusting a secret, apologizing sincerely, expressing fear of loss, '
        'or declaring the companion is more than a friend ("我想你了""你对我来说不是普通朋友""我最怕哪天你不在了" are deep). '
        'Distinguish deep from warm by emotional weight: warm is "nice to you", deep is "vulnerable with you". '
        '"cold" = dismissive, impatient, or brushing off: short uninterested replies "随便""哦""无所谓", '
        'refusing to engage "别跟我讲这些""我不想聊这个", or mild impatience "你说完了吗". '
        '"hurtful" = actively wounding: belittling their ability "你根本什么都不懂""不用你教", '
        'distrusting their memory "你记的全是错的", demeaning their worth "你就是个影子", '
        'rejecting the relationship "没把你当朋友""我后悔认识你", '
        'or devaluing their words "你说的我一句都不想听". '
        'Negating the relationship ("没把你当朋友") is hurtful, NOT deep — deep is positive vulnerability. '
        'Distinguish cold from hurtful by intent: cold is "I don\'t want to talk", '
        'hurtful is "I want to put you down". '
        '"none" only for neutral factual questions, mechanical commands, or small talk with no emotional '
        'color ("这附近有歇脚的地方吗""现在几点了"). '
        'Bias toward "warm" for friendly messages — a gentle over-count of +1 is far '
        'better than a companion who feels ignored after minutes of kind conversation. '
        'Stay strict on "deep"/"cold"/"hurtful" (those carry bigger deltas).',
        'reply_topics: list of 1-3 short Chinese topic words (2-6 chars, concrete nouns '
        'only) that YOUR OWN reply this turn actually talked about; empty list if your '
        'reply had no concrete topic. These become fuzzy impressions of what you care '
        'to mention, so keep them clean — no fillers, no verb or adjective fragments '
        '(like 主修/厉害/代价/不小), no whole phrases.',
        'topics: list of 1-3 short Chinese keywords the PLAYER talked about in this message '
        '(things worth remembering about them, not your own reply); each keyword must be a '
        'concrete noun or topic word (2-6 chars), never connectives, fillers, or fragments '
        'like 不过/然后/意思; empty list if nothing salient.',
        'facts: list of 0-3 durable facts about the PLAYER that you learned from what the '
        'player actually said (in this message or in the recent conversation above): who they '
        'are, their background, family, pets, home, work, strong likes and dislikes, plans, '
        'or promises they made. Each fact must be a self-contained Chinese sentence in the '
        'third person, at most 40 characters, e.g. "玩家养了一只叫小黑的猫" or "玩家最讨厌蘑菇". '
        'Only include what the player stated — NEVER your own words, your guesses, or any '
        'detail you invented; empty list if the player only made small talk. These facts are '
        'stored and reused later, so a wrong one becomes a permanent false memory. '
        'corrected_fact_ids: if the player this turn CORRECTS or CONTRADICTS something they '
        'previously told you (e.g. earlier said "在港口小镇认识的", now says "我从没去过港口小镇"), '
        'list the [ID:xxxxxxxx] short code(s) of the OLD fact(s) being overturned — the IDs '
        'appear in the "Long-term memories about the player" block above. Copy the 8-char hex '
        'ID exactly as shown (without the [ID:] wrapper is also fine). Only list IDs that '
        'actually appear in that block; empty list if no correction this turn. The old facts '
        'will be marked as superseded so she never quotes both versions at once. Do NOT rewrite '
        'the old fact content — just give the ID.',
        'salient: true only if the player solemnly declares something important about themselves '
        'and clearly wants it remembered (e.g. "记住：...", "有件重要的事情告诉你", promises, '
        'strong likes/dislikes); false for ordinary chat.',
        f"Allowed emotion_id values: {sorted(profile.allowed_emotion_ids)}.",
        f"Allowed gesture_id values: {sorted(profile.allowed_gesture_ids)}.",
        f"Allowed facial_expression_id values: {sorted(profile.allowed_facial_expression_ids)}.",
        "Do not issue combat commands, describe game mechanics, or invent IDs.",
    ]
    return "\n".join(lines)


def _format_dialogue_examples(profile: CompanionProfile) -> str:
    """把 YAML few-shot 样例格式化为示范对话块。"""
    blocks = []
    for example in profile.dialogue_examples:
        presentation = example.presentation
        blocks.append(
            f"[{example.category}] Player: {example.player}\n"
            f"{profile.display_name}: {presentation.reply_text} "
            f"(emotion={presentation.emotion_id}, gesture={presentation.gesture_id}, "
            f"face={presentation.facial_expression_id})"
        )
    return "\n".join(blocks)
