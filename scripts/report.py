"""스냅샷 -> Gemini 리포트 생성 -> 텔레그램 전송 (블로그 발행 전 테스트용)."""
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

SYSTEM = """당신은 한국어 금융 블로그의 필자다. 새벽 미국시장 데이터를 받아 아침 리뷰를 쓴다.
독자는 금융 전문가가 아니라 일반 투자자다. 글을 다 읽고 나면 "아, 이래서 시장이 이렇게 움직였구나"
하고 이해할 수 있어야 한다. 숫자 나열이 아니라 인과를 설명하는 글을 쓴다.

원칙:
- 주어진 숫자 밖의 수치를 절대 만들어내지 않는다. 모르면 언급하지 않는다.
- 금리는 반드시 bp(베이시스포인트)로 표기한다. 데이터의 chg_bp 값을 쓰고 금리 변동을 %로 쓰지 않는다.
  (예: "10년물 4.679%, 2.4bp 하락")
- 원인은 단정하지 말고 시장의 통상적 해석으로 서술한다. ("~라는 분석이 우세합니다", "~로 풀이됩니다")
- 전문용어는 괄호로 짧게 풀어준다. (예: 차익실현(오른 종목을 팔아 이익을 확정하는 것))
- 현황은 짧게, 원인과 해석에 분량을 쓴다.
- 본문 전체 2,500자 안팎.

반드시 아래 JSON 형식으로만 답한다. 다른 말은 붙이지 않는다.
{"title": "...", "html": "...", "summary3": ["...", "...", "..."], "labels": ["..."]}

html 본문은 <h2>, <h3>, <p>, <table>, <tr>, <td>, <ul>, <li>만 사용한다.
아래 세 부분으로만 구성하고, 그 밖의 섹션은 만들지 않는다.

[1] 맨 위 주요 지표 <table>. 첫 행은 머리글(지표/종가/등락).
    주가지수는 %, 금리는 bp, 환율·유가·금은 % 로 표기.

[2] <h2>시장을 지배한 핵심 이슈 3가지</h2>
    이슈는 반드시 아래 세 가지 영역을 하나씩 맡는다. 순서와 말머리를 그대로 지킨다.
    <h3>1. [주식] 이슈 제목</h3>
    <p>1) 현황: 한두 문장</p>
    <p>2) 원인</p>
    <ul><li>...</li><li>...</li></ul>
    <p>3) 해석</p>
    <ul><li>...</li><li>...</li></ul>

    <h3>2. [채권] 이슈 제목</h3>   (같은 형식)
    <h3>3. [기타] 이슈 제목</h3>   (환율·원자재·가상자산 중 그날 가장 움직임이 큰 것)

    원인과 해석은 각각 불릿 2~3개, 한 불릿은 한 문장.
    해석에는 이 움직임이 앞으로 무엇을 의미하는지를 담는다.

[3] <h2>향후 주요 일정</h2> <ul><li>날짜 - 일정명 - 왜 중요한지</li></ul>
    검색으로 확인된 실제 일정만 쓴다. 확인하지 못했으면 목록 대신
    <p>확인된 주요 일정이 없습니다.</p> 로 대체한다. 날짜를 추측해서 쓰지 않는다.

summary3은 텔레그램용 3줄 요약이며 각 45자 내외."""

B, BE = "\x01b\x02", "\x01/b\x02"
P, PE = "\x01p\x02", "\x01/p\x02"


def http_json(url: str, body: dict | None = None, timeout: int = 300) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        msg = re.search(r'"message":\s*"([^"]{0,300})', detail)
        safe = re.sub(r"key=[^&]+", "key=***", url)
        print(f"[HTTP {e.code}] {safe}\n   {msg.group(1) if msg else detail[:300]}")
        raise


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
            and not any(
                x in m["name"]
                for x in ("image", "tts", "embedding", "vision", "live", "omni")
            )
        ]
        if names:
            return ver, names
    raise SystemExit("모델 목록을 가져오지 못했습니다. API 키를 확인하세요.")


def rank(names: list[str]) -> list[str]:
    def score(n: str) -> tuple:
        m = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        ver = float(m.group(1)) if m else 0.0
        is_flash = "flash" in n and "lite" not in n
        return (0 if is_flash else 1 if "flash" in n else 2,
                1 if ("preview" in n or "exp" in n) else 0, -ver, n)

    return sorted(names, key=score)


def latest_snapshot_file() -> Path:
    files = sorted(Path("snapshots").glob("*.jsonl"))
    if not files:
        raise SystemExit("snapshots 폴더가 비어 있습니다. collect를 먼저 실행하세요.")
    return files[-1]


def add_bp(snaps: list) -> list:
    for rec in snaps:
        for k, v in rec.get("data", {}).items():
            if k in YIELD_KEYS and v.get("last") is not None and v.get("prev_close"):
                v["chg_bp"] = round((v["last"] - v["prev_close"]) * 100, 1)
                v.pop("chg_pct", None)
    return snaps


def extract_json(text: str) -> dict:
    t = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        s, e = t.find("{"), t.rfind("}")
        if s == -1 or e == -1:
            raise
        return json.loads(t[s : e + 1])


