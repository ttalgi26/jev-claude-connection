"""
Jev(판정) + Claude(생성) 질의응답 파이프라인

흐름:
  1) 캐시 조회 (같은 질문 → API 호출 0회)
  2) Jev 라우팅: 난이도 / 최신정보 필요 여부 / 정밀 계산 필요 여부  (1회 요청, 병렬 판정)
  3) 난이도에 맞는 Claude 모델로 답변 (Haiku → Sonnet → Opus)
  4) Jev 검증: 답변이 질문에 충분히 답했는지
  5) 검증 미달이면 한 단계 위 모델로 1회만 재시도

설치:
  pip install -r requirements.txt
환경변수:
  ANTHROPIC_API_KEY, TYPESAFE_API_KEY
실행:
  python jev_claude_qa.py          # 대화형
  python jev_claude_qa.py -v       # 라우팅/검증 수치 표시
"""

import hashlib
import os
import sqlite3
import sys
import time

import requests
from anthropic import Anthropic

# ───────────── 설정 ─────────────
JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"

TIERS = ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]
# 5.5 계열은 adaptive thinking이 기본으로 켜져 있고, thinking 토큰도 max_tokens에 포함된다.
# 너무 낮으면 답변이 중간에 잘리므로 여유 있게 잡는다.
MAX_TOKENS = {0: 4096, 1: 8192, 2: 16000}
# 티어별 사고 깊이 (Haiku/Opus 5.5 기본값은 medium, Sonnet 5.5는 high)
EFFORT = {0: "low", 1: "medium", 2: "high"}

ROUTE_CONF_MIN = 0.60      # 라우팅 신뢰도가 이보다 낮으면 한 단계 위 모델 사용
NEEDS_WEB_MIN = 0.60       # 최신정보 필요 확률이 이 이상이면 웹검색 켬
EXACT_CALC_MIN = 0.70      # 정밀 계산 필요 확률이 이 이상이면 Haiku 제외
VERIFY_PASS_MIN = 0.75     # 검증 통과 기준 (noul 확률)
JEV_TIMEOUT = 5            # 초. Jev 실패 시 Sonnet으로 폴백
JEV_MAX_CHARS = 20000      # Jev 컨텍스트 32K 제한 대비 자르기

# Claude 서버측 웹검색 도구.
# 동적 필터링 버전(20260209)은 Sonnet/Opus 5.5 지원, Haiku는 기본 버전 사용.
WEB_SEARCH_TOOL = {
    0: {"type": "web_search_20250305", "name": "web_search", "max_uses": 3},
    1: {"type": "web_search_20260209", "name": "web_search", "max_uses": 3},
    2: {"type": "web_search_20260209", "name": "web_search", "max_uses": 3},
}
MAX_CONTINUATIONS = 3      # 웹검색 pause_turn 재개 최대 횟수

# 안전 분류기 거절 시 서버측 대체 모델로 자동 재실행 (Sonnet/Opus만 지원, Haiku는 미지원)
FALLBACK_BETA = "server-side-fallback-2026-07-01"

CACHE_DB = "qa_cache.sqlite"
CACHE_TTL = 7 * 24 * 3600  # 초. 오래된 캐시 답변은 무시

SYSTEM_PROMPT = (
    "You are a precise assistant. Answer in the user's language. "
    "Lead with the answer, then only the reasoning needed. "
    "If you are not sure, say so instead of guessing. "
    "For calculations, show the key steps and double-check the result."
)

VERBOSE = "-v" in sys.argv
claude = Anthropic()


# ───────────── 캐시 ─────────────
_db = None


def _cache():
    global _db
    if _db is None:
        _db = sqlite3.connect(CACHE_DB)
        _db.execute("CREATE TABLE IF NOT EXISTS qa (k TEXT PRIMARY KEY, answer TEXT, ts REAL)")
    return _db


def _key(q: str) -> str:
    return hashlib.sha256(" ".join(q.lower().split()).encode()).hexdigest()


def cache_get(q):
    row = _cache().execute(
        "SELECT answer FROM qa WHERE k=? AND ts>?", (_key(q), time.time() - CACHE_TTL)
    ).fetchone()
    return row[0] if row else None


def cache_put(q, a):
    db = _cache()
    db.execute("INSERT OR REPLACE INTO qa VALUES (?,?,?)", (_key(q), a, time.time()))
    db.commit()


