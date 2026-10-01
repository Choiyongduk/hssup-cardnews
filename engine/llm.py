"""클로드를 부르는 창구. 구독(Pro/Max)을 먼저 쓰고, 안 되면 API 로 넘어갑니다.

API 는 쓴 만큼 돈이 나갑니다. 원장님은 이미 클로드 구독을 내고 계셔서,
자동화도 그 구독으로 돌리면 추가 비용이 없습니다.

구독으로 부르는 길은 클로드 코드(claude -p) 하나뿐입니다. 구독 토큰으로 API 를
직접 부를 수는 없습니다. 그래서 여기서 API 와 같은 모양으로 감싸 둡니다.
각 스크립트는 Anthropic() 대신 llm.client() 를 쓰면 되고, 나머지 코드는 그대로입니다.

  CLAUDE_CODE_OAUTH_TOKEN  있으면 구독을 먼저 씁니다 (claude setup-token 으로 만든 1년짜리 토큰)
  LLM_BACKEND=api          구독을 건너뛰고 API 만 씁니다 (약관이 바뀌거나 문제가 생길 때)

구독은 원장님이 직접 클로드를 쓰는 것과 사용량 한도를 나눠 씁니다. 한도에 걸리거나
모델이 구독에 없거나 클로드 코드가 실패하면, 그 한 번만 API 로 넘어갑니다.

구독 쪽에서 안 되는 것: 도구를 주고받으며 이어가는 대화(틀 없이 그리기)와 프롬프트 캐시.
그런 호출은 처음부터 API 로 갑니다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SYSTEM = "당신은 히썹 반영구 아카데미의 업무 담당자입니다. 요청한 것만 답하세요."


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    name: str
    input: dict
    id: str = "toolu_subscription"
    type: str = "tool_use"


@dataclass
class Message:
    content: list = field(default_factory=list)
    stop_reason: str = "end_turn"
    model: str = ""


class SubscriptionUnavailable(RuntimeError):
    """구독으로 못 했다. API 로 넘어가라는 뜻."""


def _use_subscription() -> bool:
    if os.environ.get("LLM_BACKEND", "").lower() == "api":
        return False
    return bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")) and bool(_claude_bin())


_install_tried = False


def _claude_bin() -> str | None:
    """claude 명령의 위치. GitHub 에서 처음 부를 때 없으면 한 번 설치합니다(약 15초).

    워크플로마다 설치 단계를 넣지 않아도 되게 여기서 합니다. 설치가 실패하면 None 이고,
    그러면 API 로 갑니다.
    """
    global _install_tried
    found = os.environ.get("CLAUDE_BIN") or shutil.which("claude")
    if found or _install_tried or not os.environ.get("CI"):
        return found
    _install_tried = True
    print("  · 클로드 코드 설치 중 (구독으로 처리하려고)")
    try:
        subprocess.run(["npm", "install", "-g", "--silent", "@anthropic-ai/claude-code@latest"],
                       check=True, timeout=300, capture_output=True)
    except Exception as e:
        print(f"  · 클로드 코드를 설치하지 못했습니다: {e}")
        return None
    return shutil.which("claude")


def _text_of(system) -> str:
    if not system:
        return DEFAULT_SYSTEM
    if isinstance(system, str):
        return system
    return "\n\n".join(b.get("text", "") for b in system if isinstance(b, dict))


def _blocks_of(content) -> list[dict]:
    """메시지 내용을 글과 그림 조각으로. 그 밖의 것(도구 결과 등)은 구독 쪽에서 못 다룬다."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    out = []
    for b in content:
        b = b if isinstance(b, dict) else {"type": getattr(b, "type", ""), "text": getattr(b, "text", "")}
        if b.get("type") in ("text", "image"):
            out.append({k: v for k, v in b.items() if k != "cache_control"})
        elif b.get("type") in ("tool_use", "tool_result"):
            raise SubscriptionUnavailable("도구를 주고받는 대화는 구독으로 못 합니다")
    return out


def _flatten(messages: list[dict]) -> list[dict]:
    """여러 차례 오간 대화를 한 번의 요청으로 펼칩니다. 클로드 코드는 한 번에 한 말만 받습니다."""
    if len(messages) == 1 and messages[0]["role"] == "user":
        return _blocks_of(messages[0]["content"])
    out: list[dict] = [{"type": "text", "text": "[지금까지 오간 대화입니다. 마지막 원장님 말에 답하세요]"}]
    for m in messages:
        who = "원장님" if m["role"] == "user" else "담당자(당신)"
        out.append({"type": "text", "text": f"\n── {who} ──"})
        out += _blocks_of(m["content"])
    return out


