"""스냅샷 + 뉴스 헤드라인 -> Gemini 리포트 -> Blogger 발행 -> 텔레그램 알림."""
import datetime as dt
import html as htmllib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import news as news_mod

KST = dt.timezone(dt.timedelta(hours=9))
HOST = "https://generativelanguage.googleapis.com"
YIELD_KEYS = {"US13W", "US5Y", "US10Y", "US30Y"}
DRAFT = os.environ.get("PUBLISH_DRAFT", "true").lower() == "true"

COMMON = """당신은 한국어 금융 블로그의 필자다.
독자는 금융 전문가가 아니라 일반 투자자다. 글을 다 읽고 나면 "아, 이래서 시장이 이렇게 움직였구나"
하고 이해할 수 있어야 한다. 숫자 나열이 아니라 인과를 설명하는 글을 쓴다.

가장 중요한 규칙 — 원인은 반드시 근거가 있어야 한다:
- 원인은 [뉴스 헤드라인]에 나온 사실에만 근거해 쓴다. 헤드라인에 없는 원인을 지어내지 않는다.
- 각 원인 불릿 끝에 근거가 된 매체명을 괄호로 붙인다. 예: (로이터), (CNBC)
- 근거가 될 헤드라인이 없으면 솔직하게 쓴다.
  예: "뚜렷한 촉발 요인은 확인되지 않았습니다. 특정 재료보다 수급 요인이 컸을 가능성이 있습니다."
- "차익실현", "경계감", "관망세" 같은 표현만으로 원인을 때우지 않는다. 이런 말은 어느 날에나
  갖다 붙일 수 있어서 독자에게 아무 정보도 주지 못한다. 구체적인 사건, 기업, 정책, 지표를 짚는다.

표기 규칙:
- 주어진 숫자 밖의 수치를 절대 만들어내지 않는다.
- 수치를 처음 제시할 때 기준을 밝힌다. (예: "직전 거래일 종가 대비")
- 금리는 반드시 bp(베이시스포인트)로 표기하고 %로 쓰지 않는다.
- 국내 금융시장에서 실제로 쓰는 표준 용어만 사용한다. 사전에 없는 조어나 어색한 한자 조합을
  절대 만들지 않는다. 애매하면 쉬운 우리말로 풀어 쓴다.
  허용: 안전자산 선호, 위험자산 선호, 차익실현, 순환매, 되돌림, 커브 스티프닝, 커브 플래트닝,
        강세/약세, 매수세/매도세, 반발 매수, 실적 발표, 공급 과잉, 수요 둔화, 규제 리스크.
- 전문용어는 처음 나올 때 괄호로 짧게 풀어준다.

맥락 규칙 — 오늘 하루만 보지 않는다:
- [최근 거래일 추이]가 주어지면 오늘의 움직임을 그 흐름 속에 놓고 설명한다.
  (예: "3거래일 연속 하락", "이번 주 누적 -3.2%", "지난주 고점 대비 되돌림")
- 어제까지 이어지던 흐름이 오늘 바뀌었다면 그 전환을 가장 먼저 짚는다.
- [어제 글]이 주어지면, 어제 해석에서 제시한 조건이나 확인 포인트가 오늘 어떻게 되었는지
  첫 번째 이슈의 해석에 한 문장 이상 반영한다. 어제 글이 없으면 무시한다.

반드시 아래 JSON 형식으로만 답한다. 다른 말은 붙이지 않는다.
{"title": "...", "html": "...", "summary3": ["...", "...", "..."], "labels": ["..."]}

title에는 날짜를 넣지 않는다. 날짜는 나중에 자동으로 붙는다.
title에는 그날의 구체적인 사건을 담는다. ("증시 혼조" 같은 무난한 제목을 쓰지 않는다)
html 본문은 <h2>, <h3>, <p>, <table>, <tr>, <td>, <ul>, <li>만 사용한다.
style 속성이나 색상은 넣지 않는다. 서식은 나중에 자동으로 입혀진다.
labels는 해시태그로 쓰인다. 공백 없는 한글 키워드 4~5개를 넣는다.
summary3은 텔레그램용 3줄 요약이며 각 45자 내외."""

