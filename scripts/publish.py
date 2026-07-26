"""스냅샷 -> Gemini 리포트 -> Blogger 발행 -> 텔레그램 알림."""
import datetime as dt
import html as htmllib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

KST = dt.timezone(dt.timedelta(hours=9))
HOST = "https://generativelanguage.googleapis.com"
YIELD_KEYS = {"US13W", "US5Y", "US10Y", "US30Y"}
DRAFT = os.environ.get("PUBLISH_DRAFT", "true").lower() == "true"

COMMON = """당신은 한국어 금융 블로그의 필자다.
독자는 금융 전문가가 아니라 일반 투자자다. 글을 다 읽고 나면 "아, 이래서 시장이 이렇게 움직였구나"
하고 이해할 수 있어야 한다. 숫자 나열이 아니라 인과를 설명하는 글을 쓴다.

원칙:
- 주어진 숫자 밖의 수치를 절대 만들어내지 않는다. 모르면 언급하지 않는다.
- 금리는 반드시 bp(베이시스포인트)로 표기한다. 금리 변동을 %로 쓰지 않는다.
- 원인은 단정하지 말고 시장의 통상적 해석으로 서술한다. ("~라는 분석이 우세합니다")
- 국내 금융시장에서 실제로 통용되는 표준 용어만 쓴다. 임의로 단어를 만들거나 변형하지 않는다.
  올바른 예: 안전자산 선호, 위험자산 선호, 차익실현, 되돌림, 순환매, 커브 스티프닝, 커브 플래트닝,
  강세/약세, 매수세/매도세, 반발 매수, 경계감, 관망세.
- 전문용어는 처음 나올 때 괄호로 짧게 풀어준다.
- 현황은 짧게, 원인과 해석에 분량을 쓴다.
- 본문 전체 2,500자 안팎.

반드시 아래 JSON 형식으로만 답한다. 다른 말은 붙이지 않는다.
{"title": "...", "html": "...", "summary3": ["...", "...", "..."], "labels": ["..."]}

html 본문은 <h2>, <h3>, <p>, <table>, <tr>, <td>, <ul>, <li>만 사용한다.
summary3은 텔레그램용 3줄 요약이며 각 45자 내외."""

MARKET_SYSTEM = COMMON + """

새벽 미국시장 데이터를 받아 아침 리뷰를 쓴다. 아래 세 부분으로만 구성한다.

[1] 맨 위 주요 지표 <table>. 첫 행은 머리글(지표/종가/등락).
    주가지수는 %, 금리는 bp, 환율·유가·금은 % 로 표기.

[2] <h2>시장을 지배한 핵심 이슈 3가지</h2>
    <h3>1. [주식] 이슈 제목</h3>
    <p>1) 현황: 한두 문장</p>
    <p>2) 원인</p>
    <ul><li>...</li><li>...</li></ul>
    <p>3) 해석</p>
    <ul><li>...</li><li>...</li></ul>

    <h3>2. [채권] 이슈 제목</h3>   (같은 형식)
    <h3>3. [기타] 이슈 제목</h3>   (환율·원자재·가상자산 중 그날 움직임이 가장 큰 것)

[3] <h2>향후 주요 일정</h2> <ul><li>날짜 - 일정명 - 왜 중요한지</li></ul>
    검색으로 확인된 실제 일정만 쓴다. 확인하지 못했으면 목록 대신
    <p>확인된 주요 일정이 없습니다.</p> 로 대체한다."""

NEWS_SYSTEM = COMMON + """

오늘은 미국장 휴장일이다. 시황 대신 지난 24~48시간의 주요 금융·경제 뉴스를 정리한다.
반드시 웹 검색으로 실제 보도된 내용만 쓰고, 확인되지 않은 내용은 쓰지 않는다.

[1] <h2>주말 주요 뉴스 3가지</h2>
    <h3>1. [분야] 뉴스 제목</h3>
    <p>1) 현황: 무슨 일이 있었는지 한두 문장</p>
    <p>2) 원인</p>
    <ul><li>...</li><li>...</li></ul>
    <p>3) 해석</p>
    <ul><li>...</li><li>...</li></ul>

    분야는 통화정책·경제지표·기업·지정학·원자재 등 그 주에 실제로 중요했던 것으로 고른다.

[2] <h2>이번 주 주요 일정</h2> <ul><li>날짜 - 일정명 - 왜 중요한지</li></ul>
    검색으로 확인된 것만. 없으면 <p>확인된 주요 일정이 없습니다.</p>"""

B, BE = "\x01b\x02", "\x01/b\x02"
P, PE = "\x01p\x02", "\x01/p\x02"


def http_json(url: str, body: dict | None = None, timeout: int = 300,
              headers: dict | None = None, raw: bytes | None = None) -> dict:
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
        msg = re.search(r'"message":\s*"([^"]{0,300})', detail)
        safe = re.sub(r"key=[^&]+", "key=***", url)
        print(f"[HTTP {e.code}] {safe}\n   {msg.group(1) if msg else detail[:300]}")
        raise


# ---------- Gemini ----------

def list_models(key: str) -> tuple[str, list[str]]:
    for ver in ("v1beta", "v1"):
        try:
            res = http_json(f"{HOST}/{ver}/models?key={key}", timeout=30)
        except urllib.error.HTTPError:
            continue
        names = [
            m["name"]
            for m in res.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
            and not any(x in m["name"] for x in
                        ("image", "tts", "embedding", "vision", "live", "omni"))
        ]
        if names:
            return ver, names
    raise SystemExit("모델 목록을 가져오지 못했습니다.")


