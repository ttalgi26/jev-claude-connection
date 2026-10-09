import os

# ───────────── 판정 모델 (Groq 무료 API) ─────────────
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
JUDGE_TIMEOUT = 10         # 초. 실패 시 규칙 기반 판정으로 폴백
JUDGE_MAX_CHARS = 12000    # 무료 티어 분당 토큰 한도 대비 답변 자르기

# ───────────── 라우팅 기준 ─────────────
ROUTE_CONF_MIN = 0.60      # 라우팅 신뢰도가 이보다 낮으면 한 단계 위 모델 사용
NEEDS_WEB_MIN = 0.60       # 최신정보 필요 확률이 이 이상이면 웹검색 켬
EXACT_CALC_MIN = 0.70      # 정밀 계산 필요 확률이 이 이상이면 Haiku 제외
FILE_OUTPUT_MIN = 0.50     # 파일/차트 생성 요청 확률이 이 이상이면 코드 실행 켬
VERIFY_PASS_MIN = 0.75     # 검증 통과 기준 (noul 확률)

# ───────────── Claude ─────────────
TIERS = ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]
# 5.5 계열은 adaptive thinking이 기본으로 켜져 있고, thinking 토큰도 max_tokens에 포함된다.
MAX_TOKENS = {0: 4096, 1: 8192, 2: 16000}
MAX_TOKENS_CODE = 16000    # 코드 실행(파일 생성) 시 최소값
# 티어별 사고 깊이 (Haiku/Opus 5.5 기본값은 medium, Sonnet 5.5는 high)
EFFORT = {0: "low", 1: "medium", 2: "high"}

# 웹검색 도구. 동적 필터링 버전(20260209)은 Sonnet/Opus 5.5 지원.
# Haiku, 그리고 코드 실행과 함께 쓸 때는 기본 버전 사용
# (20260209는 내부적으로 코드 실행을 쓰므로 별도 code_execution과 같이 넣으면 모델이 혼동).
WEB_SEARCH_BASIC = {"type": "web_search_20250305", "name": "web_search", "max_uses": 3}
WEB_SEARCH_DYNAMIC = {"type": "web_search_20260209", "name": "web_search", "max_uses": 3}
CODE_EXEC_TOOL = {"type": "code_execution_20260521", "name": "code_execution"}
MAX_CONTINUATIONS = 5      # 서버측 도구 pause_turn 재개 최대 횟수

# 안전 분류기 거절 시 서버측 대체 모델로 자동 재실행 (Sonnet/Opus만 지원, Haiku는 미지원)
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = (
    "You are a precise assistant. Answer in the user's language. "
    "Lead with the answer, then only the reasoning needed. "
    "If you are not sure, say so instead of guessing. "
    "For calculations, show the key steps and double-check the result."
)
SYSTEM_PROMPT_CODE = (
    " When the user asks for a file, chart, table image or diagram, create it with the code "
    "execution tool (matplotlib for charts and diagrams, python-docx, openpyxl, python-pptx, "
    "reportlab or pandas for documents) and save it with a short descriptive filename. "
    "Then briefly say what you created. Do not paste the file contents into the answer."
)

# ───────────── 파일 ─────────────
OUTPUT_DIR = os.path.abspath(os.environ.get("CLAUDEQA_OUTPUT_DIR", "outputs"))
IMAGE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp",
}

# ───────────── 캐시 ─────────────
CACHE_DB = os.environ.get("CLAUDEQA_CACHE_DB", "qa_cache.sqlite")
CACHE_TTL = 7 * 24 * 3600  # 초. 오래된 캐시 답변은 무시

HISTORY_MAX = 12           # 최근 6턴만 유지 → 입력 토큰 절감