def call(key: str, ver: str, name: str, prompt: str, with_search: bool) -> dict:
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 32768},
    }
    if with_search:
        body["tools"] = [{"google_search": {}}]
    else:
        body["generationConfig"]["responseMimeType"] = "application/json"

    res = http_json(f"{HOST}/{ver}/{name}:generateContent?key={key}", body)
    cand = res.get("candidates", [{}])[0]
    text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
    return extract_json(text)


def generate(key: str, ver: str, candidates: list[str], prompt: str) -> dict:
    for name in candidates[:6]:
        for with_search in (True, False):
            tag = "검색O" if with_search else "검색X"
            try:
                report = call(key, ver, name, prompt, with_search)
            except urllib.error.HTTPError:
                print(f"[skip] {name} ({tag})")
                continue
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                print(f"[skip] {name} ({tag}) 파싱 실패: {e}")
                continue
            print(f"[model] {name} ({tag}) 사용")
            return report
    raise SystemExit("사용 가능한 모델을 찾지 못했습니다.")


# ---------- 텔레그램 서식 ----------

def _width(s: str) -> int:
    return sum(2 if ord(c) > 0x1100 else 1 for c in s)


def _pad(s: str, w: int) -> str:
    return s + " " * max(0, w - _width(s))


def _table_repl(m: re.Match) -> str:
    rows = []
    for r in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", m.group(0)):
        cells = [
            re.sub(r"<[^>]+>", "", c).strip()
            for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", r)
        ]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    widths = [max(_width(r[i]) for r in rows) for i in range(n)]
    lines = ["  ".join(_pad(c, widths[i]) for i, c in enumerate(r)).rstrip() for r in rows]
    return f"\n{P}" + "\n".join(lines) + f"{PE}\n"


def html_to_telegram(html: str) -> str:
    t = re.sub(r"(?is)<table.*?</table>", _table_repl, html)
    t = re.sub(r"(?is)<h2[^>]*>(.*?)</h2>",
               lambda m: f"\n\n━━━━━━━━━━━━\n{B}{m.group(1).strip()}{BE}\n", t)
    t = re.sub(r"(?is)<h3[^>]*>(.*?)</h3>",
               lambda m: f"\n\n{B}{m.group(1).strip()}{BE}\n", t)
    t = re.sub(r"(?is)<li[^>]*>(.*?)</li>", lambda m: f"  · {m.group(1).strip()}\n", t)
    t = re.sub(r"(?is)</p>", "\n\n", t)
    t = re.sub(r"(?is)<br\s*/?>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = htmllib.unescape(t)
    # "1) 현황", "2) 원인", "3) 해석" 말머리를 굵게
    t = re.sub(r"(?m)^\s*(\d\)\s*(?:현황|원인|해석))", lambda m: f"{B}{m.group(1)}{BE}", t)
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = (t.replace(B, "<b>").replace(BE, "</b>")
          .replace(P, "<pre>").replace(PE, "</pre>"))
    t = re.sub(r"[ \t]+\n", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def send_telegram(text: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat = os.environ["TELEGRAM_CHAT_ID"]
    chunks, buf = [], ""
    for para in text.split("\n\n"):
        if _width(buf) + _width(para) > 3400 and buf:
            chunks.append(buf)
            buf = ""
        buf += ("\n\n" if buf else "") + para
    if buf:
        chunks.append(buf)

    for c in chunks:
        data = urllib.parse.urlencode(
            {"chat_id": chat, "text": c, "parse_mode": "HTML",
             "disable_web_page_preview": "true"}
        ).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=data
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
    print(f"[telegram] {len(chunks)}개 메시지 전송")


def main() -> None:
    key = os.environ["GEMINI_API_KEY"]
    now_kst = dt.datetime.now(dt.timezone.utc).astimezone(KST)

    path = latest_snapshot_file()
    snaps = add_bp(
        [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    )
    print(f"[data] {path.name}, 스냅샷 {len(snaps)}건")

    ver, names = list_models(key)
    ranked = rank(names)
    print(f"[api] {ver} / 시도 순서: {', '.join(n.split('/')[-1] for n in ranked[:5])}")

    prompt = (
        f"오늘은 {now_kst:%Y년 %m월 %d일} 한국시간 아침이다.\n"
        f"[장중 스냅샷 {len(snaps)}건] 금리 항목의 chg_bp는 bp 단위 변동이다.\n"
        + json.dumps(snaps, ensure_ascii=False)
        + "\n\n마지막 스냅샷이 사실상 종가다. 장중 흐름의 변화도 해석에 반영하라."
        + "\n향후 일정은 검색으로 실제 발표 예정일을 확인한 것만 쓴다."
    )

    report = generate(key, ver, ranked, prompt)
    print(f"[title] {report['title']}")

    head = (
        f"<b>{htmllib.escape(report['title'])}</b>\n\n"
        + "\n".join(f"▸ {htmllib.escape(s)}" for s in report["summary3"])
    )
    send_telegram(head + "\n\n" + html_to_telegram(report["html"]))


if __name__ == "__main__":
    main()
