"""소거 실험 — 기본 / 스위치 하나 끔 / 단일 에이전트 대조군 × 질문 × 반복 → output/.

실행:  python ablation.py                     (questions.json 의 '실험' 표시 질문, 반복 2회)
       python ablation.py --q Q3 Q5 --rep 2 --off 재위임
이미 있는 output 파일은 건너뛴다(중간에 끊겨도 이어서 돈다).
늘 기본 설정에서 출발해 한 번에 하나만 끈다. 끈 스위치는 실행 기록의 '설정'에 그대로 남아,
"로그만 바뀌고 코드 경로는 그대로" 사고가 없었는지 기록으로 확인할 수 있다.
"""
import argparse, json, sys
from pathlib import Path

import graph as G
import baseline as B
import metrics as M

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
QUESTIONS = json.loads((HERE / "data" / "questions.json").read_text(encoding="utf-8"))
원본 = dict(G.설정)


def save(r: dict, name: str):
    OUT.mkdir(exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")


def load(name: str) -> dict | None:
    f = OUT / f"{name}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--q", nargs="*", help="질문 id (기본: 실험 표시된 것)")
    ap.add_argument("--rep", type=int, default=2)
    ap.add_argument("--off", nargs="*", default=["재위임"], help="하나씩 끌 스위치 이름들")
    a = ap.parse_args()
    qs = [q for q in QUESTIONS if (q["id"] in a.q if a.q else q.get("실험"))]
    for q in qs:
        for rep in range(1, a.rep + 1):
            # 기본
            name = f"{q['id']}_기본_{rep}"
            base = load(name)
            if base is None:
                G.설정.clear(); G.설정.update(원본)
                base = G.run(q["질문"]); save(base, name)
            print(f"{name:<22} {M.한줄(base['지표'])}", flush=True)
            # 스위치 하나씩 끔
            for sw in a.off:
                name = f"{q['id']}_{sw}끔_{rep}"
                if load(name) is None:
                    G.설정.clear(); G.설정.update(원본); G.설정[sw] = False
                    r = G.run(q["질문"]); save(r, name)
                    G.설정.clear(); G.설정.update(원본)
                print(f"{name:<22} {M.한줄(load(name)['지표'])}", flush=True)
            # 대조군 — 그 반복의 기본 실행이 실제로 읽은 만큼
            name = f"{q['id']}_단일_{rep}"
            if load(name) is None:
                save(B.run(q["질문"], base["지표"]["읽은문서"]), name)
            r = load(name)
            print(f"{name:<22} {M.한줄(r['지표'])} · 소진율 {r['지표']['소진율']}%", flush=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
