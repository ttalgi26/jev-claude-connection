# jev-claude-connection

**Jev(판정 모델)** 로 질문의 난이도를 판정하고 답변을 검증하며, **Claude**(Haiku / Sonnet / Opus)가 답변을 생성하는 비용 최적화 질의응답 CLI.

쉬운 질문은 싼 모델로, 어려운 질문은 강한 모델로 보내고, 답변 품질이 기준에 못 미치면 한 단계 위 모델로 한 번만 다시 시도합니다.

## 동작 흐름

```
질문
 │
 ├─ 1. 캐시 조회 ──── hit → 바로 반환 (API 호출 0회)
 │
 ├─ 2. Jev 라우팅 (요청 1회, 세 가지 판정 병렬)
 │     • difficulty          simple / moderate / hard
 │     • needs_current_info  최신정보 필요 확률 → 웹검색 on/off
 │     • needs_exact_calc    정밀 계산 필요 확률 → Haiku 제외
 │
 ├─ 3. Claude 답변 생성
 │     simple → Haiku 5.5 / moderate → Sonnet 5.5 / hard → Opus 5.5
 │
 ├─ 4. Jev 검증: answers_fully (0~1)
 │
 └─ 5. 0.75 미만, 답변 잘림, 거절 → 한 단계 위 모델로 1회 재시도
```

### 라우팅 규칙

| 조건 | 결과 |
|---|---|
| `difficulty` | simple=Haiku, moderate=Sonnet, hard=Opus |
| 판정 신뢰도 < 0.60 | 한 단계 위 모델 |
| 정밀 계산 확률 ≥ 0.70 | 최소 Sonnet |
| 최신정보 확률 ≥ 0.60 | Claude 웹검색 도구 켬 (최대 3회) |
| Jev 장애 / 응답 형식 오류 | Sonnet, 웹검색 끔 |

### 캐시 규칙

다음 조건을 모두 만족하는 답변만 `qa_cache.sqlite`에 저장합니다(유효기간 7일).

- 대화의 첫 질문일 것 (이어지는 질문은 앞 문맥에 따라 답이 달라지므로)
- 웹검색을 쓰지 않았을 것 (최신정보는 금방 바뀌므로)
- Jev 검증을 실제로 통과했을 것 (Jev 장애로 검증을 건너뛴 답변은 저장 안 함)

질문은 소문자 변환과 공백 정리 후 SHA-256으로 키를 만듭니다.

