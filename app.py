"""데모 — streamlit run app.py

보고서와 함께 '절마다 누가 무엇을 읽고 무엇을 썼는지'를 보여 준다. 숫자만 보여 주는 화면은 요점을 놓친다.
키가 없어도 output/ 의 저장된 실행을 열람할 수 있고, .env 에 키가 있으면 새 질문을 돌릴 수 있다.
"""
import json, re
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
CORPUS = json.loads((HERE / "data" / "corpus.json").read_text(encoding="utf-8"))
DOCS, LINKS = CORPUS["docs"], CORPUS["links"]
META = json.loads((HERE / "data" / "meta.json").read_text(encoding="utf-8"))
QUESTIONS = json.loads((HERE / "data" / "questions.json").read_text(encoding="utf-8"))
CITE = re.compile(r"«([^»]+)»")

import metrics as M


def md(text: str) -> str:
    """'120~130' 의 물결표가 마크다운 취소선이 되어 '120130' 으로 보이던 것을 막는다."""
    return (text or "").replace("~", "\\~")

st.set_page_config(page_title="간호조무사 딥리서처", page_icon="🩺", layout="wide")


def runs() -> dict:
    out = {}
    for f in sorted(OUT.glob("*.json")) if OUT.exists() else []:
        if not f.name.startswith("_"):
            out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    return out


def 지표판(m: dict, 단일: bool = False, report: str = ""):
    숫자 = M.지어낸숫자(report, DOCS)
    경보 = len(m["허위인용"]) + len(m["인용0절"]) + len(m.get("배정오류", [])) + len(숫자)
    c = st.columns(6)
    c[0].metric("경보 (0이어야 함)", 경보)
    c[1].metric("근거율 · 수업 규칙", f"{m['근거율']}%")
    c[2].metric("근거율 · 보정", f"{m['근거율_보정']}%")
    c[3].metric("읽은 문서", m["읽은문서"])
    c[4].metric("인용 편중", f"{m['인용편중']}%")
    c[5].metric("LLM 호출", m["LLM호출"])
    if 경보:
        st.error(f"허위 인용 {m['허위인용']} · 인용 0인 절 {m['인용0절']} · 배정 오류 {m.get('배정오류', [])} · "
                 f"인용한 문서에 없는 숫자 {len(숫자)}건")
        for x in 숫자:
            st.caption(md(f"⚠ 숫자 {x['숫자']} — «{'», «'.join(x['인용'])}» 원문에 없음: {x['문장']}"))
    if 단일:
        st.caption(f"대조군 예산 {m.get('예산')}건 · 소진율 {m.get('소진율')}% · 엉뚱한 선택 대체 {m.get('고르기대체')}회")
    else:
        st.caption(f"격리 — 코디네이터가 본 글자 {m['코디네이터본글자']:,} · 리서처들이 본 글자 {m['리서처본글자']:,} "
                   f"(격리율 {m['격리율']}%) · 코퍼스 {sum(len(v) for v in DOCS.values()):,}자 · "
                   f"중복률 {m['중복률']}% · 보고서 {m['보고서자수']:,}자")


def 절카드(r: dict):
    st.subheader("절마다 누가 무엇을 읽고 무엇을 썼나")
    if r["구조"] == "팀" and r.get("배정오류"):
        st.warning(f"① 기획에서 코디네이터가 코퍼스에 없는 제목을 배정 → 코드가 걸러 냄: {r['배정오류']}")
    for sec in sorted(r["파견"], key=lambda x: (x.get("번호", 0), x.get("라운드", 1))):
        인용 = [c for c in sec.get("인용", []) if c in DOCS]
        허위 = sec.get("허위인용", [])
        표 = "✅ 충분" if sec.get("충분") else f"🔁 부족 신고: {sec.get('부족', '')}"
        with st.expander(f"{sec.get('번호', 0) + 1}. {sec['절']} — {sec['역할']} · {sec.get('라운드', 1)}라운드 · "
                         f"{len(sec['읽은문서'])}건 읽음 · 인용 {len(인용)}곳 · {표}"):
            if sec.get("지시"):
                st.markdown(f"**지시** {sec['지시']}")
            if sec.get("시작문서") is not None and r["구조"] == "팀":
                st.markdown(f"**배정된 시작 문서** «{sec.get('시작문서') or '자율'}» · "
                            f"**피하기(남의 구역)** {', '.join(sec.get('피하기', [])) or '없음'}")
            st.markdown("**읽은 순서** " + " → ".join(
                f"«{d}» ({META.get(d, {}).get('과목', '')})" for d in sec["읽은문서"]))
            if 허위:
                st.error(f"읽지 않은 문서를 인용: {허위}")
            t1, t2 = st.tabs(["올린 원고", "읽으며 남긴 메모 (원문은 코디네이터에게 올라가지 않는다)"])
            t1.markdown(md(sec["본문"]))
            for d, n in sec.get("메모", []):
                t2.markdown(md(f"**«{d}»** — {n}"))


