"""간호조무사 딥리서처 — 코디네이터 + 서브에이전트 (LangGraph).

① plan → ② dispatch ─Send×N→ ③ researcher → ④ review ─(부족 신고)→ ② … → ⑤ synthesize → ⑥ evaluate
뼈대는 수업(11/4·11/5) 통합 코드와 같고, 바꾼 것은 도메인 값(역할 명단·카드의 과목 표시·지시문)과
아래 네 가지다.
  · 배정 검사 결과를 버리지 않고 plan["배정오류"] 로 남긴다 (모델이 지어낸 제목을 세기 위해)
  · 재위임 원고가 인용을 잃으면 옛 원고를 지킨다 (metrics.절모음)
  · 실행 기록 전체(목차·절별 읽은 문서·메모·원고·자기신고)를 dict 로 돌려준다 → output/ 과 app.py
  · 설정·역할 명단은 config.json 한 곳에서 읽는다
"""
import json, operator, os, re, sys, time
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

import metrics as M

HERE = Path(__file__).resolve().parent
CORPUS = json.loads((HERE / "data" / "corpus.json").read_text(encoding="utf-8"))
DOCS, LINKS = CORPUS["docs"], CORPUS["links"]
META = json.loads((HERE / "data" / "meta.json").read_text(encoding="utf-8"))
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
설정 = dict(CONFIG["설정"])
ROSTER = CONFIG["역할명단"]
기본역할 = "큰그림 담당"

COST = {"calls": 0, "sub_chars": 0, "coord_chars": 0}
_llm = None


def llm():
    """키가 없어도 app.py 가 저장된 기록을 열 수 있도록, 모델은 처음 부를 때 만든다."""
    global _llm
    if _llm is None:
        from dotenv import load_dotenv
        from langchain_openai import ChatOpenAI
        load_dotenv(HERE / ".env")
        _llm = ChatOpenAI(model=os.getenv("LLM_MODEL", "gpt-4o-mini"), temperature=0,
                          timeout=90, max_retries=0)
    return _llm


일시적오류 = ("RateLimit", "APIConnection", "Timeout", "InternalServer")


def ask(system: str, user: str, coord: bool = False, cap: int = 60000) -> str:
    body = user[:cap]
    COST["calls"] += 1
    COST["coord_chars" if coord else "sub_chars"] += len(body)
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": body}]
    for 시도 in range(4):
        try:
            return llm().invoke(msgs).content
        except Exception as e:
            if 시도 == 3 or not any(k in type(e).__name__ for k in 일시적오류):
                raise
            time.sleep(2 ** (시도 + 1))


def jload(raw: str, default):
    try:
        m = re.search(r"\[.*\]" if isinstance(default, list) else r"\{.*\}", raw, re.S)
        return json.loads(m.group(0))
    except Exception:
        return default


class Research(TypedDict):
    question: str
    plan: dict
    sections: Annotated[list, operator.add]
    visited: Annotated[list, operator.add]
    report: str
    metrics: dict
    log: Annotated[list, operator.add]
    task: dict
    prior: dict


# ── ① 기획 ────────────────────────────────────────────────────────────
def cards() -> str:
    """코디네이터는 원문을 읽지 않는다 — 제목 · 과목 · 앞 N자 카드만 본다."""
    n = 설정["카드길이"]
    # 과목 표시를 제목 앞에 둔다 — 뒤에 두면 모델이 '결핵 [공중보건학 개론]' 을 제목으로 베껴 적는다(첫 실행에서 3건).
    return "\n".join(f"- ({META.get(t, {}).get('과목', '?')}) {t}: {re.sub(chr(10), ' ', v[:n])}"
                     for t, v in DOCS.items())


