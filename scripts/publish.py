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
- 단, 표 아래에 들어가는 "※ 위 수치는 ... 수집 시점 기준이며 ..." 형태의 안내 문구는 절대 쓰지 않는다.
  이 문구는 발행 직전에 코드가 자동으로 삽입하므로, 본문에 쓰면 같은 문장이 두 번 나온다.
- 금리는 반드시 bp(베이시스포인트)로 표기하고 %로 쓰지 않는다.
- 국내 금융시장에서 실제로 쓰는 표준 용어만 사용한다. 사전에 없는 조어나 어색한 한자 조합을
  절대 만들지 않는다. 애매하면 쉬운 우리말로 풀어 쓴다.
  허용: 안전자산 선호, 위험자산 선호, 차익실현, 순환매, 되돌림, 커브 스티프닝, 커브 플래트닝,
        강세/약세, 매수세/매도세, 반발 매수, 실적 발표, 공급 과잉, 수요 둔화, 규제 리스크.
- 전문용어는 처음 나올 때 괄호로 짧게 풀어준다.

시간 규칙 — 정규장과 시간외를 절대 섞지 않는다:
- 뉴스에는 [장중] [마감후] 표시가 붙어 있다. 코드가 정규장 마감 시각과 보도 시각을 대조해 붙인 값이다.
- [마감후] 뉴스의 주가 반응은 시간외 거래(정규장이 끝난 뒤 이뤄지는 거래)이며, 오늘 종가에는
  반영되지 않았다. 반드시 "시간외 거래에서", "다음 거래일에 반영될 전망" 같은 표현으로 구분한다.
- 실적 발표는 대개 장 마감 후에 나온다. 마감 후 실적에 따른 급등락을 그날 종가 하락의 원인으로
  적으면 사실관계 오류다. 이런 실수를 하지 않는다.
- 제공된 스냅샷 데이터는 정규장 종료 시점까지만 담고 있다. 개별 종목 등락률은 데이터에 없으므로
  기사에 적힌 수치만 인용하고, 그것이 정규장인지 시간외인지 반드시 밝힌다.

소수점 규칙:
- 등락률과 bp는 소수점 첫째 자리까지만 쓴다. (-1.5%, +13.5%, +1.8bp)
- 지수 종가는 소수점 둘째 자리까지 쓴다.

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
    주가지수는 %, 금리는 bp, 환율·유가·금은 % 로 표기하고 모두 소수점 첫째 자리까지만 쓴다.

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
PP = 'style="line-height:1.9;margin:10px 0;"'
UL = 'style="line-height:1.9;margin:8px 0 18px;padding-left:24px;"'
LI = 'style="margin:7px 0;"'
NOTE = 'style="font-size:13px;color:#64748b;margin:2px 0 20px;"'
LABEL = 'style="font-weight:700;color:#0f172a;border-bottom:2px solid #fcd34d;padding-bottom:1px;"'
BOX = 'style="background:#fffbeb;border-left:4px solid #f59e0b;padding:14px 18px;margin:14px 0 22px;border-radius:6px;"'
TAGS = 'style="margin:34px 0 0;font-size:13px;color:#9ca3af;line-height:1.9;"'
WRAP = 'style="line-height:1.9;"'
IMG = 'style="width:100%;height:auto;margin:10px 0 4px;border:1px solid #e5e7eb;border-radius:8px;"'
CAP = 'style="font-size:13px;color:#6b7280;text-align:center;margin:0 0 24px;"'
HR = '<hr style=""border:0;border-top:1px solid #e5e7eb;margin:30px 0 6px;">'
KEY = 'style="color:#c0392b;font-weight:700;"'


def wrap_interpretation(html: str) -> str:
    pat = re.compile(
        r"(?is)(<p[^>]*>\s*3\)\s*해석\s*</p>)(\s*(?:<ul[^>]*>.*?</ul>|<p[^>]*>.*?</p>|<table[^>]*>.*?</table>)+)"
    )

    def repl(m):
        return f'<div {BOX}><p><span {LABEL}>해석</span></p>{m.group(2)}</div>{HR}'

    return pat.sub(repl, html)


