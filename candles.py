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
- 回傳包含「還在形成中」的最後一根。而且剛結束的 K 棒幾秒內仍可能被修正：
  2330 11:19 那根在 11:20:05 抓是 量 21／收 2575，11:26:50 再抓變成 量 30／收 2570。
  所以「已完成」的判定 = 抓取時間 ≥ 開始時間 + 週期 + 緩衝秒數（預設 60 秒，可調）。
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

DEFAULT_GRACE_SECONDS = 60          # 實測剛結束的 K 棒 5 秒後還在變；保守給 60 秒（可調）
TIME_SEMANTICS = "bar_start"


def candle_section_name(timeframe: int) -> str:
    return f"{timeframe}分K"


def _parse_bar_time(s: str) -> datetime:
    t = datetime.fromisoformat(str(s))
    return require_aware(t, "K 棒時間")


def fugle_candles(raw: dict, fetched_at: datetime, timeframe: int,
                  grace_seconds: float = DEFAULT_GRACE_SECONDS) -> Section:
    """富果 intraday/candles → K 線區塊。每一列多一個 completed（已完成）欄位。"""
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
            "completed": fetched_at >= end + timedelta(seconds=grace_seconds),
        })
    as_of = rows[-1]["start"] if rows else None
    sec = Section(candle_section_name(timeframe), "Fugle", SourceType.VENDOR, fetched_at, as_of=as_of, rows=rows,
                  meta={"timeframe_minutes": timeframe, "time_semantics": TIME_SEMANTICS, "sort": "oldest_first",
                        "volume_unit": "lots", "average_means": "當日累積均價",
                        "no_trade_minutes": "不出現（不補 0 量 K 棒）",
                        "grace_seconds": grace_seconds,
                        "as_of_means": "最後一根 K 棒的開始時間"})
    if not rows:
        sec.availability = Availability.UNAVAILABLE
        sec.note = "今天還沒有成交"
    return sec


def completed_bars(sec: Section) -> List[Dict[str, Any]]:
    """只給已完成的 K 棒（指標、回測只能用這些，避免偷看未來）。"""
    return [r for r in sec.rows if r["completed"]]


def live_bar(sec: Section) -> Optional[Dict[str, Any]]:
    """形成中的最後一根（畫面可以畫，但要標示「未完成」）；沒有就回 None。"""
    if sec.rows and not sec.rows[-1]["completed"]:
        return sec.rows[-1]
    return None


def aggregate(bars: List[Dict[str, Any]], minutes: int) -> List[Dict[str, Any]]:
    """把已完成的 1 分 K 聚合成 N 分 K（邊界對齊整點，與富果 5 分 K 相同）。只接受已完成的 K 棒。"""
    if any(not b["completed"] for b in bars):
        raise ValueError("只能聚合已完成的 K 棒")
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