def plan(s: dict) -> dict:
    roster = "\n".join(f"- {k}: {v}" for k, v in ROSTER.items())
    raw = ask(
        "너는 간호조무사 국가시험 대비 리서치 팀의 코디네이터다. 아래 질문에 답하는 학습 보고서의 목차를 "
        f"짜고, 각 절을 리서처 에이전트 하나에게 맡긴다. 절은 최대 {설정['절수']}개.\n"
        "목차는 반드시 **내용 단위**로 나눠라 — 질환·대상자·술기·제도처럼 질문이 실제로 묻는 덩어리로 "
        "쪼갠다. '개요·정의·분석·정리' 같은 형식 단위로 나누지 마라. 그렇게 나누면 리서처 전부가 같은 "
        "문서를 읽는다.\n"
        "절마다 그 절을 쓰는 데 가장 먼저 읽어야 할 문서를 문서 카드 목록에서 하나 배정하라. 절끼리 다른 "
        "문서를 주어라. 시작문서에는 괄호 속 과목 표시 없이 제목만, 목록에 있는 그대로 적어라.\n"
        f"절의 성격에 맞는 리서처를 명단에서 골라 붙여라.\n[리서처 명단]\n{roster}\n"
        'JSON으로만: {"제목":"보고서 제목","목차":[{"절":"절 제목","지시":"이 절에서 밝혀야 할 것 '
        '한두 문장","역할":"명단에 있는 이름 그대로","시작문서":"목록에 있는 제목"}]}',
        f"[질문] {s['question']}\n[읽을 수 있는 문서 카드]\n{cards()}", coord=True)
    obj = jload(raw, {})
    toc, taken, 오류 = [], set(), []
    for item in obj.get("목차", [])[:설정["절수"]]:
        role, seed = item.get("역할", ""), str(item.get("시작문서") or "")
        if 설정["배정"] and seed and seed not in DOCS:
            오류.append(seed)                      # 모델이 그럴듯한 제목을 지어냈다 — 코드가 거른다
        if not 설정["배정"] or seed not in DOCS or seed in taken:
            # 수업 코드는 여기서 '코퍼스 맨 앞의 안 쓴 문서'로 채웠다 — 결핵 질문에 «간호»«순환계» 가 배정됐다.
            # 엉뚱한 문서를 억지로 주느니 리서처가 직접 고르게(자율) 둔다.
            seed = ""
        if seed:
            taken.add(seed)
        toc.append({"절": item.get("절", "무제"), "지시": item.get("지시", s["question"]),
                    "역할": role if (설정["역할"] and role in ROSTER) else 기본역할,
                    "시작문서": seed, "예산": 설정["절예산"]})
    if not toc:
        toc = [{"절": "개요", "지시": s["question"], "역할": 기본역할, "시작문서": "",
                "예산": 설정["절예산"]}]
    p = {"제목": obj.get("제목", s["question"]), "목차": toc, "배치": list(range(len(toc))),
         "바퀴": 1, "배정오류": 오류}
    seeds = " · ".join(f"{t['역할']}→«{t['시작문서'] or '자율'}»" for t in toc)
    log = [f"① 기획   목차 {len(toc)}절 · {seeds}"]
    if 오류:
        log.append(f"   ⚠ 배정 검사: 코퍼스에 없는 제목 {len(오류)}건을 걸러 냄 — {', '.join(오류)}")
    return {"plan": p, "log": log}


# ── ② 배치 ────────────────────────────────────────────────────────────
def dispatch(s: dict) -> dict:
    n, w = len(s["plan"].get("배치", [])), s["plan"].get("바퀴", 1)
    return {"log": [f"② 배치   {w}라운드 · 서브에이전트 {n}개 동시 파견"]}


def fanout(s: dict):
    idxs = s["plan"].get("배치", [])
    if not idxs:
        return "review"
    done = M.절모음(s["sections"])
    사절 = s["plan"]["목차"]
    sends = []
    for i in idxs:
        mine = 사절[i]["절"]
        남의구역 = {t["시작문서"] for j, t in enumerate(사절) if j != i and t["시작문서"]}
        남의구역 |= {d for name, sec in done.items() if name != mine for d in sec["읽은문서"]}
        sends.append(Send("researcher", {
            "question": s["question"],
            "task": {**사절[i], "번호": i, "라운드": s["plan"].get("바퀴", 1),
                     "피하기": sorted(남의구역) if 설정["구역"] else []},
            "prior": done.get(mine, {})}))
    return sends


