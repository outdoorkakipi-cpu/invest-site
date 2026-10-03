"""毎日の更新処理: データ取得 → 判定 → 履歴保存 → site/index.html 生成。

  python -m invest_site.main           実データで更新
  python -m invest_site.main --sample  ネットに出ず、合成データで画面だけ確認
"""

from __future__ import annotations

import argparse
import json
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import signals as sg
from . import sources as src
from .render import render

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = ROOT / "site"
JST = timezone(timedelta(hours=9))

NEWS_FEEDS = [
    ("FRB（米連邦準備制度）", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("日本銀行", "https://www.boj.or.jp/rss/whatsnew.xml"),
    ("金融政策・景気", "https://news.google.com/rss/search?q=%E5%88%A9%E4%B8%8B%E3%81%92+OR+%E5%88%A9%E4%B8%8A%E3%81%92+OR+%E6%99%AF%E6%B0%97%E5%BE%8C%E9%80%80+when:7d&hl=ja&gl=JP&ceid=JP:ja"),
    ("暗号資産", "https://news.google.com/rss/search?q=%E3%83%93%E3%83%83%E3%83%88%E3%82%B3%E3%82%A4%E3%83%B3+ETF+OR+%E8%A6%8F%E5%88%B6+when:7d&hl=ja&gl=JP&ceid=JP:ja"),
]


def build_indicators(get) -> list[sg.Indicator]:
    """get(name) で系列を取り出し、指標ごとに判定する。1つ失敗しても他は続ける。"""
    specs = [
        ("hy", "macro", "米ハイイールド債スプレッド", lambda: sg.hy_spread(get("BAMLH0A0HYM2"))),
        ("liq", "macro", "米ネット流動性", lambda: sg.net_liquidity(get("WALCL"), get("WTREGEN"), get("RRPONTSYD"))),
        ("curve", "macro", "長短金利差（10年−3か月）", lambda: sg.yield_curve(get("T10Y3M"))),
        ("claims", "macro", "新規失業保険申請（4週平均）", lambda: sg.jobless_claims(get("ICSA"))),
        ("nfci", "macro", "金融環境指数", lambda: sg.financial_conditions(get("NFCI"))),
        ("vix", "macro", "VIX（米国株の恐怖指数）", lambda: sg.vix(get("VIXCLS"))),
        ("usd", "macro", "ドル指数（広義）", lambda: sg.dollar(get("DTWEXBGS"))),
        ("spx", "us", "S&P500", lambda: sg.trend_200d("spx", "us", "S&P500", "Yahoo Finance ^GSPC", get("^GSPC"))),
        ("ndx", "us", "NASDAQ100", lambda: sg.trend_200d("ndx", "us", "NASDAQ100", "Yahoo Finance ^NDX", get("^NDX"))),
        ("breadth", "us", "S&P500 200日線より上の銘柄割合", lambda: sg.breadth(get("breadth"))),
        ("n225", "jp", "日経平均", lambda: sg.trend_200d("n225", "jp", "日経平均", "Yahoo Finance ^N225", get("^N225"))),
        ("topix", "jp", "TOPIX（ETF 1306）", lambda: sg.trend_200d("topix", "jp", "TOPIX（ETF 1306）", "Yahoo Finance 1306.T", get("1306.T"))),
        ("usdjpy", "jp", "ドル円", lambda: sg.usdjpy(get("JPY=X"))),
        ("btc200w", "crypto", "BTC / 200週移動平均", lambda: sg.btc_200w(get("BTC-USD:1wk"))),
        ("mvrv", "crypto", "BTC MVRV", lambda: sg.mvrv(get("mvrv"))),
        ("fng", "crypto", "Crypto Fear & Greed", lambda: sg.fear_greed(get("fng"))),
        ("stable", "crypto", "ステーブルコイン総額", lambda: sg.stablecoins(get("stablecoins"))),
        ("funding", "crypto", "BTC 資金調達率（7日平均）", lambda: sg.funding(get("funding"))),
    ]
    out = []
    for id_, market, name, fn in specs:
        try:
            out.append(fn())
        except Exception as e:
            traceback.print_exc()
            out.append(sg.Indicator(id_, market, name, error=type(e).__name__))
    return out


def live_getter():
    cache: dict[str, pd.Series] = {}

    def get(name: str) -> pd.Series:
        if name not in cache:
            if name == "breadth":
                cache[name] = src.sp500_breadth()
            elif name == "mvrv":
                cache[name] = src.btc_mvrv()
            elif name == "fng":
                cache[name] = src.crypto_fear_greed()
            elif name == "stablecoins":
                cache[name] = src.stablecoin_total()
            elif name == "funding":
                cache[name] = src.btc_funding()
            elif name == "BTC-USD:1wk":
                cache[name] = src.yahoo("BTC-USD", "10y", "1wk")
            elif name[0] == "^" or "." in name or "=" in name:
                cache[name] = src.yahoo(name, "2y")
            else:
                cache[name] = src.fred(name)
        return cache[name]

    return get


def sample_getter():
    """オフライン確認用の合成データ（実在の値ではない）。"""
    rng = np.random.default_rng(7)

    def walk(n, start, vol, freq="B", drift=0.0):
        idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=n, freq=freq)
        return pd.Series(start * np.exp(np.cumsum(rng.normal(drift, vol, n))), index=idx)

    fixed = {
        "BAMLH0A0HYM2": walk(600, 3.2, 0.02), "WALCL": walk(120, 6.6e6, 0.004, "W-WED"),
        "WTREGEN": walk(120, 8e5, 0.03, "W-WED"), "RRPONTSYD": walk(600, 200, 0.03),
        "T10Y3M": pd.Series(np.linspace(-1.2, 0.4, 700), index=pd.date_range(end=pd.Timestamp.today(), periods=700, freq="B")),
        "ICSA": walk(120, 230e3, 0.03, "W-SAT"), "NFCI": walk(120, 1, 0.02, "W-FRI") - 1.5,
        "VIXCLS": walk(600, 18, 0.05), "DTWEXBGS": walk(600, 120, 0.004, drift=-0.0004),
        "^GSPC": walk(600, 5000, 0.01, drift=0.0004), "^NDX": walk(600, 18000, 0.013),
        "breadth": pd.Series(np.clip(55 + np.cumsum(rng.normal(0, 3, 400)), 5, 95), index=pd.date_range(end=pd.Timestamp.today(), periods=400, freq="B")),
        "^N225": walk(600, 38000, 0.012, drift=-0.0006), "1306.T": walk(600, 2800, 0.01),
        "JPY=X": walk(600, 148, 0.005), "BTC-USD:1wk": walk(500, 9000, 0.06, "W-MON", 0.006),
        "mvrv": walk(800, 1.8, 0.02, "D"), "fng": pd.Series(np.clip(50 + np.cumsum(rng.normal(0, 5, 400)), 5, 95), index=pd.date_range(end=pd.Timestamp.today(), periods=400)),
        "stablecoins": walk(800, 1.6e11, 0.003, "D", 0.001), "funding": walk(300, 0.01, 0.1, "8h"),
    }
    return lambda name: fixed[name]


