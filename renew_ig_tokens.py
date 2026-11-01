"""사용법: python renew_ig_tokens.py
토큰이 이미 만료됐을 때 한 번에 다시 발급합니다. (내 컴퓨터에서 실행, gh CLI 로그인 필요)

1. Graph API 탐색기에서 우리 앱을 고르고 사용자 토큰을 만들어 붙여넣습니다.
   (권한: instagram_basic, instagram_content_publish, pages_show_list, pages_read_engagement,
    instagram_manage_comments, instagram_manage_messages, business_management)
2. 장기 사용자 토큰으로 바꾼 뒤, 각 인스타 계정에 연결된 페이지의 토큰을 받습니다.
   장기 사용자 토큰에서 받은 페이지 토큰은 만료가 없어서 다시 만료될 일이 거의 없습니다.
3. .env 의 *_IG_BUSINESS_ID 와 맞는 계정의 토큰을 GitHub Secret 과 .env 에 넣습니다.
"""
from __future__ import annotations

import getpass
import os
import re
import subprocess
import sys

import yaml

from engine import instagram
from engine.config import ROOT
from refresh_ig_tokens import REPO

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def set_env_line(name: str, value: str) -> None:
    path = ROOT / ".env"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    line = f"{name}={value}"
    if re.search(rf"^{name}=.*$", text, flags=re.M):
        text = re.sub(rf"^{name}=.*$", lambda _: line, text, flags=re.M)
    else:
        text = text.rstrip("\n") + f"\n{line}\n"
    path.write_text(text, encoding="utf-8")


def main() -> int:
    app_id = os.environ.get("FB_APP_ID")
    app_secret = os.environ.get("FB_APP_SECRET")
    if not app_id or not app_secret:
        print(".env 에 FB_APP_ID / FB_APP_SECRET 이 없습니다.")
        return 1

    # {토큰 환경변수명: 인스타 비즈니스 ID}
    targets: dict[str, str] = {}
    for path in sorted((ROOT / "channels").glob("*.yaml")):
        ig_cfg = yaml.safe_load(path.read_text(encoding="utf-8")).get("instagram")
        if ig_cfg:
            targets[ig_cfg["token_env"]] = os.environ.get(ig_cfg["business_id_env"], "")

    short = getpass.getpass("Graph API 탐색기 사용자 토큰 붙여넣기 (화면에 안 보임): ").strip()
    if not short:
        return 1
    user_token, _ = instagram.refresh_long_lived_token(short, app_id, app_secret)

    pages = instagram._get(
        "me/accounts",
        fields="name,access_token,instagram_business_account{id,username}",
        limit=100,
        access_token=user_token,
    ).get("data", [])
    by_ig = {
        p["instagram_business_account"]["id"]: p
        for p in pages
        if p.get("instagram_business_account")
    }
    print("이 계정으로 관리하는 인스타:", ", ".join(
        f"@{p['instagram_business_account'].get('username')}" for p in by_ig.values()) or "없음")

    missing = 0
    for token_env, ig_id in targets.items():
        page = by_ig.get(ig_id)
        if not page:
            print(f"  ! {token_env}: 인스타 ID {ig_id or '(비어 있음)'} 를 못 찾음, 토큰 권한에서 이 계정을 골랐는지 확인")
            missing += 1
            continue
        token = page["access_token"]
        subprocess.run(["gh", "secret", "set", token_env, "--repo", REPO, "--body", token], check=True)
        set_env_line(token_env, token)
        print(f"  - {token_env}: @{page['instagram_business_account'].get('username')} 페이지 토큰으로 교체 완료")

    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
