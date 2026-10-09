"""
웹 채팅 UI (Gradio)

  python app.py                  # http://127.0.0.1:7860
  python app.py --share          # 외부 공유 링크 생성
"""

import os
import sys

import gradio as gr

from claudeqa.config import OUTPUT_DIR
from claudeqa.pipeline import Session, answer

ACCEPT = [
    "image", ".pdf", ".csv", ".tsv", ".xlsx", ".xls", ".json", ".txt", ".md",
    ".docx", ".pptx", ".py", ".html", ".xml", ".zip",
]


def respond(msg, chat, session, show_info):
    text = (msg or {}).get("text", "").strip()
    files = (msg or {}).get("files", []) or []
    if not text and not files:
        yield chat, gr.update(), session
        return
    if not text:
        text = "첨부한 파일을 분석해줘."
    session = session or Session()

    user_content = [text] + [{"path": f} for f in files]
    chat = chat + [{"role": "user", "content": user_content}]
    yield chat, gr.update(value=None, interactive=False), session

    try:
        r = answer(text, session, files)
    except Exception as e:
        chat = chat + [{"role": "assistant", "content": f"⚠️ 오류: {e}"}]
        yield chat, gr.update(interactive=True), session
        return

    if show_info:
        chat = chat + [{
            "role": "assistant",
            "content": r.info_line(),
            "metadata": {"title": "라우팅 정보", "status": "done"},
        }]
    chat = chat + [{"role": "assistant", "content": [r.text] + [{"path": f} for f in r.files]}]
    yield chat, gr.update(interactive=True), session


def new_chat():
    return [], None


with gr.Blocks(title="Claude QA") as demo:
    gr.Markdown(
        "## Claude QA\n"
        "질문 난이도에 따라 Haiku / Sonnet / Opus 중 하나를 자동으로 고릅니다. "
        "차트·도표·다이어그램 이미지와 docx / xlsx / pptx / pdf / csv 파일을 만들 수 있고, "
        "이미지·PDF·데이터 파일을 첨부할 수 있습니다."
    )
    session = gr.State(None)  # 브라우저 탭마다 Session 하나 (첫 질문 때 생성)
    chatbot = gr.Chatbot(height=620, placeholder="무엇이든 물어보세요.")
    box = gr.MultimodalTextbox(
        file_count="multiple",
        file_types=ACCEPT,
        sources=["upload"],
        placeholder="질문 입력 (Enter 전송, 📎 파일 첨부)",
        show_label=False,
    )
    with gr.Row():
        show_info = gr.Checkbox(label="라우팅 정보 표시", value=False)
        clear = gr.Button("새 대화", size="sm")

    gr.Examples(
        examples=[
            {"text": "2020~2025년 한국 GDP 성장률을 막대 차트 이미지로 만들어줘"},
            {"text": "주간 업무 보고서 양식을 docx 파일로 만들어줘"},
            {"text": "월별 가계부 템플릿을 xlsx로 만들어줘. 합계 수식 포함해서"},
            {"text": "로그인 처리 흐름을 다이어그램 이미지로 그려줘"},
        ],
        inputs=box,
    )

    box.submit(respond, [box, chatbot, session, show_info], [chatbot, box, session])
    clear.click(new_chat, None, [chatbot, session])


if __name__ == "__main__":
    if not os.environ.get("GROQ_API_KEY"):
        print("경고: GROQ_API_KEY가 없어 규칙 기반 라우팅으로 동작하고 답변 검증은 건너뜁니다.")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    demo.queue().launch(share="--share" in sys.argv, allowed_paths=[OUTPUT_DIR])
