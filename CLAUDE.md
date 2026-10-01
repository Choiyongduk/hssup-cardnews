# 히썹 · 프루피팝 인스타그램 자동 게시

## 목적
세 인스타그램 계정에 콘텐츠를 자동으로 게시하는 엔진.
- **히썹 아카데미** (@hssup_academy) — 반영구 수강·교육 콘텐츠 전용 계정 (메인 계정 @h_ssup_과는 별개)
- **히썹 아트메이크/시술계정** (@h_ssup_artmake) — 시술 전후·기법 콘텐츠 전용 계정
- **프루피팝(Fruppy Pop, 인스타 계정명은 아직 preppypop_official)** — 개발 중인 반영구 색소 브랜드 전용 계정

세 계정 모두 와이프(민희님)가 관리하며, 텔레그램 봇 3개(계정별 1개)로 사진을 보내면 자동 처리됩니다.

`cardnews` 프로젝트(경제 뉴스 브리핑 자동화)에서 검증된 엔진(텔레그램 승인, 게시 파이프라인)을 재사용하되,
계정·시크릿·저장소는 완전히 분리했습니다. Instagram 게시는 Buffer가 아니라 **Meta Graph API 직접 연동**으로
진행합니다. Meta for Developers 앱은 세 계정 공용으로 하나만 등록했습니다(앱 이름 "hssup auto").

## 콘텐츠 파이프라인 — cardnews와 다른 방식
cardnews는 RSS 기사를 요약해 디자인 카드(PNG)를 만드는 구조였지만, 이 프로젝트는 **실제 사진을
그대로 게시**하는 "미디어 인박스" 구조입니다. 사진 위에 브랜드 로고+헤드라인만 자동으로 입힙니다.

1. 사장님/사모님이 각자의 텔레그램 봇에 사진 + 설명(캡션 입력창에 같이 써서 한 메시지로)을 보냄
   **주의**: 사진과 설명은 반드시 한 메시지로 같이 보내야 함(캡션 필드만 읽음, 별도 텍스트 메시지는 안 합쳐짐)
2. `poll_telegram.py`가 감지 → 원본 사진을 공개 저장소(ASSETS_REPO)에 올리고 `queue/<slug>/`에 대기열로 등록
   (즉시 처리 아님 — 매일 하나씩 순서대로 게시하기 위한 대기열)
3. `process_queue.py`가 **매일 저녁 8시(KST)** 채널마다 대기열 맨 앞 1개를 꺼내 처리:
   - Claude Vision(`engine/media_caption.write_post`)이 사진+설명을 보고 헤드라인(사진에 얹을 짧은 문구)과
     인스타 캡션을 한 번에 작성 (tool_use 구조화 출력)
   - `overlay` 설정이 있는 채널은 `engine/overlay.render_overlay`(Playwright)로 사진 위에 로고 뱃지+헤드라인+
     브랜드 컬러 포인트바를 합성 (`templates/brand-overlay/`)
   - 완성된 이미지를 ASSETS_REPO에 업로드 → `pending/<slug>/<날짜시각>.json` 생성 → 같은 봇으로
     캡션 미리보기 + [게시]/[건너뛰기] 버튼 전송
4. 버튼을 누르면 `poll_telegram.py`가 감지해 상태 갱신
5. `publish_instagram.py`가 승인된 것만 Instagram Graph API로 게시 (사진 1장이면 단일 이미지, 2장 이상이면 캐러셀)
6. `refresh_ig_tokens.py`가 장기 토큰을 매주 자동 갱신 (약 60일 만료)

지금은 텔레그램보다 **앱(히썹앱의 AI 오피스)** 이 주 경로입니다. 텔레그램은 나란히 살아 있고,
앱 쪽이 검증되면 걷어냅니다. 앱에서 올리면 사진 여러 장을 한 게시물(캐러셀)로 묶고,
영상도 받고, "바로 작업" 으로 몇 분 안에 처리할 수 있습니다.

