// Meta(인스타그램) 웹훅 검증/수신용 최소 응답 서버.
// 실제 DM 처리는 poll_dm.py가 주기적으로 Graph API를 조회해서 하므로,
// 이 워커는 Meta가 요구하는 "웹훅이 존재한다"는 조건만 충족시키는 역할입니다.
//
// 배포 전 VERIFY_TOKEN을 원하는 임의의 문자열로 바꾸고,
// Meta 앱 대시보드의 Webhooks 설정에 같은 값을 넣어주세요.

const VERIFY_TOKEN = "hssup-webhook-verify-2026"; // 아무 문자열이나 가능, Meta 설정과 동일해야 함

export default {
  async fetch(request) {
    const url = new URL(request.url);

    if (request.method === "GET") {
      // Meta의 웹훅 등록 검증 요청
      const mode = url.searchParams.get("hub.mode");
      const token = url.searchParams.get("hub.verify_token");
      const challenge = url.searchParams.get("hub.challenge");

      if (mode === "subscribe" && token === VERIFY_TOKEN) {
        return new Response(challenge, { status: 200 });
      }
      return new Response("Forbidden", { status: 403 });
    }

    if (request.method === "POST") {
      // 실제 이벤트 수신 — 아무 처리 없이 200만 응답 (poll_dm.py가 따로 조회함)
      return new Response("EVENT_RECEIVED", { status: 200 });
    }

    return new Response("OK", { status: 200 });
  },
};
