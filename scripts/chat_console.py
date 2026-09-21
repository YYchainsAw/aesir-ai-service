"""终端对话 REPL（方案 A）：start.bat 启动服务后直接与 NPC 对话，用于质量检查。

不依赖 UE：httpx 直连本地服务，POST /v1/companion/chat/stream（SSE 流式）固定
session_id，回复按增量打字机式输出，meta 帧显示来源（mock/llm/fallback）与
表现 ID，方便核对角色人设是否合格。--no-stream 回退到非流式 /chat。

用法：
    .venv/Scripts/python -m scripts.chat_console                     # 默认 127.0.0.1:8000
    .venv/Scripts/python -m scripts.chat_console --port 8001
    .venv/Scripts/python -m scripts.chat_console --companion companion.alice
    .venv/Scripts/python -m scripts.chat_console --no-stream

内置命令：
    /help                     命令列表
    /memory                   查看该角色三级长期记忆（GET /v1/console/memory）
    /reset                    清空会话 + 长期记忆（POST /v1/console/memory/reset）
    /scene exploration|conversation   切换对话场景状态（默认 conversation）
    /quit | /exit             退出
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid

import httpx

DEFAULT_COMPANION = "companion.alice"
_WAIT_TIMEOUT_SECONDS = 60.0
_TYPEWRITER_STEP_SECONDS = 0.02  # 每个 delta 间的步进停顿，让打字机节奏可读


def _utf8_stdio() -> None:
    """Windows 终端/管道默认 GBK：统一切到 UTF-8，避免中文乱码与代理字符。"""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if stream.encoding and stream.encoding.lower() not in ("utf-8", "utf8"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _wait_for_service(client: httpx.Client) -> bool:
    """轮询 /health 直到服务就绪（服务可能仍在启动中）。"""
    deadline = time.monotonic() + _WAIT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            if client.get("/health", timeout=2.0).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


def _print_reply(reply: dict) -> None:
    source = reply.get("source", "?")
    print(f"\n艾莉：{reply['reply_text']}")
    print(
        f"  [source={source} | emotion={reply['emotion_id']}"
        f" | gesture={reply['gesture_id']}"
        f" | face={reply['facial_expression_id']}]"
    )


def _print_meta(reply: dict) -> None:
    """流式 meta 帧的信息行（正文已由 delta 打字机输出，不重复打印）。"""
    source = reply.get("source", "?")
    print(
        f"\n  [source={source} | emotion={reply['emotion_id']}"
        f" | gesture={reply['gesture_id']}"
        f" | face={reply['facial_expression_id']}]"
    )


def _send_streaming(client: httpx.Client, payload: dict) -> None:
    """SSE 流式对话：delta 增量打字机输出，meta 打印信息行。"""
    with client.stream("POST", "/v1/companion/chat/stream", json=payload) as response:
        if response.status_code != 200:
            print(f"[错误] HTTP {response.status_code}：{response.read().decode('utf-8', 'replace')}")
            return
        event_kind = ""
        for line in response.iter_lines():
            if line.startswith("event:"):
                event_kind = line[len("event:"):].strip()
                continue
            if not line.startswith("data:"):
                continue
            data = json.loads(line[len("data:"):].strip())
            if event_kind == "delta":
                print(data["text"], end="", flush=True)
                time.sleep(_TYPEWRITER_STEP_SECONDS)
            elif event_kind == "meta":
                _print_meta(data)
            elif event_kind == "error":
                print(f"\n[流中断] {data.get('detail', '')}")


def _show_memory(client: httpx.Client, companion_id: str) -> None:
    response = client.get("/v1/console/memory", params={"companion_id": companion_id})
    if response.status_code != 200:
        print(f"[错误] 查看记忆失败：HTTP {response.status_code} {response.text}")
        return
    data = response.json()
    print(f"\n=== 长期记忆（{data['counts']}）===")
    for tier, label in (("archive", "档案"), ("summaries", "摘要"), ("short_term", "短期")):
        for entry in data[tier]:
            print(f"  [{label}/{entry['importance']}] {entry['content']}")
    if not any(data[tier] for tier in ("archive", "summaries", "short_term")):
        print("  （空）")
    # 模糊印象：按权重取前 10，标注谁提的（玩家 / 她自己）。
    impressions = sorted(
        data.get("impressions", []), key=lambda i: i["weight"], reverse=True
    )[:10]
    if impressions:
        print("  --- 模糊印象（按权重前 10）---")
        for i in impressions:
            origin = "玩家" if i.get("origin", "player") == "player" else "她自己"
            print(
                f"  [印象] {i['topic']}（{origin}提过 {i['mention_count']} 次，"
                f"权重 {i['weight']:.2f}）"
            )


def _reset(client: httpx.Client, companion_id: str) -> None:
    response = client.post("/v1/console/memory/reset", json={"companion_id": companion_id})
    if response.status_code == 200:
        print(f"\n[已重置] reset={response.json()['reset']}（false 表示长期记忆写入故障，仅清了会话）")
    else:
        print(f"\n[错误] 重置失败：HTTP {response.status_code} {response.text}")


def main(base_url: str, companion_id: str, *, no_stream: bool = False) -> int:
    _utf8_stdio()
    session_id = f"console-{uuid.uuid4().hex[:8]}"
    game_state = "conversation"

    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        if not _wait_for_service(client):
            print(f"[错误] {base_url}/health 在 {_WAIT_TIMEOUT_SECONDS:.0f}s 内未就绪，请确认服务已启动。")
            return 1

        try:
            state = client.get(
                "/v1/console/state", params={"companion_id": companion_id}
            ).json()
            display_name = state["display_name"]
        except (httpx.HTTPError, KeyError):
            display_name = "艾莉"

        print(f"=== Aesir 终端对话（{display_name} / {companion_id} / session={session_id}）===")
        print("直接输入文字对话；/help 查看调试命令；/quit 退出。\n")

        while True:
            try:
                text = input("你：").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not text:
                continue
            if text in ("/quit", "/exit"):
                break
            if text == "/help":
                print(__doc__.split("内置命令：")[-1].strip())
                continue
            if text == "/memory":
                _show_memory(client, companion_id)
                continue
            if text == "/reset":
                _reset(client, companion_id)
                continue
            if text.startswith("/scene"):
                parts = text.split()
                if len(parts) == 2 and parts[1] in ("exploration", "conversation"):
                    game_state = parts[1]
                    print(f"[已切换] game_state={game_state}")
                else:
                    print("用法：/scene exploration|conversation")
                continue
            if text.startswith("/"):
                print("未知命令，/help 查看可用命令。")
                continue

            payload = {
                "text": text,
                "companion_id": companion_id,
                "game_state": game_state,
                "session_id": session_id,
            }
            try:
                if no_stream:
                    response = client.post("/v1/companion/chat", json=payload)
                    if response.status_code == 200:
                        _print_reply(response.json())
                    elif response.status_code == 404:
                        print(f"[错误] 角色未登记：{companion_id}")
                    else:
                        print(f"[错误] HTTP {response.status_code}：{response.text}")
                else:
                    print("\n艾莉：", end="", flush=True)
                    _send_streaming(client, payload)
            except httpx.HTTPError as error:
                print(f"[错误] 请求失败：{error}")
    print("再见。")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Aesir 终端对话 REPL")
    parser.add_argument("--port", default="8000", help="服务端口（默认 8000）")
    parser.add_argument("--host", default="127.0.0.1", help="服务地址（默认 127.0.0.1）")
    parser.add_argument("--companion", default=DEFAULT_COMPANION, help="对话角色 ID")
    parser.add_argument("--no-stream", action="store_true", help="禁用流式，回退非流式 /chat")
    args = parser.parse_args()
    raise SystemExit(main(f"http://{args.host}:{args.port}", args.companion, no_stream=args.no_stream))
