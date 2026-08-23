# seoyeon-automations

서연(개인 AI 비서)이 대표님을 위해 운영하는 자동화 모음. GitHub Actions + Notion + ntfy 조합으로 동작합니다.

## 알림 채널

- **ntfy.sh** — 실제 폰 푸시 알림 (토픽: 비공개, GitHub Secret `NTFY_TOPIC`)
- **Notion** — 모든 데이터의 원본 저장소 (GitHub Secret `NOTION_TOKEN`, 내부 통합명 "서연 백업봇")

## 워크플로 목록

| 파일 | 주기(KST) | 내용 |
|---|---|---|
| `morning-push.yml` | 매일 07:35 | 오늘의 브리핑 준비 알림 + 날씨/미세먼지(전일 대비 비교) |
| `dday-alert.yml` | 매일 08:00 | `data/important-events.json` 기준 D-7/3/1/0 알림 |
| `fixed-expense-reminder.yml` | 매일 08:10 | 고정지출 결제일 D-1 알림 |
| `notion-backup.yml` | 매일 08:50 | 하루일기/연락처/오늘의브리핑을 `backups/`에 백업 |
| `travel-check.yml` | 매일 10:00 | `data/travel-checks.json`에 오늘 날짜 있으면 TMAP 실시간 교통 체크 후 출발시각 알림 |
| `budget-check.yml` | 매일 21:00 | 이번달 카테고리별 지출이 예산 70/90/100% 도달시 알림 |
| `weekly-retro-push.yml` | 일요일 22:05 | 주간 회고 준비 알림 |
| `monthly-report.yml` | 매월 1일 09:10 | 지난달 지출 집계 리포트를 가계부 DB에 추가 |

## 클라우드 루틴 (claude.ai/code/routines, 이 저장소 밖에서 실행)

- **서연 모닝 브리핑** — 매일 07:30, 캘린더 확인 후 "오늘의 브리핑" 노션 페이지 업데이트
- **서연 데일리 다이어리** — 매일 23:50, 하루 요약 일기를 "서연의 하루일기" DB에 기록
- **서연 주간 회고** — 일요일 22:00, 그 주 일기를 모아 "주간 회고" DB에 기록

## Notion 데이터베이스

- 서연의 하루일기 / 오늘의 브리핑 / 연락처 / 가계부 / 고정지출 / 예산설정 / 주간 회고 / 건강기록

## 대표님 지시사항 (세션 간 기억용)

세션이 끊겨도 반드시 참고해야 할, 대표님이 주신 지속적인 지시사항은 Notion "대표님 지시사항" 페이지(서연 비서실 하위)에 누적 기록됩니다. 새 세션 시작 시 이 페이지를 먼저 확인할 것.
- https://app.notion.com/p/3c51811a40e98141beebdd0d97c19e58

## 데이터 파일

- `data/important-events.json` — D-day 알림 대상 (새 중요 일정 생기면 추가)
- `data/travel-checks.json` — 실시간 교통체크 대상 (출장/이동 일정 생기면 추가)
- `data/weather-history.json`, `data/budget-alert-state.json` — 자동 생성되는 상태 파일 (수동 편집 불필요)

## 알려진 함정

1. 클라우드 루틴(Bash)에서는 ntfy 같은 임의 외부 서버로 직접 요청이 안 감 — 실제 푸시는 항상 GitHub Actions가 담당.
2. 신규 개인 계정의 private 저장소는 Actions가 등록 안 될 수 있음 — public 전환 + 워크플로 파일 사소한 변경 후 재커밋으로 우회.
3. `gh secret set`은 `--body` 플래그로 직접 지정할 것 (파이프로 넘기면 개행문자 섞여 깨짐).
4. Notion DB 생성 시 "database url"과 "data source url(collection://)"을 혼동하지 말 것 — API 호출엔 database id 사용.
5. Windows PowerShell 5.1은 한글 다루는 스크립트를 UTF-8 BOM 없이 저장하면 파싱이 깨짐 — `.ps1` 파일은 항상 BOM 포함 UTF-8로 저장.
