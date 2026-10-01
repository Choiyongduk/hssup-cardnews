"""새 그림을 그립니다 (Cloudflare Workers AI 의 FLUX.1 schnell).

클로드는 그림을 못 그립니다. 사진, 글자, 도형으로만 디자인합니다.
일러스트나 배경처럼 "없는 그림" 이 필요할 때 여기서 그립니다.

- 오픈소스 모델 FLUX.1 schnell (Apache 2.0, 상업적으로 써도 됨)
- 그림 모델을 돌리려면 그래픽카드가 필요한데 GitHub 러너에는 없습니다.
  Cloudflare 가 자기 서버에서 돌려 주고, 매일 무료 사용량이 있습니다
  (1024x1024, 8단계 기준 하루 약 100장). 무료 요금제는 그걸 넘으면 그날은 실패할 뿐 과금되지 않습니다.
- 그림 모델은 한글을 제대로 못 씁니다. 글자 없는 그림만 그리게 하고,
  한글은 디자인 담당(클로드)이 그 위에 얹습니다.

  CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN  (Workers AI 권한 토큰)
  ILLUST_MODEL  바꿀 모델 (기본 @cf/black-forest-labs/flux-1-schnell)
"""
from __future__ import annotations

import base64
import os

import requests

DEFAULT_MODEL = "@cf/black-forest-labs/flux-1-schnell"

# 글자를 그리지 말라는 말을 늘 붙인다. 그림 모델이 쓴 글자는 깨진 외계어처럼 나온다.
NO_TEXT = ", no text, no letters, no words, no watermark, no logo"


def available() -> bool:
    return bool(os.environ.get("CLOUDFLARE_ACCOUNT_ID") and os.environ.get("CLOUDFLARE_API_TOKEN"))


def generate(prompt: str, steps: int = 8) -> bytes:
    """영어 설명으로 그림 한 장(JPEG, 1024x1024)을 그립니다. 실패하면 RuntimeError."""
    account = os.environ["CLOUDFLARE_ACCOUNT_ID"].strip()  # 붙여넣다 딸려 온 공백, 줄바꿈 제거
    model = os.environ.get("ILLUST_MODEL", DEFAULT_MODEL)
    resp = requests.post(
        f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}",
        headers={"Authorization": f"Bearer {os.environ['CLOUDFLARE_API_TOKEN'].strip()}"},
        json={"prompt": prompt.strip() + NO_TEXT, "steps": steps},
        timeout=120,
    )
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"그림 서버 응답을 읽지 못했습니다 ({resp.status_code})")
    if resp.status_code != 200 or not data.get("success", True):
        errors = data.get("errors") or [{"message": resp.text[:200]}]
        raise RuntimeError(f"그림을 그리지 못했습니다: {errors[0].get('message')}")
    image = (data.get("result") or {}).get("image")
    if not image:
        raise RuntimeError("그림이 비어서 왔습니다")
    return base64.b64decode(image)
