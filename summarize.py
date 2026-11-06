"""output/ 의 실행 기록 → REPORT 에 넣을 비교표(마크다운). 손으로 옮기지 않는다.

실행:  python summarize.py > output/_summary.md
값은 반복마다 따로 적고(1회 / 2회) 평균을 붙인다 — 한 번의 차이로 방향을 단정하지 않기 위해서다.
"""
import json, sys
from collections import defaultdict
from pathlib import Path

import metrics as M

OUT = Path(__file__).resolve().parent / "output"
DOCS = json.loads((OUT.parent / "data" / "corpus.json").read_text(encoding="utf-8"))["docs"]
QS = {q["id"]: q for q in json.loads((OUT.parent / "data" / "questions.json").read_text(encoding="utf-8"))}
ORDER = ["기본", "배정끔", "재위임끔", "단일"]
COLS = [("근거율", "근거율 %"), ("읽은문서", "읽은 문서"), ("인용문서수", "인용된 문서 수"), ("인용편중", "편중 %"),
        ("중복률", "중복 %"), ("보고서자수", "보고서 자"), ("LLM호출", "LLM 호출"), ("격리율", "격리율 %")]


def main():
    runs = defaultdict(dict)
    for f in sorted(OUT.glob("Q*_*.json")):
        qid, 설정, rep = f.stem.split("_")
        runs[(qid, 설정)][int(rep)] = json.loads(f.read_text(encoding="utf-8"))
    for qid in sorted({k[0] for k in runs}, key=lambda x: int(x[1:])):
        q = QS[qid]
        print(f"\n### {qid} ({q['유형']}) {q['질문']}\n")
        print("| 설정 | 경보 (허위·인용0절·배정오류·지어낸숫자) | "+ " | ".join(c[1] for c in COLS) + " | 대조군 소진율 |")
        print("|---|---|" + "---|" * len(COLS) + "---|")
        for s in ORDER:
            reps = runs.get((qid, s), {})
            if not reps:
                continue
            ms = [reps[r]["지표"] for r in sorted(reps)]
            # 지어낸 숫자는 실험 도중 더한 지표라 저장된 보고서에서 다시 잰다
            숫자 = [len(M.지어낸숫자(reps[r]["최종보고서"], DOCS)) for r in sorted(reps)]
            경보 = " / ".join(f"{len(m['허위인용'])}·{len(m['인용0절'])}·{len(m['배정오류'])}·{n}"
                            for m, n in zip(ms, 숫자))
            cells = []
            for k, _ in COLS:
                vals = [m[k] for m in ms]
                avg = sum(vals) / len(vals)
                cells.append(" / ".join(f"{v:g}" for v in vals) + (f" (평균 {avg:.1f})" if len(vals) > 1 else ""))
            소진 = " / ".join(f"{m['소진율']:g}%" for m in ms) if s == "단일" else "-"
            print(f"| {s} | {경보} | " + " | ".join(cells) + f" | {소진} |")
    print("\n값은 `1회 / 2회 (평균)`. 경보는 반복마다 `허위·인용0절·배정오류·지어낸숫자` 개수.")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
