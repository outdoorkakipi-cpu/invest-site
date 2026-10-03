"""判定結果から静的な index.html を作る。外部JSは使わない。"""

from __future__ import annotations

from datetime import datetime
from html import escape

import pandas as pd

from .signals import Indicator

MARKETS = [
    ("macro", "マクロ（全市場共通）"),
    ("us", "米国株"),
    ("jp", "日本株"),
    ("crypto", "暗号資産"),
]
MARKET_SHORT = {"macro": "共通", "us": "米国", "jp": "日本", "crypto": "暗号"}
STATUS_LABEL = {"signal": "点灯", "watch": "注目", "caution": "警戒", "neutral": "平常", "error": "取得失敗"}
STATUS_ORDER = {"signal": 0, "watch": 1, "caution": 2, "neutral": 3, "error": 4}


def _fmt(v: float) -> str:
    a = abs(v)
    if a >= 1000:
        return f"{v:,.0f}"
    if a >= 10:
        return f"{v:.1f}"
    if a >= 0.1:
        return f"{v:.2f}"
    return f"{v:.4f}"


def sparkline(s: pd.Series | None, w: int = 260, h: int = 52) -> str:
    if s is None or len(s) < 2:
        return ""
    s = s.dropna()
    if len(s) > 260:  # 点を間引いて軽くする
        s = s.iloc[:: max(1, len(s) // 260)].combine_first(s.iloc[-1:])
    lo, hi = float(s.min()), float(s.max())
    span = hi - lo or 1.0
    pad = 4
    n = len(s) - 1
    pts = [
        (pad + i / n * (w - 2 * pad), pad + (1 - (v - lo) / span) * (h - 2 * pad))
        for i, v in enumerate(s.values)
    ]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"{pts[0][0]:.1f},{h - pad} {line} {pts[-1][0]:.1f},{h - pad}"
    lx, ly = pts[-1]
    start = s.index[0].strftime("%Y/%m")
    return (
        f'<svg class="spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" '
        f'aria-label="{start}以降の推移">'
        f'<polygon class="spark-area" points="{area}"/>'
        f'<polyline class="spark-line" points="{line}"/>'
        f'<circle class="spark-dot" cx="{lx:.1f}" cy="{ly:.1f}" r="3"/></svg>'
        f'<div class="spark-axis"><span>{start}</span><span>最小 {_fmt(lo)} / 最大 {_fmt(hi)}</span></div>'
    )


def _card(ind: Indicator) -> str:
    st = "error" if ind.error else ind.status
    body = (
        f'<p class="summary">取得できませんでした（{escape(ind.error)}）。次回の更新で再試行します。</p>'
        if ind.error
        else f'<p class="summary">{escape(ind.summary)}</p>{sparkline(ind.series)}'
    )
    return f"""
<article class="card st-{st}" id="{ind.id}">
  <header><h3>{escape(ind.name)}</h3><span class="pill">{STATUS_LABEL[st]}</span></header>
  <div class="value">{escape(ind.value)}</div>
  {body}
  <details><summary>判定ルール・出典</summary>
    <p>{escape(ind.rule)}</p><p class="meta">{escape(ind.source)}・データ日付 {escape(ind.asof or '—')}</p>
  </details>
</article>"""


def _highlights(inds: list[Indicator]) -> str:
    hot = [i for i in inds if not i.error and i.status != "neutral"]
    hot.sort(key=lambda i: STATUS_ORDER[i.status])
    if not hot:
        return '<p class="empty">いま点灯・注目・警戒している指標はありません。</p>'
    rows = "".join(
        f'<li class="st-{i.status}"><a href="#{i.id}"><span class="pill">{STATUS_LABEL[i.status]}</span>'
        f'<span class="mk">{MARKET_SHORT[i.market]}</span><b>{escape(i.name)}</b>'
        f'<span class="why">{escape(i.summary)}</span></a></li>'
        for i in hot
    )
    return f'<ul class="hl">{rows}</ul>'


def _changes(log: pd.DataFrame, names: dict[str, str]) -> str:
    if log.empty:
        return '<p class="empty">まだ変化の記録はありません。毎日の更新で、状態が変わった指標がここに残ります。</p>'
    recent = log.sort_values("date", ascending=False).head(15)
    rows = "".join(
        f'<tr><td class="num">{r.date}</td><td>{escape(names.get(r.id, r.id))}</td>'
        f'<td><span class="pill st-{r.prev}">{STATUS_LABEL.get(r.prev, "—")}</span> → '
        f'<span class="pill st-{r.status}">{STATUS_LABEL.get(r.status, r.status)}</span></td></tr>'
        for r in recent.itertuples()
    )
    return f'<div class="tbl"><table><tr><th>日付</th><th>指標</th><th>変化</th></tr>{rows}</table></div>'


def _news(feeds: list[tuple[str, list[dict] | None]]) -> str:
    cols = []
    for title, items in feeds:
        if items is None:
            lis = '<li class="empty">取得できませんでした</li>'
        elif not items:
            lis = '<li class="empty">新しい記事はありません</li>'
        else:
            lis = "".join(
                f'<li><a href="{escape(it["link"])}" target="_blank" rel="noopener">{escape(it["title"])}</a>'
                f'<span class="meta">{it["date"].strftime("%m/%d") if it["date"] else ""}</span></li>'
                for it in items
            )
        cols.append(f'<div class="feed"><h3>{escape(title)}</h3><ul>{lis}</ul></div>')
    return f'<div class="feeds">{"".join(cols)}</div>'


def render(inds: list[Indicator], log: pd.DataFrame, feeds, generated: datetime) -> str:
    sections = []
    for key, label in MARKETS:
        items = [i for i in inds if i.market == key]
        counts = {s: sum(1 for i in items if not i.error and i.status == s) for s in ("signal", "watch", "caution")}
        tally = "".join(
            f'<span class="pill st-{s}">{STATUS_LABEL[s]} {n}</span>' for s, n in counts.items() if n
        )
        sections.append(
            f'<section id="m-{key}"><h2>{label}<span class="tally">{tally}</span></h2>'
            f'<div class="grid">{"".join(_card(i) for i in items)}</div></section>'
        )
    names = {i.id: i.name for i in inds}
    return TEMPLATE.format(
        updated=generated.strftime("%Y年%m月%d日 %H:%M"),
        highlights=_highlights(inds),
        changes=_changes(log, names),
        sections="".join(sections),
        news=_news(feeds),
    )


TEMPLATE = """<!doctype html>
<html lang="ja"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>投資シグナル帳</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=BIZ+UDPGothic:wght@400;700&family=Zen+Kaku+Gothic+New:wght@700;900&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{{--bg:#f4f6f5;--surface:#fff;--fg:#1b2420;--muted:#5d6a64;--line:#d9dfdb;--accent:#1f6f5c;
--signal:#16794f;--signal-bg:#dcf1e6;--watch:#2a5fb0;--watch-bg:#dfe8f8;--caution:#b0413e;--caution-bg:#f8e1df;
--neutral:#6b7570;--neutral-bg:#e9eceb;--error:#8a6d1a;--error-bg:#f6edd2;
--display:"Zen Kaku Gothic New","Hiragino Sans","Yu Gothic",sans-serif;--body:"BIZ UDPGothic","Hiragino Sans","Yu Gothic",sans-serif;--mono:"IBM Plex Mono",ui-monospace,Menlo,monospace}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111614;--surface:#1a211e;--fg:#e4ebe7;--muted:#9aa8a1;--line:#2c3632;--accent:#5fc0a3;
--signal:#5fcf98;--signal-bg:#173326;--watch:#86aef0;--watch-bg:#1a2740;--caution:#ec8a84;--caution-bg:#3a1d1c;
--neutral:#a3ada8;--neutral-bg:#252d29;--error:#e3c062;--error-bg:#352c14;color-scheme:dark}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);font-family:var(--body);font-size:15px;line-height:1.7}}
.wrap{{max-width:1120px;margin:0 auto;padding-inline:16px;padding-block:28px 64px;display:flex;flex-direction:column;gap:40px}}
h1,h2,h3{{font-family:var(--display);margin:0;line-height:1.35;text-wrap:balance}}
h1{{font-size:clamp(24px,4vw,32px);font-weight:900}}
h2{{font-size:20px;display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-bottom:14px}}
h3{{font-size:15px}}
a{{color:var(--accent)}}
.top{{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:8px}}
.meta{{color:var(--muted);font-size:12.5px}}
.num,.value,.pill,.meta{{font-variant-numeric:tabular-nums}}
.pill{{display:inline-block;font-size:12px;font-weight:700;padding:1px 9px;border-radius:999px;white-space:nowrap;color:var(--neutral);background:var(--neutral-bg)}}
.st-signal .pill,.pill.st-signal{{color:var(--signal);background:var(--signal-bg)}}
.st-watch .pill,.pill.st-watch{{color:var(--watch);background:var(--watch-bg)}}
.st-caution .pill,.pill.st-caution{{color:var(--caution);background:var(--caution-bg)}}
.st-error .pill,.pill.st-error{{color:var(--error);background:var(--error-bg)}}
.tally{{display:flex;gap:6px}}
.hl{{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;border:1px solid var(--line);border-radius:8px;background:var(--surface)}}
.hl li+li{{border-top:1px solid var(--line)}}
.hl a{{display:grid;grid-template-columns:auto auto minmax(0,1fr);gap:4px 10px;align-items:baseline;padding:10px 14px;color:inherit;text-decoration:none}}
.hl a:hover{{background:var(--bg)}}
.hl .mk{{font-size:12px;color:var(--muted)}}
.hl .why{{grid-column:3;color:var(--muted);font-size:13.5px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}}
.card{{background:var(--surface);border:1px solid var(--line);border-top:3px solid var(--neutral-bg);border-radius:8px;padding:14px 16px;display:flex;flex-direction:column;gap:6px;min-width:0}}
.card.st-signal{{border-top-color:var(--signal)}}.card.st-watch{{border-top-color:var(--watch)}}.card.st-caution{{border-top-color:var(--caution)}}.card.st-error{{border-top-color:var(--error)}}
.card header{{display:flex;justify-content:space-between;gap:8px;align-items:start}}
.value{{font-family:var(--mono);font-size:22px;font-weight:500}}
.summary{{margin:0;font-size:13.5px}}
.spark{{width:100%;height:52px;display:block;margin-top:4px}}
.spark-line{{fill:none;stroke:var(--accent);stroke-width:1.6;vector-effect:non-scaling-stroke}}
.spark-area{{fill:var(--accent);opacity:.08}}
.spark-dot{{fill:var(--accent)}}
.spark-axis{{display:flex;justify-content:space-between;gap:8px;font-family:var(--mono);font-size:10.5px;color:var(--muted)}}
details{{font-size:12.5px;color:var(--muted)}}
details p{{margin:4px 0 0}}
summary{{cursor:pointer}}
.tbl{{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--surface)}}
table{{border-collapse:collapse;width:100%;font-size:14px}}
th,td{{text-align:left;padding:8px 12px;border-bottom:1px solid var(--line);white-space:nowrap}}
th{{font-size:12px;color:var(--muted);font-weight:400}}
tr:last-child td{{border-bottom:none}}
.feeds{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}}
.feed{{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:14px 16px;min-width:0}}
.feed ul{{list-style:none;margin:8px 0 0;padding:0;display:flex;flex-direction:column;gap:8px;font-size:14px}}
.feed li{{display:flex;justify-content:space-between;gap:10px}}
.feed li a{{min-width:0;overflow-wrap:anywhere}}
.empty{{color:var(--muted)}}
footer{{font-size:12.5px;color:var(--muted);max-width:70ch}}
a:focus-visible,summary:focus-visible{{outline:2px solid var(--accent);outline-offset:2px}}
@media (max-width:520px){{.hl a{{grid-template-columns:auto minmax(0,1fr)}}.hl .mk{{display:none}}.hl .why{{grid-column:1/-1}}}}
</style></head>
<body><div class="wrap">
<div class="top"><h1>投資シグナル帳</h1><span class="meta">最終更新 {updated}（日本時間）</span></div>
<section><h2>いま動いている指標</h2>{highlights}</section>
<section><h2>最近の変化</h2>{changes}</section>
{sections}
<section><h2>ニュース</h2>{news}</section>
<footer>判定ルールは過去に有効だった経験則による初期値で、将来の値動きを保証するものではありません。投資判断はご自身の責任で行ってください。</footer>
</div></body></html>
"""