STRUCT = """
[1] 맨 위 주요 지표 <table>. 첫 행 머리글은 (지표 / 종가 / 전 거래일 대비).
    주가지수는 %, 금리는 bp, 환율·유가·금은 % 로 표기.

[2] <h2>시장을 움직인 3가지 요인</h2>
    <h3>1. [주식] 이슈 제목</h3>
    <p>1) 현황: 한두 문장. 첫 문장에 기준 시점을 밝힌다.</p>
    <p>2) 원인</p>
    <ul><li>...</li><li>...</li><li>...</li></ul>
    <p>3) 해석</p>
    <ul><li>...</li><li>...</li><li>...</li></ul>

    <h3>2. [채권] 이슈 제목</h3>   (같은 형식)
    <h3>3. [기타] 이슈 제목</h3>   (환율·원자재·가상자산 중 움직임이 가장 큰 것)

    원인은 불릿 3~4개. 무슨 일이 있었는지 사건 자체를 쓴다. 매체명을 괄호로 붙인다.

    해석은 이 글의 핵심이다. 불릿 3~4개, 각 두 문장까지 허용하고 아래를 담는다.
    - 이 흐름이 이어지려면 무엇이 유지되어야 하는지
    - 반대로 꺾인다면 어떤 신호가 먼저 나타날지
    - 투자자가 다음에 확인해야 할 지표나 이벤트는 무엇인지
    비교가 필요하면 해석 안에 작은 <table>을 넣어 정리해도 좋다.

본문 전체 3,500자 안팎. 이 두 부분으로만 구성하고 다른 섹션은 만들지 않는다."""

MARKET_SYSTEM = COMMON + "\n\n새벽 미국시장 데이터와 뉴스 헤드라인을 받아 아침 리뷰를 쓴다." + STRUCT

NEWS_SYSTEM = COMMON + """

오늘은 미국장 휴장일이다. 시황 대신 지난 48시간의 주요 금융·경제 뉴스를 정리한다.
[뉴스 헤드라인]에 실제로 있는 내용만 쓴다.

[1] <h2>주말 시장을 움직인 3가지 요인</h2>
    <h3>1. [분야] 뉴스 제목</h3>
    <p>1) 현황: 무슨 일이 있었는지 한두 문장</p>
    <p>2) 원인</p>
    <ul><li>...</li><li>...</li><li>...</li></ul>
    <p>3) 해석</p>
    <ul><li>...</li><li>...</li><li>...</li></ul>

    분야는 통화정책·경제지표·기업·지정학·원자재 중 실제로 중요했던 것으로 고른다.
    해석은 불릿 3~4개로 두텁게 쓴다. 본문 전체 3,000자 안팎.
    지표 표는 넣지 않는다. 이 한 부분으로만 구성한다."""

# ---------- 서식 ----------
TABLE = 'style="width:100%;border-collapse:collapse;font-size:15px;margin:18px 0 6px;"'
HEAD_L = 'style="background:#f1f5f9;font-weight:700;padding:10px 10px;border-bottom:2px solid #cbd5e1;text-align:left;"'
HEAD_R = 'style="background:#f1f5f9;font-weight:700;padding:10px 10px;border-bottom:2px solid #cbd5e1;text-align:right;"'
TD_NAME = 'style="padding:9px 10px;border-bottom:1px solid #e5e7eb;font-weight:700;"'
TD_NUM = 'style="padding:9px 10px;border-bottom:1px solid #e5e7eb;text-align:right;font-variant-numeric:tabular-nums;"'
H2 = 'style="font-size:20px;font-weight:700;margin:36px 0 14px;padding-bottom:8px;border-bottom:2px solid #334155;"'
H3 = 'style="font-size:17px;font-weight:700;margin:28px 0 12px;padding:8px 0 8px 12px;border-left:4px solid #2563eb;background:#f8fafc;"'
PP = 'style="line-height:1.8;margin:10px 0;"'
UL = 'style="line-height:1.85;margin:8px 0 18px;padding-left:24px;"'
LI = 'style="margin:7px 0;"'
NOTE = 'style="font-size:13px;color:#64748b;margin:2px 0 20px;"'
LABEL = 'style="font-weight:700;color:#0f172a;border-bottom:2px solid #fcd34d;padding-bottom:1px;"'
BOX = 'style="background:#fffbeb;border-left:4px solid #f59e0b;padding:14px 18px;margin:14px 0 22px;border-radius:6px;"'
TAGS = 'style="margin:30px 0 0;font-size:14px;color:#2563eb;line-height:1.9;"'


