# 히썹 · 프레피팝 인스타그램 자동 게시

## 목적
두 인스타그램 계정에 콘텐츠를 자동으로 게시하는 엔진.
- **히썹 아카데미** ([@h_ssup_](https://www.instagram.com/h_ssup_/)) — 반영구 화장 교육 브랜드. 사모님이 사진/영상을 보내면 게시.
- **프레피팝(Preppy Pop)** — 개발 중인 반영구 색소 브랜드 전용 신규 계정. 사장님이 사진/영상을 보내면 게시.

`cardnews` 프로젝트(경제 뉴스 브리핑 자동화)에서 검증된 엔진(텔레그램 승인, 게시 파이프라인)을 재사용하되,
계정·시크릿·저장소는 완전히 분리했습니다. Instagram 게시는 Buffer가 아니라 **Meta Graph API 직접 연동**으로
진행합니다(사업주 요청). Meta for Developers 앱은 두 계정 공용으로 하나만 등록합니다.

## 콘텐츠 파이프라인 — cardnews와 다른 방식
cardnews는 RSS 기사를 요약해 디자인 카드(PNG)를 만드는 구조였지만, 이 프로젝트는 **실제 사진/영상을
그대로 게시**하는 "미디어 인박스" 구조입니다. 디자인 템플릿·렌더링이 필요 없습니다.

1. 사장님/사모님이 각자의 텔레그램 봇에 사진(또는 영상) + 간단한 설명을 보냄
2. `poll_telegram.py`가 감지 → 사진을 Claude에게 직접 보여주고(Vision), 설명을 참고해 인스타 캡션 작성
3. 사진을 공개 저장소(ASSETS_REPO)에 올려 공개 URL 확보 → `pending/<slug>/<날짜시각>.json` 생성 → 같은 봇으로 캡션 미리보기 + [게시]/[건너뛰기] 버튼 전송
4. 버튼을 누르면 `poll_telegram.py`가 감지해 상태 갱신
5. `publish_instagram.py`가 승인된 것만 Instagram Graph API로 게시
6. `refresh_ig_tokens.py`가 장기 토큰을 매주 자동 갱신 (약 60일 만료)

**V1 제한**: 메시지당 사진/영상 1개만 처리(여러 장 앨범은 첫 장만 반영). 영상은 이미지보다 처리가 복잡하고
(media_type=REELS, 긴 처리 대기시간) 대용량 호스팅도 고민 필요해서 **다음 단계로 미룸** — 지금은 사진 위주.

## 구조
- `engine/config.py` — 채널(yaml) 로딩
- `engine/telegram.py` — 텔레그램 봇 (여러 봇 동시 지원: 모든 함수가 token/chat_id를 인자로 받음)
  - `poll(token, bot_name, inbox_chat_id)` — 승인 버튼 응답 처리 + (inbox_chat_id 지정 시) 새 사진/영상 감지·다운로드
  - `send_preview()`, `create_pending()`, `notify()`
- `engine/media_caption.py` — 사진 + 사용자 설명 → Claude Vision으로 인스타 캡션 작성
- `engine/assets.py` — 이미지를 공개 저장소(ASSETS_REPO)에 업로드해 공개 URL 확보
- `engine/instagram.py` — Meta Graph API 캐러셀 게시 + 장기 토큰 갱신
- `engine/renderer.py`, `engine/theme.py`, `engine/validate.py`, `engine/caption.py`, `engine/sources.py` —
  cardnews에서 그대로 가져온 카드뉴스(디자인 렌더링)용 코드. **지금 두 채널(히썹/프레피팝)은 안 씀** —
  나중에 "교육 팁 카드뉴스" 같은 걸 추가하면 그때 씀.
- `channels/hssup-academy.yaml`, `channels/preppy-pop.yaml` — 채널 설정 (완료)
- `assets/fonts/` Pretendard (지금 미사용, 카드뉴스형 채널 추가 시 사용)

## 실행
```
python poll_telegram.py          # 모든 채널 봇 폴링 (승인 처리 + 새 사진 감지·캡션 작성)
python publish_instagram.py      # 승인된 것만 인스타그램 게시
python refresh_ig_tokens.py      # 장기 토큰 갱신 (FB_APP_ID/SECRET 필요)
```
(참고: `render.py`는 카드뉴스형 채널을 나중에 추가할 때 씀 — 지금 두 채널엔 해당 없음)

## 환경
Windows, PowerShell, VS Code, Python 3. 가상환경 `.venv` 사용 (설치 완료).

## GitHub
- 코드: [hssup-cardnews](https://github.com/Choiyongduk/hssup-cardnews) (private)
- 이미지 공개 호스팅: [hssup-cardnews-assets](https://github.com/Choiyongduk/hssup-cardnews-assets) (public)
- 워크플로: `telegram-poll.yml`(5분마다), `instagram-publish.yml`(10분마다), `refresh-ig-tokens.yml`(매주 월요일) — 전부 작성 완료

## 필요한 비밀값 (.env, GitHub Secrets 둘 다)
- `ANTHROPIC_API_KEY` — Claude API (워크스페이스 연결된 키여야 함)
- `PREPPY_POP_BOT_TOKEN` — 프레피팝용 텔레그램 봇 (사장님이 사진 보내는 봇)
- `HSSUP_ACADEMY_BOT_TOKEN` — 히썹 아카데미용 텔레그램 봇 (사모님이 사진 보내는 봇)
- `FB_APP_ID`, `FB_APP_SECRET` — Meta for Developers 앱 (developers.facebook.com에서 발급, 두 계정 공용)
- `PREPPY_POP_IG_BUSINESS_ID`, `PREPPY_POP_IG_TOKEN` — 프레피팝 IG 비즈니스 계정 ID + 장기 토큰
- `HSSUP_IG_BUSINESS_ID`, `HSSUP_IG_TOKEN` — h_ssup_ IG 비즈니스 계정 ID + 장기 토큰
- `ASSETS_REPO`(owner/repo), `ASSETS_REPO_TOKEN` — 이미지 공개 호스팅용 저장소 접근 토큰

채널 yaml의 `telegram.chat_id`도 채워야 합니다 (각자 봇과 대화 시작 후 chat_id 확인 — cardnews 때처럼
`getUpdates`로 조회 가능, `.env`의 봇 토큰만 있으면 코드로 바로 조회해줄 수 있음).

### Meta 설정 시 참고 (cardnews에서 겪은 문제)
- **전화 인증(SMS)이 잘 안 오는 경우가 흔함**. 다른 번호로 재시도하거나, "계정 센터"에 번호를 먼저 등록해야 한다는 안내가 뜰 수 있음.
- Facebook 페이지를 새로 만들 때 "최근에 페이지를 너무 많이 만들려고 시도했습니다" 에러가 뜨면 일시적 속도 제한 — 몇 시간~하루 대기 후 재시도.
- 이미지 URL은 반드시 공개 HTTPS 주소여야 함(로컬 파일 업로드 불가) — `engine/assets.py`가 이미 해결해둠.
- 앱 1개로 페이지(계정) 여러 개를 등록할 수 있으니, 히썹+프레피팝 둘 다 같은 앱에 연결하면 인증 절차를 한 번만 거치면 됨.

## 규칙
- API 키 등 비밀값은 `.env`에만 저장. `.env`, `output/`, `state/inbox/`(다운로드된 원본 미디어)는 git 제외.
- 단계별로 진행: 각 단계 시작 전 계획을 보여주고 승인 후 구현.
- 코드 변경 후 반드시 실행해서 결과를 확인하고 보고.
- 실제 고객 사진을 쓸 때는 초상권 동의 여부를 반드시 확인.
- 반영구/의료미용 광고 관련 규제(효과 보장·과장 표현 금지 등) 주의 — `engine/media_caption.py`의
  시스템 프롬프트에 기본 규칙을 넣어뒀지만, 사업주가 원하는 구체적인 톤·금지 표현이 있으면 반영.

## 로드맵
- [x] 엔진 스캐폴딩 (cardnews에서 재사용 가능한 부분 이식)
- [x] GitHub 저장소 생성 (코드 private + 이미지 호스팅 public)
- [x] Instagram 게시를 Meta Graph API 직접 연동으로 구현 (앱 공용, 계정 2개)
- [x] 콘텐츠 구조 확정: 텔레그램 미디어 인박스 방식 (히썹 아카데미 + 프레피팝, 채널 2개, 봇 2개)
- [x] `channels/hssup-academy.yaml`, `channels/preppy-pop.yaml` 작성
- [x] `engine/telegram.py`를 멀티 봇 지원으로 리팩터링, `engine/media_caption.py`(Vision 캡션) 신설
- [x] 워크플로 3종(`telegram-poll`, `instagram-publish`, `refresh-ig-tokens`) 작성
- [ ] 텔레그램 봇 2개 생성 (BotFather) + chat_id 확인
- [ ] Meta for Developers 앱 생성, 두 계정 비즈니스 전환 + 페이지 연결, 토큰 발급
- [ ] 시크릿 전부 등록 (.env + GitHub Secrets) 후 실전 테스트 (사진 1장 보내서 끝까지 게시 확인)
- [ ] (다음 단계) 영상 지원, 앨범(여러 장) 지원, 카드뉴스형 콘텐츠(교육 팁) 추가 여부 검토
