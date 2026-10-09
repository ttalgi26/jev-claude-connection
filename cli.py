"""
터미널 대화형 실행

  python cli.py          # 대화형
  python cli.py -v       # 라우팅/검증 수치 표시

명령:
  /new            새 대화
  /attach 경로    다음 질문에 파일 첨부 (여러 번 가능)
  /quit           종료
"""

import os
import sys

from jevqa.pipeline import Session, answer

VERBOSE = "-v" in sys.argv


def main():
    if not os.environ.get("TYPESAFE_API_KEY"):
        print("경고: TYPESAFE_API_KEY가 없어 Jev 라우팅/검증 없이 Sonnet으로만 동작합니다.")
    session, pending = Session(), []
    print("질문을 입력하세요. (/new 새 대화, /attach 경로 파일 첨부, /quit 종료)")
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
            session.reset()
            pending = []
            print("새 대화를 시작합니다.")
            continue
        if q.startswith("/attach "):
            path = os.path.expanduser(q[len("/attach "):].strip())
            if os.path.isfile(path):
                pending.append(path)
                print(f"첨부됨: {os.path.basename(path)}")
            else:
                print(f"파일이 없습니다: {path}")
            continue
        try:
            r = answer(q, session, pending)
        except Exception as e:
            print(f"\n오류: {e}")
            continue
        pending = []
        if VERBOSE:
            print("  " + r.info_line())
        print("\n" + r.text)
        for f in r.files:
            print(f"  📎 {f}")


if __name__ == "__main__":
    main()
