"""헤드라인은 구글 뉴스 RSS, 본문은 매체 RSS에서 직접 가져온다. 키도 한도도 없다."""
import datetime as dt
import html as htmllib
import re
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
GNEWS = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"

# 본문 링크가 바로 열리는 매체 피드 (실패해도 조용히 건너뛴다)
DIRECT_FEEDS = [
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("CNBC Markets", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    ("MarketWatch", "http://feeds.marketwatch.com/marketwatch/topstories/"),
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
]

FIXED_EN = ["stock market today", "Federal Reserve interest rates", "Treasury yields"]
FIXED_KO = ["미국 증시 마감"]

MOVER_QUERY = {
    "SMH": "semiconductor stocks", "XLK": "technology stocks",
    "XLF": "bank stocks", "XLE": "energy stocks",
    "RUSSELL2000": "small cap stocks", "NASDAQ": "Nasdaq",
    "WTI": "oil prices", "GOLD": "gold prices", "BTC": "bitcoin price",
    "DXY": "dollar index", "USDKRW": "원달러 환율",
    "US10Y": "bond market yields", "US30Y": "long term Treasury",
    "VIX": "market volatility",
}


def _get(url: str, limit: int = 600_000):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read(limit), r.headers.get("Content-Type", ""), r.geturl()


def _parse_rss(raw: bytes, source_hint: str = "") -> list:
    out = []
    try:
        root = ET.fromstring(raw)
    except Exception:
        return out
    for item in root.findall(".//item")[:12]:
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        src_el = item.find("{*}source")
        source = (src_el.text if src_el is not None else "") or source_hint
        try:
            when = parsedate_to_datetime(item.findtext("pubDate") or "")
        except Exception:
            when = None
        desc = re.sub(r"<[^>]+>", " ", item.findtext("description") or "")
        out.append({"title": htmllib.unescape(title),
                    "link": (item.findtext("link") or "").strip(),
                    "source": (source or "").strip(),
                    "desc": htmllib.unescape(re.sub(r"\s+", " ", desc)).strip()[:400],
                    "when": when, "body": "", "direct": False})
    return out


def google_news(query: str, korean: bool = False) -> list:
    url = GNEWS.format(q=urllib.parse.quote(query),
                       hl="ko" if korean else "en-US",
                       gl="KR" if korean else "US",
                       ceid="KR:ko" if korean else "US:en")
    try:
        raw, _, _ = _get(url)
    except Exception as exc:
        print(f"[news] 구글 '{query}' 실패: {type(exc).__name__}")
        return []
    return _parse_rss(raw)


def direct_feed(name: str, url: str) -> list:
    try:
        raw, _, _ = _get(url)
    except Exception as exc:
        print(f"[news] {name} 피드 실패: {type(exc).__name__}")
        return []
    items = _parse_rss(raw, source_hint=name)
    for it in items:
        it["direct"] = True
    return items


def fetch_body(url: str, max_chars: int = 1600) -> str:
    """기사 페이지에서 본문 문단만 뽑는다. 실패하면 빈 문자열."""
    if not url or "news.google.com" in url:
        return ""
    try:
        raw, ctype, _ = _get(url, limit=800_000)
    except Exception:
        return ""
    if "html" not in ctype.lower():
        return ""
    doc = raw.decode("utf-8", "replace")
    doc = re.sub(r"(?is)<(script|style|nav|header|footer|aside|form)[^>]*>.*?</\1>", " ", doc)
    chunks = []
    for p in re.findall(r"(?is)<p[^>]*>(.*?)</p>", doc):
        t = htmllib.unescape(re.sub(r"<[^>]+>", "", p))
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) >= 60:  # 짧은 건 대개 광고나 안내 문구
            chunks.append(t)
    return " ".join(chunks)[:max_chars]


def pick_movers(snaps: list, top: int = 5) -> list:
    if not snaps:
        return []
    last = snaps[-1].get("data", {})
    scored = []
    for k, v in last.items():
        if k not in MOVER_QUERY:
            continue
        pct, bp = v.get("chg_pct"), v.get("chg_bp")
        mag = abs(pct) if pct is not None else (abs(bp) / 4 if bp is not None else None)
        if mag is not None:
            scored.append((mag, k))
    scored.sort(reverse=True)
    return [k for _, k in scored[:top]]


def collect(snaps: list, max_age_hours: int = 48, bodies: int = 6) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    seen, items = set(), []

    for name, url in DIRECT_FEEDS:
        items += direct_feed(name, url)

    queries = [(q, False) for q in FIXED_EN] + [(q, True) for q in FIXED_KO]
    for key in pick_movers(snaps):
        q = MOVER_QUERY[key]
        pair = (q, not q.isascii())
        if pair not in queries:
            queries.append(pair)
    for q, ko in queries:
        items += google_news(q, ko)

    fresh = []
    for it in items:
        t = it["title"]
        if not t or t in seen:
            continue
        if it["when"] and (now - it["when"]).total_seconds() > max_age_hours * 3600:
            continue
        seen.add(t)
        fresh.append(it)

    fresh.sort(key=lambda x: x["when"] or now, reverse=True)

    got = 0
    for it in fresh:
        if got >= bodies:
            break
        if not it.get("direct"):
            continue
        body = fetch_body(it["link"])
        if len(body) > 300:
            it["body"] = body
            got += 1

    print(f"[news] 헤드라인 {len(fresh)}건 / 본문 확보 {got}건")
    return {"items": fresh, "bodies": got}


def session_tag(when, cutoff) -> str:
    """정규장 마감(cutoff) 이후 보도인지 코드로 판정한다."""
    if when is None:
        return "시각미확인"
    if cutoff is None:
        return "시각확인"
    return "마감후" if when > cutoff else "장중"


def as_prompt(res: dict, cutoff=None, headline_limit: int = 40) -> str:
    items = res.get("items", [])
    body_items = [i for i in items if i.get("body")]
    head_items = [i for i in items if not i.get("body")][:headline_limit]

    out = []
    if body_items:
        out.append("[기사 본문] 원인을 쓸 때 이 내용을 최우선 근거로 삼는다.")
        for i, it in enumerate(body_items, 1):
            when = f"{it['when']:%m-%d %H:%MZ}" if it["when"] else "?"
            tag = session_tag(it["when"], cutoff)
            out.append(f"\n({i}) [{tag}] {it['title']}  [{it['source']} / {when}]\n{it['body']}")
    if head_items:
        out.append("\n[헤드라인] 본문은 없다. 제목에서 확인되는 사실만 근거로 쓴다.")
        for it in head_items:
            when = f"{it['when']:%m-%d %H:%M}Z" if it["when"] else "?"
            src = f" / {it['source']}" if it["source"] else ""
            tag = session_tag(it["when"], cutoff)
            out.append(f"- [{tag}] [{when}{src}] {it['title']}")
    return "\n".join(out)
