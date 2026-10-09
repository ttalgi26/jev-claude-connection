import base64
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

from .config import (
    CODE_EXEC_TOOL, EFFORT, FALLBACK_BETA, IMAGE_TYPES, MAX_CONTINUATIONS, MAX_TOKENS,
    MAX_TOKENS_CODE, OUTPUT_DIR, SYSTEM_PROMPT, SYSTEM_PROMPT_CODE, TIERS, WEB_SEARCH_BASIC,
    WEB_SEARCH_DYNAMIC,
)

client = anthropic.Anthropic()


@dataclass
class ClaudeResult:
    text: str
    stop: str
    tok_in: int
    tok_out: int
    file_ids: list = field(default_factory=list)
    container_id: str | None = None


# ───────────── 첨부 파일 → 메시지 블록 ─────────────
def build_user_content(question: str, paths: list):
    """returns (content, needs_code)

    이미지·PDF는 메시지에 직접 넣고, 그 외 파일(csv, xlsx, txt 등)은 Files API로 올려
    코드 실행 컨테이너에 넣는다 → 코드 실행 필요.
    """
    if not paths:
        return question, False
    blocks, needs_code = [], False
    for p in paths:
        ext = Path(p).suffix.lower()
        if ext in IMAGE_TYPES:
            data = base64.standard_b64encode(Path(p).read_bytes()).decode()
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": IMAGE_TYPES[ext], "data": data}})
        elif ext == ".pdf":
            data = base64.standard_b64encode(Path(p).read_bytes()).decode()
            blocks.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}})
        else:
            uploaded = client.files.upload(file=Path(p))
            blocks.append({"type": "container_upload", "file_id": uploaded.id})
            needs_code = True
    blocks.append({"type": "text", "text": question})
    return blocks, needs_code


# ───────────── 생성 파일 수집·다운로드 ─────────────
def _file_ids(blocks) -> list:
    ids = []
    for b in blocks:
        if not b.type.endswith("code_execution_tool_result"):
            continue
        for item in getattr(b.content, "content", None) or []:
            fid = getattr(item, "file_id", None)
            if fid and fid not in ids:
                ids.append(fid)
    return ids


def download_files(file_ids: list) -> list:
    """생성된 파일을 OUTPUT_DIR에 저장하고 로컬 경로 목록 반환."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    paths = []
    for fid in file_ids:
        meta = client.files.retrieve_metadata(fid)
        name = os.path.basename(meta.filename)  # 경로 조작 방지
        if not name or name in (".", ".."):
            name = fid
        path = os.path.join(OUTPUT_DIR, f"{stamp}_{name}")
        n = 1
        while os.path.exists(path):
            path = os.path.join(OUTPUT_DIR, f"{stamp}_{n}_{name}")
            n += 1
        client.files.download(fid).write_to_file(path)
        paths.append(path)
    return paths


# ───────────── 요청 ─────────────
def _tools(tier: int, use_web: bool, use_code: bool):
    tools = []
    if use_code:
        tools.append(CODE_EXEC_TOOL)
    if use_web:
        tools.append(WEB_SEARCH_DYNAMIC if tier > 0 and not use_code else WEB_SEARCH_BASIC)
    return tools


def ask_claude(messages, tier: int, use_web: bool, use_code: bool, container: str | None = None) -> ClaudeResult:
    kwargs = dict(
        model=TIERS[tier],
        max_tokens=max(MAX_TOKENS[tier], MAX_TOKENS_CODE) if use_code else MAX_TOKENS[tier],
        system=SYSTEM_PROMPT + (SYSTEM_PROMPT_CODE if use_code else ""),
        output_config={"effort": EFFORT[tier]},
    )
    if tools := _tools(tier, use_web, use_code):
        kwargs["tools"] = tools
    if tier > 0:
        kwargs["betas"] = [FALLBACK_BETA]
        kwargs["fallbacks"] = "default"

    msgs = list(messages)
    content, tok_in, tok_out = [], 0, 0
    for _ in range(MAX_CONTINUATIONS + 1):
        if use_code and container:
            kwargs["container"] = container
        try:
            resp = client.beta.messages.create(messages=msgs, **kwargs)
        except anthropic.BadRequestError as e:
            # 이전 대화의 컨테이너가 만료된 경우 새 컨테이너로 한 번 더
            if kwargs.pop("container", None) and "container" in str(e).lower():
                container = None
                resp = client.beta.messages.create(messages=msgs, **kwargs)
            else:
                raise
        tok_in += resp.usage.input_tokens
        tok_out += resp.usage.output_tokens
        content += resp.content
        if getattr(resp, "container", None):
            container = resp.container.id
        if resp.stop_reason != "pause_turn":
            break
        # 서버측 도구 루프가 한도에 걸림 → 지금까지의 응답을 붙여 재개 ("계속" 메시지 추가 금지)
        msgs = list(messages) + [{"role": "assistant", "content": content}]

    text = "".join(b.text for b in content if b.type == "text").strip()
    return ClaudeResult(text, resp.stop_reason, tok_in, tok_out, _file_ids(content), container)
