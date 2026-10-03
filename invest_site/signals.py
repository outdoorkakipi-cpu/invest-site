"""指標ごとの判定ルール。

状態は4種類:
  signal  点灯   … 数か月〜1年の上昇を期待しやすい局面（買い方向）
  watch   注目   … 売られすぎ・転換の手前など、点灯に近い局面
  caution 警戒   … 景気・需給の悪化や過熱
  neutral 平常
閾値は過去に有効だった経験則の初期値で、将来を保証するものではない。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Indicator:
    id: str
    market: str  # macro / us / jp / crypto
    name: str
    status: str = "neutral"
    value: str = "—"
    summary: str = ""
    rule: str = ""
    source: str = ""
    asof: str = ""
    series: pd.Series | None = field(default=None, repr=False)
    error: str | None = None


def _asof(s: pd.Series) -> str:
    return s.index[-1].strftime("%Y-%m-%d")


def _chg(s: pd.Series, days: int) -> float:
    """days 日前（カレンダー日）からの変化率。"""
    past = s[s.index <= s.index[-1] - pd.Timedelta(days=days)]
    if past.empty:
        return float("nan")
    return s.iloc[-1] / past.iloc[-1] - 1


def _window(s: pd.Series, days: int) -> pd.Series:
    return s[s.index > s.index[-1] - pd.Timedelta(days=days)]


# ---------- マクロ ----------

def hy_spread(s: pd.Series) -> Indicator:
    ind = Indicator("hy", "macro", "米ハイイールド債スプレッド", source="FRED BAMLH0A0HYM2",
                    rule="3か月内のピークが1年最低から1pt以上拡大し、そこから0.5pt以上縮小で点灯")
    cur = s.iloc[-1]
    w3 = _window(s, 92)
    peak = w3.max()
    low1y = _window(s, 365).min()
    ind.value = f"{cur:.2f}%"
    if peak - low1y >= 1.0 and peak - cur >= 0.5:
        ind.status, ind.summary = "signal", f"信用不安のピーク（{peak:.2f}%）を通過し縮小中"
    elif cur - w3.min() >= 1.0:
        ind.status, ind.summary = "caution", f"3か月で{cur - w3.min():+.2f}pt拡大。信用不安が高まっている"
    else:
        ind.summary = f"1年の範囲 {low1y:.2f}〜{_window(s, 365).max():.2f}%"
    ind.series, ind.asof = _window(s, 365), _asof(s)
    return ind


def net_liquidity(walcl: pd.Series, tga: pd.Series, rrp: pd.Series) -> Indicator:
    ind = Indicator("liq", "macro", "米ネット流動性", source="FRED WALCL − WTREGEN − RRPONTSYD",
                    rule="13週で+2%以上増加なら点灯、−2%以下なら警戒")
    # 単位: WALCL・WTREGEN は百万ドル、RRPONTSYD は十億ドル
    idx = walcl.index
    tga_a = tga.reindex(idx, method="ffill")
    rrp_a = rrp.reindex(rrp.index.union(idx)).ffill().reindex(idx)
    s = ((walcl - tga_a - rrp_a * 1000) / 1e6).dropna()  # 兆ドル
    c = _chg(s, 91)
    ind.value = f"{s.iloc[-1]:.2f}兆ドル"
    if c >= 0.02:
        ind.status, ind.summary = "signal", f"13週で{c:+.1%}。株・暗号資産の追い風"
    elif c <= -0.02:
        ind.status, ind.summary = "caution", f"13週で{c:+.1%}。市場から資金が抜けている"
    else:
        ind.summary = f"13週で{c:+.1%}。横ばい"
    ind.series, ind.asof = _window(s, 365), _asof(s)
    return ind


def yield_curve(s: pd.Series) -> Indicator:
    ind = Indicator("curve", "macro", "長短金利差（10年−3か月）", source="FRED T10Y3M",
                    rule="1年以内に逆イールドだったものがプラスに戻ったら警戒")
    cur = s.iloc[-1]
    ind.value = f"{cur:+.2f}pt"
    was_inverted = (_window(s, 365) < 0).any()
    if cur < 0:
        ind.status, ind.summary = "watch", "逆イールド中。解消のタイミングに注意"
    elif was_inverted:
        ind.status, ind.summary = "caution", "逆イールドが解消。過去は解消後に景気後退入りが多い"
    else:
        ind.summary = "順イールド。景気後退のサインなし"
    ind.series, ind.asof = _window(s, 730), _asof(s)
    return ind


def jobless_claims(s: pd.Series) -> Indicator:
    ind = Indicator("claims", "macro", "新規失業保険申請（4週平均）", source="FRED ICSA",
                    rule="4週平均が1年の最低から20%以上増えたら警戒")
    avg = s.rolling(4).mean().dropna()
    cur = avg.iloc[-1]
    low = _window(avg, 365).min()
    up = cur / low - 1
    ind.value = f"{cur / 1000:.0f}千件"
    if up >= 0.2:
        ind.status, ind.summary = "caution", f"1年最低から{up:+.0%}。雇用が悪化し始めている"
    else:
        ind.summary = f"1年最低から{up:+.0%}"
    ind.series, ind.asof = _window(avg, 365), _asof(s)
    return ind


def financial_conditions(s: pd.Series) -> Indicator:
    ind = Indicator("nfci", "macro", "金融環境指数", source="FRED NFCI",
                    rule="プラス（平均より引き締め）なら警戒、13週で0.1以上低下なら点灯")
    cur = s.iloc[-1]
    past = s[s.index <= s.index[-1] - pd.Timedelta(days=91)]
    d = cur - past.iloc[-1] if not past.empty else 0.0
    ind.value = f"{cur:+.2f}"
    if cur > 0:
        ind.status, ind.summary = "caution", "平均より引き締まった金融環境"
    elif d <= -0.1:
        ind.status, ind.summary = "signal", f"13週で{d:+.2f}。緩和方向へ"
    else:
        ind.summary = f"13週で{d:+.2f}。マイナスは平均より緩和的"
    ind.series, ind.asof = _window(s, 365), _asof(s)
    return ind


def vix(s: pd.Series) -> Indicator:
    ind = Indicator("vix", "macro", "VIX（米国株の恐怖指数）", source="FRED VIXCLS",
                    rule="1か月内に30超、そこから2割以上低下で点灯")
    cur = s.iloc[-1]
    peak = _window(s, 30).max()
    ind.value = f"{cur:.1f}"
    if peak >= 30 and cur <= peak * 0.8:
        ind.status, ind.summary = "signal", f"恐怖のピーク（{peak:.1f}）を通過"
    elif cur >= 30:
        ind.status, ind.summary = "watch", "パニック水準。ピークアウト待ち"
    elif cur >= 22:
        ind.status, ind.summary = "caution", "不安が高まっている"
    else:
        ind.summary = "落ち着いている"
    ind.series, ind.asof = _window(s, 365), _asof(s)
    return ind


def dollar(s: pd.Series) -> Indicator:
    ind = Indicator("usd", "macro", "ドル指数（広義）", source="FRED DTWEXBGS",
                    rule="13週で−3%以下のドル安なら点灯、+3%以上のドル高なら警戒")
    c = _chg(s, 91)
    ind.value = f"{s.iloc[-1]:.1f}"
    if c <= -0.03:
        ind.status, ind.summary = "signal", f"13週で{c:+.1%}のドル安。リスク資産の追い風"
    elif c >= 0.03:
        ind.status, ind.summary = "caution", f"13週で{c:+.1%}のドル高。リスク資産の逆風"
    else:
        ind.summary = f"13週で{c:+.1%}"
    ind.series, ind.asof = _window(s, 365), _asof(s)
    return ind


# ---------- 株価指数 ----------

def trend_200d(id_: str, market: str, name: str, source: str, s: pd.Series) -> Indicator:
    ind = Indicator(id_, market, name, source=source,
                    rule="200日線を上抜けて20営業日以内なら点灯、下回っていれば警戒")
    ma = s.rolling(200).mean()
    above = (s > ma)[ma.notna()]
    cur, m = s.iloc[-1], ma.iloc[-1]
    gap = cur / m - 1
    ind.value = f"{cur:,.0f}"
    if above.iloc[-1]:
        recent = above.iloc[-21:]
        if (~recent).any():
            ind.status, ind.summary = "signal", f"200日線を上抜け（乖離{gap:+.1%}）。中期上昇トレンド入りの候補"
        else:
            ind.summary = f"200日線の上で推移（乖離{gap:+.1%}）"
    else:
        ind.status, ind.summary = "caution", f"200日線の下（乖離{gap:+.1%}）。中期は守り"
    ind.series, ind.asof = _window(s, 365), _asof(s)
    return ind


def breadth(s: pd.Series) -> Indicator:
    ind = Indicator("breadth", "us", "S&P500 200日線より上の銘柄割合", source="Yahoo Finance（構成銘柄から計算）",
                    rule="60日内に20%以下、現在30%以上まで回復で点灯")
    cur = s.iloc[-1]
    low = _window(s, 90).min()
    ind.value = f"{cur:.0f}%"
    if low <= 20 and cur >= 30:
        ind.status, ind.summary = "signal", f"売られすぎ（{low:.0f}%）から回復中"
    elif cur <= 20:
        ind.status, ind.summary = "watch", "売られすぎ圏。回復待ち"
    elif cur >= 85:
        ind.status, ind.summary = "caution", "ほぼ全銘柄が上昇トレンド。過熱気味"
    else:
        ind.summary = "中立圏"
    ind.series, ind.asof = _window(s, 365), _asof(s)
    return ind


def usdjpy(s: pd.Series) -> Indicator:
    ind = Indicator("usdjpy", "jp", "ドル円", source="Yahoo Finance JPY=X",
                    rule="13週で−5%以下の急な円高なら警戒")
    c = _chg(s, 91)
    ind.value = f"{s.iloc[-1]:.2f}円"
    if c <= -0.05:
        ind.status, ind.summary = "caution", f"13週で{c:+.1%}の急な円高。輸出株に逆風"
    elif c >= 0.05:
        ind.status, ind.summary = "watch", f"13週で{c:+.1%}の円安。輸出株に追い風、介入に注意"
    else:
        ind.summary = f"13週で{c:+.1%}"
    ind.series, ind.asof = _window(s, 365), _asof(s)
    return ind


# ---------- 暗号資産 ----------

def btc_200w(weekly: pd.Series) -> Indicator:
    ind = Indicator("btc200w", "crypto", "BTC / 200週移動平均", source="Yahoo Finance BTC-USD（週足）",
                    rule="200週線の1.2倍以内で点灯、2.5倍以上で警戒")
    ma = weekly.rolling(200).mean()
    ratio = (weekly / ma).dropna()
    r = ratio.iloc[-1]
    ind.value = f"{r:.2f}倍（${weekly.iloc[-1]:,.0f}）"
    if r <= 1.2:
        ind.status, ind.summary = "signal", "長期の割安圏"
    elif r >= 2.5:
        ind.status, ind.summary = "caution", "長期平均から大きく上に乖離。過熱"
    else:
        ind.summary = f"200週線 ${ma.iloc[-1]:,.0f}"
    ind.series, ind.asof = ratio.iloc[-156:], _asof(weekly)
    return ind


def mvrv(s: pd.Series) -> Indicator:
    ind = Indicator("mvrv", "crypto", "BTC MVRV", source="Coin Metrics Community",
                    rule="1.0以下で点灯、3.0以上で警戒")
    cur = s.iloc[-1]
    ind.value = f"{cur:.2f}"
    if cur <= 1.0:
        ind.status, ind.summary = "signal", "保有者の平均取得価格を下回る割安圏"
    elif cur >= 3.0:
        ind.status, ind.summary = "caution", "含み益が大きく、売り圧力が出やすい過熱圏"
    else:
        ind.summary = "中立圏（1〜3）"
    ind.series, ind.asof = _window(s, 730), _asof(s)
    return ind


def fear_greed(s: pd.Series) -> Indicator:
    ind = Indicator("fng", "crypto", "Crypto Fear & Greed", source="alternative.me",
                    rule="30日内に20以下が7日以上、現在30超で点灯。80以上で警戒")
    cur = s.iloc[-1]
    w = _window(s, 30)
    ind.value = f"{cur:.0f}"
    if (w <= 20).sum() >= 7 and cur > 30:
        ind.status, ind.summary = "signal", "極度の恐怖を抜けて回復"
    elif cur <= 20:
        ind.status, ind.summary = "watch", "極度の恐怖。回復待ち"
    elif cur >= 80:
        ind.status, ind.summary = "caution", "極度の強欲。過熱"
    else:
        ind.summary = "中立圏"
    ind.series, ind.asof = _window(s, 365), _asof(s)
    return ind


def stablecoins(s: pd.Series) -> Indicator:
    ind = Indicator("stable", "crypto", "ステーブルコイン総額", source="DefiLlama",
                    rule="30日で+2%以上なら点灯、−2%以下なら警戒")
    c = _chg(s, 30)
    ind.value = f"${s.iloc[-1] / 1e9:,.0f}B"
    if c >= 0.02:
        ind.status, ind.summary = "signal", f"30日で{c:+.1%}。待機資金が増えている"
    elif c <= -0.02:
        ind.status, ind.summary = "caution", f"30日で{c:+.1%}。資金が流出している"
    else:
        ind.summary = f"30日で{c:+.1%}"
    ind.series, ind.asof = _window(s, 365), _asof(s)
    return ind


def funding(s: pd.Series) -> Indicator:
    ind = Indicator("funding", "crypto", "BTC 資金調達率（7日平均）", source="OKX BTC-USDT-SWAP",
                    rule="7日平均がマイナスで注目、0.03%/8h以上で警戒")
    daily = s.resample("D").mean().dropna()
    avg7 = daily.rolling(7).mean().dropna()
    cur = avg7.iloc[-1]
    ind.value = f"{cur:.4f}%"
    if cur < 0:
        ind.status, ind.summary = "watch", "先物が売りに偏っている（売られすぎ寄り）"
    elif cur >= 0.03:
        ind.status, ind.summary = "caution", "レバレッジの買いが過熱"
    else:
        ind.summary = "平常（年率換算 約{:.0f}%）".format(cur * 3 * 365)
    ind.series, ind.asof = avg7, _asof(s)
    return ind
