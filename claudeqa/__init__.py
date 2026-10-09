"""판정 모델(Groq) + Claude(생성) 질의응답 파이프라인."""

import os
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
KEYS = ("ANTHROPIC_API_KEY", "GROQ_API_KEY")

# 프로젝트 폴더의 .env에서 API 키를 읽는다.
# 실행 위치와 상관없이 이 경로를 쓰고, 셸에 빈 값으로 잡힌 변수는 .env 값으로 덮어쓴다.
if ENV_FILE.is_file():
    for _k, _v in dotenv_values(ENV_FILE, encoding="utf-8-sig").items():
        if _v and _v.strip() and not os.environ.get(_k, "").strip():
            os.environ[_k] = _v.strip()


def env_report() -> str:
    """시작 시 키 설정 상태 (키 값 자체는 출력하지 않음)."""
    lines = [f".env 위치: {ENV_FILE} ({'있음' if ENV_FILE.is_file() else '없음'})"]
    if not ENV_FILE.is_file():
        near = [p.name for p in ROOT.glob(".env*") if p.name != ".env.example"] + \
               [p.name for p in ROOT.glob("env*")]
        if near:
            lines.append(f"  비슷한 파일 발견: {', '.join(near)} → 이름을 정확히 '.env'로 바꾸세요")
    else:
        names = list(dotenv_values(ENV_FILE, encoding="utf-8-sig"))
        unknown = [n for n in names if n not in KEYS and n != "GROQ_MODEL"]
        if unknown:
            lines.append(f"  .env에 알 수 없는 이름: {', '.join(unknown)} → 철자 확인 ({', '.join(KEYS)})")
    for k in KEYS:
        v = os.environ.get(k, "").strip()
        lines.append(f"  {k}: " + (f"설정됨 ({v[:7]}…, {len(v)}자)" if v else "없음"))
    return "\n".join(lines)