MOVE_WORDS = ("상승", "하락", "급등", "급락", "폭등", "폭락", "오르", "내리",
              "빠지", "반등", "되돌림", "약세", "강세")


def round_metrics(html: str) -> str:
    """등락률과 bp만 소수점 첫째 자리로 줄인다. 금리 레벨(4.622%)은 그대로 둔다."""
    # 부호가 붙은 값은 무조건 등락이다
    html = re.sub(r"([+\-]\d+\.\d{2,})\s*(%p|%|bp)",
                  lambda m: f"{float(m.group(1)):+.1f}{m.group(2)}", html)

    # 부호가 없으면 뒤에 오는 서술어로 등락인지 판단한다
    verbs = "|".join(MOVE_WORDS)
    html = re.sub(
        rf"(?<![\d.+\-])(\d+\.\d{{2,}})\s*(%p|%|bp)(\s*(?:{verbs}))",
        lambda m: f"{float(m.group(1)):.1f}{m.group(2)}{m.group(3)}", html)
    return html


def add_thousands(html: str) -> str:
    """표 셀의 4자리 이상 숫자에 천단위 쉼표를 넣는다. 이미 있으면 건드리지 않는다."""
    def fix(m):
        head, num, tail = m.group(1), m.group(2), m.group(3)
        if "," in num:
            return m.group(0)
        parts = num.split(".")
        try:
            whole = f"{int(parts[0]):,}"
        except ValueError:
            return m.group(0)
        body = whole + ("." + parts[1] if len(parts) > 1 else "")
        return f"{head}{body}{tail}"

    return re.sub(r"(?is)(<td[^>]*>\s*)(\d{4,}(?:\.\d+)?)(\s*(?:원|%|\$)?\s*</td>)",
                  fix, html)


KEYWORDS = (
    # 통화정책
    "연준", "FOMC", "금리 인하", "금리 인상", "매파", "비둘기", "기준금리", "양적긴축",
    # 지표
    "CPI", "PCE", "고용지표", "실업률", "GDP", "소비자물가", "인플레이션", "경기 침체",
    # 실적·기업
    "실적 발표", "가이던스", "어닝 서프라이즈", "어닝 쇼크", "설비투자", "감원",
    # 정책·지정학
    "관세", "수출 규제", "지정학", "제재", "감산", "증산",
    # 시장 구조
    "안전자산 선호", "위험자산 선호", "순환매", "차익실현", "시간외 거래",
    "커브 스티프닝", "커브 플래트닝", "변동성 확대",
)
KEY_PAT = re.compile("(" + "|".join(
    re.escape(w) for w in sorted(KEYWORDS, key=len, reverse=True)) + ")")


def highlight_keywords(html: str) -> str:
    """핵심 이슈 문단의 주요 키워드만 빨간 굵은 글씨로 강조한다.

    - 표 안, 이미 강조된 문단은 건드리지 않는다
    - 문단당 1개, 글 전체 8개까지만 칠해 시선이 분산되지 않게 한다
    - 같은 키워드는 처음 나올 때 한 번만 칠한다
    """
    used, budget = set(), [8]

    def per_block(m):
        tag, inner = m.group(1), m.group(2)
        if budget[0] <= 0 or "<span" in inner or "<td" in inner:
            return m.group(0)

        def one(x):
            w = x.group(1)
            if w in used or budget[0] <= 0:
                return w
            used.add(w)
            budget[0] -= 1
            return f'<span {KEY}>{w}</span>'

        return f"<{tag}>" + KEY_PAT.sub(one, inner, count=1) + f"</{tag}>"

    return re.sub(r"(?is)<(li|p)>(.*?)</\1>", per_block, html)


def style_html(html: str) -> str:
    html = round_metrics(html)
    html = add_thousands(html)
    html = highlight_keywords(html)
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


