# -*- coding: utf-8 -*-
"""Gate 2.2：內外盤與均價的對帳（只用富果 RAW 欄位，不猜）。

2330（2026-10-07 09:32:06 實抓）：
  tradeVolume 4,904 張；AtAsk 1,383 + AtBid 948 = 2,331 張；差 2,573 張沒有歸到內外盤。
  同一份資料 lastTrial（開盤前試撮）size 2,570 張，與差額接近 → 推測差額主要是開盤集合競價，
  但富果文件沒有明寫，所以畫面只說「無法歸類」，不說成「開盤量」。
因此：
  - 外盤比一律用 AtAsk ÷ (AtAsk + AtBid)，不能除以總量（否則會被開盤量稀釋）。
  - 另外顯示「可歸類比例」＝(AtAsk + AtBid) ÷ 總量，讓使用者知道外盤比是用多少量算的。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from data_bundle import Section


@dataclass
class AskBidBreakdown:
    total: Optional[float]
    at_ask: Optional[float]
    at_bid: Optional[float]
    unclassified: Optional[float]      # 總量 − 外盤 − 內盤
    classified_share: Optional[float]  # (外盤 + 內盤) ÷ 總量
    ask_ratio: Optional[float]         # 外盤 ÷ (外盤 + 內盤)
    consistent: bool                   # 外盤 + 內盤 ≤ 總量（資料自洽）
    note: str = ""


def ask_bid_breakdown(quote: Section) -> AskBidBreakdown:
    g = lambda k: quote.items[k].value if k in quote.items else None  # noqa: E731
    total, a, b = g("trade_volume"), g("volume_at_ask"), g("volume_at_bid")
    if None in (total, a, b):
        return AskBidBreakdown(total, a, b, None, None, None, False, "內外盤資料不完整")
    classified = a + b
    ratio = a / classified if classified > 0 else None
    share = classified / total if total > 0 else None
    ok = classified <= total + 1e-9
    note = "" if ok else "外盤＋內盤大於總量，資料可能有誤"
    return AskBidBreakdown(total, a, b, total - classified, share, ratio, ok, note)


def vwap_matches_avg_price(quote: Section, tolerance: float = 0.01) -> Optional[bool]:
    """自己算的 VWAP（tradeValue ÷ 張數×1000）是否等於富果 avgPrice；任一缺值回 None。"""
    v = quote.items.get("vwap")
    p = quote.items.get("avg_price")
    if v is None or p is None or v.value is None or p.value is None:
        return None
    return abs(v.value - p.value) <= tolerance
