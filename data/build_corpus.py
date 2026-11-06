"""간호조무사 국가시험 4과목 코퍼스 만들기 — 한국어 위키백과 (+ data/extra/*.json 공공문서).

실행:  python data/build_corpus.py          (받아 둔 data/raw/ 가 있으면 다시 받지 않는다)
결과:  data/corpus.json  {"docs": {제목: 본문}, "links": {제목: [제목…]}}
       data/meta.json    {제목: {과목, 출처, url, 라이선스, 수집일}}

수집 규칙 (수업 프롬프트): MediaWiki API · 3,000자 미만 제외 · 아스키 User-Agent ·
호출 사이 간격(429 가 나면 Retry-After 만큼 쉰다) · links 는 continue 로 끝까지 이어 받기.
"""
import json, re, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
EXTRA = HERE / "extra"
API = "https://ko.wikipedia.org/w/api.php"
UA = "my-deep-researcher/0.1 (class project; https://github.com/ldk1575/my-deep-researcher)"
MIN_CHARS = 3000
# 실기 예외: 한국어 위키의 술기 문서는 대부분 토막글이다(활력 징후 1,590자 · 욕창 339자). 짧은 문서가
# 유일한 재료라 실기만 1,000자로 낮춘다. 총량 전제(창 초과)에는 영향이 없다.
MIN_BY = {"실기": 1000}
GAP = 1.0           # 호출 사이 초

# 과목별 시드 — 시험 범위에서 골랐다. 없거나 3,000자 미만이면 버려진다.
SEEDS = {
    "기초간호학 개요": [
        "간호", "해부학", "생리학", "순환계", "호흡계", "소화계", "신경계", "내분비계", "비뇨계",
        "근골격계", "피부", "혈액", "심장", "폐", "간", "콩팥", "당뇨병", "고혈압", "심근경색",
        "뇌졸중", "폐렴", "천식", "만성 폐쇄성 폐질환", "위염", "간경변", "빈혈", "골다공증",
        "관절염", "골절", "화상", "쇼크 (의학)", "통증", "약리학", "항생제", "인슐린", "마취",
        "임신", "출산", "모유 수유", "신생아", "영아", "노화", "치매", "파킨슨병", "우울증",
        "조현병", "충치", "치주염", "영양소", "비타민", "단백질", "암",
    ],
    "보건간호학 개요": [
        "보건교육", "보건소", "학교보건", "산업재해", "직업병", "가족계획", "피임", "노인 복지",
        "재활", "건강증진", "흡연", "금연", "알코올 사용 장애", "비만", "자살", "호스피스",
    ],
    "공중보건학 개론": [
        "공중보건", "역학 (의학)", "감염병", "면역", "백신", "예방접종", "결핵", "인플루엔자",
        "코로나바이러스감염증-19", "홍역", "수두", "B형 간염", "말라리아", "콜레라", "장티푸스",
        "식중독", "대기 오염", "수질 오염", "상수도", "하수 처리", "소음", "인구", "출산율",
        "국민건강보험", "의료급여", "대한민국의 의료 제도", "세계보건기구", "질병관리청",
        "후천성 면역 결핍 증후군", "성매개감염병",
    ],
    "실기": [
        "활력 징후", "체온", "맥박", "혈압", "심폐소생술", "응급처치", "자동심장충격기",
        "하임리히법", "주사", "정맥 주사", "카테터", "관장", "욕창", "손 씻기", "소독", "멸균",
        "무균술", "개인 보호 장비", "산소 요법", "상처", "붕대", "낙상", "격리 (의학)",
        "출혈", "지혈", "열사병", "저체온증", "탈수", "수혈", "혈액형", "변비", "설사", "요실금", "발열",
        "인공호흡", "기관 내 삽관", "근육 주사", "피하 주사", "혈당", "구토", "경관 영양",
    ],
}


def get(params: dict, tries: int = 6) -> dict:
    params = {**params, "format": "json", "formatversion": "2", "maxlag": "5"}
    url = API + "?" + urllib.parse.urlencode(params)
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.load(r)
            if d.get("error", {}).get("code") == "maxlag":
                time.sleep(5); continue
            return d
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and i < tries - 1:
                wait = int(e.headers.get("Retry-After") or 0) or 10 * (i + 1)
                print(f"   … {e.code}, {wait}초 쉼", flush=True)
                time.sleep(wait); continue
            raise
    raise RuntimeError("재시도 초과")


