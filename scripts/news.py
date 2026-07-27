"""구글 뉴스 RSS에서 헤드라인을 긁어온다. API 키도 한도도 없다."""
import datetime as dt
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

UA = {"User-Agent": "Mozilla/5.0 (compatible; market-bot/1.0)"}
BASE = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"

# 항상 확인하는 주제
FIXED_EN = [
    "stock market today",
    "Federal Reserve interest rates",
    "Treasury yields",
]
FIXED_KO = ["미국 증시 마감"]

# 데이터에서 크게 움직인 자산에 붙일 검색어
MOVER_QUERY = {
    "SMH": "semiconductor stocks",
    "XLK": "technology stocks",
    "XLF": "bank stocks",
    "XLE": "energy stocks",
    "RUSSELL2000": "small cap stocks",
    "NASDAQ": "Nasdaq",
    "WTI": "oil prices",
    "GOLD": "gold prices",
    "BTC": "bitcoin price",
    "DXY": "dollar index",
    "USDKRW": "원달러 환율",
    "US10Y": "bond market yields",
    "US30Y": "long term Treasury",
    "VIX": "market volatility",
}


def _fetch(query: str, korean: bool = False, limit: int = 8) -> list:
    url = BASE.format(
        q=urllib.parse.quote(query),
        hl="ko" if korean else "en-US",
        gl="KR" if korean else "US",
        ceid="KR:ko" if korean else "US:en",
    )
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=25) as r:
            root = ET.fromstring(r.read())
    except Exception as exc:
        print(f"[news] '{query}' 실패: {type(exc).__name__}")
        return []

    out = []
    for item in root.findall(".//item")[:limit]:
        title = (item.findtext("title") or "").strip()
        src = item.find("{*}source")
        source = (src.text if src is not None else "") or ""
        pub = item.findtext("pubDate") or ""
        try:
            when = parsedate_to_datetime(pub)
        except Exception:
            when = None
        out.append({"title": title, "source": source.strip(), "when": when,
                    "query": query})
    return out


def pick_movers(snaps: list, top: int = 5) -> list:
    """마지막 스냅샷에서 절대 변동폭이 큰 순으로 자산 키를 고른다."""
    if not snaps:
        return []
    last = snaps[-1].get("data", {})
    scored = []
    for k, v in last.items():
        if k not in MOVER_QUERY:
            continue
        pct = v.get("chg_pct")
        bp = v.get("chg_bp")
        mag = abs(pct) if pct is not None else (abs(bp) / 4 if bp is not None else None)
        if mag is not None:
            scored.append((mag, k))
    scored.sort(reverse=True)
    return [k for _, k in scored[:top]]


def collect(snaps: list, max_age_hours: int = 48) -> list:
    queries = [(q, False) for q in FIXED_EN] + [(q, True) for q in FIXED_KO]
    for key in pick_movers(snaps):
        q = MOVER_QUERY[key]
        korean = not q.isascii()
        if (q, korean) not in queries:
            queries.append((q, korean))

    now = dt.datetime.now(dt.timezone.utc)
    seen, items = set(), []
    for q, korean in queries:
        for it in _fetch(q, korean):
            if not it["title"] or it["title"] in seen:
                continue
            if it["when"] and (now - it["when"]).total_seconds() > max_age_hours * 3600:
                continue
            seen.add(it["title"])
            items.append(it)

    items.sort(key=lambda x: x["when"] or now, reverse=True)
    print(f"[news] 헤드라인 {len(items)}건 수집 ({len(queries)}개 검색어)")
    return items


def as_text(items: list, limit: int = 45) -> str:
    lines = []
    for it in items[:limit]:
        when = f"{it['when']:%m-%d %H:%M}Z" if it["when"] else "?"
        src = f" / {it['source']}" if it["source"] else ""
        lines.append(f"- [{when}{src}] {it['title']}")
    return "\n".join(lines)