def wrap_interpretation(html: str) -> str:
    pat = re.compile(
        r"(?is)(<p[^>]*>\s*3\)\s*해석\s*</p>)(\s*(?:<ul[^>]*>.*?</ul>|<p[^>]*>.*?</p>|<table[^>]*>.*?</table>)+)"
    )

    def repl(m):
        return f'<div {BOX}><p><span {LABEL}>해석</span></p>{m.group(2)}</div>'

    return pat.sub(repl, html)


def style_html(html: str) -> str:
    html = wrap_interpretation(html)

    def color(m):
        v = m.group(0)
        c = "#d32f2f" if v.startswith("+") else "#1565c0"
        return f'<span style="color:{c};font-weight:600;">{v}</span>'

    html = re.sub(r"[+\-−]\d+(?:[.,]\d+)?\s*(?:%p|%|bp)", color, html)
    html = re.sub(r"(\d\)\s*(?:현황|원인))",
                  lambda m: f'<span {LABEL}>{m.group(1)}</span>', html)

    def table(m):
        t = m.group(0)
        for i, r in enumerate(re.findall(r"(?is)<tr[^>]*>.*?</tr>", t)):
            nr = r
            for j, c in enumerate(re.findall(r"(?is)<t[dh][^>]*>.*?</t[dh]>", r)):
                if i == 0:
                    st = HEAD_L if j == 0 else HEAD_R
                else:
                    st = TD_NAME if j == 0 else TD_NUM
                nr = nr.replace(c, re.sub(r"(?i)^<(td|th)[^>]*>", f"<\\1 {st}>", c), 1)
            t = t.replace(r, nr, 1)
        return re.sub(r"(?i)^<table[^>]*>", f"<table {TABLE}>", t)

    html = re.sub(r"(?is)<table.*?</table>", table, html)
    html = re.sub(r"(?i)<h2[^>]*>", f"<h2 {H2}>", html)
    html = re.sub(r"(?i)<h3[^>]*>", f"<h3 {H3}>", html)
    html = re.sub(r"(?i)<p[^>]*>", f"<p {PP}>", html)
    html = re.sub(r"(?i)<ul[^>]*>", f"<ul {UL}>", html)
    html = re.sub(r"(?i)<li[^>]*>", f"<li {LI}>", html)
    return html


def basis_note(snaps: list) -> str:
    if not snaps:
        return ""
    try:
        ts = dt.datetime.fromisoformat(snaps[-1]["ts_kst"])
        stamp = f"{ts:%Y년 %m월 %d일 %H:%M} KST"
    except Exception:
        stamp = snaps[-1].get("ts_kst", "")
    return (f'<p {NOTE}>※ 위 수치는 {stamp} 수집 시점 기준이며, '
            f'등락은 직전 거래일 종가 대비입니다.</p>')


def http_json(url, body=None, timeout=300, headers=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hdrs = dict(headers or {})
    if body is not None and raw is None:
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        msg = re.search(r'"message":\s*"([^"]{0,200})', detail)
        safe = re.sub(r"key=[^&]+", "key=***", url)
        print(f"[HTTP {e.code}] {safe}\n   {msg.group(1) if msg else detail[:200]}")
        raise


def list_models(key):
    for ver in ("v1beta", "v1"):
        try:
            res = http_json(f"{HOST}/{ver}/models?key={key}", timeout=30)
        except urllib.error.HTTPError:
            continue
        names = [m["name"] for m in res.get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])
                 and not any(x in m["name"] for x in
                             ("image", "tts", "embedding", "vision", "live", "omni"))]
        if names:
            return ver, names
    raise SystemExit("모델 목록을 가져오지 못했습니다.")


def rank(names):
    def score(n):
        m = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        ver = float(m.group(1)) if m else 0.0
        is_flash = "flash" in n and "lite" not in n
        return (0 if is_flash else 1 if "flash" in n else 2,
                1 if ("preview" in n or "exp" in n) else 0, -ver, n)
    return sorted(names, key=score)


def extract_json(text):
    t = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        s, e = t.find("{"), t.rfind("}")
        if s == -1 or e == -1:
            raise
        return json.loads(t[s : e + 1])


