"""대조군 — 나누지 않는 단일 에이전트. 같은 코퍼스 · 같은 모델 · 같은 도구(read_one · 후보목록) ·
같은 읽기 예산을 준다. 예산은 '팀이 그 실행에서 실제로 읽은 문서 수'로 맞춘다
(재위임으로 팀이 더 읽었으면 대조군도 그만큼 읽는다).

공정성 확인: 소진율 = 실제로 읽은 수 / 예산. 중간에 멈췄다면 상대를 묶어 둔 것이다.
"""
import sys, time

import graph as G
import metrics as M


def run(question: str, 예산: int) -> dict:
    G.COST.update(calls=0, sub_chars=0, coord_chars=0)
    t0 = time.time()
    읽음, 메모, 대체 = [], [], 0
    while len(읽음) < 예산:
        cand = G.후보목록(읽음, [])
        if not cand:
            break
        고름 = ""
        # 팀 리서처와 같은 규칙: 링크 후보 → (못 고르면) 링크 밖 후보. '이미 읽음'도 팀과 똑같이 보여 준다.
        for 후보, 이름 in ((cand, "후보"), (G.링크밖(읽음, []), "링크 밖 후보")):
            if 이름 == "링크 밖 후보" and set(후보) <= set(cand):
                break
            raw = G.ask("너는 자료 조사 오케스트레이터다. 질문에 답하려면 다음에 어느 문서를 읽어야 하는지 "
                        f"{이름} 중에서 정확히 하나 고른다. 이미 읽은 문서는 고르지 마라.\n"
                        'JSON으로만: {"문서":"후보에 있는 제목"}',
                        f"[질문] {question}\n[이미 읽음] {', '.join(읽음) or '없음'}\n[지금까지 모은 요약]\n"
                        + "\n".join(f"- {t}: {n[:120]}" for t, n in 메모)
                        + f"\n[{이름}] {', '.join(후보[:G.CAND_MAX])}", coord=True)
            고름 = str(G.jload(raw, {}).get("문서") or "")
            if 고름 in G.DOCS and 고름 not in 읽음:
                break
        if 고름 not in G.DOCS or 고름 in 읽음:
            고름, 대체 = cand[0], 대체 + 1          # 그래도 엉뚱하면 후보 첫 번째 — 예산은 끝까지 쓴다
        읽음.append(고름)
        메모.append([고름, G.read_one(고름, question)])

    절수 = G.설정["절수"]
    보고서 = G.ask("너는 간호조무사 시험 대비 학습 보고서를 쓰는 필자다. 아래 요약들만 근거로 질문에 답하는 "
                f"보고서를 써라. 절을 {절수}개 두고 각 절은 여섯 문장 이상 쓴다. 문장마다 근거가 된 문서 "
                "제목을 «문서명» 으로 마침표 앞에 붙여라. 요약에 없는 내용은 쓰지 마라.",
                f"[질문] {question}\n[모은 요약]\n" + "\n\n".join(f"[{t}]\n{n}" for t, n in 메모),
                coord=True)
    sec = [{"번호": 0, "절": "(단일 에이전트 전체)", "역할": "단일 에이전트", "본문": 보고서,
            "읽은문서": 읽음, "메모": 메모, "인용": M.CITE.findall(보고서), "충분": True, "부족": ""}]
    m = M.evaluate([["(단일)", d] for d in 읽음], 보고서, [], G.DOCS, G.COST)
    m["예산"], m["소진율"], m["고르기대체"] = 예산, round(100 * len(읽음) / max(예산, 1), 1), 대체
    return {"구조": "단일 에이전트", "질문": question, "설정": {"예산": 예산}, "목차": [], "종료": "",
            "배정오류": [], "파견": sec, "최종보고서": 보고서, "지표": m,
            "로그": [f"단일 에이전트  예산 {예산}건 중 {len(읽음)}건 읽음 (소진율 {m['소진율']}%, "
                     f"엉뚱한 선택 대체 {대체}회)", f"⑥ 평가   {M.한줄(m)}"],
            "비용": dict(G.COST), "초": round(time.time() - t0, 1),
            "코퍼스": {"문서수": len(G.DOCS), "총글자": sum(len(v) for v in G.DOCS.values())}}


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    r = run(" ".join(sys.argv[2:]) or "결핵은 어떻게 전파되고, 환자 간호와 법적 신고·관리는 어떻게 하나?",
            int(sys.argv[1]) if len(sys.argv) > 1 else G.설정["절수"] * G.설정["절예산"])
    print("\n".join(r["로그"]))
