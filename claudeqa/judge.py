"""
판정 모델: Groq 무료 API로 질문 라우팅과 답변 검증.
키가 없거나 한도 초과(429)·장애 시 규칙 기반 판정으로 자동 전환.
"""

import json
import os
import re

import requests

from .config import (
    EXACT_CALC_MIN, FILE_OUTPUT_MIN, GROQ_MODEL, GROQ_URL, JUDGE_MAX_CHARS, JUDGE_TIMEOUT,
    NEEDS_WEB_MIN, ROUTE_CONF_MIN,
)

ROUTE_PROMPT = """You classify a user's question for a model router. Reply with JSON only:
{
  "difficulty": "simple" | "moderate" | "hard",
  "confidence": number 0-1,          // how sure you are about difficulty
  "needs_current_info": number 0-1,  // probability
  "needs_exact_calc": number 0-1,    // probability
  "wants_file_output": number 0-1    // probability
}
difficulty — how much reasoning a correct, complete answer needs:
  simple: greeting, definition, well-known fact, short rewrite or translation
  moderate: explanation, comparison, everyday code, standard homework problem
  hard: multi-step proof or derivation, complex or long code, research-level or high-stakes analysis
needs_current_info: answering correctly requires information that may have changed recently
  (news, prices, current officeholders, latest versions, schedules).
needs_exact_calc: the answer depends on exact multi-step arithmetic or numeric computation.
wants_file_output: the user asks for a downloadable file or an image to be produced
  (chart, graph, diagram, spreadsheet, document, slides, PDF, CSV)."""

VERIFY_PROMPT = """You grade whether an answer addresses a question. Reply with JSON only:
{"answers_fully": number 0-1}
answers_fully is the probability that the answer directly and completely addresses what the question
asks, without obvious errors, contradictions, or evasion. A '[generated files: N]' note means N files
were actually produced and attached for the user."""


def _groq(system: str, payload: dict) -> dict:
    r = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
        json={
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "temperature": 0,
            "max_completion_tokens": 1024,
            "response_format": {"type": "json_object"},
        },
        timeout=JUDGE_TIMEOUT,
    )
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])


def _p(x) -> float:
    """모델이 준 확률 값을 0~1로 정리."""
    return min(max(float(x), 0.0), 1.0)


def _context(base: dict, history: list, attachments: list) -> dict:
    """후속 질문("그거 더 자세히")을 판정 모델이 이해할 수 있도록 직전 대화 일부와 첨부 파일명을 붙인다."""
    if history:
        base["previous_turns"] = [
            {"role": m["role"], "content": m["content"][:1500]} for m in history[-2:]
        ]
    if attachments:
        base["attached_files"] = attachments
    return base


# ───────────── 규칙 기반 폴백 ─────────────
_WEB = re.compile(r"오늘|어제|내일|최신|최근|현재|지금|요즘|올해|뉴스|속보|가격|시세|주가|환율|날씨|일정|버전|"
                  r"\b(today|latest|current|now|news|price|stock|weather|schedule|version)\b", re.I)
_CALC = re.compile(r"\d\s*[-+*/×÷^%]\s*\d|계산|합계|평균|이자|확률|적분|미분|방정식|\b(calculate|compute|solve)\b", re.I)
_FILE = re.compile(r"차트|그래프|도표|다이어그램|그림|이미지|엑셀|워드|파워포인트|슬라이드|보고서 ?파일|파일로|"
                   r"xlsx|xls|docx|pptx|pdf|csv|\b(chart|graph|plot|diagram|image|spreadsheet|slides?)\b", re.I)
_HARD = re.compile(r"증명|유도|설계|아키텍처|최적화|리팩터|논문|전략|심층|자세히 분석|"
                   r"\b(prove|derive|architecture|optimi[sz]e|refactor|research)\b", re.I)
_SIMPLE = re.compile(r"^(안녕|고마워|감사|hi|hello|thanks)|뜻|의미|번역|translate|정의", re.I)


def _rule_route(question: str, attachments: list):
    q = question
    if _HARD.search(q) or len(q) > 600:
        diff = "hard"
    elif _SIMPLE.search(q) and len(q) < 80 and not attachments:
        diff = "simple"
    else:
        diff = "moderate"
    return {
        "difficulty": diff,
        "confidence": ROUTE_CONF_MIN,  # 상향 보정 없이 규칙 결과 그대로 사용
        "needs_current_info": 0.7 if _WEB.search(q) else 0.1,
        "needs_exact_calc": 0.8 if _CALC.search(q) else 0.1,
        "wants_file_output": 0.8 if _FILE.search(q) else 0.1,
    }


# ───────────── 공개 함수 ─────────────
def route(question: str, history: list, attachments: list):
    """returns (tier_index, use_web, wants_file, info_dict)"""
    judge = "groq"
    try:
        a = _groq(ROUTE_PROMPT, _context({"user_question": question}, history, attachments))
        diff = a["difficulty"]
        tier = {"simple": 0, "moderate": 1, "hard": 2}[diff]
        conf = _p(a.get("confidence", 1))
        web_p, calc_p, file_p = (_p(a[k]) for k in ("needs_current_info", "needs_exact_calc", "wants_file_output"))
    except Exception as e:  # 키 없음·한도 초과·응답 형식 오류 → 규칙 기반
        judge = f"rules ({type(e).__name__})"
        a = _rule_route(question, attachments)
        diff, conf = a["difficulty"], a["confidence"]
        tier = {"simple": 0, "moderate": 1, "hard": 2}[diff]
        web_p, calc_p, file_p = a["needs_current_info"], a["needs_exact_calc"], a["wants_file_output"]

    if conf < ROUTE_CONF_MIN:
        tier = min(tier + 1, 2)
    if calc_p >= EXACT_CALC_MIN:
        tier = max(tier, 1)  # 정밀 계산은 Haiku 제외
    info = {
        "judge": judge,
        "difficulty": diff,
        "conf": round(conf, 2),
        "web_p": round(web_p, 2),
        "calc_p": round(calc_p, 2),
        "file_p": round(file_p, 2),
    }
    return tier, web_p >= NEEDS_WEB_MIN, file_p >= FILE_OUTPUT_MIN, info


def verify(question: str, answer: str, history: list, attachments: list):
    """0~1 반환. 판정 실패 시 None (통과 처리하되 캐시하지 않음)."""
    try:
        a = _groq(
            VERIFY_PROMPT,
            _context({"question": question, "answer": answer[:JUDGE_MAX_CHARS]}, history, attachments),
        )
        return _p(a["answers_fully"])
    except Exception:
        return None