def _pick_tool(tools, tool_choice) -> dict | None:
    if not tools:
        return None
    if tool_choice and tool_choice.get("type") == "tool":
        return next((t for t in tools if t["name"] == tool_choice["name"]), None)
    if len(tools) == 1:
        return tools[0]
    raise SubscriptionUnavailable("고를 도구가 여럿이라 구독으로 못 합니다")


def _via_subscription(model: str, system=None, messages=None, tools=None, tool_choice=None, **_ignored) -> Message:
    tool = _pick_tool(tools, tool_choice)
    blocks = _flatten(messages or [])
    if tool:
        blocks.append({"type": "text", "text": f"\n결과는 `{tool['name']}` 형식으로 내세요. ({tool.get('description', '')})"})

    with tempfile.TemporaryDirectory() as tmp:
        prompt_file = Path(tmp) / "system.txt"
        prompt_file.write_text(_text_of(system), encoding="utf-8")
        cmd = [
            _claude_bin(), "-p",
            # 그림을 넘기려면 입력을 stream-json 으로 줘야 하고, 그러면 출력도 stream-json 이어야 한다.
            # 마지막 result 줄만 읽는다(_parse).
            "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--model", model,
            "--system-prompt-file", str(prompt_file),
            "--tools", "",                    # 파일 읽기, 명령 실행 같은 건 필요 없다. 답만 한다
            "--disallowedTools", "mcp__*",
            "--safe-mode",                    # 이 컴퓨터의 설정, 플러그인, CLAUDE.md 를 읽지 않는다
            "--no-session-persistence",
            "--max-turns", "4",
        ]
        if tool:
            cmd += ["--json-schema", json.dumps(tool["input_schema"], ensure_ascii=False)]

        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
        line = json.dumps({"type": "user", "message": {"role": "user", "content": blocks}}, ensure_ascii=False)
        try:
            proc = subprocess.run(
                cmd, input=line + "\n", capture_output=True, text=True, encoding="utf-8",
                timeout=900, cwd=tmp, env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise SubscriptionUnavailable(f"클로드 코드를 실행하지 못했습니다: {e}") from e

    out = _parse(proc.stdout)
    if proc.returncode != 0 or not out or out.get("is_error") or out.get("subtype", "success") != "success":
        reason = (out or {}).get("result") or proc.stderr.strip()[-300:] or f"종료 코드 {proc.returncode}"
        raise SubscriptionUnavailable(str(reason)[:300])

    if tool:
        data = out.get("structured_output")
        if not isinstance(data, dict):
            raise SubscriptionUnavailable("정해진 형식으로 답하지 않았습니다")
        return Message(content=[ToolUseBlock(name=tool["name"], input=data)], stop_reason="tool_use", model=model)
    return Message(content=[TextBlock(text=out.get("result") or "")], model=model)


def _parse(stdout: str) -> dict | None:
    """마지막 결과 줄을 찾습니다. 앞에 다른 줄이 섞여 나올 때가 있습니다."""
    for raw in reversed((stdout or "").strip().splitlines()):
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("type") == "result":
            return obj
    try:
        obj = json.loads(stdout)
        return obj if isinstance(obj, dict) else None
    except ValueError:
        return None


class _Messages:
    def __init__(self):
        self._api = None

    def _api_client(self):
        if self._api is None:
            from anthropic import Anthropic

            self._api = Anthropic()
        return self._api

    def create(self, **kwargs):
        if _use_subscription():
            try:
                msg = _via_subscription(**kwargs)
                print(f"  · 구독으로 처리 ({kwargs.get('model')})")
                return msg
            except SubscriptionUnavailable as e:
                print(f"  · 구독으로 못 해서 API 로 넘어갑니다: {e}")
        return self._api_client().messages.create(**kwargs)


class _Client:
    def __init__(self):
        self.messages = _Messages()


def client() -> _Client:
    """Anthropic() 자리에 그대로 쓰면 됩니다. client().messages.create(...)"""
    return _Client()
