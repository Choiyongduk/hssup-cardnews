# 히썹 인스타그램 자동 게시

## 목적
히썹(H.SSUP, 반영구 화장 아카데미, [@h_ssup_](https://www.instagram.com/h_ssup_/)) 인스타그램 계정에
카드뉴스 형태의 콘텐츠를 자동으로 만들어 게시하는 엔진. `cardnews` 프로젝트(경제 뉴스 브리핑 자동화)에서
검증된 엔진(렌더링·텔레그램 승인·Buffer 게시 파이프라인)을 재사용하되, 계정·시크릿·저장소는 완전히 분리했습니다.

## 콘텐츠 전략 (TBD — 사모님 확인 필요)
- 반영구 교육 팁 카드뉴스 (AI가 주제를 잡아 교육 콘텐츠 생성)
- 강좌 모집·프로모션 홍보 카드 (사장님이 문구/일정 입력)
- 비포/애프터 시술 결과 소개 (사장님이 직접 올린 사진 사용, 초상권 동의 확인 필요)
- 톤앤매너: 전문적이면서 친근한 교육자 톤. 효과 과장·의료적 표현 등 반영구 업종 광고 규제 주의.

## 구조 (cardnews와 동일한 패턴)
- `engine/` 공통 로직 — config(채널 로딩), renderer(HTML→PNG), theme(컬러 팔레트),
  telegram(승인 봇), assets(이미지 공개 업로드), instagram(Buffer 경유 게시), validate, caption
- `engine/sources.py`는 아직 비어있음 — 콘텐츠 전략이 정해지면 소스 타입을 추가 (cardnews의
  `engine/summarize.py`, `engine/rss.py` 참고해서 구조 잡기)
- `channels/<slug>.yaml` 채널 설정 — 아직 없음, 콘텐츠 전략 확정 후 작성
- `templates/<template>/` 디자인 — 아직 없음. 히썹 기존 계정 톤(전문적인 뷰티 브랜드 느낌)에 맞게
  새로 디자인 필요 (cardnews의 네온 팝 스타일과는 다르게)
- `assets/fonts/` Pretendard (cardnews에서 복사)

## 실행
python render.py --channel <slug> [--date YYYY-MM-DD] [--slot am|pm]

## 파이프라인 (cardnews와 동일)
1. `render.py` — 콘텐츠 생성 → PNG 렌더링 → 공개 저장소(ASSETS_REPO) 업로드 → `pending/<slug>/<date>.json` 생성 → 텔레그램 미리보기 전송
2. `poll_telegram.py` — 텔레그램 승인 버튼 응답 확인 → `pending/` 상태 갱신
3. `publish_instagram.py` — 승인된 것만 Buffer API로 인스타그램 게시

GitHub Actions로 자동화할 때는 cardnews의 `.github/workflows/daily-cardnews.yml`,
`telegram-poll.yml`, `instagram-publish.yml`을 참고해서 이 저장소용으로 새로 작성.

## 환경
Windows, PowerShell, VS Code, Python 3. 가상환경 `.venv` 사용.

## 필요한 비밀값 (.env, GitHub Secrets 둘 다)
- `ANTHROPIC_API_KEY` — Claude API (워크스페이스 연결된 키여야 함)
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — 승인 알림용 (cardnews와 별도 봇 권장)
- `BUFFER_API_KEY` — Instagram 게시용 (buffer.com 무료 플랜, h_ssup_ 계정 연결 후 channel_id 확인)
- `ASSETS_REPO`(owner/repo), `ASSETS_REPO_TOKEN` — 이미지 공개 호스팅용 별도 public 저장소

## 규칙
- API 키 등 비밀값은 `.env`에만 저장. `.env`, `output/`은 git 제외.
- 단계별로 진행: 각 단계 시작 전 계획을 보여주고 승인 후 구현.
- 코드 변경 후 반드시 render.py를 실행해 결과를 확인하고 보고.
- 비포/애프터 등 실제 고객 사진을 쓸 때는 초상권 동의 여부를 반드시 확인.
- 반영구/의료미용 광고 관련 규제(효과 보장·과장 표현 금지 등) 주의.

## 로드맵
- [x] 엔진 스캐폴딩 (cardnews에서 재사용 가능한 부분 이식)
- [ ] 콘텐츠 전략 확정 (사모님 확인: 팁/홍보/비포애프터 각각 어떻게 운영할지)
- [ ] 디자인: 히썹 브랜드 톤에 맞는 템플릿 제작
- [ ] `channels/hssup.yaml` + 소스 로직 구현
- [ ] Buffer에 h_ssup_ 계정 연결, channel_id 확인
- [ ] 텔레그램 봇 신규 생성 (또는 기존 재사용 여부 결정)
- [ ] GitHub 저장소 생성 + Actions 자동화
