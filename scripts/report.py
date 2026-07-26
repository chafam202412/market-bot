"""스냅샷 -> Gemini 리포트 생성 -> 텔레그램 전송 (블로그 발행 전 테스트용)."""
import datetime as dt
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

KST = dt.timezone(dt.timedelta(hours=9))
GEMINI = "https://generativelanguage.googleapis.com/v1beta"

SYSTEM = """당신은 한국어 금융 블로그의 필자다. 새벽 미국시장 스냅샷을 받아 아침 리뷰를 쓴다.

원칙:
- 주어진 숫자 밖의 수치를 절대 만들어내지 않는다. 모르면 언급하지 않는다.
- 등락에 사후 서사를 단정하지 않는다. "시장이 붙인 설명"과 "해석"을 구분해 쓴다.
- 과장이나 낚시 표현을 쓰지 않는다. 담백한 전문가 톤.

반드시 아래 JSON 형식으로만 답한다.
{"title": "...", "html": "...", "summary3": ["...", "...", "..."], "labels": ["..."]}

html은 블로그 본문이다. <h2>, <h3>, <p>, <table>, <ul>, <li>만 사용한다. 구성:
1) 맨 위에 주요 지표 요약 <table> (지수, 금리, 달러, 유가, VIX / 종가와 등락률)
2) <h2>시장을 지배한 핵심 이슈 3가지</h2> 각각 현황 / 시장이 붙인 설명 / 해석
3) <h2>주식시장 리뷰 및 해석</h2> 지수와 섹터
4) <h2>채권시장 리뷰 및 해석</h2> 금리 레벨과 커브 방향
5) <h2>기타 이슈</h2> 환율, 원자재, 가상자산
6) <h2>향후 주요 일정</h2>

summary3은 텔레그램용 3줄 요약이며 각 60자 내외로 쓴다."""


def pick_model(key: str) -> str:
    """무료 티어에서 쓸 수 있는 flash 계열 모델을 자동으로 고른다."""
    if os.environ.get("GEMINI_MODEL"):
        return os.environ["GEMINI_MODEL"]
    with urllib.request.urlopen(f"{GEMINI}/models?key={key}", timeout=30) as r:
        models = json.load(r).get("models", [])
    usable = [
        m["name"].split("/")[-1]
        for m in models
        if "generateContent" in m.get("supportedGenerationMethods", [])
        and not any(x in m["name"] for x in ("image", "tts", "embedding", "vision"))
    ]
    for pref in ("flash", "lite", ""):
        for m in usable:
            if pref in m:
                print(f"[model] {m}  (후보 {len(usable)}개)")
                return m
    raise RuntimeError("사용 가능한 모델을 찾지 못했습니다")


def latest_snapshot_file() -> Path:
    files = sorted(Path("snapshots").glob("*.jsonl"))
    if not files:
        raise SystemExit("snapshots 폴더에 파일이 없습니다. collect를 먼저 실행하세요.")
    return files[-1]


def generate(key: str, model: str, prompt: str) -> dict:
    body = json.dumps(
        {
            "systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.4,
                "maxOutputTokens": 8192,
                "responseMimeType": "application/json",
            },
        }
    ).encode()
    req = urllib.request.Request(
        f"{GEMINI}/models/{model}:generateContent?key={key}",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        res = json.load(r)
    text = "".join(p.get("text", "") for p in res["candidates"][0]["content"]["parts"])
    return json.loads(text)


def send_telegram(text: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat = os.environ["TELEGRAM_CHAT_ID"]
    for i in range(0, len(text), 3800):  # 텔레그램 메시지 길이 제한
        data = urllib.parse.urlencode({"chat_id": chat, "text": text[i : i + 3800]}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=data
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()


def html_to_text(html: str) -> str:
    t = re.sub(r"</(h2|h3|p|tr|li)>", "\n", html)
    t = re.sub(r"</t[dh]>", " | ", t)
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def main() -> None:
    key = os.environ["GEMINI_API_KEY"]
    now_kst = dt.datetime.now(dt.timezone.utc).astimezone(KST)

    path = latest_snapshot_file()
    snaps = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"[data] {path.name}, 스냅샷 {len(snaps)}건")

    prompt = (
        f"오늘은 {now_kst:%Y년 %m월 %d일} 한국시간 아침이다.\n"
        f"[장중 스냅샷 {len(snaps)}건]\n"
        + json.dumps(snaps, ensure_ascii=False)
        + "\n\n마지막 스냅샷이 사실상 종가다. 장중 흐름의 변화도 해석에 반영하라."
    )

    model = pick_model(key)
    report = generate(key, model, prompt)
    print(f"[title] {report['title']}")

    msg = (
        f"[테스트] {report['title']}\n\n"
        + "\n".join(f"• {s}" for s in report["summary3"])
        + "\n\n---\n"
        + html_to_text(report["html"])
    )
    send_telegram(msg)
    print("[telegram] 전송 완료")


if __name__ == "__main__":
    main()
