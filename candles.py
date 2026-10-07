# -*- coding: utf-8 -*-
"""Gate 2.2：富果 K 線與大盤指數 adapter（依 2026-10-07 盤中 RAW_CAPTURE 寫成，不猜格式）。

實測確認（tests/fixtures/raw/fugle_candles_*、fugle_quote_IX*）：
- 回傳：{"date","type","exchange","market","symbol","timeframe","data":[...]}；
  每根 {"date": "2026-10-07T09:00:00.000+08:00", open, high, low, close, volume, average}。
- 時間 = K 棒「開始」時間（第一根 09:00；5 分 K 邊界對齊 09:00、09:05、09:10…）。
- 排序：舊 → 新。一次回傳當日全部 K 棒（139 根 1 分 K 沒有分頁）。
- volume 單位：張。2330 09:00～09:31 的 1 分 K 量加總 4,901 張，報價 09:32:06 總量 4,904 張。
  09:00 那根包含開盤集合競價的量。
- average：當日累積均價（2330 09:31 為 2568.98、09:32 為 2569.01；同時報價 avgPrice 2568.99）。
- 沒有成交的分鐘「不會出現」（不會補一根量 0 的 K 棒）；低流動股一天只有幾根。
- 回傳包含「還在形成中」的最後一根，而且已結束的 K 棒之後仍可能被修正：
  2330 11:19 那根在 11:20:05 抓是 量 21／收 2575，11:26:50 再抓變成 量 30／收 2570。
  每根 K 棒沒有「已定案」之類的欄位（只有 date/open/high/low/close/volume/average）。
  revision study（fugle_candles_revision_study_20261007.json，11:45～12:11，每約 21 秒重抓）：
    2330、1711 共 74 根 K 棒，每根結束後觀察 151～891 秒；其中 29 根在結束後還被修正，
    最晚一次在結束後 ≤18 秒被看到（因為取樣間隔約 21 秒，這是上限），沒有任何一根在 60 秒後才變。
    低流動 2701 沒有觀察到修正。
    注意範圍：只量了午盤；09:00 開盤集合競價那根、13:30 收盤那根還沒量。
  所以：
  * 不宣稱「已完成」；只分 PROVISIONAL（暫定，可能被修正）與 SETTLED（可給指標用）。
  * SETTLED 的條件 = 抓取時間 ≥ K 棒結束時間 + settle_seconds。預設 120 秒
    （約實測最大值 18 秒的 6 倍）；這是設定值，不是資料源保證。
- 已完成的 1 分 K 聚合後和 5 分 K 一致（2330 11:15～11:19：量 75、收 2570）。
- 盤中價格是原始成交價，沒有還原權值的問題。

大盤（IX0001 加權、IX0043 櫃買）：用同一個 quote 端點，type="INDEX"，沒有五檔與 lastPrice；
最新點數在 closePrice。total.tradeVolume 的單位文件沒寫，這裡不換算、標「單位未確認」。

排行與全市場快照（snapshot/actives、movers、quotes）：目前方案回 403 Forbidden，
不能用來做排行榜格，要換方案或改用其他資料源（需使用者決定）。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from data_bundle import Availability, Section, from_epoch_us, num, require_aware
from schema import DataKind, SourceType

DEFAULT_SETTLE_SECONDS = 120      # 依 2026-10-07 revision study（最大 ≤18 秒）取 6 倍餘裕；可調
TIME_SEMANTICS = "bar_start"
PROVISIONAL = "PROVISIONAL"       # 暫定：資料源可能還會修正
SETTLED = "SETTLED"               # 已過設定的穩定期：可給指標／回測使用


def candle_section_name(timeframe: int) -> str:
    return f"{timeframe}分K"


def _parse_bar_time(s: str) -> datetime:
    t = datetime.fromisoformat(str(s))
    return require_aware(t, "K 棒時間")


def fugle_candles(raw: dict, fetched_at: datetime, timeframe: int,
                  settle_seconds: float = DEFAULT_SETTLE_SECONDS) -> Section:
    """富果 intraday/candles → K 線區塊。每一列多一個 state 欄位（PROVISIONAL／SETTLED）。"""
    if not isinstance(settle_seconds, (int, float)) or settle_seconds < 60:
        raise ValueError("settle_seconds 至少 60 秒（實測修正會發生在結束後十幾秒）")
    if not isinstance(raw, dict) or not isinstance(raw.get("data"), list):
        raise ValueError("富果 K 線格式錯誤")
    if str(raw.get("timeframe")) != str(timeframe):
        raise ValueError(f"要求 {timeframe} 分 K，回傳是 {raw.get('timeframe')} 分 K")
    fetched_at = require_aware(fetched_at)
    span = timedelta(minutes=timeframe)
    rows: List[Dict[str, Any]] = []
    prev = None
    for bar in raw["data"]:
        start = _parse_bar_time(bar.get("date"))
        if prev is not None and start <= prev:
            raise ValueError("K 線不是由舊到新排序（與實測格式不符）")
        prev = start
        end = start + span
        rows.append({
            "start": start, "end": end,
            "open": num(bar.get("open")), "high": num(bar.get("high")),
            "low": num(bar.get("low")), "close": num(bar.get("close")),
            "volume": num(bar.get("volume")),
            "day_average": num(bar.get("average")),
            "state": SETTLED if fetched_at >= end + timedelta(seconds=settle_seconds) else PROVISIONAL,
        })
    as_of = rows[-1]["start"] if rows else None
    settled = [r for r in rows if r["state"] == SETTLED]
    sec = Section(candle_section_name(timeframe), "Fugle", SourceType.VENDOR, fetched_at, as_of=as_of, rows=rows,
                  meta={"timeframe_minutes": timeframe, "time_semantics": TIME_SEMANTICS, "sort": "oldest_first",
                        "volume_unit": "lots", "average_means": "當日累積均價",
                        "no_trade_minutes": "不出現（不補 0 量 K 棒）",
                        "settle_seconds": settle_seconds,
                        "settle_policy": "K 棒結束後再過 settle_seconds 才算 SETTLED（設定值，依 revision study）",
                        "has_final_flag": False,
                        "as_of_means": "最後一根 K 棒的開始時間（latest_bar_as_of）",
                        "latest_bar_as_of": as_of,
                        "latest_settled_bar_as_of": settled[-1]["start"] if settled else None})
    if not rows:
        sec.availability = Availability.UNAVAILABLE
        sec.note = "今天還沒有成交"
    return sec


def settled_bars(sec: Section) -> List[Dict[str, Any]]:
    """只給 SETTLED 的 K 棒（指標、回測只能用這些）。不代表資料源保證不再修正。"""
    return [r for r in sec.rows if r["state"] == SETTLED]


def provisional_bars(sec: Section) -> List[Dict[str, Any]]:
    """暫定的 K 棒（畫面可以畫，但要標示「可能被資料源修正」）。"""
    return [r for r in sec.rows if r["state"] == PROVISIONAL]


def aggregate(bars: List[Dict[str, Any]], minutes: int) -> List[Dict[str, Any]]:
    """把 SETTLED 的 1 分 K 聚合成 N 分 K（邊界對齊整點，與富果 5 分 K 相同）。含暫定 K 棒就拋例外。"""
    if any(b["state"] != SETTLED for b in bars):
        raise ValueError("只能聚合 SETTLED 的 K 棒")
    out: Dict[datetime, Dict[str, Any]] = {}
    for b in bars:
        s = b["start"]
        k = s.replace(minute=s.minute - s.minute % minutes, second=0, microsecond=0)
        if k not in out:
            out[k] = {"start": k, "end": k + timedelta(minutes=minutes), "open": b["open"], "high": b["high"],
                      "low": b["low"], "close": b["close"], "volume": b["volume"]}
        else:
            o = out[k]
            o["high"], o["low"] = max(o["high"], b["high"]), min(o["low"], b["low"])
            o["close"], o["volume"] = b["close"], o["volume"] + b["volume"]
    return list(out.values())


def revision_lags(observations: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """revision study：每檔每根 K 棒「最後一次數值改變」被看到時，距離 K 棒結束幾秒。

    observations：[{"s": 代號, "t": "YYYY-MM-DD HH:MM:SS", "bars": [[HH:MM, o, h, l, c, v], ...]}, ...]（1 分 K）
    回傳 {代號: {"watched": 觀察超過 min_watch 秒的 K 棒數, "revised_after_end": 結束後才變的根數,
               "max_lag": 最大秒數（取樣上限）, "lags": [...]}}
    """
    def sec(hms: str) -> int:
        h, m, *rest = (int(x) for x in hms.split(":"))
        return h * 3600 + m * 60 + (rest[0] if rest else 0)
    out: Dict[str, Dict[str, Any]] = {}
    for sym in sorted({o["s"] for o in observations}):
        last, changed, watched = {}, {}, {}
        for o in observations:
            if o["s"] != sym:
                continue
            ft = sec(o["t"][11:])
            for b in o["bars"]:
                k, v = b[0], tuple(b[1:])
                end = sec(k) + 60
                if k in last and last[k] != v:
                    changed[k] = ft - end
                last[k] = v
                watched[k] = ft - end
        keep = [k for k, w in watched.items() if w >= 120]
        lags = sorted(changed[k] for k in keep if k in changed and changed[k] > 0)
        out[sym] = {"watched": len(keep), "revised_after_end": len(lags), "max_lag": lags[-1] if lags else None,
                    "lags": lags}
    return out


def candles_as_of(raw: dict) -> Optional[datetime]:
    """給 MarketDataCoordinator 的 Source.as_of：K 線的資料時間 = 最後一根的開始時間。"""
    data = raw.get("data") if isinstance(raw, dict) else None
    return _parse_bar_time(data[-1]["date"]) if data else None


INDEX = "大盤指數"


def fugle_index_quote(raw: dict, fetched_at: datetime) -> Section:
    """富果 quote（type=INDEX）→ 大盤區塊。最新點數用 closePrice；成交量單位未確認，不換算。"""
    if not isinstance(raw, dict) or raw.get("type") != "INDEX":
        raise ValueError("不是指數報價")
    sec = Section(f"{INDEX}：{raw.get('name') or raw.get('symbol')}", "Fugle", SourceType.VENDOR, fetched_at,
                  as_of=from_epoch_us(raw.get("lastUpdated")),
                  meta={"symbol": raw.get("symbol"), "trade_volume_unit": "未確認（文件沒寫）",
                        "trade_value_unit": "TWD"})
    for key, src in (("last", "closePrice"), ("previous_close", "previousClose"), ("open", "openPrice"),
                     ("high", "highPrice"), ("low", "lowPrice"), ("change", "change"),
                     ("change_percent", "changePercent")):
        sec.dp(key, num(raw.get(src)))
    total = raw.get("total") or {}
    sec.dp("trade_value", num(total.get("tradeValue")), note="單位：元")
    sec.dp("trade_volume", num(total.get("tradeVolume")), note="單位未確認")
    if sec.items["last"].value is None:
        sec.availability, sec.note = Availability.PARTIAL, "缺最新點數"
    return sec
