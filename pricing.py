"""
台股戰情室：價格工具（第二階段 D2-10，v0）

- 只做「價格合法性」與「風險參考價」的計算，不做任何多空判斷。
- 所有參數（1.5×ATR、1.5R、3R、結構低點天數）都是 v0 固定規則，尚未經過歷史回測驗證。
- 用 Decimal 計算，避免浮點誤差（例如 44.66 對齊成 44.65）。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from typing import Optional, Sequence

STOCK = "STOCK"
ETF = "ETF"
UNKNOWN = "UNKNOWN"

# 股票升降單位（證交所現行規則）：價格區間上限（不含） → 跳動單位
_STOCK_TICKS = [
    (Decimal("10"), Decimal("0.01")),
    (Decimal("50"), Decimal("0.05")),
    (Decimal("100"), Decimal("0.1")),
    (Decimal("500"), Decimal("0.5")),
    (Decimal("1000"), Decimal("1")),
    (None, Decimal("5")),
]
# ETF：50 元以下 0.01，50 元以上 0.05
_ETF_TICKS = [
    (Decimal("50"), Decimal("0.01")),
    (None, Decimal("0.05")),
]


# ETF 子類別（策略語意不同：債券、槓桿、反向 ETF 的長線判斷先不支援）
ETF_EQUITY = "EQUITY"
ETF_BOND = "BOND"
ETF_LEVERAGED = "LEVERAGED"
ETF_INVERSE = "INVERSE"
ETF_OTHER = "OTHER"

# 已知 ETF 清單（正式資料應來自交易所商品清單；這裡只放少量已確認代號）
KNOWN_ETFS = {
    "0050": ETF_EQUITY, "0056": ETF_EQUITY, "006208": ETF_EQUITY, "00878": ETF_EQUITY,
    "00919": ETF_EQUITY, "00929": ETF_EQUITY, "00940": ETF_EQUITY, "00713": ETF_EQUITY,
    "00679B": ETF_BOND, "00631L": ETF_LEVERAGED, "00632R": ETF_INVERSE,
}


@dataclass
class AssetInfo:
    asset_type: str          # STOCK / ETF / UNKNOWN
    subtype: Optional[str]   # ETF 子類別；股票為 None
    source: str              # "商品清單" / "已知清單" / "代號推測" / "無法確認"


def asset_info(symbol: str, metadata: Optional[dict] = None) -> AssetInfo:
    """
    商品類別判斷優先順序：
      1. 交易所／資料源商品清單 metadata（例如 {"type": "ETF", "subtype": "BOND"}）
      2. 已知 ETF 清單
      3. 代號推測（00 開頭＝ETF；字尾 B／L／R＝債券／槓桿／反向）— 只是 heuristic
      4. 都無法確認 → UNKNOWN
    """
    s = str(symbol).strip().upper()
    if metadata and metadata.get("type") in (STOCK, ETF):
        return AssetInfo(metadata["type"], metadata.get("subtype"), "商品清單")
    if s in KNOWN_ETFS:
        return AssetInfo(ETF, KNOWN_ETFS[s], "已知清單")
    if re.fullmatch(r"00\d{2,4}[A-Z]?", s):
        sub = {"B": ETF_BOND, "L": ETF_LEVERAGED, "R": ETF_INVERSE}.get(s[-1], ETF_OTHER)
        return AssetInfo(ETF, sub, "代號推測")
    if re.fullmatch(r"[1-9]\d{3}", s):
        return AssetInfo(STOCK, None, "代號推測")
    return AssetInfo(UNKNOWN, None, "無法確認")


def asset_type_of(symbol: str, metadata: Optional[dict] = None) -> str:
    return asset_info(symbol, metadata).asset_type


def _num_ok(x) -> bool:
    if x is None:
        return False
    try:
        v = float(x)
    except (TypeError, ValueError):
        return False
    return not (math.isnan(v) or math.isinf(v))


def _d(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def tick_size(price, asset_type: str = STOCK) -> Optional[Decimal]:
    """依「這個價格本身」所在區間回傳跳動單位；不支援的商品回傳 None。"""
    if asset_type not in (STOCK, ETF) or not _num_ok(price):
        return None
    p = _d(price)
    if p <= 0:
        return None
    table = _STOCK_TICKS if asset_type == STOCK else _ETF_TICKS
    for upper, tick in table:
        if upper is None or p < upper:
            return tick
    return None


def align_price(price, asset_type: str = STOCK, mode: str = "down") -> Optional[Decimal]:
    """
    把價格對齊到合法升降單位。
    mode = "down"（不超過原價的最大合法價）/ "up"（不低於原價的最小合法價）/ "nearest"。
    跨級距時（例如 49.97 往上 → 50.0），以「對齊後的候選價格」所在級距為準。
    """
    if not _num_ok(price):
        return None
    p = _d(price)
    tick = tick_size(p, asset_type)
    if tick is None:
        return None
    rounding = {"down": ROUND_FLOOR, "up": ROUND_CEILING, "nearest": ROUND_HALF_UP}[mode]
    cand = (p / tick).quantize(Decimal("1"), rounding=rounding) * tick
    # 跨級距修正：候選價格所在級距的 tick 可能不同
    t2 = tick_size(cand, asset_type)
    if t2 is not None and t2 != tick:
        cand = (p / t2).quantize(Decimal("1"), rounding=rounding) * t2
        if mode == "down" and cand > p:
            cand -= t2
        if mode == "up" and cand < p:
            cand += t2
    return cand.normalize() if cand == cand.to_integral() else cand


def is_valid_price(price, asset_type: str = STOCK) -> bool:
    if not _num_ok(price):
        return False
    a = align_price(price, asset_type, "nearest")
    return a is not None and a == _d(price)


@dataclass
class LimitPrices:
    up: Optional[Decimal]
    down: Optional[Decimal]
    source: str  # "資料源提供" / "依一般 10% 規則計算" / "無法判斷"
    is_suspect: bool = False   # 資料源提供的值與一般規則明顯不一致（不覆蓋，只標記）
    note: str = ""


def limit_prices(reference, asset_type: str = STOCK,
                 provided_up=None, provided_down=None,
                 special_day: bool = False) -> LimitPrices:
    """
    漲跌停價。優先使用資料源直接提供的值；
    其次用一般規則（參考價 ±10%，漲停向下、跌停向上對齊合法價）；
    特殊交易日（新上市前 5 日、除權息特殊基準等）或不支援商品 → 無法判斷。
    """
    if _num_ok(provided_up) and _num_ok(provided_down):
        # 資料源已提供 → 直接採用，不得自行重算覆蓋；但明顯異常要標記 suspect
        up, down = _d(provided_up), _d(provided_down)
        out = LimitPrices(up, down, "資料源提供")
        if not (up > down > 0):
            out.is_suspect, out.note = True, "來源漲跌停價順序或數值異常，請確認資料品質"
        elif _num_ok(reference) and float(reference) > 0 and asset_type in (STOCK, ETF):
            ref = _d(reference)
            # 與一般 ±10% 規則相差超過 1 個百分點 → 可能是特殊交易日或資料錯誤
            if abs(up / ref - Decimal("1.1")) > Decimal("0.01") or abs(down / ref - Decimal("0.9")) > Decimal("0.01"):
                out.is_suspect = True
                out.note = "來源漲跌停價與一般 10% 規則差異異常，請確認是否為特殊交易日或資料品質問題"
        return out
    if special_day or asset_type not in (STOCK, ETF) or not _num_ok(reference) or float(reference) <= 0:
        return LimitPrices(None, None, "無法判斷")
    ref = _d(reference)
    up = align_price(ref * Decimal("1.1"), asset_type, "down")
    down = align_price(ref * Decimal("0.9"), asset_type, "up")
    return LimitPrices(up, down, "依一般 10% 規則計算")


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], n: int = 14) -> Optional[float]:
    """Wilder ATR。資料不足 n+1 根回傳 None。"""
    if len(closes) < n + 1 or not (len(highs) == len(lows) == len(closes)):
        return None
    if not all(_num_ok(v) for v in list(highs) + list(lows) + list(closes)):
        return None
    trs = []
    for i in range(1, len(closes)):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:n]) / n
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return a if a > 0 else None


# 近 N 日最低價：固定定義 = 最近 N 根「已完成」日K 的最低價（不含當天這根）。
# 注意：這不是技術分析的 swing low／結構支撐，只是可重現的「近 N 日最低價」。
RECENT_LOW_WINDOW = {"短線": 5, "波段": 20}


def recent_low(lows: Sequence[float], n: int, include_today: bool = False) -> Optional[float]:
    seq = list(lows) if include_today else list(lows)[:-1]
    if len(seq) < n or not all(_num_ok(v) for v in seq[-n:]):
        return None
    return min(seq[-n:])


def validate_long_levels(current, stop, tp1, tp2) -> list[str]:
    """多單價格順序檢查；回傳不通過的原因（空清單 = 通過）。"""
    problems = []
    vals = {"現價": current, "停損": stop, "停利1": tp1, "停利2": tp2}
    for k, v in vals.items():
        if not _num_ok(v):
            problems.append(f"{k}無法計算")
    if problems:
        return problems
    c, s, t1, t2 = map(_d, (current, stop, tp1, tp2))
    if not s < c:
        problems.append(f"停損 {s} 沒有低於現價 {c}")
    if not t1 > c:
        problems.append(f"停利1 {t1} 沒有高於現價 {c}")
    if not t2 > t1:
        problems.append(f"停利2 {t2} 沒有高於停利1 {t1}")
    return problems


@dataclass
class RiskReference:
    horizon: str
    stop: Optional[Decimal] = None
    tp1: Optional[Decimal] = None
    tp2: Optional[Decimal] = None
    r_per_share: Optional[Decimal] = None
    notes: list = field(default_factory=list)
    problems: list = field(default_factory=list)
    label: str = "風險參考價（v0 固定規則，尚未經歷史回測驗證）"

    @property
    def ok(self) -> bool:
        return not self.problems


def risk_reference_levels(current, highs, lows, closes, horizon: str = "短線",
                          asset_type: str = STOCK, limit: Optional[LimitPrices] = None,
                          atr_mult: float = 1.5, tp1_r: float = 1.5, tp2_r: float = 3.0) -> RiskReference:
    """
    多單風險參考價 v0：
      停損 = 「近 N 日最低價」與「現價 − atr_mult × ATR14」兩者中較緊（較高）的一個，向下對齊合法價
      （這不是「結構低點再減 ATR 緩衝」的模型）
      R = 現價 − 停損
      停利1 = 現價 + tp1_r × R、停利2 = 現價 + tp2_r × R，向上對齊合法價
      超過漲停價 → 加註「需隔日重算」（價格照列，但標示）
    """
    out = RiskReference(horizon=horizon)
    window = RECENT_LOW_WINDOW.get(horizon)
    if window is None:
        out.problems.append(f"不支援的週期：{horizon}")
        return out
    if asset_type not in (STOCK, ETF):
        out.problems.append("商品類別不支援")
        return out
    a = atr(highs, lows, closes)
    sl = recent_low(lows, window)
    if a is None or sl is None or not _num_ok(current) or float(current) <= 0:
        out.problems.append("歷史 K 線不足，無法計算")
        return out
    c = _d(current)
    raw_stop = max(_d(sl), c - _d(atr_mult) * _d(a))
    stop = align_price(raw_stop, asset_type, "down")
    if stop is None or stop >= c:
        out.problems.append("現價已低於近期最低價，或停損無法低於現價")
        return out
    r = c - stop
    tp1 = align_price(c + _d(tp1_r) * r, asset_type, "up")
    tp2 = align_price(c + _d(tp2_r) * r, asset_type, "up")
    out.stop, out.tp1, out.tp2, out.r_per_share = stop, tp1, tp2, r
    if limit is not None and limit.up is not None:
        if tp1 > limit.up or tp2 > limit.up:
            out.notes.append("停利價超過今日漲停價，需隔日重算")
    if limit is not None and limit.down is not None and stop < limit.down:
        out.notes.append("停損價低於今日跌停價，今日可能無法成交")
    out.problems.extend(validate_long_levels(c, stop, tp1, tp2))
    return out


def risk_amount(entry, stop, lots: float, fee_rate: float = 0.001425,
                fee_discount: float = 1.0, fee_min: int = 20, tax_rate: float = 0.003) -> Optional[int]:
    """若在停損價賣出，估計虧損金額（含買賣手續費與證交稅）。1 張 = 1000 股。"""
    if not (_num_ok(entry) and _num_ok(stop) and _num_ok(lots)) or lots <= 0 or float(stop) <= 0:
        return None
    shares = lots * 1000
    e, s = float(entry), float(stop)
    fee = lambda amt: max(int(amt * fee_rate * fee_discount), fee_min)
    loss = (e - s) * shares + fee(e * shares) + fee(s * shares) + int(s * shares * tax_rate)
    return int(round(loss))