def fetch_news(sample: bool):
    if sample:
        demo = [{"title": "（サンプル）見出しがここに並びます", "link": "https://example.com", "date": datetime.now(JST)}]
        return [(t, demo) for t, _ in NEWS_FEEDS]
    out = []
    for title, url in NEWS_FEEDS:
        try:
            out.append((title, src.rss(url)))
        except Exception:
            traceback.print_exc()
            out.append((title, None))
    return out


def update_log(inds: list[sg.Indicator], today: str, path: Path) -> pd.DataFrame:
    """状態が前回から変わった指標だけを追記する。"""
    cols = ["date", "id", "prev", "status"]
    log = pd.read_csv(path, dtype=str) if path.exists() else pd.DataFrame(columns=cols)
    last = log.groupby("id")["status"].last().to_dict() if not log.empty else {}
    new = [
        {"date": today, "id": i.id, "prev": last.get(i.id, "new"), "status": i.status}
        for i in inds
        if not i.error and last.get(i.id) != i.status
    ]
    if new:
        log = pd.concat([log, pd.DataFrame(new)], ignore_index=True)
        log.to_csv(path, index=False)
    # 初回登録（prev=new）は「変化」ではないので表示しない
    return log[log["prev"] != "new"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    args = ap.parse_args()

    now = datetime.now(JST)
    get = sample_getter() if args.sample else live_getter()
    inds = build_indicators(get)
    feeds = fetch_news(args.sample)

    DATA.mkdir(exist_ok=True)
    SITE.mkdir(exist_ok=True)
    log_path = DATA / ("sample_log.csv" if args.sample else "signal_log.csv")
    changes = update_log(inds, now.strftime("%Y-%m-%d"), log_path)

    if not args.sample:
        snapshot = {
            "generated": now.isoformat(),
            "indicators": [
                {k: getattr(i, k) for k in ("id", "market", "name", "status", "value", "summary", "asof", "error")}
                for i in inds
            ],
        }
        (DATA / "latest.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")

    (SITE / "index.html").write_text(render(inds, changes, feeds, now), encoding="utf-8")
    failed = [i.id for i in inds if i.error]
    print(f"{len(inds) - len(failed)}/{len(inds)} 指標を更新。失敗: {failed or 'なし'}")
    if len(failed) == len(inds):
        raise SystemExit("すべての指標の取得に失敗しました")


if __name__ == "__main__":
    main()
