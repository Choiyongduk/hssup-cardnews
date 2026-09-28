"""hssup-app(Supabase)과 주고받는 것들을 모아둔 모듈.

- trends: 인스타그램에 게시한 뒤 앱의 "트렌드 속보"에 같은 글을 올립니다.
- ai_reports: 피드·직원 분석 리포트를 앱의 AI 오피스 탭에서 읽을 수 있게 올립니다.
- ai_approvals: 게시와 DM 답장을 앱에서 승인할 수 있게 올리고, 결정된 건을 가져옵니다.

모두 서비스 롤 키로 RLS를 우회해서 씁니다.
민감한 권한이므로 이 모듈 밖에서는 절대 이 키를 로그나 출력에 남기지 않습니다."""
from __future__ import annotations

import datetime as dt
import os

import requests

KST = dt.timezone(dt.timedelta(hours=9))


def _post(table: str, payload: dict) -> None:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise ValueError("SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY가 설정되어 있지 않습니다.")

    resp = requests.post(
        f"{url}/rest/v1/{table}",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
        json=payload,
        timeout=30,
    )
    if resp.status_code not in (200, 201, 204):
        raise RuntimeError(f"{table} 등록 실패: {resp.status_code} {resp.text}")


def create_approval(
    kind: str,
    channel: str,
    ref_key: str,
    title: str | None = None,
    body: str | None = None,
    incoming_text: str | None = None,
    image_urls: list[str] | None = None,
    payload: dict | None = None,
) -> None:
    """앱에서 승인할 수 있도록 대기 레코드를 올립니다.

    전환 기간에는 텔레그램에도 같은 건이 올라갑니다. 같은 건이 두 번 올라오면
    (kind, channel, ref_key) 유니크 제약에 걸리는데, 그건 이미 등록됐다는 뜻이라 무시합니다.
    """
    try:
        _post(
            "ai_approvals",
            {
                "kind": kind,
                "channel": channel,
                "ref_key": ref_key,
                "title": title,
                "body": body,
                "incoming_text": incoming_text,
                "image_urls": image_urls,
                "payload": payload,
            },
        )
    except RuntimeError as e:
        if "duplicate key" in str(e) or "23505" in str(e):
            return
        raise


def fetch_decided_approvals(kind: str | None = None) -> list[dict]:
    """앱에서 승인하거나 건너뛴 건을 가져옵니다."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise ValueError("SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY가 설정되어 있지 않습니다.")

    params = {"select": "*", "status": "in.(approved,skipped)", "order": "created_at.asc"}
    if kind:
        params["kind"] = f"eq.{kind}"
    resp = requests.get(
        f"{url}/rest/v1/ai_approvals",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        params=params,
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"승인 목록 조회 실패: {resp.status_code} {resp.text}")
    return resp.json()


def update_approval(row_id: int, status: str, error: str | None = None) -> None:
    """처리 결과를 되돌려 적습니다 (sent/failed)."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    resp = requests.patch(
        f"{url}/rest/v1/ai_approvals",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
        params={"id": f"eq.{row_id}"},
        json={"status": status, "error": error},
        timeout=30,
    )
    if resp.status_code not in (200, 204):
        raise RuntimeError(f"승인 상태 갱신 실패: {resp.status_code} {resp.text}")


def _get(table: str, params: dict) -> list[dict]:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise ValueError("SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY가 설정되어 있지 않습니다.")
    resp = requests.get(
        f"{url}/rest/v1/{table}",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        params=params,
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"{table} 조회 실패: {resp.status_code} {resp.text}")
    return resp.json()


def fetch_unanswered_messages() -> list[dict]:
    """원장이 남겼는데 아직 답하지 않은 메시지를 오래된 순으로 가져옵니다."""
    return _get(
        "ai_messages",
        {
            "select": "*,ai_reports(id,kind,title,body,target)",
            "role": "eq.owner",
            "answered": "is.false",
            "order": "created_at.asc",
            "limit": "10",
        },
    )


def fetch_thread(report_id: int) -> list[dict]:
    """한 리포트에 달린 대화를 시간순으로 가져옵니다."""
    return _get(
        "ai_messages",
        {"select": "role,body,created_at", "report_id": f"eq.{report_id}", "order": "created_at.asc"},
    )


def create_message(report_id: int, role: str, body: str) -> None:
    _post("ai_messages", {"report_id": report_id, "role": role, "body": body, "answered": True})


def mark_answered(message_id: int) -> None:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    resp = requests.patch(
        f"{url}/rest/v1/ai_messages",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
        params={"id": f"eq.{message_id}"},
        json={"answered": True},
        timeout=30,
    )
    if resp.status_code not in (200, 204):
        raise RuntimeError(f"메시지 상태 갱신 실패: {resp.status_code} {resp.text}")