## 설치

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 키 입력 후 export 하거나 셸에서 직접 설정
export ANTHROPIC_API_KEY=sk-ant-...
export TYPESAFE_API_KEY=...
```

## 실행

```bash
python jev_claude_qa.py        # 대화형
python jev_claude_qa.py -v     # 라우팅/모델/검증 점수/토큰/소요시간 표시
```

| 명령 | 동작 |
|---|---|
| `/new` | 새 대화 (히스토리 초기화) |
| `/quit` | 종료 |

`-v` 출력 예시:

```
[route {'difficulty': 'moderate', 'conf': 0.82, 'web_p': 0.1, 'calc_p': 0.05}] [model claude-sonnet-5-5] [web False] [stop end_turn] [verify 0.91] [tok in 412 / out 380] [3.2s]
```

## 설정값 (`jev_claude_qa.py` 상단)

| 이름 | 기본값 | 의미 |
|---|---|---|
| `TIERS` | haiku / sonnet / opus 5.5 | 티어별 모델 |
| `MAX_TOKENS` | 4096 / 8192 / 16000 | 티어별 최대 출력 토큰 (thinking 포함) |
| `EFFORT` | low / medium / high | 티어별 사고 깊이 |
| `ROUTE_CONF_MIN` | 0.60 | 이보다 판정 신뢰도가 낮으면 상위 모델 |
| `NEEDS_WEB_MIN` | 0.60 | 웹검색을 켜는 기준 |
| `EXACT_CALC_MIN` | 0.70 | Haiku를 빼는 기준 |
| `VERIFY_PASS_MIN` | 0.75 | 검증 통과 기준 |
| `JEV_TIMEOUT` | 5초 | Jev 요청 타임아웃 |
| `CACHE_TTL` | 7일 | 캐시 유효기간 |
| `MAX_CONTINUATIONS` | 3 | 웹검색 `pause_turn` 재개 횟수 |

## 원본 코드 대비 수정 사항

| # | 문제 | 수정 |
|---|---|---|
| 1 | `route()`에서 Jev 응답 파싱이 `try` 밖에 있음 → 예상 밖 `choice` 값이나 누락 필드가 오면 프로그램이 죽음 | 파싱까지 `try` 안으로 옮기고 실패 시 Sonnet으로 폴백 |
| 2 | Jev 검증이 실패하면 1.0(통과)을 반환 → 검증되지 않은 답변이 캐시에 영구 저장됨 | 실패 시 `None` 반환: 답변은 통과시키되 캐시에는 저장하지 않음 |
| 3 | 5.5 계열은 adaptive thinking이 기본으로 켜져 있고 thinking 토큰도 `max_tokens`에 포함됨 → Haiku 1024 토큰이면 답변이 잘리기 쉬움 | 4096 / 8192 / 16000으로 상향. 잘리면(`max_tokens`) 검증 미달로 보고 상위 모델로 재시도 |
| 4 | 웹검색 버전 `web_search_20250305` 고정 | Sonnet/Opus 5.5는 `web_search_20260209`(동적 필터링), Haiku는 기본 버전 사용 |
| 5 | 웹검색 중 `stop_reason == "pause_turn"`이면 답변이 미완성인 채로 끝남 | 최대 3회 이어서 요청 |
| 6 | 시스템 프롬프트(약 60토큰)가 캐시 최소 길이보다 짧아 `cache_control` 효과 없음 | 제거 |
| 7 | 재시도하면 첫 시도의 토큰 사용량이 로그에서 빠짐 | 모든 시도 합산 |
| 8 | Jev 라우팅·검증에 질문만 넘김 → "그거 더 자세히" 같은 후속 질문은 판정이 부정확하고 불필요한 재시도가 생김 | 직전 2개 메시지(각 2000자)를 `previous_turns`로 함께 전달 |
| 9 | 매 호출마다 SQLite 연결을 새로 열고 닫지 않음 | 연결 1개 재사용 |
| 10 | 캐시 만료 없음 | `CACHE_TTL` 7일 |
| 11 | `TYPESAFE_API_KEY` 미설정 시 조용히 모든 질문이 Sonnet으로 감 | 시작 시 경고 출력 |
| 12 | 안전 분류기 거절(`refusal`) 처리 없음 | Sonnet/Opus는 서버측 대체 모델 자동 재실행(`fallbacks: "default"`, 베타), Haiku 거절은 상위 모델로 재시도 |

## 알려진 한계 / 확인 필요

- **Jev API 스펙은 확인하지 못했습니다.** 엔드포인트(`/v1/systemone`), 요청 형식(`state`, `questions`), 응답 필드(`choice`, `confidence`, `noul`)는 원본 코드를 그대로 따랐습니다. 실제 스펙과 다르면 `route()` / `verify()`를 맞춰야 합니다.
- Haiku 5.5에서 `web_search_20260209` 지원 여부가 문서에 명시되어 있지 않아 기본 버전을 씁니다.
- `fallbacks` 파라미터는 베타입니다(`server-side-fallback-2026-07-01`). 계정에서 지원하지 않으면 `ask_claude()`의 `betas` / `fallbacks` 두 줄을 지우세요.
- 히스토리에는 답변 텍스트만 저장합니다. 웹검색 결과·인용은 다음 턴에 전달되지 않습니다.
- 대화 히스토리는 최근 6턴(12개 메시지)만 유지합니다.

## 파일 구성

```
jev_claude_qa.py   메인 스크립트
requirements.txt   의존성 (anthropic, requests)
.env.example       환경변수 예시
.gitignore         캐시 DB, .env, 가상환경 제외
```