def 인용대조(r: dict):
    st.subheader("인용 대조 — 읽은 문서를 엉뚱한 문장에 붙였는지는 사람만 잡는다")
    메모 = {d: n for sec in r["파견"] for d, n in sec.get("메모", [])}
    문장 = [s for s in re.split(r"(?<=[.!?])\s+|\n", r["최종보고서"]) if CITE.search(s)]
    if not 문장:
        st.info("인용이 붙은 문장이 없다.")
        return
    i = st.slider("문장 고르기", 1, len(문장), 1, key=f"cite_{id(r)}") - 1
    st.markdown(md(f"> {문장[i]}"))
    for c in dict.fromkeys(CITE.findall(문장[i])):
        if c in DOCS:
            st.markdown(md(f"**«{c}» 리서처 메모** — {메모.get(c, '(이 실행의 메모에 없음)')}"))
            with st.popover(f"«{c}» 원문 앞부분"):
                st.write(DOCS[c][:1500])
        else:
            st.error(f"«{c}» 는 코퍼스에 없는 제목")


def 실행보기(r: dict, key: str):
    st.markdown(f"**질문** {r['질문']}  \n**구조** {r['구조']} · **설정** `{json.dumps(r['설정'], ensure_ascii=False)}` · "
                f"{r.get('초', '?')}초 · 종료 이유: {r.get('종료') or '-'}")
    지표판(r["지표"], r["구조"] != "팀", r["최종보고서"])
    t1, t2, t3, t4 = st.tabs(["보고서", "절별 과정", "인용 대조", "로그"])
    with t1:
        st.markdown(md(r["최종보고서"]))
    with t2:
        절카드(r)
    with t3:
        인용대조(r)
    with t4:
        st.code("\n".join(r["로그"]), language=None)


st.title("🩺 간호조무사 국가시험 딥리서처")
st.caption("코디네이터 + 서브에이전트 · 한국어 위키백과 코퍼스 · 정답표 없이 코드로 재는 지표 · "
           "연습용 자료이며 의료 판단의 근거로 쓰지 말 것")

tab_saved, tab_side, tab_new, tab_corpus = st.tabs(["저장된 실행", "나란히 읽기", "새 질문 실행", "코퍼스"])
R = runs()

with tab_saved:
    if not R:
        st.info("output/ 에 저장된 실행이 없다. `python ablation.py` 로 만든다.")
    else:
        name = st.selectbox("실행 기록", list(R), format_func=lambda k: f"{k} — {R[k]['질문'][:40]}")
        실행보기(R[name], name)

with tab_side:
    if len(R) >= 2:
        a, b = st.columns(2)
        ka = a.selectbox("왼쪽", list(R), index=0, key="ka")
        kb = b.selectbox("오른쪽", list(R), index=min(len(R) - 1, 2), key="kb")
        for col, k in ((a, ka), (b, kb)):
            with col:
                m = R[k]["지표"]
                st.caption(f"{R[k]['구조']} · 근거율 {m['근거율']}% (보정 {m['근거율_보정']}%) · 읽은 {m['읽은문서']}건 · "
                           f"경보 {len(m['허위인용']) + len(m['인용0절'])} · {m['보고서자수']:,}자")
                st.markdown(md(R[k]["최종보고서"]))

with tab_new:
    q = st.selectbox("질문 세트에서 고르기", [""] + [x["질문"] for x in QUESTIONS])
    q = st.text_input("또는 직접 쓰기", value=q)
    if st.button("실행 (약 1~2분, OpenAI 키 필요)", disabled=not q):
        try:
            import graph as G
            with st.spinner("코디네이터가 목차를 짜고 리서처들이 읽는 중…"):
                r = G.run(q)
            OUT.mkdir(exist_ok=True)
            (OUT / f"live_{len(list(OUT.glob('live_*.json'))) + 1}.json").write_text(
                json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
            실행보기(r, "live")
        except Exception as e:
            st.error(f"실행 실패: {type(e).__name__} — .env 의 OPENAI_API_KEY 를 확인할 것. {e}")

with tab_corpus:
    total = sum(len(v) for v in DOCS.values())
    st.markdown(f"**{len(DOCS)}건 · {total:,}자** — gpt-4o-mini 컨텍스트 창(128,000 토큰)에 한 번에 들어가지 않는다 "
                "(o200k_base 기준 토큰 수는 `python data/build_corpus.py` 출력).")
    rows = [{"제목": t, "과목": META[t]["과목"], "글자": len(DOCS[t]), "나가는 링크": len(LINKS[t]),
             "들어오는 링크": sum(t in v for v in LINKS.values()), "출처": META[t]["출처"], "url": META[t]["url"]}
            for t in DOCS]
    st.dataframe(rows, use_container_width=True, hide_index=True)
