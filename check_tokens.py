"""사용법: python check_tokens.py [--days 14]
채널마다 쓰는 인스타그램 액세스 토큰의 만료일을 확인하고,
만료됐거나 곧 만료되는 게 있으면 텔레그램으로 알립니다.

토큰이 조용히 만료되면 게시가 실패하는데도 아무도 모르는 일이 생겨서 만들었습니다.
(장기 토큰도 약 60일이면 만료됩니다.)
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

import requests
import yaml

from engine.config import ROOT

# 윈도우 콘솔 기본 인코딩(cp949)으로는 알림에 쓰는 이모지를 출력할 수 없습니다.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API = "https://graph.facebook.com/v21.0"
DEFAULT_WARN_DAYS = 14


def inspect(token: str, app_token: str) -> dict:
    """토큰 상태를 조회합니다. 만료된 토큰도 앱 토큰으로 조회하면 정보가 나옵니다."""
    resp = requests.get(
        f"{API}/debug_token",
        params={"input_token": token, "access_token": app_token},
        timeout=30,
    )
    body = resp.json()
    if "error" in body:
        raise RuntimeError(body["error"].get("message", str(body["error"])))
    return body.get("data", {})


def collect_targets() -> dict[str, list[str]]:
    """{토큰 환경변수명: [채널 slug, ...]} — 같은 토큰을 여러 채널이 공유할 수 있습니다."""
    targets: dict[str, list[str]] = {}
    for path in sorted((ROOT / "channels").glob("*.yaml")):
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
        ig_cfg = cfg.get("instagram")
        if not ig_cfg:
            continue
        targets.setdefault(ig_cfg["token_env"], []).append(cfg["slug"])
    return targets


def _notify(text: str) -> None:
    """알림은 아무 채널 봇으로나 보냅니다 — 받는 사람은 어차피 같습니다."""
    for path in sorted((ROOT / "channels").glob("*.yaml")):
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
        tg_cfg = cfg.get("telegram")
        if not tg_cfg:
            continue
        token = os.environ.get(tg_cfg["bot_token_env"])
        if not token:
            continue
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={"chat_id": str(tg_cfg["chat_id"]), "text": text},
                timeout=30,
            ).raise_for_status()
            return
        except Exception as e:
            print(f"  ! 텔레그램 알림 실패({cfg['slug']}): {e}")
    print("  ! 알림을 보낼 수 있는 텔레그램 봇이 없습니다.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=DEFAULT_WARN_DAYS, help="며칠 전부터 경고할지")
    args = parser.parse_args()

    app_id = os.environ.get("FB_APP_ID")
    app_secret = os.environ.get("FB_APP_SECRET")
    if not app_id or not app_secret:
        print("FB_APP_ID / FB_APP_SECRET 이 없어 토큰을 확인할 수 없습니다.")
        return 1
    app_token = f"{app_id}|{app_secret}"

    now = dt.datetime.now(dt.timezone.utc)
    problems: list[str] = []

    for token_env, slugs in collect_targets().items():
        label = f"{token_env} ({', '.join(slugs)})"
        token = os.environ.get(token_env)
        if not token:
            problems.append(f"❌ {label}: 환경변수가 비어 있음")
            continue

        try:
            data = inspect(token, app_token)
        except Exception as e:
            problems.append(f"❌ {label}: 확인 실패 — {e}")
            continue

        expires_at = data.get("expires_at", 0)
        if not data.get("is_valid"):
            problems.append(f"❌ {label}: 이미 만료됨 (재발급 필요)")
            continue

        if not expires_at:  # 0이면 만료 없음
            print(f"  [O] {label}: 만료 없음")
            continue

        expiry = dt.datetime.fromtimestamp(expires_at, dt.timezone.utc)
        left = (expiry - now).days
        if left <= args.days:
            problems.append(f"⚠️ {label}: {left}일 뒤 만료 ({expiry:%Y-%m-%d})")
        else:
            print(f"  [O] {label}: {left}일 남음 ({expiry:%Y-%m-%d})")

    if problems:
        text = "🔑 인스타그램 토큰 점검\n\n" + "\n".join(problems)
        text += "\n\nGraph API 탐색기에서 사용자 토큰을 새로 발급받아 교체해주세요."
        print("\n".join(problems))
        _notify(text)
    else:
        print("모든 토큰이 정상입니다.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
