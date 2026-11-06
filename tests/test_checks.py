"""키 없이 도는 검사 — 경보 지표와 배정 검사가 실제로 잡는지 일부러 틀린 입력으로 확인한다.

실행:  python tests/test_checks.py      (또는 python -m pytest tests)
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import graph as G
import metrics as M


def test_배정검사가_지어낸_제목을_거른다():
    """P3 — 코디네이터가 코퍼스에 없는 제목을 배정하면 코드가 걸러 내고 기록한다."""
    가짜 = {"제목": "t", "목차": [
        {"절": "가", "지시": "x", "역할": "기초간호 담당", "시작문서": "결핵"},
        {"절": "나", "지시": "x", "역할": "실기 절차 담당", "시작문서": "간호조무사 실기 핵심 요약"},  # 없는 제목
    ]}
    원래 = G.ask
    G.ask = lambda *a, **k: json.dumps(가짜, ensure_ascii=False)
    try:
        out = G.plan({"question": "q"})
    finally:
        G.ask = 원래
    p = out["plan"]
    assert p["배정오류"] == ["간호조무사 실기 핵심 요약"], p["배정오류"]
    assert p["목차"][0]["시작문서"] == "결핵"
    assert p["목차"][1]["시작문서"] == "", "걸러 낸 자리는 엉뚱한 문서 대신 자율(빈 값)이어야 한다"
    assert any("배정 검사" in line for line in out["log"])


def test_허위인용_경보가_뜬다():
    """P5 — 읽지 않은 문서를 인용하면 허위인용 경보가 1 이상."""
    보고서 = "결핵은 공기로 전파된다 «결핵». 손 위생이 중요하다 «개인 보호 장비»."
    sec = [{"절": "가", "인용": ["결핵", "개인 보호 장비"], "읽은문서": ["결핵"]}]
    m = M.evaluate([["가", "결핵"]], 보고서, sec, G.DOCS, {"calls": 1})
    assert m["허위인용"] == ["개인 보호 장비"], m["허위인용"]
    assert m["경보"] >= 1


def test_인용0절_경보가_뜬다():
    m = M.evaluate([["가", "결핵"]], "인용 없는 글이다. 아주 길게 쓴 문장이다.",
                   [{"절": "가", "인용": [], "읽은문서": ["결핵"]}], G.DOCS, {})
    assert m["인용0절"] == ["가"]


def test_재위임_원고가_인용을_잃으면_옛_원고를_지킨다():
    옛 = {"절": "가", "인용": ["결핵"], "본문": "옛"}
    새 = {"절": "가", "인용": [], "본문": "새"}
    assert M.절모음([옛, 새])["가"]["본문"] == "옛"
    assert M.절모음([새, 옛])["가"]["본문"] == "옛"


def test_보정_근거율은_마침표_뒤_인용을_앞_문장에_붙인다():
    글 = "결핵은 결핵균이 일으키는 감염병이다. «결핵»\n치료에는 여러 항생제를 함께 쓴다 «항생제»."
    _, 원래 = M.근거율(M.문장들(글), G.DOCS)
    _, 보정 = M.근거율(M.문장들_보정(글), G.DOCS)
    assert 원래 == 50.0 and 보정 == 100.0, (원래, 보정)


def test_지어낸숫자_경보는_원문에_없는_숫자를_잡는다():
    """직접 대조에서 찾은 실제 사례 — 「호흡계」 원문에는 '12'도 '분당'도 없다."""
    글 = ("정상 범위는 성인의 경우 분당 12-20회로 알려져 있다 «호흡계». "
          "8차 JNC는 60세 이상의 고혈압 기준을 150/90으로 완화했다 «고혈압».")
    잡힘 = {x["숫자"] for x in M.지어낸숫자(글, G.DOCS)}
    assert {"12", "20"} <= 잡힘, 잡힘
    assert not ({"60", "150", "90"} & 잡힘), "원문에 있는 숫자는 잡지 않아야 한다"


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print("PASS", name)
            except AssertionError as e:
                fails += 1; print("FAIL", name, e)
    sys.exit(1 if fails else 0)
