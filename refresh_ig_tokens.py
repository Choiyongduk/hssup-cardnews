"""사용법: python refresh_ig_tokens.py
channels/*.yaml 중 instagram 설정이 있는 모든 채널의 장기 액세스 토큰을 갱신하고
'gh secret set'으로 GitHub Secret에 반영합니다. (실행 전에 gh CLI 로그인이 되어 있어야 합니다.)
만료 전에 미리 갱신해두는 용도이므로 주기적으로(예: 매주) 실행합니다.
만료가 없는 페이지 토큰(renew_ig_tokens.py로 발급)은 갱신할 필요가 없어 건너뜁니다.
토큰이 없거나 갱신에 실패하면 작업을 실패로 끝내서 GitHub에서 바로 보이게 합니다."""
from __future__ import annotations

import os
import subprocess
import sys

import yaml

from check_tokens import inspect
from engine import instagram
from engine.config import ROOT

REPO = "Choiyongduk/hssup-cardnews"


def main() -> int:
    app_id = os.environ.get("FB_APP_ID")
    app_secret = os.environ.get("FB_APP_SECRET")
    if not app_id or not app_secret:
        print("FB_APP_ID/FB_APP_SECRET이 없어 중단합니다.")
        return 1
    app_token = f"{app_id}|{app_secret}"

    token_envs: list[str] = []
    for path in sorted((ROOT / "channels").glob("*.yaml")):
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
        ig_cfg = cfg.get("instagram")
        if ig_cfg and ig_cfg["token_env"] not in token_envs:
            token_envs.append(ig_cfg["token_env"])

    if not token_envs:
        print("instagram 설정이 있는 채널이 없습니다.")
        return 0

    failed = 0
    for token_env in token_envs:
        current = os.environ.get(token_env)
        if not current:
            print(f"  ! {token_env} 없음 (워크플로 env에 넣었는지 확인)")
            failed += 1
            continue
        try:
            if not inspect(current, app_token).get("expires_at", 0):
                print(f"  - {token_env} 만료 없는 토큰, 건너뜀")
                continue
            new_token, expires_in = instagram.refresh_long_lived_token(current, app_id, app_secret)
        except Exception as e:
            print(f"  ! {token_env} 갱신 실패: {e}")
            failed += 1
            continue
        subprocess.run(
            ["gh", "secret", "set", token_env, "--repo", REPO, "--body", new_token],
            check=True,
        )
        days = expires_in // 86400
        print(f"  - {token_env} 갱신 완료 (약 {days}일 유효)")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