**운영 전반(담당자, 흐름, 크론 시간, 말투 규칙, 막혔을 때)은 `운영.md` 를 보세요.**
여기는 코드 구조만 적습니다.

## 구조
- `engine/config.py` — 채널(yaml) 로딩
- `engine/telegram.py` — 텔레그램 봇 (여러 봇 동시 지원: 모든 함수가 token/chat_id를 인자로 받음)
  - `poll(token, bot_name, inbox_chat_id)` — 승인 버튼 응답 처리 + (inbox_chat_id 지정 시) 새 사진 감지·다운로드
  - `send_preview()`, `create_pending()`, `notify()`
- `engine/media_caption.py` — 사진 + 사용자 설명 → Claude Vision으로 헤드라인+캡션 동시 작성.
  전송 전 Pillow로 sRGB JPEG 정규화(색상 프로파일 문제로 Claude API가 이미지를 거부하는 것 방지).
- `engine/overlay.py` — 사진에 로고+헤드라인을 합성해 PNG로 렌더링 (Playwright, `templates/brand-overlay/`).
  `logo`(이미지 파일 경로) 또는 `logo_text`(텍스트 로고, 이미지 없을 때 대체) 둘 중 하나 사용.
- `engine/free_design.py` — 틀 없이 처음부터 그리는 사진 게시물 디자인. 디자인 담당(Opus)이 HTML 을 쓰고,
  그려진 그림을 직접 보고 최대 2번 고칩니다. 제목 자리는 `data-slot="headline"`.
  그린 HTML 은 `data/posts/<채널>-<ref>-free.html` 에 떠두고 이후 수정은 그 위에서 합니다.
  저장한 디자인(`ai_styles`)은 `apply_style` 로 AI 없이 제목만 바꿔 그립니다.
- `engine/attachments.py` — 원장님이 대화에 붙인 사진을 클로드에게 그림으로 넘깁니다.
- `engine/assets.py` — 이미지를 공개 저장소(ASSETS_REPO)에 업로드해 공개 URL 확보
- `engine/instagram.py` — Meta Graph API 게시(1장이면 단일 이미지, 2장 이상이면 캐러셀) + 장기 토큰 갱신
- `engine/renderer.py`, `engine/theme.py`, `engine/validate.py`, `engine/caption.py`, `engine/sources.py` —
  카드뉴스(글에서 그려내는 캐러셀)용. `hssup-tips`, `hssup-news` 채널이 씁니다.
  renderer 는 그리면서 깨진 곳을 함께 검사해 `self.problems` 에 담습니다.
- `engine/cards.py` — 카드뉴스를 다시 그리는 일. 게시물마다 카드 내용을 `data/posts/` 에 따로 떠둡니다.
  채널 파일 하나만 쓰면 카드뉴스가 여러 개 대기할 때 서로 섞입니다.
- `engine/design.py` — 디자인을 고쳤을 때 깨졌는지 보는 검사기. 걸리면 되돌립니다.
- `engine/staff.py` — 담당자 명단. 누가 어떤 요청을 맡는지. 앱의 AI_STAFF 와 같은 사람들.
- `engine/voice.py` — 캡션 말투 기준. 실제 히썹 계정 글에서 뽑았습니다.
- `engine/trends_sync.py` — Supabase 와 주고받는 모든 것. 앱이 보는 표들을 여기서 씁니다.
- `channels/*.yaml` — 채널 설정. 사진 게시(`telegram_inbox`)와 카드뉴스(`json`, `rss`)가 섞여 있습니다.
- `assets/fonts/` Pretendard, `assets/logos/` 히썹 브랜드 로고(hssup-academy.png, hssup-general.png)