def call(key, ver, name, system, prompt):
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.25, "maxOutputTokens": 32768,
                                 "responseMimeType": "application/json"}}
    res = http_json(f"{HOST}/{ver}/{name}:generateContent?key={key}", body)
    cand = res.get("candidates", [{}])[0]
    text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
    return extract_json(text)


def try_generate(key, ver, candidates, system, prompt):
    for i, name in enumerate(candidates[:4]):
        if i:
            time.sleep(3)
        try:
            return call(key, ver, name, system, prompt), name
        except urllib.error.HTTPError as e:
            if e.code == 429 and i == 0:
                print("   분당 한도로 보임 -> 65초 대기 후 재시도")
                time.sleep(65)
                try:
                    return call(key, ver, name, system, prompt), name
                except urllib.error.HTTPError:
                    pass
            print(f"[skip] {name}")
        except (json.JSONDecodeError, KeyError, IndexError) as ex:
            print(f"[skip] {name} 파싱 실패: {ex}")
    return None, None


def load_snapshots(date_kst):
    path = Path("snapshots") / f"{date_kst:%Y-%m-%d}.jsonl"
    if not path.exists():
        files = sorted(Path("snapshots").glob("*.jsonl"))
        if not files:
            return [], ""
        path = files[-1]
    snaps = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    for rec in snaps:
        for k, v in rec.get("data", {}).items():
            if k in YIELD_KEYS and v.get("last") is not None and v.get("prev_close"):
                v["chg_bp"] = round((v["last"] - v["prev_close"]) * 100, 1)
                v.pop("chg_pct", None)
    return snaps, path.stem


TREND_KEYS = ["S&P500", "NASDAQ", "DOW", "RUSSELL2000", "VIX", "US10Y", "US30Y",
               "DXY", "USDKRW", "WTI", "GOLD", "SMH", "XLK", "XLF", "XLE", "BTC"]


