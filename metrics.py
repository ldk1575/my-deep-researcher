"""⑥ 평가 — 정답표도 판정 모델도 쓰지 않는다. 만들어진 글과 실제로 읽은 자료만 본다.

지표마다 보는 장치:
  경보(0 이어야 함) 허위인용 · 인용0절 · 배정오류 · 지어낸숫자(직접 읽기 뒤 추가)
  비교              근거율(수업 규칙) · 근거율_보정 · 인용편중 · 중복률
  증명              격리율 · 코디네이터본글자 · 리서처본글자
"""
import re
from collections import Counter

CITE = re.compile(r"«([^»]+)»")


def 문장들(글: str) -> list:
    """수업 규칙 그대로 — 마침표·물음표·느낌표 뒤 공백과 줄바꿈에서 자르고 15자 이하는 버린다."""
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n", 글) if len(x.strip()) > 15]


def 문장들_보정(글: str) -> list:
    """같은 규칙으로 자르되, '…했다. «문서»' 처럼 마침표 뒤로 밀려난 인용 조각을 앞 문장에 다시 붙인다.
    (수업 2일차 Q4: 규칙 탓에 근거 비율이 67.4% 로 낮게 나왔고, 다시 붙이면 85.4% 였다.)"""
    out = []
    for x in re.split(r"(?<=[.!?])\s+|\n", 글):
        x = x.strip()
        if not x:
            continue
        if out and re.fullmatch(r"(«[^»]+»[\s,.)]*)+", x):
            out[-1] += " " + x
        elif len(x) > 15:
            out.append(x)
    return out


def 근거율(문장: list, docs: dict) -> tuple[int, float]:
    붙은 = [s for s in 문장 if any(c in docs for c in CITE.findall(s))]
    return len(붙은), round(100 * len(붙은) / max(len(문장), 1), 1)


NUM = re.compile(r"\d+(?:\.\d+)?")


def 지어낸숫자(report: str, docs: dict) -> list:
    """인용이 붙은 문장의 숫자(두 자리 이상 또는 소수)가 그 문장이 인용한 문서 어디에도 없으면 잡는다.
    직접 대조에서 «호흡계» '분당 12-20회' · «활력 징후» '36.1~37.2°C' 가 원문에 없는 것을 보고 더했다.
    한계: 원문에 있는 숫자를 뜻을 뒤집어 붙인 것(«고혈압» 135/80)은 못 잡는다 — 그건 사람이 읽어야 한다."""
    out = []
    for s in 문장들_보정(report):
        cited = [c for c in CITE.findall(s) if c in docs]
        if not cited:
            continue
        본문 = CITE.sub("", s)
        src = " ".join(docs[c] for c in cited).replace(",", "")
        for n in NUM.findall(본문.replace(",", "")):
            if (len(n) >= 2 or "." in n) and n not in src:
                out.append({"숫자": n, "인용": cited, "문장": s[:120]})
    return out


def 절모음(sections: list) -> dict:
    """재위임되면 같은 절이 두 번 올라온다. 마지막 원고를 쓰되,
    새 원고가 인용을 하나도 못 남겼는데 옛 원고에는 있었다면 옛 것을 지킨다 (덮어쓰기 사고 방지)."""
    out = {}
    for sec in sections:
        old = out.get(sec["절"])
        if old and not sec.get("인용") and old.get("인용"):
            out[sec["절"]] = {**old, "덮어쓰기막음": True}
            continue
        out[sec["절"]] = sec
    return out


def evaluate(visited: list, report: str, sections: list, docs: dict, cost: dict,
             배정오류: list | None = None) -> dict:
    쌍 = sorted({tuple(v) for v in visited})
    읽기시도 = [d for _, d in 쌍]
    읽은 = set(읽기시도)
    인용 = [c for c in CITE.findall(report) if c in docs]
    쓰임 = Counter(인용)
    문장 = 문장들(report)
    n붙은, 율 = 근거율(문장, docs)
    _, 율보정 = 근거율(문장들_보정(report), docs)
    절 = 절모음(sections)
    m = {
        # 경보
        "허위인용": sorted(set(인용) - 읽은),
        "인용0절": sorted(t for t, s in 절.items() if not [c for c in s.get("인용", []) if c in docs]),
        "배정오류": list(배정오류 or []),
        "지어낸숫자": 지어낸숫자(report, docs),
        # 비교
        "문장수": len(문장), "근거붙은문장": n붙은, "근거율": 율, "근거율_보정": 율보정,
        "인용수": len(인용), "인용문서수": len(쓰임),
        "인용편중": round(100 * max(쓰임.values()) / sum(쓰임.values()), 1) if 쓰임 else 0.0,
        "중복률": round(100 * (1 - len(읽은) / len(읽기시도)), 1) if 읽기시도 else 0.0,
        "읽은문서": len(읽은), "읽고안쓴": sorted(읽은 - set(쓰임)),
        "절수": len(절), "보고서자수": len(report),
        # 증명
        "LLM호출": cost.get("calls", 0),
        "코디네이터본글자": cost.get("coord_chars", 0),
        "리서처본글자": cost.get("sub_chars", 0),
        "격리율": round(100 * cost.get("coord_chars", 0) /
                     max(cost.get("sub_chars", 0) + cost.get("coord_chars", 0), 1), 1),
    }
    m["경보"] = len(m["허위인용"]) + len(m["인용0절"]) + len(m["배정오류"]) + len(m["지어낸숫자"])
    return m


def 한줄(m: dict) -> str:
    return (f"근거율 {m['근거율']}% (보정 {m['근거율_보정']}%) · 허위 {len(m['허위인용'])} · "
            f"지어낸숫자 {len(m.get('지어낸숫자', []))} · "
            f"인용0절 {len(m['인용0절'])} · 배정오류 {len(m['배정오류'])} · 편중 {m['인용편중']}% · "
            f"중복 {m['중복률']}% · 읽은 {m['읽은문서']}건 · {m['보고서자수']:,}자 · "
            f"LLM {m['LLM호출']}회 · 격리율 {m['격리율']}%")