# ── ③ 조사 ────────────────────────────────────────────────────────────
def read_one(title: str, brief: str) -> str:
    return ask("너는 자료 조사 담당이다. 아래 문서를 읽고 지시에 관련된 내용만 여섯 문장 이내로 간추려라. "
               "수치·기준·순서가 있으면 그대로 옮겨라. 관련 없으면 '관련 없음'이라고만 답하라.\n"
               f"[지시] {brief}", f"[문서: {title}]\n{DOCS[title]}")


CAND_MAX = 100   # 수업 코드는 60 — 코퍼스가 69건이라 맨 뒤 실기 문서 9건이 후보에서 늘 잘렸다


def 후보목록(read: list, 피하기: list) -> list:
    쓴것 = set(read) | set(피하기)
    frontier = sorted({x for v in read for x in LINKS.get(v, []) if x in DOCS} - 쓴것)
    return frontier or [x for x in DOCS if x not in 쓴것] or [x for x in DOCS if x not in read]


def 역할문장(t: dict) -> str:
    return f"너는 {t['역할']}이다. {ROSTER.get(t['역할'], ROSTER[기본역할])}."


def 링크밖(read: list, 피하기: list) -> list:
    쓴것 = set(read) | set(피하기)
    return [x for x in DOCS if x not in 쓴것] or [x for x in DOCS if x not in read]


def 다음문서(t: dict, read: list, 피하기: list) -> str | None:
    """링크 후보에서 먼저 고르고, '더 없다'고 하면 링크 밖 후보로 넓혀 한 번 더 묻는다.
    (「결핵」은 「대한민국 질병관리청」을 링크하지 않는다 — 링크만 보면 법규 담당이 첫 문서 뒤에 멈췄다.)"""
    cand = 후보목록(read, 피하기)
    for 후보, 이름 in ((cand, "후보"), (링크밖(read, 피하기), "링크 밖 후보")):
        if 이름 == "링크 밖 후보" and set(후보) <= set(cand):
            break                                      # 이미 전체를 보여 줬다
        raw = ask(f"{역할문장(t)} 맡은 절을 쓰기 위해 다음에 읽을 문서를 {이름} 중에서 정확히 하나 고른다. "
                  "더 읽을 것이 없으면 그만둔다.\n"
                  'JSON으로만: {"문서":"후보에 있는 제목"} 또는 {"문서":null}',
                  f"[맡은 절] {t['절']}\n[지시] {t['지시']}\n"
                  f"[이미 읽음] {', '.join(read) or '없음'}\n[{이름}] {', '.join(후보[:CAND_MAX])}")
        pick = str(jload(raw, {}).get("문서") or "")
        if pick in DOCS and pick not in read:
            return pick
    return None


def 탐색(t: dict, prior: dict) -> tuple[list, list]:
    read, notes = list(prior.get("읽은문서", [])), list(prior.get("메모", []))
    피하기 = t.get("피하기") or []
    다음 = t.get("시작문서") if t.get("시작문서") in DOCS else None
    for _ in range(t["예산"]):
        if 다음 is None or 다음 in read:
            다음 = 다음문서(t, read, 피하기)
        if 다음 is None:
            break
        notes.append([다음, read_one(다음, t["지시"])])
        read.append(다음)
        다음 = None
    return read, notes