def load_recent_days(n: int = 6) -> list:
    """최근 n개 거래일의 마지막 스냅샷만 뽑아 흐름 비교용으로 만든다."""
    out = []
    for f in sorted(Path("snapshots").glob("*.jsonl"))[-n:]:
        lines = [l for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        if not lines:
            continue
        last = json.loads(lines[-1])
        row = {}
        for k, v in last.get("data", {}).items():
            if k not in TREND_KEYS or v.get("last") is None:
                continue
            cell = {"last": v["last"]}
            if v.get("chg_bp") is not None:
                cell["bp"] = v["chg_bp"]
            elif v.get("chg_pct") is not None:
                cell["pct"] = v["chg_pct"]
            row[k] = cell
        if row:
            out.append({"date": f.stem, "data": row})
    print(f"[trend] 최근 {len(out)}개 거래일 확보")
    return out


def previous_post_text(limit: int = 1400) -> str:
    """블로그의 직전 글을 가져와 텍스트로 만든다. 실패해도 빈 문자열."""
    try:
        token = blogger_token()
        blog_id = os.environ["BLOG_ID"]
        url = (f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts"
               f"?maxResults=1&fetchBodies=true&fetchImages=false")
        res = http_json(url, timeout=30, headers={"Authorization": f"Bearer {token}"})
        items = res.get("items") or []
        if not items:
            return ""
        post = items[0]
        text = re.sub(r"(?is)<[^>]+>", " ", post.get("content", ""))
        text = htmllib.unescape(re.sub(r"\s+", " ", text)).strip()
        print(f"[prev] 직전 글 확보: {post.get('title', '')[:40]}")
        return f"{post.get('title', '')}\n{text[:limit]}"
    except Exception as exc:
        print(f"[prev] 직전 글 없음: {type(exc).__name__}")
        return ""


def blogger_token():
    data = urllib.parse.urlencode({
        "client_id": os.environ["BLOGGER_CLIENT_ID"],
        "client_secret": os.environ["BLOGGER_CLIENT_SECRET"],
        "refresh_token": os.environ["BLOGGER_REFRESH_TOKEN"],
        "grant_type": "refresh_token"}).encode()
    return http_json("https://oauth2.googleapis.com/token", raw=data, timeout=30,
                     headers={"Content-Type": "application/x-www-form-urlencoded"})["access_token"]


def post_to_blogger(title, body_html, labels):
    token = blogger_token()
    blog_id = os.environ["BLOG_ID"]
    url = f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts/"
    if DRAFT:
        url += "?isDraft=true"
    res = http_json(url, {"kind": "blogger#post", "title": title,
                          "content": body_html, "labels": labels[:5]},
                    timeout=60, headers={"Authorization": f"Bearer {token}"})
    return res.get("url") or f"https://www.blogger.com/blog/posts/{blog_id}"


def send_telegram(text):
    data = urllib.parse.urlencode({
        "chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text,
        "parse_mode": "HTML"}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage", data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()


def main():
    key = os.environ["GEMINI_API_KEY"]
    now_kst = dt.datetime.now(dt.timezone.utc).astimezone(KST)
    snaps, _ = load_snapshots(now_kst.date())
    market = now_kst.weekday() in (1, 2, 3, 4, 5) and len(snaps) >= 4
    print(f"[mode] {'시장리뷰' if market else '뉴스'} / 스냅샷 {len(snaps)}건 / 초안={DRAFT}")

    news_block = news_mod.as_prompt(news_mod.collect(snaps))
    if not news_block:
        news_block = "(뉴스를 가져오지 못했습니다. 원인을 추측하지 말고 확인되지 않았다고 쓰세요.)"

    trend = load_recent_days()
    trend_block = json.dumps(trend, ensure_ascii=False) if trend else ""
    prev = previous_post_text()

    ver, names = list_models(key)
    cands = rank(names)

    if market:
        prompt = (f"오늘은 {now_kst:%Y년 %m월 %d일} 한국시간 아침이다.\n\n"
                  f"[장중 스냅샷 {len(snaps)}건] ts_kst는 수집 시각(KST), "
                  f"chg_bp는 bp 단위 변동, prev_close는 직전 거래일 종가다. "
                  f"마지막 스냅샷이 사실상 종가다.\n"
                  + json.dumps(snaps, ensure_ascii=False))
        if trend_block:
            prompt += ("\n\n[최근 거래일 추이] 각 날짜의 마지막 스냅샷이다. "
                       "pct는 그날의 전일 대비 %, bp는 금리의 전일 대비 변동이다. "
                       "며칠째 이어지는 흐름인지, 최근 누적으로 얼마나 움직였는지 본문에 반영하라.\n"
                       + trend_block)
        if prev:
            prompt += f"\n\n[어제 글] 어제 발행한 글이다. 해석에서 짚은 조건이 오늘 어떻게 되었는지 확인하라.\n{prev}"
        prompt += f"\n\n[뉴스] 지난 48시간 수집분이다. 원인은 반드시 여기에 근거해 쓴다.\n{news_block}"
        system, mode = MARKET_SYSTEM, "시장리뷰"
    else:
        prompt = f"오늘은 {now_kst:%Y년 %m월 %d일} 한국시간 아침이다. 미국장 휴장 구간이다.\n"
        if prev:
            prompt += f"\n[어제 글]\n{prev}\n"
        prompt += f"\n[뉴스] 지난 48시간 수집분이다. 여기 있는 내용만 쓴다.\n{news_block}"
        system, mode = NEWS_SYSTEM, "뉴스"

    report, used = try_generate(key, ver, cands, system, prompt)
    if report is None:
        send_telegram("⚠️ 오늘 리포트 생성 실패 (API 한도 초과로 보임). 발행을 건너뜁니다.")
        return

    print(f"[model] {used} / [mode] {mode}")
    body = style_html(report["html"])
    if market:
        note = basis_note(snaps)
        body = body.replace("</table>", "</table>" + note, 1) if "</table>" in body else note + body

    labels = (report.get("labels") or []) + [mode]
    tags = " ".join("#" + re.sub(r"[\s#]+", "", t) for t in labels if t.strip())
    body += f'<p {TAGS}>{tags}</p>'

    title = f"{now_kst:%y%m%d}_{report['title']}"
    url = post_to_blogger(title, body, labels)
    print(f"[blogger] {url}")

    prefix = "[초안] " if DRAFT else ""
    send_telegram(f"{prefix}<b>{htmllib.escape(title)}</b>\n\n"
                  + "\n".join(f"▸ {htmllib.escape(s)}" for s in report["summary3"])
                  + f"\n\n{url}\n\n{htmllib.escape(tags)}")
    print("[telegram] 전송 완료")


if __name__ == "__main__":
    main()
