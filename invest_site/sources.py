"""無料のデータ源から時系列を取得する。

どの関数も pandas.Series（日付インデックス、昇順）を返す。
取得に失敗したら例外を投げ、呼び出し側でその指標だけを「取得失敗」にする。
"""

from __future__ import annotations

import csv
import io
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (invest-site; personal dashboard)"}
TIMEOUT = 30


def _get(url: str, **kw) -> requests.Response:
    last = None
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=TIMEOUT, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException as e:  # 一時的な失敗は少し待って再試行
            last = e
            time.sleep(2 * (attempt + 1))
    raise last  # type: ignore[misc]


def fred(series_id: str) -> pd.Series:
    """FRED の公開CSV（APIキー不要）。欠損は '.' で表される。"""
    r = _get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": series_id})
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    s = df.dropna().set_index("date")["value"]
    s.name = series_id
    return s


def yahoo(symbol: str, range_: str = "2y", interval: str = "1d") -> pd.Series:
    """Yahoo Finance の chart API から終値を取得する。"""
    r = _get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        params={"range": range_, "interval": interval},
    )
    res = r.json()["chart"]["result"][0]
    ts = pd.to_datetime(res["timestamp"], unit="s").normalize()
    close = res["indicators"]["quote"][0]["close"]
    s = pd.Series(close, index=ts, dtype="float64").dropna()
    s = s[~s.index.duplicated(keep="last")]
    s.name = symbol
    return s


def sp500_symbols() -> list[str]:
    r = _get("https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    return [row["Symbol"].replace(".", "-") for row in rows]


def sp500_breadth() -> pd.Series:
    """S&P500 構成銘柄のうち 200日移動平均より上にある割合(%)の日次系列。"""
    symbols = sp500_symbols()

    def one(sym: str):
        try:
            return yahoo(sym, "2y")
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=8) as ex:
        series = [s for s in ex.map(one, symbols) if s is not None and len(s) > 220]
    if len(series) < len(symbols) * 0.8:
        raise RuntimeError(f"取得できた銘柄が少なすぎます ({len(series)}/{len(symbols)})")
    closes = pd.concat(series, axis=1).sort_index().ffill(limit=3)
    above = closes > closes.rolling(200).mean()
    valid = closes.rolling(200).mean().notna()
    pct = (above & valid).sum(axis=1) / valid.sum(axis=1) * 100
    pct = pct[valid.sum(axis=1) > len(series) * 0.8]
    pct.name = "breadth"
    return pct


def crypto_fear_greed() -> pd.Series:
    r = _get("https://api.alternative.me/fng/", params={"limit": 400})
    data = r.json()["data"]
    s = pd.Series(
        [float(d["value"]) for d in data],
        index=pd.to_datetime([int(d["timestamp"]) for d in data], unit="s").normalize(),
    ).sort_index()
    s.name = "fng"
    return s


def btc_mvrv() -> pd.Series:
    r = _get(
        "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics",
        params={
            "assets": "btc",
            "metrics": "CapMVRVCur",
            "frequency": "1d",
            "start_time": (pd.Timestamp.utcnow() - pd.Timedelta(days=800)).strftime("%Y-%m-%d"),
            "page_size": 10000,
        },
    )
    data = r.json()["data"]
    s = pd.Series(
        [float(d["CapMVRVCur"]) for d in data],
        index=pd.to_datetime([d["time"] for d in data]).tz_localize(None).normalize(),
    ).sort_index()
    s.name = "mvrv"
    return s


def stablecoin_total() -> pd.Series:
    r = _get("https://stablecoins.llama.fi/stablecoincharts/all")
    data = r.json()
    s = pd.Series(
        [float(d["totalCirculatingUSD"]["peggedUSD"]) for d in data],
        index=pd.to_datetime([int(d["date"]) for d in data], unit="s").normalize(),
    ).sort_index()
    s.name = "stablecoins"
    return s


def btc_funding() -> pd.Series:
    """OKX の BTC 無期限先物の資金調達率（8時間ごと、%）。Binance は米国IPを拒否するため使わない。"""
    rows = []
    after = None
    for _ in range(3):  # 1回100件 × 3 = 約100日分
        params = {"instId": "BTC-USDT-SWAP", "limit": 100}
        if after:
            params["after"] = after
        data = _get("https://www.okx.com/api/v5/public/funding-rate-history", params=params).json()["data"]
        if not data:
            break
        rows += data
        after = data[-1]["fundingTime"]
    s = pd.Series(
        [float(d["realizedRate"] or d["fundingRate"]) * 100 for d in rows],
        index=pd.to_datetime([int(d["fundingTime"]) for d in rows], unit="ms"),
    ).sort_index()
    s = s[~s.index.duplicated()]
    s.name = "funding"
    return s


def rss(url: str, limit: int = 8) -> list[dict]:
    """RSS / Atom を読み、見出し・リンク・日付だけを返す（本文は扱わない）。"""
    r = _get(url)
    root = ET.fromstring(r.content)
    items = []
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        title = link = date = None
        for c in it:
            ct = c.tag.split("}")[-1]
            if ct == "title":
                title = (c.text or "").strip()
            elif ct == "link":
                link = (c.text or c.get("href") or "").strip()
            elif ct in ("pubDate", "date", "updated", "published"):
                date = (c.text or "").strip()
        if not title or not link:
            continue
        when = None
        if date:
            try:
                when = parsedate_to_datetime(date)
            except (TypeError, ValueError):
                try:
                    when = pd.Timestamp(date).to_pydatetime()
                except ValueError:
                    when = None
        items.append({"title": title, "link": link, "date": when})
    items.sort(key=lambda x: (x["date"] is not None, x["date"] and x["date"].timestamp()), reverse=True)
    return items[:limit]
