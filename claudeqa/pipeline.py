"""
흐름:
  1) 캐시 조회 (같은 질문 → API 호출 0회)
  2) 판정(Groq) 라우팅: 난이도 / 최신정보 / 정밀 계산 / 파일 생성 요청 여부  (1회 요청)
  3) 난이도에 맞는 Claude 모델로 답변 (Haiku → Sonnet → Opus)
     파일·차트 요청이나 데이터 파일 첨부 시 코드 실행 도구 사용
  4) 판정(Groq) 검증: 답변이 질문에 충분히 답했는지
  5) 검증 미달·잘림·거절이면 한 단계 위 모델로 1회만 재시도
"""

import os
import time
from dataclasses import dataclass, field

from . import cache
from .claude import ask_claude, build_user_content, download_files
from .config import HISTORY_MAX, TIERS, VERIFY_PASS_MIN
from .judge import route, verify


@dataclass
class Session:
    history: list = field(default_factory=list)   # Claude에 넘길 텍스트 대화 기록
    container_id: str | None = None                # 코드 실행 컨테이너 (후속 요청에서 파일 재사용)

    def reset(self):
        self.history, self.container_id = [], None


@dataclass
class Result:
    text: str
    files: list = field(default_factory=list)      # 생성된 파일 로컬 경로
    info: dict = field(default_factory=dict)

    def info_line(self) -> str:
        i = self.info
        if i.get("cache"):
            return "[cache hit]"
        score = i["verify"]
        return (
            f"[route {i['route']}] [model {i['model']}{' ↑' if i['escalated'] else ''}] "
            f"[web {i['web']}] [code {i['code']}] [stop {i['stop']}] "
            f"[verify {'n/a' if score is None else f'{score:.2f}'}] "
            f"[tok in {i['tok_in']} / out {i['tok_out']}] [{i['secs']:.1f}s]"
        )


def answer(question: str, session: Session, attachments: list | None = None) -> Result:
    t0 = time.time()
    attachments = attachments or []
    names = [os.path.basename(p) for p in attachments]
    history = session.history

    if not history and not attachments and (hit := cache.cache_get(question)):
        return _finish(session, question, names, Result(hit, info={"cache": True}))

    tier, use_web, wants_file, route_info = route(question, history, names)
    content, needs_code = build_user_content(question, attachments)
    use_code = wants_file or needs_code
    if use_code:
        tier = max(tier, 1)  # 코드 실행·파일 생성은 Sonnet 이상
    msgs = history + [{"role": "user", "content": content}]

    tok_in = tok_out = 0
    escalated = False
    while True:
        r = ask_claude(msgs, tier, use_web, use_code, session.container_id)
        session.container_id = r.container_id or session.container_id
        tok_in, tok_out = tok_in + r.tok_in, tok_out + r.tok_out
        text = r.text
        # 잘림·거절은 검증 없이 미달로 처리
        if r.stop in ("end_turn", "stop_sequence") and (text or r.file_ids):
            checked = text + (f"\n\n[generated files: {len(r.file_ids)}]" if r.file_ids else "")
            score = verify(question, checked, history, names)
        else:
            score = 0.0
        if score is None or score >= VERIFY_PASS_MIN or tier >= 2 or escalated:
            break
        tier += 1
        escalated = True

    # 최종 시도에서 만든 파일만 내려받음 (재시도 전 실패한 시도의 파일은 버림)
    files = download_files(r.file_ids) if r.file_ids else []
    if not text and not files:
        text = "이 요청에는 답변할 수 없습니다." if r.stop == "refusal" else "답변을 생성하지 못했습니다."

    result = Result(text, files, {
        "route": route_info, "model": TIERS[tier], "escalated": escalated,
        "web": use_web, "code": use_code, "stop": r.stop, "verify": score,
        "tok_in": tok_in, "tok_out": tok_out, "secs": time.time() - t0,
    })
    # 첫 질문 + 첨부·웹검색·파일생성 없음 + 검증 실제 통과한 답변만 캐시
    if (not history and not attachments and not use_web and not use_code
            and score is not None and score >= VERIFY_PASS_MIN):
        cache.cache_put(question, text)
    return _finish(session, question, names, result)


def _finish(session: Session, question: str, names: list, result: Result) -> Result:
    """다음 턴 문맥용으로 텍스트만 기록 (첨부·생성 파일은 이름만 남김)."""
    q = question + (f"\n\n[첨부: {', '.join(names)}]" if names else "")
    a = result.text + (
        f"\n\n[생성 파일: {', '.join(os.path.basename(f) for f in result.files)}]" if result.files else ""
    )
    session.history = (session.history + [
        {"role": "user", "content": q},
        {"role": "assistant", "content": a},
    ])[-HISTORY_MAX:]
    return result
