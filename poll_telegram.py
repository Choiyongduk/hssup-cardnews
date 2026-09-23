"""사용법: python poll_telegram.py
텔레그램 승인 버튼 응답을 확인해 pending/<slug>/<date>.json에 기록합니다."""
from __future__ import annotations

import sys

from engine.telegram import poll_and_record


def main() -> int:
    decided = poll_and_record()
    if not decided:
        print("새로운 응답 없음")
        return 0
    for d in decided:
        print(f"  - {d['slug']} {d['date']}: {d['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