def fetch(title: str) -> dict | None:
    """본문(평문)과 링크 전부. data/raw/ 에 캐시."""
    RAW.mkdir(exist_ok=True)
    cache = RAW / (re.sub(r'[\\/:*?"<>|]', "_", title) + ".json")
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    params = {"action": "query", "prop": "extracts|links|info", "explaintext": 1, "inprop": "url",
              "titles": title, "redirects": 1, "pllimit": "max", "plnamespace": 0}
    text, links, real, url = "", [], None, ""
    while True:
        d = get(params)
        time.sleep(GAP)
        p = d["query"]["pages"][0]
        if p.get("missing") or p.get("invalid"):
            out = None
            break
        real = p["title"]; url = p.get("fullurl", url)
        text = p.get("extract", text) or text
        links += [l["title"] for l in p.get("links", [])]
        if "continue" not in d:
            out = {"title": real, "url": url, "text": text, "links": links}
            break
        params = {**params, **d["continue"]}
    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def clean(text: str) -> str:
    """각주·참고 문헌 이후를 자르고 빈 줄을 접는다 (본문 문장은 고치지 않는다)."""
    text = re.split(r"\n== ?(각주|참고 문헌|같이 보기|외부 링크|참고 자료|출처) ?==", text)[0]
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def mention_links(docs: dict, links: dict) -> int:
    """위키가 아닌 문서는 링크가 없다 — 본문에 다른 문서 제목이 나오면 잇는다."""
    added = 0
    titles = sorted(docs, key=len, reverse=True)
    for t, body in docs.items():
        if links.get(t):
            continue
        found = [x for x in titles if x != t and len(x) >= 2 and re.sub(r" \(.*\)$", "", x) in body]
        links[t] = found; added += len(found)
    return added


def main():
    docs, links, meta = {}, {}, {}
    today = date.today().isoformat()
    dropped = []
    for 과목, titles in SEEDS.items():
        for t in titles:
            r = fetch(t)
            if not r:
                dropped.append((t, "없음")); continue
            body = clean(r["text"])
            if len(body) < MIN_BY.get(과목, MIN_CHARS):
                dropped.append((r["title"], f"{len(body)}자")); continue
            if r["title"] in docs:
                continue
            docs[r["title"]] = body
            links[r["title"]] = r["links"]
            meta[r["title"]] = {"과목": 과목, "출처": "한국어 위키백과", "url": r["url"],
                                "라이선스": "CC BY-SA 4.0", "수집일": today}
            print(f"  + [{과목}] {r['title']} {len(body):,}자", flush=True)

    # 공공문서 (data/extra/*.json: {"title","text","url","과목","출처","라이선스"})
    for f in sorted(EXTRA.glob("*.json")) if EXTRA.exists() else []:
        x = json.loads(f.read_text(encoding="utf-8"))
        if len(x["text"]) < MIN_CHARS:
            dropped.append((x["title"], f"{len(x['text'])}자")); continue
        docs[x["title"]] = x["text"]; links[x["title"]] = []
        meta[x["title"]] = {k: x[k] for k in ("과목", "출처", "url", "라이선스")} | {"수집일": x.get("수집일", today)}

    # 링크는 코퍼스 안의 것만
    for t in links:
        links[t] = sorted({x for x in links[t] if x in docs and x != t})
    added = mention_links(docs, links)

    (HERE / "corpus.json").write_text(json.dumps({"docs": docs, "links": links}, ensure_ascii=False, indent=1), encoding="utf-8")
    (HERE / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    import tiktoken
    enc = tiktoken.get_encoding("o200k_base")       # gpt-4o-mini 의 토크나이저
    total = sum(len(v) for v in docs.values())
    tokens = sum(len(enc.encode(v)) for v in docs.values())
    by = {}
    for t, m in meta.items():
        by[m["과목"]] = by.get(m["과목"], 0) + 1
    print("\n버린 것:", ", ".join(f"{t}({w})" for t, w in dropped))
    print("\n" + "=" * 60)
    print(f"문서 {len(docs)}건 · 총 {total:,}자 · 토큰 {tokens:,} (o200k_base)")
    print(f"gpt-4o-mini 컨텍스트 창 128,000 토큰의 {tokens / 128000:.2f}배 → "
          f"{'한 번에 안 들어간다' if tokens > 128000 else '들어간다 (이 구조를 쓸 이유가 약하다)'}")
    print("과목별:", " · ".join(f"{k} {v}건" for k, v in by.items()))
    print(f"링크 {sum(len(v) for v in links.values())}개 (본문 언급으로 이은 것 {added}개) · "
          f"링크 0개 문서 {sum(1 for v in links.values() if not v)}건 · "
          f"아무도 가리키지 않는 문서 {sum(1 for t in docs if not any(t in v for v in links.values()))}건")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
