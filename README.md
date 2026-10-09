# jev-claude-connection

**Jev(판정 모델)** 로 질문의 난이도를 판정하고 답변을 검증하며, **Claude**(Haiku / Sonnet / Opus)가 답변을 생성하는 비용 최적화 질의응답 앱입니다. 웹 채팅 UI와 터미널 CLI를 모두 제공합니다.

- 쉬운 질문은 싼 모델로, 어려운 질문은 강한 모델로 보냅니다.
- 답변 품질이 기준에 못 미치면 한 단계 위 모델로 한 번만 다시 시도합니다.
- **차트·도표·다이어그램 이미지**와 **docx / xlsx / pptx / pdf / csv 파일**을 생성합니다. Claude 코드 실행 도구를 씁니다.
- 이미지·PDF·데이터 파일(csv, xlsx 등)을 첨부해서 질문할 수 있습니다.

> 사진이나 일러스트 같은 AI 그림 생성은 지원하지 않습니다. Claude는 코드로 그릴 수 있는 이미지(matplotlib 차트, 다이어그램 등)만 만듭니다.

## 빠른 시작

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
export TYPESAFE_API_KEY=...

python app.py          # 웹 UI → http://127.0.0.1:7860
python cli.py -v       # 터미널
```

## 웹 UI (`app.py`)

| 기능 | 사용법 |
|---|---|
| 질문 | 입력창에 입력 후 Enter |
| 파일 첨부 | 입력창의 📎 버튼 (여러 개 가능) |
| 생성 파일 | 이미지는 채팅에 바로 표시, 그 외 파일은 다운로드 링크로 표시. `outputs/`에도 저장 |
| 라우팅 정보 | "라우팅 정보 표시" 체크 → 모델·검증 점수·토큰을 접이식 메시지로 표시 |
| 새 대화 | "새 대화" 버튼 |
| 외부 공유 | `python app.py --share` (임시 공개 링크 생성. 누구나 내 API 키로 질문할 수 있으니 주의) |

브라우저 탭마다 대화 기록이 따로 유지됩니다.

## CLI (`cli.py`)

```bash
python cli.py        # 대화형
python cli.py -v     # 라우팅/모델/검증 점수/토큰/소요시간 표시
```

| 명령 | 동작 |
|---|---|
| `/attach 경로` | 다음 질문에 파일 첨부 (여러 번 입력 가능) |
| `/new` | 새 대화 |
| `/quit` | 종료 |

생성된 파일은 `📎 outputs/...` 형태로 경로가 출력됩니다.

## 동작 흐름

```
질문 (+ 첨부 파일)
 │
 ├─ 1. 캐시 조회 ──── hit → 바로 반환 (API 호출 0회)
 │
 ├─ 2. Jev 라우팅 (요청 1회, 네 가지 판정)
 │     • difficulty          simple / moderate / hard
 │     • needs_current_info  최신정보 필요 확률 → 웹검색 on/off
 │     • needs_exact_calc    정밀 계산 필요 확률 → Haiku 제외
 │     • wants_file_output   파일·차트 생성 요청 확률 → 코드 실행 on/off
 │
 ├─ 3. Claude 답변 생성
 │     simple → Haiku 5.5 / moderate → Sonnet 5.5 / hard → Opus 5.5
 │     코드 실행 시 컨테이너에서 파일 생성 → Files API로 내려받아 outputs/에 저장
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
| 최신정보 확률 ≥ 0.60 | 웹검색 도구 켬 (최대 3회) |
| 파일 생성 확률 ≥ 0.50 | 코드 실행 도구 켬, 최소 Sonnet |
| 이미지·PDF 이외의 파일 첨부 | 코드 실행 도구 켬, 최소 Sonnet |
| Jev 장애 / 응답 형식 오류 | Sonnet, 웹검색·파일 생성 판정 끔 (데이터 파일 첨부 시 코드 실행은 켜짐) |

### 첨부 파일 처리

| 종류 | 처리 |
|---|---|
| 이미지 (png, jpg, gif, webp) | 메시지에 직접 포함 → Claude가 바로 봄 |
| PDF | 메시지에 직접 포함 |
| 그 외 (csv, xlsx, docx, txt, json …) | Files API로 업로드 → 코드 실행 컨테이너에 넣고 Python으로 읽음 |

### 코드 실행 컨테이너 재사용

한 대화 안에서는 같은 컨테이너를 계속 씁니다. 그래서 "방금 만든 차트 색만 바꿔줘"처럼 앞에서 만든 파일이나 올린 데이터를 다시 쓸 수 있습니다. 컨테이너가 만료되면 새 컨테이너로 자동 재시도합니다.

### 캐시 규칙

다음 조건을 모두 만족하는 답변만 `qa_cache.sqlite`에 저장합니다(유효기간 7일).

- 대화의 첫 질문일 것
- 첨부 파일, 웹검색, 파일 생성이 모두 없을 것
- Jev 검증을 실제로 통과했을 것 (Jev 장애로 검증을 건너뛴 답변은 저장 안 함)

## 파일 구성

```
app.py               웹 채팅 UI (Gradio)
cli.py               터미널 CLI
jevqa/
  config.py          모든 설정값
  pipeline.py        전체 흐름: 캐시 → 라우팅 → 생성 → 검증 → 재시도
  jev.py             Jev API 호출, 라우팅·검증 판정
  claude.py          Claude 호출, 도구 구성, 첨부 처리, 생성 파일 다운로드
  cache.py           SQLite 답변 캐시
requirements.txt
.env.example
outputs/             생성 파일 저장 위치 (git 제외)
```

