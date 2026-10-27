"""few-shot 示例与 Memory-honesty 规则的机制性一致性守卫。

历史教训（examples.yaml 注释里的五修/六修/七修）：few-shot 的权重会压过
prompt 规则文字——一旦示例里出现「无据事实」，模型就把它当可照抄的事实。
此前只有 `test_examples_carry_no_unanswerable_riddle_or_time_assertion` 硬编码
守住了「口袋」「才认识几天」两个具体词。本测试把黑名单升级为机制性扫描：
所有已注册人格包的示例回复一旦命中「无据事实信号」即 fail，不依赖人工
逐个复盘新示例时记住加词表。

信号分四类（每类都有对应事故出处）：
- 时长断言：「才几天/认识多久/上次见面距今」——无时钟的角色不该断言相处时长
- 无据谜题：「猜猜/上次那个谜题」——没定义谜底的题会逼模型现编
- 无据天气/地名：「今天要下雨/我们在 X 地」——世界状态只信任查证回填
- 过往具体事件：「上次我们一起/那天我答应你」——记录里没有的事件不得声称
"""
from pathlib import Path

import pytest
import yaml

from app.services.companion.profile_repository import get_registered_profile

# 无据事实信号（小写子串匹配 reply_text）。新增词时注释其来源事故。
BARE_TIME_CLAIMS = (
    "才几天", "才认识", "认识多久", "认识这么久", "上次见面", "多久没见",
)
UNANSWERABLE_RIDDLES = (
    "猜猜", "猜一猜", "你猜", "上次那个谜题", "上次那个谜",
)
UNVERIFIED_WORLD = (
    "要下雨", "要下雪", "今天是个好天", "我记得这个地方", "我们现在在",
)
UNRECORDED_PAST = (
    "上次我们一起", "那天我答应", "我们以前约定", "上次答应过",
)

ALL_SIGNALS = {
    "time_claim": BARE_TIME_CLAIMS,
    "unanswerable_riddle": UNANSWERABLE_RIDDLES,
    "unverified_world": UNVERIFIED_WORLD,
    "unrecorded_past": UNRECORDED_PAST,
}


def _all_example_files():
    root = Path("data/personas")
    return sorted(root.glob("*/companion.*/examples.yaml"))


@pytest.mark.parametrize("example_file", _all_example_files())
def test_examples_carry_no_unverifiable_factual_claims(example_file):
    doc = yaml.safe_load(example_file.read_text(encoding="utf-8")) or {}
    hits = []
    for example in doc.get("dialogue_examples", []):
        reply = (example.get("reply_text") or "").lower()
        for signal_kind, phrases in ALL_SIGNALS.items():
            for phrase in phrases:
                if phrase.lower() in reply:
                    hits.append(f"{example_file.name} [{example.get('category')}] "
                                f"hit {signal_kind}: {phrase!r} in {example.get('reply_text')!r}")
    assert not hits, "few-shot 示例出现无据事实信号（会压过 honesty 规则）：\n" + "\n".join(hits)


@pytest.mark.parametrize("example_file", _all_example_files())
def test_examples_reference_only_whitelisted_emotion_gesture_face(example_file):
    """示例表现 ID 必须在对应人格包的 presentation 白名单内。

    demo-vn 包（companion.narrator）不注册进 profile_repository，无法取白名单，
    对它只跑事实信号扫描；已注册角色（alice/bruno）才校验表现 ID。
    """
    companion_id = example_file.parts[-2]
    try:
        profile = get_registered_profile(companion_id)
    except Exception:
        pytest.skip(f"{companion_id} 未注册，无白名单可校验")
    allowed = {
        "emotion_id": set(profile.allowed_emotion_ids),
        "gesture_id": set(profile.allowed_gesture_ids),
        "facial_expression_id": set(profile.allowed_facial_expression_ids),
    }
    doc = yaml.safe_load(example_file.read_text(encoding="utf-8")) or {}
    bad = []
    for example in doc.get("dialogue_examples", []):
        for field, whitelist in allowed.items():
            value = example.get(field)
            if value is not None and value not in whitelist:
                bad.append(f"{example_file.name} [{example.get('category')}] {field}={value!r} 不在 {sorted(whitelist)}")
    assert not bad, "few-shot 表现 ID 不在白名单：\n" + "\n".join(bad)