def fetch_requests(urgency: str | None = None) -> list[dict]:
    """원장이 올린 콘텐츠 요청 중 아직 처리하지 않은 것."""
    params = {"select": "*", "status": "eq.open", "order": "created_at.asc"}
    if urgency:
        params["urgency"] = f"eq.{urgency}"
    try:
        return _get("ai_requests", params)
    except Exception as e:
        print(f"  ! 콘텐츠 요청 조회 실패: {e}")
        return []


def close_requests(ids: list[int]) -> None:
    """처리 끝난 요청에 표시합니다."""
    if not ids:
        return
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    resp = requests.patch(
        f"{url}/rest/v1/ai_requests",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
        params={"id": f"in.({','.join(str(i) for i in ids)})"},
        json={"status": "done", "done_at": dt.datetime.now(dt.timezone.utc).isoformat()},
        timeout=30,
    )
    if resp.status_code not in (200, 204):
        raise RuntimeError(f"요청 상태 갱신 실패: {resp.status_code} {resp.text}")


def fetch_context(key: str = "business") -> str:
    """원장이 앱에 적어둔 사업 상황 메모. 숫자로는 알 수 없는 사정이 여기 들어옵니다."""
    try:
        rows = _get("ai_context", {"select": "body", "key": f"eq.{key}"})
    except Exception:
        return ""
    return (rows[0]["body"].strip() if rows else "")


def update_report(report_id: int, body: str) -> None:
    """리포트 본문을 고쳐 씁니다. 원장 피드백을 반영해 다시 쓸 때 사용합니다.
    고치기 전 내용은 대화 기록이 남기므로 따로 보관하지 않습니다."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    resp = requests.patch(
        f"{url}/rest/v1/ai_reports",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
        params={"id": f"eq.{report_id}"},
        json={"body": body},
        timeout=30,
    )
    if resp.status_code not in (200, 204):
        raise RuntimeError(f"리포트 수정 실패: {resp.status_code} {resp.text}")


def fetch_recent_reports(exclude_id: int | None = None, limit: int = 6) -> list[dict]:
    """동료들이 최근에 낸 결과물. 대화 중에 "지난주 대비" 같은 질문에 답하려면 필요합니다."""
    rows = _get(
        "ai_reports",
        {"select": "id,kind,title,body,created_at", "order": "created_at.desc", "limit": str(limit)},
    )
    return [r for r in rows if r["id"] != exclude_id]


def fetch_latest_report(kind: str) -> dict | None:
    """같은 종류의 가장 최근 리포트를 가져옵니다. 한 직원의 결과물을 다음 직원이 읽을 때 씁니다."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise ValueError("SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY가 설정되어 있지 않습니다.")

    resp = requests.get(
        f"{url}/rest/v1/ai_reports",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        params={"select": "*", "kind": f"eq.{kind}", "order": "created_at.desc", "limit": 1},
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"리포트 조회 실패: {resp.status_code} {resp.text}")
    rows = resp.json()
    return rows[0] if rows else None


def create_report(kind: str, title: str, body: str, target: str | None = None, period_days: int | None = None) -> str:
    """분석 리포트를 앱의 AI OFFICE 탭에서 볼 수 있도록 저장합니다.

    같은 날 같은 종류의 리포트가 이미 있으면 새로 만들지 않고 덮어씁니다.
    하루에 여러 번 돌릴 때마다 쌓이면 무엇이 최신인지 알 수 없게 됩니다.
    반환: "created" 또는 "updated"
    """
    today = dt.datetime.now(KST).strftime("%Y-%m-%d")
    params = {
        "select": "id,created_at",
        "kind": f"eq.{kind}",
        "order": "created_at.desc",
        "limit": "5",
    }
    if target:
        params["target"] = f"eq.{target}"

    try:
        for row in _get("ai_reports", params):
            when = dt.datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
            if when.astimezone(KST).strftime("%Y-%m-%d") == today:
                update_report(row["id"], body)
                return "updated"
    except Exception as e:
        print(f"  ! 기존 리포트 확인 실패, 새로 만듭니다: {e}")

    _post(
        "ai_reports",
        {"kind": kind, "target": target, "title": title, "body": body, "period_days": period_days},
    )
    return "created"


def create_trend(
    title: str,
    content: str | None = None,
    image_urls: list[str] | None = None,
    category: str = "업계소식",
    link_url: str | None = None,
) -> None:
    image_urls = image_urls or []
    _post(
        "trends",
        {
            "category": category,
            "title": title,
            "content": content or None,
            "link_url": link_url,
            "image_urls": image_urls,
            "image_url": image_urls[0] if image_urls else None,
            "is_active": True,
        },
    )