## 실행
```
python poll_telegram.py          # 텔레그램 봇 폴링 (승인 처리 + 새 사진을 대기열에 등록)
python process_queue.py          # 대기열에서 꺼내 처리 (--urgent 는 "바로 작업" 만)
python publish_instagram.py      # 승인된 것만 인스타그램 게시
python refresh_ig_tokens.py      # 장기 토큰 갱신 (FB_APP_ID/SECRET 필요)

python revise_post.py            # 시안에 남긴 수정 요청 처리 (--plan-only / --apply-plan)
python answer_owner.py           # 리포트에 남긴 피드백에 답하기
python run_requests.py           # "지금" 으로 올린 콘텐츠 요청 처리

python make_cards.py --channel hssup-tips [--report-id N] [--section N]
python render.py --channel hssup-tips [--slot qna]     # 카드 그리기 + 승인 등록
python apply_design.py --channel hssup-tips --css-file new.css   # 디자인 입혀보기

python morning_brief.py          # 아침 보고
python weekly_meeting.py         # 월요일 회의록
python analyze_feed.py           # 피드 성과 분석
python plan_content.py           # 주간 콘텐츠 기획
```

## 자동화 트리거 — GitHub 기본 `schedule`가 아니라 외부 크론(cron-job.org) 사용
GitHub Actions의 `schedule` 트리거는 지연이 심함(몇 시간까지 밀린 적 있음, private 저장소일수록 심함).
대신 **cron-job.org**(무료)가 GitHub API의 `workflow_dispatch`를 직접 호출하도록 구성했음 — dispatch는
거의 즉시 실행됨. 등록된 크론 잡: `hssup-telegram-poll`(1분마다), `hssup-instagram-publish`(2분마다),
`hssup-process-queue`(매일 낮 12:30·저녁 8시 KST), `hssup-revise-post`(수정 요청 처리), `hssup-process-now`(앱에서 "지금 바로"로 올린 소재).
뒤의 둘은 사람이 기다리는 일이라 몇 분 간격 — 할 일이 없으면 값싼 확인만 하고 끝난다. `schedule:`도 백업용으로 남겨뒀지만 실질적 트리거는 cron-job.org.

이 저장소(`hssup-cardnews`, `hssup-cardnews-assets`)는 **public**으로 전환됨 — GitHub Actions 무료 분량
(월 2,000분)은 private 저장소에만 적용되고 public은 무제한이라, 1~2분 간격 폴링을 계속 쓰려면 필수였음.
코드/로직은 공개되지만 시크릿은 전부 GitHub Secrets에만 있어 노출 위험 없음.

## 환경
Windows, PowerShell, VS Code, Python 3. 가상환경 `.venv` 사용 (설치 완료, Pillow 포함).