## 설정값 (`jevqa/config.py`)

| 이름 | 기본값 | 의미 |
|---|---|---|
| `TIERS` | haiku / sonnet / opus 5.5 | 티어별 모델 |
| `MAX_TOKENS` | 4096 / 8192 / 16000 | 티어별 최대 출력 토큰 (thinking 포함) |
| `MAX_TOKENS_CODE` | 16000 | 파일 생성 시 최소 출력 토큰 |
| `EFFORT` | low / medium / high | 티어별 사고 깊이 |
| `ROUTE_CONF_MIN` | 0.60 | 이보다 판정 신뢰도가 낮으면 상위 모델 |
| `NEEDS_WEB_MIN` | 0.60 | 웹검색을 켜는 기준 |
| `EXACT_CALC_MIN` | 0.70 | Haiku를 빼는 기준 |
| `FILE_OUTPUT_MIN` | 0.50 | 코드 실행을 켜는 기준 |
| `VERIFY_PASS_MIN` | 0.75 | 검증 통과 기준 |
| `JEV_TIMEOUT` | 5초 | Jev 요청 타임아웃 |
| `MAX_CONTINUATIONS` | 5 | 서버 도구 `pause_turn` 재개 횟수 |
| `CACHE_TTL` | 7일 | 캐시 유효기간 |
| `HISTORY_MAX` | 12 | 유지할 대화 메시지 수 (6턴) |

환경변수 `JEVQA_OUTPUT_DIR`, `JEVQA_CACHE_DB`로 저장 위치를 바꿀 수 있습니다.

## 원본 코드 대비 수정 사항

| # | 문제 | 수정 |
|---|---|---|
| 1 | `route()`에서 Jev 응답 파싱이 `try` 밖에 있음 → 예상 밖 응답이 오면 프로그램이 죽음 | 파싱까지 `try` 안으로 옮기고 실패 시 Sonnet으로 폴백 |
| 2 | Jev 검증이 실패하면 1.0(통과)을 반환 → 검증되지 않은 답변이 캐시에 영구 저장됨 | 실패 시 `None` 반환: 답변은 통과시키되 캐시에는 저장하지 않음 |
| 3 | 5.5 계열은 thinking 토큰도 `max_tokens`에 포함됨 → Haiku 1024 토큰이면 답변이 잘리기 쉬움 | 4096 / 8192 / 16000으로 상향. 잘리면 상위 모델로 재시도 |
| 4 | 웹검색 버전 `web_search_20250305` 고정 | Sonnet/Opus 5.5는 `web_search_20260209`, Haiku와 코드 실행 병행 시는 기본 버전 |
| 5 | 웹검색 중 `pause_turn`이면 미완성 답변으로 끝남 | 이어서 재요청 |
| 6 | 시스템 프롬프트가 캐시 최소 길이보다 짧아 `cache_control` 효과 없음 | 제거 |
| 7 | 재시도 시 첫 시도 토큰이 로그에서 빠짐 | 합산 |
| 8 | 후속 질문을 Jev가 앞 대화 없이 판정 | 직전 2개 메시지를 함께 전달 |
| 9 | SQLite 연결 누수, 캐시 만료 없음 | 연결 재사용(스레드 잠금), 7일 TTL |
| 10 | `TYPESAFE_API_KEY` 미설정 시 경고 없음 | 시작 시 경고 |
| 11 | 거절(`refusal`) 처리 없음 | Sonnet/Opus는 서버측 대체 모델 자동 재실행(`fallbacks: "default"`, 베타), Haiku는 상위 모델로 재시도 |

## 알려진 한계 / 확인 필요

- **Jev API 스펙은 확인하지 못했습니다.** 엔드포인트, 요청 형식(`state`, `questions`), 응답 필드(`choice`, `confidence`, `noul`)는 원본 코드를 그대로 따랐습니다. `wants_file_output` 판정은 같은 형식으로 새로 추가했습니다.
- **어떤 파일이 다운로드 대상으로 돌아오는지는 확인하지 못했습니다.** 코드 실행 결과 블록에 들어 있는 `file_id`를 모두 내려받도록 했습니다. 파일이 생성됐다고 하는데 UI에 안 보이면 `jevqa/claude.py`의 `_file_ids()`를 확인하세요.
- Haiku 5.5의 코드 실행과 `web_search_20260209` 지원 여부가 문서에 명시되어 있지 않습니다. 그래서 파일 생성은 Sonnet 이상만 하고, Haiku 웹검색은 기본 버전을 씁니다.
- `fallbacks`는 베타입니다. 계정에서 지원하지 않으면 `jevqa/claude.py`의 `betas` / `fallbacks` 두 줄을 지우세요.
- 대화 기록에는 텍스트만 남습니다. 첨부 이미지·PDF는 그 질문에서만 보이고 다음 턴에는 파일명만 전달됩니다. 데이터 파일은 컨테이너에 남아 있어 계속 쓸 수 있습니다.
- 재시도하면 실패한 첫 시도에서 만든 파일은 버리고, 마지막 시도에서 만든 파일만 저장합니다.
- 코드 실행은 별도 사용료(컨테이너 사용 시간)가 붙습니다.