# ───────────── Jev ─────────────
def jev(state, questions):
    r = requests.post(
        JEV_URL,
        headers={
            "Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}",
            "Content-Type": "application/json",
        },
        json={"model": JEV_MODEL, "state": state, "questions": questions},
        timeout=JEV_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["answers"]


def _context(history, n=2):
    """후속 질문("그거 더 자세히")을 Jev가 이해할 수 있도록 직전 대화 일부를 붙인다."""
    return [
        {"role": m["role"], "content": m["content"][:2000]}
        for m in history[-n:]
    ]


def route(question: str, history: list):
    """returns (tier_index, use_web, info_dict)"""
    state = {"user_question": question}
    if history:
        state["previous_turns"] = _context(history)
    try:
        a = jev(
            state,
            {
                "difficulty": {
                    "type": "choice",
                    "instructions": "How much reasoning does a correct, complete answer to this question need?",
                    "criteria": {
                        "simple": "Greeting, definition, well-known fact, short rewrite or translation",
                        "moderate": "Explanation, comparison, everyday code, standard homework problem",
                        "hard": "Multi-step proof or derivation, complex or long code, research-level or high-stakes analysis",
                    },
                },
                "needs_current_info": {
                    "type": "noul",
                    "instructions": "Does answering correctly require information that may have changed recently "
                    "(news, prices, current officeholders, latest versions, schedules)?",
                },
                "needs_exact_calc": {
                    "type": "noul",
                    "instructions": "Does the answer depend on exact multi-step arithmetic or numeric computation?",
                },
            },
        )
        d = a["difficulty"]
        tier = {"simple": 0, "moderate": 1, "hard": 2}[d["choice"]]
        conf = d.get("confidence", 1)
        web_p = a["needs_current_info"]["noul"]
        calc_p = a["needs_exact_calc"]["noul"]
    except Exception as e:  # Jev 장애·응답 형식 오류 시 중간 모델로 폴백
        return 1, False, {"jev_error": str(e)}

    if conf < ROUTE_CONF_MIN:
        tier = min(tier + 1, 2)
    if calc_p >= EXACT_CALC_MIN:
        tier = max(tier, 1)  # 정밀 계산은 Haiku 제외
    use_web = web_p >= NEEDS_WEB_MIN
    info = {
        "difficulty": d["choice"],
        "conf": round(conf, 2),
        "web_p": round(web_p, 2),
        "calc_p": round(calc_p, 2),
    }
    return tier, use_web, info


def verify(question: str, answer: str, history: list):
    """noul 확률(0~1) 반환. Jev 실패 시 None (통과 처리하되 캐시하지 않음)."""
    state = {"question": question, "answer": answer[:JEV_MAX_CHARS]}
    if history:
        state["previous_turns"] = _context(history)
    try:
        a = jev(
            state,
            {
                "answers_fully": {
                    "type": "noul",
                    "instructions": "Does the answer directly and completely address what the question asks, "
                    "without obvious errors, contradictions, or evasion?",
                }
            },
        )
        return a["answers_fully"]["noul"]
    except Exception:
        return None


# ───────────── Claude ─────────────
def ask_claude(history, tier: int, use_web: bool):
    """returns (text, stop_reason, input_tokens, output_tokens)"""
    kwargs = dict(
        model=TIERS[tier],
        max_tokens=MAX_TOKENS[tier],
        system=SYSTEM_PROMPT,  # 프롬프트가 캐시 최소 길이보다 짧아 cache_control은 효과 없음
        output_config={"effort": EFFORT[tier]},
    )
    if use_web:
        kwargs["tools"] = [WEB_SEARCH_TOOL[tier]]
    if tier > 0:
        kwargs["betas"] = [FALLBACK_BETA]
        kwargs["fallbacks"] = "default"

    msgs = list(history)
    content, tok_in, tok_out = [], 0, 0
    for _ in range(MAX_CONTINUATIONS + 1):
        resp = claude.beta.messages.create(messages=msgs, **kwargs)
        tok_in += resp.usage.input_tokens
        tok_out += resp.usage.output_tokens
        content += resp.content
        if resp.stop_reason != "pause_turn":
            break
        # 서버측 웹검색 루프가 한도에 걸림 → 같은 요청에 지금까지의 응답을 붙여 재개
        msgs = list(history) + [{"role": "assistant", "content": content}]

    text = "".join(b.text for b in content if b.type == "text").strip()
    return text, resp.stop_reason, tok_in, tok_out


# ───────────── 메인 루프 ─────────────
def answer(question: str, history: list) -> str:
    t0 = time.time()

    if not history and (hit := cache_get(question)):
        if VERBOSE:
            print("  [cache hit]")
        return hit

    tier, use_web, info = route(question, history)
    msgs = history + [{"role": "user", "content": question}]
    tok_in = tok_out = 0
    escalated = False

    while True:
        text, stop, i, o = ask_claude(msgs, tier, use_web)
        tok_in, tok_out = tok_in + i, tok_out + o
        # 잘림·거절은 Jev 검증 없이 미달로 처리
        score = verify(question, text, history) if stop in ("end_turn", "stop_sequence") and text else 0.0
        passed = score is None or score >= VERIFY_PASS_MIN
        if passed or tier >= 2 or escalated:
            break
        tier += 1
        escalated = True

    if not text:
        text = "답변을 생성하지 못했습니다." if stop != "refusal" else "이 요청에는 답변할 수 없습니다."

    if VERBOSE:
        score_s = "n/a" if score is None else f"{score:.2f}"
        print(
            f"  [route {info}] [model {TIERS[tier]}{' ↑' if escalated else ''}] "
            f"[web {use_web}] [stop {stop}] [verify {score_s}] "
            f"[tok in {tok_in} / out {tok_out}] [{time.time() - t0:.1f}s]"
        )

    # 첫 질문 + 최신정보 아님 + Jev 검증 실제 통과한 답변만 캐시
    if not history and not use_web and score is not None and score >= VERIFY_PASS_MIN:
        cache_put(question, text)
    return text


def main():
    if not os.environ.get("TYPESAFE_API_KEY"):
        print("경고: TYPESAFE_API_KEY가 없어 Jev 라우팅/검증 없이 Sonnet으로만 동작합니다.")
    history = []
    print("질문을 입력하세요. (/new 새 대화, /quit 종료)")
    while True:
        try:
            q = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            continue
        if q == "/quit":
            break
        if q == "/new":
            history = []
            print("새 대화를 시작합니다.")
            continue
        a = answer(q, history)
        print("\n" + a)
        history += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
        history = history[-12:]  # 최근 6턴만 유지 → 입력 토큰 절감


if __name__ == "__main__":
    main()