def 집필(t: dict, notes: list) -> dict:
    자료 = "\n\n".join(f"[{d}]\n{n}" for d, n in notes) or "(읽은 자료 없음)"
    raw = ask(f"{역할문장(t)} 아래 자료만 근거로 간호조무사 시험 대비 학습 보고서의 한 절을 써라. "
              "여섯 문장 이상 열두 문장 이하, 600자 이상. 문장마다 근거가 된 문서 제목을 «문서명» 으로 "
              "붙이되, 마침표 앞에 붙여라(예: …이다 «결핵».). 자료에 없는 내용은 쓰지 마라. 지시를 자료로 "
              "다 채우지 못했으면 충분을 false 로 하고 무엇이 비었는지 적어라(문장 수 같은 형식 말고 "
              "내용).\n"
              'JSON으로만: {"본문":"...","충분":true,"부족":""}',
              f"[맡은 절] {t['절']}\n[지시] {t['지시']}\n[모은 자료]\n{자료}")
    obj = jload(raw, None)
    if obj is None:                                  # JSON 이 깨졌을 때만 원문에서 건진다
        text = re.sub(r'^\s*\{.*?"본문"\s*:\s*"?', "", raw, flags=re.S)[:2000].strip()
        return {"본문": text, "충분": False, "부족": "원고 형식(JSON)이 깨짐"}
    # 모델이 본문을 비워 냈으면 비운 채로 둔다 — 찌꺼기를 원고로 채우면 '인용 0인 절' 경보가 흐려진다
    return {"본문": str(obj.get("본문") or ""), "충분": bool(obj.get("충분")),
            "부족": str(obj.get("부족") or "")}


def researcher(s: dict) -> dict:
    t = s["task"]
    read, notes = 탐색(t, s.get("prior") or {})
    원고 = 집필(t, notes)
    인용 = M.CITE.findall(원고["본문"])
    sec = {"번호": t["번호"], "절": t["절"], "역할": t["역할"], "지시": t["지시"],
           "시작문서": t.get("시작문서", ""), "피하기": t.get("피하기", []), "라운드": t.get("라운드", 1),
           "본문": 원고["본문"], "읽은문서": read, "메모": notes, "인용": 인용,
           "허위인용": sorted({c for c in 인용 if c not in read}),
           "충분": 원고["충분"], "부족": 원고["부족"]}
    mark = "충분" if sec["충분"] else f"부족({sec['부족'][:18]})"
    return {"sections": [sec], "visited": [[t["절"], d] for d in read],
            "log": [f"   ③ {t['역할']} «{t['절'][:14]}» {len(read)}건 읽고 {len(원고['본문'])}자 · "
                    f"인용 {len(인용)}곳 · {mark}"]}


# ── ④ 점검 ────────────────────────────────────────────────────────────
def review(s: dict) -> dict:
    latest = M.절모음(s["sections"])
    toc, wheel = s["plan"]["목차"], s["plan"].get("바퀴", 1)
    if not 설정["재위임"] or wheel >= 설정["최대바퀴"]:
        gaps = []
    else:
        gaps = [i for i, t in enumerate(toc) if not latest.get(t["절"], {}).get("충분", False)]
    if not gaps:
        why = "루프 없음" if not 설정["재위임"] else ("라운드 소진" if wheel >= 설정["최대바퀴"] else "빈 칸 없음")
        return {"plan": {**s["plan"], "배치": [], "종료": why},
                "log": [f"④ 점검   {len(toc)}절 중 빈 칸 0개 — 종합으로 ({why})"]}
    newtoc = [dict(t) for t in toc]
    for i in gaps:
        prev = latest.get(toc[i]["절"], {})
        newtoc[i]["지시"] = (f"{toc[i]['지시']} (재위임: 지난번에 «{'», «'.join(prev.get('읽은문서', [])) or '없음'}» "
                             f"를 읽었지만 {prev.get('부족', '근거가 모자랐다')}. 그 빈 칸을 채우도록 "
                             "아직 안 본 문서를 찾아라)")
    return {"plan": {**s["plan"], "목차": newtoc, "배치": gaps, "바퀴": wheel + 1},
            "log": [f"④ 점검   {len(toc)}절 중 빈 칸 {len(gaps)}개 — "
                    f"«{'», «'.join(toc[i]['절'][:12] for i in gaps)}» 재위임"]}


def route(s: dict) -> str:
    return "more" if s["plan"].get("배치") else "done"