## GitHub
- 코드: [hssup-cardnews](https://github.com/Choiyongduk/hssup-cardnews) (public)
- 이미지 공개 호스팅: [hssup-cardnews-assets](https://github.com/Choiyongduk/hssup-cardnews-assets) (public)
- 워크플로: `telegram-poll.yml`, `instagram-publish.yml`, `process-queue.yml`, `refresh-ig-tokens.yml` —
  전부 작성 완료, 실질 트리거는 cron-job.org (위 참고)

## 필요한 비밀값 (.env, GitHub Secrets 둘 다) — 전부 등록 완료
- `ANTHROPIC_API_KEY` — Claude API
- `PREPPY_POP_BOT_TOKEN`, `HSSUP_ACADEMY_BOT_TOKEN`, `ARTMAKE_BOT_TOKEN` — 채널별 텔레그램 봇
- `FB_APP_ID`, `FB_APP_SECRET` — Meta for Developers 앱 ("hssup auto", 세 계정 공용)
- `PREPPY_POP_IG_BUSINESS_ID`, `PREPPY_POP_IG_TOKEN` — 프루피팝(preppypop_official) IG ID + 장기 토큰
- `HSSUP_ACADEMY_IG_BUSINESS_ID`, `HSSUP_ACADEMY_IG_TOKEN` — hssup_academy IG ID + 장기 토큰
- `ARTMAKE_IG_BUSINESS_ID`, `ARTMAKE_IG_TOKEN` — h_ssup_artmake IG ID + 장기 토큰
- `ASSETS_REPO`(owner/repo), `ASSETS_REPO_TOKEN` — 이미지 공개 호스팅용 저장소 접근 토큰

### Meta 계정 연결 시 겪은 문제 (다음에 계정 추가할 때 참고)
- 인스타그램 계정을 "계정 센터"에서 Facebook 페이지에 연결해도 실제로 저장 안 되는 경우가 있었음 —
  Meta Business Suite/Graph API의 `me/accounts`에 안 나타나면 연결이 안 된 것. 인스타그램 앱에서
  설정 → 계정 유형 및 도구 → 페이지 연결(또는 새 페이지 만들기)로 직접 재시도해야 확실함.
- Facebook 페이지가 여러 개면 어느 페이지가 어느 인스타 계정에 연결됐는지 헷갈리기 쉬움 —
  Graph API Explorer에서 페이지별로 `me?fields=instagram_business_account{username}` 쿼리로 하나씩 확인.
- 페이지를 새로 만들 때 "최근에 페이지를 너무 많이 만들려고 시도했습니다" 속도 제한 — 몇 시간~하루 대기.
- 장기 토큰 발급: Graph API Explorer에서 `oauth/access_token?grant_type=fb_exchange_token&client_id=<앱ID>&client_secret=<앱시크릿>&fb_exchange_token=<현재 페이지 토큰>` 쿼리로 교환 (앱ID/시크릿에 꺾쇠<> 넣지 않도록 주의, 실제 값으로 치환).

## 규칙
- API 키 등 비밀값은 `.env`에만 저장. `.env`, `output/`, `state/inbox/`, `state/queue_tmp/`는 git 제외.
- 실제 고객 사진을 쓸 때는 초상권 동의 여부를 반드시 확인.
- 반영구/의료미용 광고 관련 규제(효과 보장·과장 표현 금지 등) 주의 — `engine/media_caption.py`의
  시스템 프롬프트에 기본 규칙을 넣어뒀지만, 사업주가 원하는 구체적인 톤·금지 표현이 있으면 반영.

## 로드맵
- [x] 3개 채널(히썹 아카데미 / 히썹 아트메이크 / 프루피팝) 계정·봇·토큰·시크릿 전부 세팅 완료
- [x] 브랜드 오버레이(로고+헤드라인 자동 합성) 구현
- [x] 대기열 방식으로 전환 (사진 여러 장 미리 보내면 매일 저녁 8시 하나씩 자동 게시)
- [x] GitHub Actions 스케줄 지연 문제 해결 (cron-job.org 외부 트리거 + 저장소 public 전환)
- [x] 앱에서 사진 여러 장을 한 게시물(캐러셀)로 올리기 + "바로 작업" 즉시 처리
- [x] 영상 지원 (프레임 추출 → 캡션, 영상 오버레이)
- [x] AI 오피스: 피드 분석, 콘텐츠 기획, 요청 처리, 시안 대화
- [x] 단체 채팅방 — 요청에 맞는 담당이 나오고 자기 일이 아니면 넘김
- [x] 주제형 카드뉴스 (기획안 → 카드 내용 → 그림 → 승인까지 한 번에)
- [x] 디자인 자유롭게 고치되 깨지면 되돌리기
- [x] 아침 보고 + 월요일 회의록
- [ ] **실제 게시를 한 번도 안 해봤음.** 시안은 여럿 만들었지만 게시 0건
- [ ] 텔레그램 경로 걷어내기 (앱 쪽이 검증되면)
- [ ] 프루피팝 인스타그램 계정명 변경 후 channels/preppy-pop.yaml 갱신
- [~] DM 자동 응대 — 접었음. 코드는 남았지만 워크플로에서 빠졌고 인스타 기본 자동응답 사용