def rank(names: list[str]) -> list[str]:
    def score(n: str) -> tuple:
        m = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        ver = float(m.group(1)) if m else 0.0
        is_flash = "flash" in n and "lite" not in n
        return (0 if is_flash else 1 if "flash" in n else 2,
                1 if ("preview" in n or "exp" in n) else 0, -ver, n)

    return sorted(names, key=score)


def extract_json(text: str) -> dict:
    t = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        s, e = t.find("{"), t.rfind("}")
        if s == -1 or e == -1:
            raise
        return json.loads(t[s : e + 1])


def call(key, ver, name, system, prompt, with_search):
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 32768},
    }
    if with_search:
        body["tools"] = [{"google_search": {}}]
    else:
        body["generationConfig"]["responseMimeType"] = "application/json"
    res = http_json(f"{HOST}/{ver}/{name}:generateContent?key={key}", body)
    cand = res.get("candidates", [{}])[0]
    text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
    return extract_json(text)


def generate(key, ver, candidates, system, prompt, need_search):
    orders = (True, False) if not need_search else (True,)
    for name in candidates[:6]:
        for with_search in orders:
            tag = "검색O" if with_search else "검색X"
            try:
                report = call(key, ver, name, system, prompt, with_search)
            except urllib.error.HTTPError:
                print(f"[skip] {name} ({tag})")
                continue
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                print(f"[skip] {name} ({tag}) 파싱 실패: {e}")
                continue
            print(f"[model] {name} ({tag}) 사용")
            return report
    raise SystemExit("사용 가능한 모델을 찾지 못했습니다.")


# ---------- 데이터 ----------

def load_snapshots(date_kst: dt.date) -> list:
    path = Path("snapshots") / f"{date_kst:%Y-%m-%d}.jsonl"
    if not path.exists():
        return []
    snaps = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    for rec in snaps:
        for k, v in rec.get("data", {}).items():
            if k in YIELD_KEYS and v.get("last") is not None and v.get("prev_close"):
                v["chg_bp"] = round((v["last"] - v["prev_close"]) * 100, 1)
                v.pop("chg_pct", None)
    return snaps


# ---------- Blogger ----------

def blogger_token() -> str:
    data = urllib.parse.urlencode({
        "client_id": os.environ["BLOGGER_CLIENT_ID"],
        "client_secret": os.environ["BLOGGER_CLIENT_SECRET"],
        "refresh_token": os.environ["BLOGGER_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode()
    res = http_json("https://oauth2.googleapis.com/token", raw=data, timeout=30,
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
    return res["access_token"]


def post_to_blogger(title: str, body_html: str, labels: list) -> str:
    token = blogger_token()
    blog_id = os.environ["BLOG_ID"]
    url = f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts/"
    if DRAFT:
        url += "?isDraft=true"
    payload = {"kind": "blogger#post", "title": title,
               "content": body_html, "labels": labels[:5]}
    res = http_json(url, payload, timeout=60,
                    headers={"Authorization": f"Bearer {token}"})
    return res.get("url") or f"https://www.blogger.com/blog/posts/{blog_id}"


# ---------- 텔레그램 ----------

def send_telegram(text: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat = os.environ["TELEGRAM_CHAT_ID"]
    data = urllib.parse.urlencode(
        {"chat_id": chat, "text": text, "parse_mode": "HTML"}
    ).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()


# ---------- 본문 ----------

def main() -> None:
    key = os.environ["GEMINI_API_KEY"]
    now_kst = dt.datetime.now(dt.timezone.utc).astimezone(KST)
    snaps = load_snapshots(now_kst.date())

    # 화~토(1~5) + 스냅샷 충분 -> 시장리뷰, 그 외 -> 뉴스 (휴장일 자동 폴백)
    market = now_kst.weekday() in (1, 2, 3, 4, 5) and len(snaps) >= 4
    mode = "시장리뷰" if market else "뉴스"
    print(f"[mode] {mode} / 스냅샷 {len(snaps)}건 / 초안={DRAFT}")

    if market:
        system = MARKET_SYSTEM
        prompt = (
            f"오늘은 {now_kst:%Y년 %m월 %d일} 한국시간 아침이다.\n"
            f"[장중 스냅샷 {len(snaps)}건] 금리 항목의 chg_bp는 bp 단위 변동이다.\n"
            + json.dumps(snaps, ensure_ascii=False)
            + "\n\n마지막 스냅샷이 사실상 종가다. 장중 흐름의 변화도 해석에 반영하라."
        )
    else:
        system = NEWS_SYSTEM
        prompt = (
            f"오늘은 {now_kst:%Y년 %m월 %d일} 한국시간 아침이다.\n"
            "미국장 휴장 구간이므로 지난 24~48시간의 주요 금융·경제 뉴스를 검색해 정리하라."
        )

    ver, names = list_models(key)
    report = generate(key, ver, rank(names), system, prompt, need_search=not market)

    labels = (report.get("labels") or []) + [mode]
    url = post_to_blogger(report["title"], report["html"], labels)
    print(f"[blogger] {url}")

    prefix = "[초안] " if DRAFT else ""
    msg = (
        f"{prefix}<b>{htmllib.escape(report['title'])}</b>\n\n"
        + "\n".join(f"▸ {htmllib.escape(s)}" for s in report["summary3"])
        + f"\n\n{url}"
    )
    send_telegram(msg)
    print("[telegram] 전송 완료")


if __name__ == "__main__":
    main()