# ── ⑤ 종합 ────────────────────────────────────────────────────────────
def synthesize(s: dict) -> dict:
    order = sorted(M.절모음(s["sections"]).values(), key=lambda x: x["번호"])
    outline = "\n".join(f"{i+1}. {x['절']}: {x['본문'][:90]}…" for i, x in enumerate(order))
    raw = ask("너는 학습 보고서를 마무리하는 편집자다. 아래는 리서처들이 각자 쓴 절의 제목과 첫머리다. "
              "본문은 고치지 말고, 전체를 여는 머리말과 닫는 맺음말만 써라. 각각 세 문장 이내. "
              "새로운 사실을 덧붙이지 마라.\n"
              'JSON으로만: {"머리말":"...","맺음말":"..."}',
              f"[질문] {s['question']}\n[보고서 제목] {s['plan']['제목']}\n[절 목록]\n{outline}",
              coord=True)
    obj = jload(raw, {})
    parts = [f"# {s['plan']['제목']}", str(obj.get("머리말") or "")]
    for i, x in enumerate(order):
        parts.append(f"## {i+1}. {x['절']}  _({x['역할']})_\n\n{x['본문']}")
    parts.append(f"## 맺음말\n\n{obj.get('맺음말') or ''}")
    report = "\n\n".join(p for p in parts if p.strip())
    return {"report": report,
            "log": [f"⑤ 종합   {len(order)}절 이어붙임 → 보고서 {len(report):,}자 (편집자는 절 첫머리만 봤다)"]}


# ── ⑥ 평가 ────────────────────────────────────────────────────────────
def evaluate(s: dict) -> dict:
    m = M.evaluate(s["visited"], s["report"], s["sections"], DOCS, COST, s["plan"].get("배정오류"))
    return {"metrics": m, "log": [f"⑥ 평가   {M.한줄(m)}"]}


NODES = {"plan": plan, "dispatch": dispatch, "researcher": researcher, "review": review,
         "synthesize": synthesize, "evaluate": evaluate}


def build():
    g = StateGraph(Research)
    for name, fn in NODES.items():
        g.add_node(name, fn)
    g.add_edge(START, "plan")
    g.add_edge("plan", "dispatch")
    g.add_conditional_edges("dispatch", fanout, ["researcher", "review"])
    g.add_edge("researcher", "review")
    g.add_conditional_edges("review", route, {"more": "dispatch", "done": "synthesize"})
    g.add_edge("synthesize", "evaluate")
    g.add_edge("evaluate", END)
    return g.compile()


def run(question: str) -> dict:
    """한 번 실행하고 기록 전체를 돌려준다."""
    COST.update(calls=0, sub_chars=0, coord_chars=0)
    t0 = time.time()
    out = build().invoke({"question": question, "plan": {}, "sections": [], "visited": [],
                          "report": "", "metrics": {}, "log": [], "task": {}, "prior": {}},
                         {"recursion_limit": 100})
    return {"구조": "팀", "질문": question, "설정": dict(설정), "목차": out["plan"].get("목차", []),
            "종료": out["plan"].get("종료", ""), "배정오류": out["plan"].get("배정오류", []),
            "파견": out["sections"], "최종보고서": out["report"], "지표": out["metrics"],
            "로그": out["log"], "비용": dict(COST), "초": round(time.time() - t0, 1),
            "코퍼스": {"문서수": len(DOCS), "총글자": sum(len(v) for v in DOCS.values())}}


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    q = " ".join(sys.argv[1:]) or "결핵은 어떻게 전파되고, 환자 간호와 법적 신고·관리는 어떻게 하나?"
    r = run(q)
    print("\n".join(r["로그"]))
    print(f"\n코디네이터가 본 글자 {r['비용']['coord_chars']:,} · 리서처가 본 글자 {r['비용']['sub_chars']:,} · "
          f"코퍼스 {r['코퍼스']['총글자']:,}자 · {r['초']}초")