def insert_section_charts(html: str, now_kst) -> str:
    """[주식] 이슈 아래에 주가 차트, [채권] 이슈 아래에 금리 차트를 넣는다."""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        return html

    def img(kind: str) -> str:
        f = Path("charts") / f"{now_kst:%Y-%m-%d}-{kind}.png"
        if not f.exists():
            print(f"[chart] 없음: {f.name}")
            return ""
        url = f"https://raw.githubusercontent.com/{repo}/main/charts/{f.name}"
        return (f'<img src="{url}" {IMG}>'
                f'<p {CAP}>최근 3년 추이 · 회색 음영은 최근 1개월</p>')

    parts = re.split(r"(?i)(<h3[^>]*>)", html)
    for i, part in enumerate(parts):
        if not part.lower().startswith("<h3") or i + 1 >= len(parts):
            continue
        body = parts[i + 1]
        kind = "equity" if "[주식]" in body else "bond" if "[채권]" in body else ""
        tag = img(kind) if kind else ""
        if not tag:
            continue
        pos = body.find(HR)          # 해석 박스 뒤 구분선 = 이슈 블록의 끝
        parts[i + 1] = body[:pos] + tag + body[pos:] if pos != -1 else body + tag
    return "".join(parts)


def strip_basis_note(html: str) -> str:
    """모델이 기준 시점 안내 문구를 직접 써넣었으면 지운다. 코드가 따로 넣기 때문."""
    pat = re.compile(r"(?is)<p[^>]*>\s*※[^<]{0,120}?(?:수집\s*시점|시점\s*기준|종가\s*대비)[^<]{0,120}?</p>")
    cleaned, n = pat.subn("", html)
    if n:
        print(f"[clean] 본문에 중복된 기준시점 문구 {n}건 제거")
    return cleaned


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
            elif v.get("chg_pct") is not None:
                v["chg_pct"] = round(v["chg_pct"], 1)
    return snaps, path.stem


BASE_TAGS = [
    "미국증시", "뉴욕증시", "해외주식", "미국주식", "S&P500", "나스닥", "다우존스",
    "국채금리", "미국채", "채권시장", "환율", "원달러환율", "달러인덱스", "국제유가",
    "WTI", "금시세", "비트코인", "연준", "FOMC", "기준금리", "인플레이션", "경제지표",
    "반도체", "빅테크", "증시전망", "시황", "재테크", "자산배분", "투자공부", "시장동향",
]

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

    cutoff = None
    if snaps:
        try:
            cutoff = dt.datetime.fromisoformat(snaps[-1]["ts_kst"]).astimezone(dt.timezone.utc)
            print(f"[cutoff] 정규장 마감 기준 {cutoff:%Y-%m-%d %H:%M}Z 이후 = 마감후")
        except Exception:
            cutoff = None
    news_block = news_mod.as_prompt(news_mod.collect(snaps), cutoff=cutoff)
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
        body = strip_basis_note(body)
        note = basis_note(snaps)
        body = body.replace("</table>", "</table>" + note, 1) if "</table>" in body else note + body
        body = insert_section_charts(body, now_kst)

    raw_tags = (report.get("labels") or []) + BASE_TAGS
    seen, tags_list = set(), []
    for t in raw_tags:
        t = re.sub(r"[\s#]+", "", str(t))
        if t and t not in seen:
            seen.add(t)
            tags_list.append("#" + t)
    tags = " ".join(tags_list[:30])
    body = f'<div {WRAP}>{body}</div>' + f'<p {TAGS}>{tags}</p>'

    title = f"{now_kst:%y%m%d}_[시장동향]_{report['title']}"
    url = post_to_blogger(title, body, ["시장동향"])
    print(f"[blogger] {url}")

    prefix = "[초안] " if DRAFT else ""
    send_telegram(f"{prefix}<b>{htmllib.escape(title)}</b>\n\n"
                  + "\n".join(f"▸ {htmllib.escape(s)}" for s in report["summary3"])
                  + f"\n\n{url}")
    print("[telegram] 전송 완료")


if __name__ == "__main__":
    main()
