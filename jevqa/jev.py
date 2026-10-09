import os

import requests

from .config import (
    EXACT_CALC_MIN, FILE_OUTPUT_MIN, JEV_MAX_CHARS, JEV_MODEL, JEV_TIMEOUT, JEV_URL,
    NEEDS_WEB_MIN, ROUTE_CONF_MIN,
)


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


def _state(base: dict, history: list, attachments: list) -> dict:
    """후속 질문("그거 더 자세히")을 Jev가 이해할 수 있도록 직전 대화 일부와 첨부 파일명을 붙인다."""
    if history:
        base["previous_turns"] = [
            {"role": m["role"], "content": m["content"][:2000]} for m in history[-2:]
        ]
    if attachments:
        base["attached_files"] = attachments
    return base


def route(question: str, history: list, attachments: list):
    """returns (tier_index, use_web, wants_file, info_dict)"""
    try:
        a = jev(
            _state({"user_question": question}, history, attachments),
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
                "wants_file_output": {
                    "type": "noul",
                    "instructions": "Does the user ask for a downloadable file or an image to be produced "
                    "(chart, graph, diagram, spreadsheet, document, slides, PDF, CSV)?",
                },
            },
        )
        d = a["difficulty"]
        tier = {"simple": 0, "moderate": 1, "hard": 2}[d["choice"]]
        conf = d.get("confidence", 1)
        web_p = a["needs_current_info"]["noul"]
        calc_p = a["needs_exact_calc"]["noul"]
        file_p = a["wants_file_output"]["noul"]
    except Exception as e:  # Jev 장애·응답 형식 오류 시 중간 모델로 폴백
        return 1, False, False, {"jev_error": str(e)}

    if conf < ROUTE_CONF_MIN:
        tier = min(tier + 1, 2)
    if calc_p >= EXACT_CALC_MIN:
        tier = max(tier, 1)  # 정밀 계산은 Haiku 제외
    info = {
        "difficulty": d["choice"],
        "conf": round(conf, 2),
        "web_p": round(web_p, 2),
        "calc_p": round(calc_p, 2),
        "file_p": round(file_p, 2),
    }
    return tier, web_p >= NEEDS_WEB_MIN, file_p >= FILE_OUTPUT_MIN, info


def verify(question: str, answer: str, history: list, attachments: list):
    """noul 확률(0~1) 반환. Jev 실패 시 None (통과 처리하되 캐시하지 않음)."""
    try:
        a = jev(
            _state({"question": question, "answer": answer[:JEV_MAX_CHARS]}, history, attachments),
            {
                "answers_fully": {
                    "type": "noul",
                    "instructions": "Does the answer directly and completely address what the question asks, "
                    "without obvious errors, contradictions, or evasion? A '[generated files: N]' note "
                    "means N files were actually produced and attached for the user.",
                }
            },
        )
        return a["answers_fully"]["noul"]
    except Exception:
        return None
