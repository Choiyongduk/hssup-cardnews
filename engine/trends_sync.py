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


def _get_thread(table: str, params: dict) -> list[dict]:
    """대화를 사진 주소(attachments)까지 가져옵니다.

    앱 쪽 db/2026-10-02_ai_attachments.sql 을 실행하기 전에는 그 칸이 없어서
    조회가 실패합니다. 그때는 글만 가져와 예전처럼 동작하게 합니다.
    """
    try:
        return _get(table, {**params, "select": "role,body,created_at,attachments"})
    except Exception:
        return _get(table, {**params, "select": "role,body,created_at"})


def fetch_thread(report_id: int) -> list[dict]:
    """한 리포트에 달린 대화를 시간순으로 가져옵니다."""
    return _get_thread("ai_messages", {"report_id": f"eq.{report_id}", "order": "created_at.asc"})


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


def fetch_unanswered_approval_messages() -> list[dict]:
    """승인 대기 게시물에 원장이 남겼는데 아직 처리하지 않은 요청."""
    try:
        return _get(
            "ai_approval_messages",
            {
                "select": "*,ai_approvals(id,channel,ref_key,body,image_urls,payload,status)",
                "role": "eq.owner",
                "answered": "is.false",
                "order": "created_at.asc",
                "limit": "5",
            },
        )
    except Exception as e:
        print(f"  ! 승인 대화 조회 실패: {e}")
        return []


def fetch_approval_thread(approval_id: int) -> list[dict]:
    return _get_thread("ai_approval_messages", {"approval_id": f"eq.{approval_id}", "order": "created_at.asc"})


def create_approval_message(approval_id: int, role: str, body: str, staff_key: str = "",
                            attachments: list[str] | None = None) -> None:
    """단체 채팅방에 한 마디 남깁니다. staff_key 는 누가 답했는지 표시용입니다.

    attachments: 말풍선에 같이 보일 그림 주소. 시안을 고쳤으면 고치기 전과 고친 후를 붙여
    대화창만 올려 봐도 어떻게 바뀌어 왔는지 보이게 합니다.
    """
    row = {"approval_id": approval_id, "role": role, "body": body, "answered": True}
    full = {**row, **({"staff": staff_key} if staff_key else {}), **({"attachments": attachments} if attachments else {})}
    try:
        _post("ai_approval_messages", full)
    except Exception:
        # staff, attachments 칸이 아직 없는 데이터베이스에서도 말은 남아야 합니다.
        _post("ai_approval_messages", row)


def mark_approval_message_answered(message_id: int) -> None:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    resp = requests.patch(
        f"{url}/rest/v1/ai_approval_messages",
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
        raise RuntimeError(f"승인 대화 갱신 실패: {resp.status_code} {resp.text}")


def update_approval_content(row_id: int, body: str | None = None, image_urls: list[str] | None = None) -> None:
    """승인 대기 건의 캡션이나 이미지를 고쳐 씁니다."""
    payload = {}
    if body is not None:
        payload["body"] = body
    if image_urls is not None:
        payload["image_urls"] = image_urls
    if not payload:
        return

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
        json=payload,
        timeout=30,
    )
    if resp.status_code not in (200, 204):
        raise RuntimeError(f"승인 내용 갱신 실패: {resp.status_code} {resp.text}")


def update_approval_payload(row_id: int, payload: dict) -> None:
    """승인 대기 건의 payload 를 통째로 바꿔 씁니다(예: 영상 위 글씨를 기록)."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    resp = requests.patch(
        f"{url}/rest/v1/ai_approvals",
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json", "Prefer": "return=minimal"},
        params={"id": f"eq.{row_id}"},
        json={"payload": payload},
        timeout=30,
    )
    if resp.status_code not in (200, 204):
        raise RuntimeError(f"승인 payload 갱신 실패: {resp.status_code} {resp.text}")


def fetch_media_queue() -> list[dict]:
    """앱에서 올린 사진·영상 중 아직 처리하지 않은 것 (오래된 순)."""
    try:
        return _get(
            "ai_media_queue",
            {"select": "*", "status": "eq.queued", "order": "created_at.asc"},
        )
    except Exception as e:
        print(f"  ! 앱 대기열 조회 실패: {e}")
        return []


def update_media_queue(row_id: int, status: str, error: str | None = None) -> None:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    resp = requests.patch(
        f"{url}/rest/v1/ai_media_queue",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
        params={"id": f"eq.{row_id}"},
        json={"status": status, "error": error, "done_at": dt.datetime.now(dt.timezone.utc).isoformat()},
        timeout=30,
    )
    if resp.status_code not in (200, 204):
        raise RuntimeError(f"앱 대기열 갱신 실패: {resp.status_code} {resp.text}")


def delete_storage_object(bucket: str, path: str) -> None:
    """게시가 끝난 원본을 지웁니다. 남겨두면 용량이 계속 쌓입니다."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    resp = requests.delete(
        f"{url}/storage/v1/object/{bucket}/{path}",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=30,
    )
    if resp.status_code not in (200, 204, 404):
        raise RuntimeError(f"원본 삭제 실패: {resp.status_code} {resp.text}")


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


NOTE_SEP = chr(10) * 2  # 메모 여러 장을 빈 줄 하나로 나눠 이어 붙인다


def fetch_context(key: str = "business") -> str:
    """원장이 앱에 적어둔 사업 상황 메모. 숫자로는 알 수 없는 사정이 여기 들어옵니다.

    메모는 여러 장(ai_notes)으로 적습니다. 한 칸에 몰아 쓰던 시절의 것(ai_context)도
    남아 있을 수 있어서 둘 다 읽어 합칩니다.
    """
    parts: list[str] = []
    try:
        for row in _get("ai_notes", {"select": "body", "key": f"eq.{key}", "order": "created_at.asc"}):
            body = (row.get("body") or "").strip()
            if body:
                parts.append(body)
    except Exception:
        pass
    try:
        rows = _get("ai_context", {"select": "body", "key": f"eq.{key}"})
        legacy = rows[0]["body"].strip() if rows else ""
        if legacy:
            parts.append(legacy)
    except Exception:
        pass
    return NOTE_SEP.join(parts)


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


# ── 저장한 디자인 (ai_styles) ────────────────────────────────
# 원장님이 "앞으로 후기는 이 디자인으로" 하면 그 HTML 을 저장합니다.
# 앱에서 소재를 올릴 때 고르면, 제목만 바꿔 같은 디자인으로 그립니다.

def fetch_style(style_id: int) -> dict | None:
    try:
        rows = _get("ai_styles", {"select": "*", "id": f"eq.{style_id}"})
    except Exception as e:
        print(f"  ! 저장한 디자인 조회 실패: {e}")
        return None
    return rows[0] if rows else None


def save_style(name: str, channel: str, html: str, fonts: list[str], preview_url: str | None) -> None:
    """같은 이름이 있으면 덮어씁니다. "후기 디자인 바꿔서 다시 저장" 이 자연스럽게 되도록."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    resp = requests.post(
        f"{url}/rest/v1/ai_styles",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
        params={"on_conflict": "channel,name"},
        json={"name": name, "channel": channel, "html": html, "fonts": fonts, "preview_url": preview_url},
        timeout=30,
    )
    if resp.status_code not in (200, 201, 204):
        raise RuntimeError(f"디자인 저장 실패: {resp.status_code} {resp.text}")
