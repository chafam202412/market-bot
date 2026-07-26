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

SYSTEM = """당신은 한국어 금융 블로그의 필자다. 새벽 미국시장 스냅샷을 받아 아침 리뷰를 쓴다.

원칙:
- 주어진 숫자 밖의 수치를 절대 만들어내지 않는다. 모르면 언급하지 않는다.
- 등락에 사후 서사를 단정하지 않는다. "시장이 붙인 설명"과 "해석"을 구분해 쓴다.
- 과장이나 낚시 표현을 쓰지 않는다. 담백한 전문가 톤.
- 한 문단은 3문장을 넘기지 않는다. 같은 숫자를 여러 번 반복하지 않는다.
- 본문 전체를 1,800자 안팎으로 쓴다.

반드시 아래 JSON 형식으로만 답한다.
{"title": "...", "html": "...", "summary3": ["...", "...", "..."], "labels": ["..."]}

html은 블로그 본문이다. <h2>, <h3>, <p>, <table>, <tr>, <td>, <ul>, <li>만 사용한다. 구성:
1) 맨 위에 주요 지표 요약 <table> (지수, 금리, 달러, 유가, VIX / 종가와 등락률). 첫 행은 머리글.
2) <h2>시장을 지배한 핵심 이슈 3가지</h2>
   각 이슈는 <h3>제목</h3> 뒤에 <p>현황: ...</p><p>시장이 붙인 설명: ...</p><p>해석: ...</p> 세 문단.
3) <h2>주식시장 리뷰 및 해석</h2>
4) <h2>채권시장 리뷰 및 해석</h2>
5) <h2>기타 이슈</h2>
6) <h2>향후 주요 일정</h2> 는 <ul><li> 목록으로.

summary3은 텔레그램용 3줄 요약이며 각 45자 내외로 짧게 쓴다."""

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
        return (
            0 if is_flash else 1 if "flash" in n else 2,
            1 if ("preview" in n or "exp" in n) else 0,
            -ver,
            n,
        )

    return sorted(names, key=score)


def latest_snapshot_file() -> Path:
    files = sorted(Path("snapshots").glob("*.jsonl"))
    if not files:
        raise SystemExit("snapshots 폴더가 비어 있습니다. collect를 먼저 실행하세요.")
    return files[-1]


def generate(key: str, ver: str, candidates: list[str], prompt: str) -> dict:
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 32768,
            "responseMimeType": "application/json",
        },
    }
    for name in candidates[:8]:
        try:
            res = http_json(f"{HOST}/{ver}/{name}:generateContent?key={key}", body)
        except urllib.error.HTTPError:
            print(f"[skip] {name}")
            continue
        cand = res.get("candidates", [{}])[0]
        finish = cand.get("finishReason", "?")
        text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
        text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        try:
            report = json.loads(text)
        except json.JSONDecodeError as e:
            print(f"[skip] {name}: 파싱 실패 (finishReason={finish}, {e})")
            continue
        print(f"[model] {name} 사용 (finishReason={finish})")
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
    lines = [
        "  ".join(_pad(c, widths[i]) for i, c in enumerate(r)).rstrip() for r in rows
    ]
    return f"\n{P}" + "\n".join(lines) + f"{PE}\n"


def html_to_telegram(html: str) -> str:
    t = re.sub(r"(?is)<table.*?</table>", _table_repl, html)
    t = re.sub(r"(?is)<h2[^>]*>(.*?)</h2>",
               lambda m: f"\n\n━━━━━━━━━━━━\n{B}{m.group(1).strip()}{BE}\n", t)
    t = re.sub(r"(?is)<h3[^>]*>(.*?)</h3>",
               lambda m: f"\n\n{B}◆ {m.group(1).strip()}{BE}\n", t)
    t = re.sub(r"(?is)<li[^>]*>(.*?)</li>", lambda m: f"· {m.group(1).strip()}\n", t)
    t = re.sub(r"(?is)</p>", "\n\n", t)
    t = re.sub(r"(?is)<br\s*/?>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = htmllib.unescape(t)
    t = re.sub(r"(?m)^\s*(현황|시장이 붙인 설명|해석)\s*:",
               lambda m: f"{B}{m.group(1)}{BE}:", t)
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
        buf += (("\n\n" if buf else "") + para)
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
    snaps = [
        json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()
    ]
    print(f"[data] {path.name}, 스냅샷 {len(snaps)}건")

    ver, names = list_models(key)
    ranked = rank(names)
    print(f"[api] {ver} / 시도 순서: {', '.join(n.split('/')[-1] for n in ranked[:5])}")

    prompt = (
        f"오늘은 {now_kst:%Y년 %m월 %d일} 한국시간 아침이다.\n"
        f"[장중 스냅샷 {len(snaps)}건]\n"
        + json.dumps(snaps, ensure_ascii=False)
        + "\n\n마지막 스냅샷이 사실상 종가다. 장중 흐름의 변화도 해석에 반영하라."
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
