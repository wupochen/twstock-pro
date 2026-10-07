# -*- coding: utf-8 -*-
"""第二段 Gate 2.1：統一資料物件（DataBundle）與各來源 adapter。

目的：把不同來源的原始資料，轉成一致、可追溯、可判斷新鮮度的格式，再交給 UI / Engine。

Adapter 只做三件事：解析 → 單位正規化 → 加 metadata。
Adapter 不做：多空判斷、技術指標、策略分數、自動補不存在的資料。

規則（GPT Gate 2.1 驗收重點）：
1. 單位一律正規化，並在 meta 保留 raw_unit／normalized_unit／conversion。
2. None 不能偷偷變 0；只有來源明確回 0 才是 0。
3. RAW（來源原值）／CALC（本站由原值算出）／EST（推估）分清楚。
4. as_of（資料本身時間）與 fetched_at（本站抓取時間）都要有，皆為 timezone-aware UTC。
5. 不猜資料日期（月營收只用 revenue_year / revenue_month）。
6. 保留來源識別 source_name / source_type。
7. 單一來源失敗不讓整包失敗（partial success）。
8. Bundle 能自動產生資料狀況清單，UI 不自己拼第二套。

本檔不做：API 呼叫、retry、排程、背景更新、同時段量比、MarketDataCoordinator、engine、UI 接線（Gate 2.2 以後）。

build_bundle() 只負責編排（呼叫 adapter → 放進 bundle），不得在裡面做資料轉換、
計算（VWAP、外盤比…）、新鮮度判斷、來源優先順序或 fallback；這些各有自己的 adapter／helper／coordinator。

可用性（availability：有沒有資料）與新鮮度（freshness：資料新不新）是兩個維度，分開記錄。
富果 candles 端點尚未實測，等 Gate 2.2 再加 adapter，避免猜格式。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from pricing import AssetInfo
from schema import DataKind, DataPoint, MarketSession, SourceType

TPE = timezone(timedelta(hours=8))
UTC = timezone.utc


# ════════════════════════════════════════════════
# 共用工具
# ════════════════════════════════════════════════
def num(v) -> Optional[float]:
    """轉成 float；None、空字串、NaN、inf、無法轉換 → None（不變成 0）。可處理 "1,234" 這類字串。"""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        if s in ("", "-", "--", "N/A", "null", "None"):
            return None
        v = s
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def from_epoch_us(us) -> Optional[datetime]:
    """富果時間（微秒 epoch）→ UTC aware datetime。"""
    v = num(us)
    if v is None:
        return None
    return datetime.fromtimestamp(v / 1_000_000, tz=UTC)


def tpe_date_to_utc(d: date, t: time = time(13, 30)) -> datetime:
    """台北日期（盤後資料預設 13:30 收盤時點）→ UTC aware datetime。"""
    return datetime.combine(d, t, tzinfo=TPE).astimezone(UTC)


def require_aware(dt: datetime, name: str = "fetched_at") -> datetime:
    if dt is None or dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{name} 必須是 timezone-aware datetime")
    return dt.astimezone(UTC)


class Availability(str, Enum):
    AVAILABLE = "正常"
    PARTIAL = "部分缺值"
    UNAVAILABLE = "無法取得"


class Freshness(str, Enum):
    FRESH = "最新"
    STALE = "過期"
    UNKNOWN = "新鮮度未判斷"


@dataclass
class Section:
    """一個資料區塊（例如：即時報價、五檔、日K、法人）。"""
    name: str
    source_name: str
    source_type: SourceType
    fetched_at: datetime
    as_of: Optional[datetime] = None
    availability: Availability = Availability.AVAILABLE
    freshness: Freshness = Freshness.UNKNOWN          # adapter 不判斷；由 assess_freshness() 另外判
    items: Dict[str, DataPoint] = field(default_factory=dict)   # 單值欄位
    rows: List[Dict[str, Any]] = field(default_factory=list)    # 表格型資料（日K、法人、營收…）
    meta: Dict[str, Any] = field(default_factory=dict)          # 單位、換算、說明
    note: str = ""

    def __post_init__(self):
        self.fetched_at = require_aware(self.fetched_at, "fetched_at")
        if self.as_of is not None:
            self.as_of = require_aware(self.as_of, "as_of")

    def dp(self, key: str, value, kind: DataKind = DataKind.RAW, as_of: Optional[datetime] = None,
           note: str = "", estimated: bool = False) -> DataPoint:
        p = DataPoint(value=value, source_name=self.source_name, source_type=self.source_type, data_kind=kind,
                      as_of=as_of or self.as_of, fetched_at=self.fetched_at, is_estimated=estimated, note=note)
        self.items[key] = p
        return p


@dataclass
class SourceError:
    section: str
    source_name: str
    message: str


@dataclass
class StatusLine:
    section: str
    source_name: str
    source_type: SourceType
    as_of: Optional[datetime]
    availability: Availability
    freshness: Freshness
    note: str

    def text(self) -> str:
        when = "—" if self.as_of is None else self.as_of.astimezone(TPE).strftime("%Y-%m-%d %H:%M:%S")
        fresh = "" if self.freshness == Freshness.UNKNOWN else f"，{self.freshness.value}"
        extra = f"，{self.note}" if self.note else ""
        return (f"{self.section}：{self.source_name}（{self.source_type.value}），資料時間 {when}，"
                f"{self.availability.value}{fresh}{extra}")


def assess_freshness(section: "Section", now: datetime, max_age_seconds: float) -> Freshness:
    """新鮮度 helper（不放在 adapter、也不放在 build_bundle）：as_of 距 now 超過門檻 → STALE。"""
    now = require_aware(now, "now")
    if section.as_of is None:
        section.freshness = Freshness.UNKNOWN
    else:
        section.freshness = Freshness.STALE if (now - section.as_of).total_seconds() > max_age_seconds else Freshness.FRESH
    return section.freshness


SOURCE_TYPES = {"Fugle": SourceType.VENDOR, "FinMind": SourceType.THIRD_PARTY,
                "yfinance": SourceType.THIRD_PARTY, "TWSE": SourceType.OFFICIAL}

# 區塊名稱（固定，不讓 UI 自己取名）
QUOTE = "即時報價"
ORDER_BOOK = "五檔"
TRADES = "成交明細"
DAILY = "日K"
INSTITUTIONAL = "三大法人"
INSTITUTIONAL_OFFICIAL = "三大法人（證交所）"
MARGIN = "融資融券"
REVENUE = "月營收"
FUNDAMENTALS = "基本面"


@dataclass
class DataBundle:
    """一檔股票在某個時間點的完整資料容器（不是平面 dict）。"""
    symbol: str
    asset_info: Optional[AssetInfo] = None
    market_session: MarketSession = MarketSession.UNKNOWN
    sections: Dict[str, Section] = field(default_factory=dict)
    errors: List[SourceError] = field(default_factory=list)

    def get(self, name: str) -> Optional[Section]:
        return self.sections.get(name)

    def add(self, name: str, source_name: str, adapter: Callable[[], Section]) -> Optional[Section]:
        """執行一個 adapter；失敗只記錄錯誤，不影響其他區塊（partial success）。"""
        try:
            sec = adapter()
        except Exception as e:  # noqa: BLE001 — 任何來源錯誤都只影響自己這一塊
            self.errors.append(SourceError(name, source_name, f"{type(e).__name__}: {e}"))
            return None
        self.sections[name] = sec
        return sec

    def data_status(self) -> List[StatusLine]:
        lines = [StatusLine(s.name, s.source_name, s.source_type, s.as_of, s.availability, s.freshness, s.note)
                 for s in self.sections.values()]
        for e in self.errors:
            lines.append(StatusLine(e.section, e.source_name, SOURCE_TYPES.get(e.source_name, SourceType.THIRD_PARTY),
                                    None, Availability.UNAVAILABLE, Freshness.UNKNOWN, "這次沒抓到資料"))
        return lines

    def data_status_text(self) -> List[str]:
        return [l.text() for l in self.data_status()]


# ════════════════════════════════════════════════
# 富果（VENDOR）
# ════════════════════════════════════════════════
def fugle_quote(raw: dict, fetched_at: datetime) -> Section:
    """富果 intraday/quote → 即時報價區塊。

    單位：tradeVolume、tradeVolumeAtAsk/AtBid、五檔 size 都是「張」；tradeValue 是「元」。
    （2330 實測：tradeValue 12,598,330,000 ÷ (4,904 張 × 1,000) = 2,568.99 = 富果 avgPrice）
    """
    if not isinstance(raw, dict):
        raise ValueError("富果報價格式錯誤")
    as_of = from_epoch_us(raw.get("lastUpdated"))
    sec = Section(QUOTE, "Fugle", SourceType.VENDOR, fetched_at, as_of=as_of,
                  meta={"volume_unit": "lots", "value_unit": "TWD", "time_unit": "epoch_us"})
    for key, src in (("last_price", "lastPrice"), ("reference_price", "referencePrice"),
                     ("previous_close", "previousClose"), ("open", "openPrice"), ("high", "highPrice"),
                     ("low", "lowPrice"), ("change", "change"), ("change_percent", "changePercent"),
                     ("avg_price", "avgPrice")):
        sec.dp(key, num(raw.get(src)))
    total = raw.get("total") or {}
    sec.dp("trade_volume", num(total.get("tradeVolume")), note="單位：張")
    sec.dp("trade_value", num(total.get("tradeValue")), note="單位：元")
    sec.dp("volume_at_ask", num(total.get("tradeVolumeAtAsk")), note="外盤（主動買）成交量，單位：張")
    sec.dp("volume_at_bid", num(total.get("tradeVolumeAtBid")), note="內盤（主動賣）成交量，單位：張")
    sec.dp("transactions", num(total.get("transaction")), note="成交筆數")
    for key, src in (("is_limit_up_price", "isLimitUpPrice"), ("is_limit_up_bid", "isLimitUpBid"),
                     ("is_limit_down_price", "isLimitDownPrice"), ("is_limit_down_ask", "isLimitDownAsk")):
        v = raw.get(src)
        sec.dp(key, v if isinstance(v, bool) else None)   # null 保持 None（沒有資訊 ≠ False）

    # CALC：由 RAW 算出，標明公式
    a, b = sec.items["volume_at_ask"].value, sec.items["volume_at_bid"].value
    ratio = a / (a + b) if a is not None and b is not None and (a + b) > 0 else None
    sec.dp("ask_ratio", ratio, kind=DataKind.CALC, note="外盤比 = AtAsk ÷ (AtAsk + AtBid)")
    tv, vol = sec.items["trade_value"].value, sec.items["trade_volume"].value
    vwap = tv / (vol * 1000) if tv is not None and vol else None
    sec.dp("vwap", vwap, kind=DataKind.CALC, note="VWAP = tradeValue ÷ (tradeVolume × 1000)")

    missing = [k for k in ("last_price", "reference_price") if sec.items[k].value is None]
    if missing:
        sec.availability = Availability.PARTIAL
        sec.note = "缺：" + "、".join(missing)
    return sec


def fugle_order_book(raw: dict, fetched_at: datetime) -> Section:
    """富果 quote 內的五檔 → 五檔區塊。缺 bids/asks 鍵＝None（沒資料）；空陣列＝真的沒有掛單。"""
    as_of = from_epoch_us(raw.get("lastUpdated"))
    sec = Section(ORDER_BOOK, "Fugle", SourceType.VENDOR, fetched_at, as_of=as_of,
                  meta={"size_unit": "lots"})

    def levels(key):
        if key not in raw or raw.get(key) is None:
            return None
        out = []
        for lv in raw.get(key) or []:
            p, s = num((lv or {}).get("price")), num((lv or {}).get("size"))
            if p is None:     # 沒價格的檔位不補、不造假
                continue
            out.append({"price": p, "size": s})
        return out

    bids, asks = levels("bids"), levels("asks")
    sec.dp("bids", bids, note="由高到低")
    sec.dp("asks", asks, note="由低到高")
    if bids is None or asks is None:
        sec.availability = Availability.PARTIAL
        sec.note = "來源沒有提供完整五檔"
    elif not asks and raw.get("isLimitUpPrice") is True:
        sec.note = "賣方目前無掛單（漲停）"
    elif not bids and raw.get("isLimitDownPrice") is True:
        sec.note = "買方目前無掛單（跌停）"
    return sec


def fugle_trades(raw, fetched_at: datetime) -> Section:
    """富果 intraday/trades → 成交明細（只有回傳的這一段，不代表全日）。"""
    rows_raw = raw if isinstance(raw, list) else (raw or {}).get("data", [])
    rows = []
    for t in rows_raw or []:
        rows.append({"time": from_epoch_us(t.get("time")), "price": num(t.get("price")),
                     "size": num(t.get("size")), "bid": num(t.get("bid")), "ask": num(t.get("ask")),
                     "serial": t.get("serial")})
    times = [r["time"] for r in rows if r["time"] is not None]
    sec = Section(TRADES, "Fugle", SourceType.VENDOR, fetched_at, as_of=max(times) if times else None,
                  rows=rows, meta={"size_unit": "lots", "count": len(rows)},
                  note=f"只含這次回傳的 {len(rows)} 筆，不是全日成交")
    if not rows:
        sec.availability = Availability.UNAVAILABLE
    return sec


# ════════════════════════════════════════════════
# FinMind（THIRD_PARTY）
# ════════════════════════════════════════════════
def _classify_institution(name: str) -> Optional[str]:
    """沿用第一段 everlight_app.py 的分類規則（外資自營商歸外資），不在 Gate 2.1 更動。"""
    n = str(name).strip()
    low = n.lower()
    if "外資" in n or "外陸資" in n or "foreign" in low:
        return "外資"
    if "投信" in n or "trust" in low:
        return "投信"
    if "自營商" in n or "dealer" in low:
        return "自營商"
    return None


def finmind_institutional(payload, fetched_at: datetime) -> Section:
    """FinMind TaiwanStockInstitutionalInvestorsBuySell → 三大法人（張）。

    buy/sell 原始單位是「股」（已用證交所 T86 對帳），一律 ÷1000 成「張」並保留小數。
    缺 buy 或 sell → 該筆淨額 None；同一天同類別全部 None → None（不是 0）。
    """
    data = payload.get("data", []) if isinstance(payload, dict) else (payload or [])
    agg: Dict[str, Dict[str, Optional[float]]] = {}
    seen: Dict[str, Dict[str, bool]] = {}
    for r in data:
        typ = _classify_institution(r.get("name", ""))
        if typ is None:
            continue
        d = str(r.get("date"))[:10]
        b, s = num(r.get("buy")), num(r.get("sell"))
        net = (b - s) / 1000 if b is not None and s is not None else None
        agg.setdefault(d, {"外資": None, "投信": None, "自營商": None})
        seen.setdefault(d, {})[typ] = True
        if net is not None:
            agg[d][typ] = (agg[d][typ] or 0.0) + net
    rows = []
    for d in sorted(agg):
        v = agg[d]
        parts = [v["外資"], v["投信"], v["自營商"]]
        total = sum(parts) if all(p is not None for p in parts) else None
        rows.append({"date": d, "外資": v["外資"], "投信": v["投信"], "自營商": v["自營商"], "合計": total})
    last = date.fromisoformat(rows[-1]["date"]) if rows else None
    sec = Section(INSTITUTIONAL, "FinMind", SourceType.THIRD_PARTY, fetched_at,
                  as_of=tpe_date_to_utc(last) if last else None, rows=rows,
                  meta={"raw_unit": "shares", "normalized_unit": "lots", "conversion": "/1000",
                        "classification": "沿用第一段規則：外資自營商歸外資"},
                  note=f"資料日 {last:%m/%d}" if last else "")
    if not rows:
        sec.availability = Availability.UNAVAILABLE
    elif any(r[k] is None for r in rows for k in ("外資", "投信", "自營商")):
        sec.availability = Availability.PARTIAL
    return sec


def finmind_margin(payload, fetched_at: datetime) -> Section:
    """FinMind TaiwanStockMarginPurchaseShortSale → 融資融券餘額。

    單位沿用第一段（張，未換算）；尚未與官方資料對帳，meta 註明。增減屬 CALC，留給後續指標層。
    """
    data = payload.get("data", []) if isinstance(payload, dict) else (payload or [])
    rows = [{"date": str(r.get("date"))[:10], "融資餘額": num(r.get("MarginPurchaseTodayBalance")),
             "融券餘額": num(r.get("ShortSaleTodayBalance"))} for r in data]
    rows.sort(key=lambda r: r["date"])
    last = date.fromisoformat(rows[-1]["date"]) if rows else None
    sec = Section(MARGIN, "FinMind", SourceType.THIRD_PARTY, fetched_at,
                  as_of=tpe_date_to_utc(last) if last else None, rows=rows,
                  meta={"raw_unit": "lots", "normalized_unit": "lots", "conversion": "none",
                        "reconciled": False},
                  note=f"資料日 {last:%m/%d}" if last else "")
    if not rows:
        sec.availability = Availability.UNAVAILABLE
    elif any(r["融資餘額"] is None or r["融券餘額"] is None for r in rows):
        sec.availability = Availability.PARTIAL
    return sec


def finmind_revenue(payload, fetched_at: datetime) -> Section:
    """FinMind TaiwanStockMonthRevenue → 月營收（元）。

    營收所屬月份只看 revenue_year / revenue_month；缺這兩個欄位的列直接略過並記錄，
    不再用 date 猜月份（date 是公布月份的 1 號，會差一個月）。
    """
    data = payload.get("data", []) if isinstance(payload, dict) else (payload or [])
    rows, skipped = [], 0
    for r in data:
        y, m = num(r.get("revenue_year")), num(r.get("revenue_month"))
        if y is None or m is None:
            skipped += 1
            continue
        pub = r.get("create_time")
        pub_dt = None
        if pub:
            try:
                pub_dt = datetime.fromisoformat(str(pub)).replace(tzinfo=TPE).astimezone(UTC)
            except ValueError:
                pub_dt = None
        yy, mm = int(y), int(m)
        nxt = date(yy + (mm == 12), mm % 12 + 1, 1)
        rows.append({"period": f"{yy:04d}/{mm:02d}",                 # 資料所屬期間
                     "period_end": nxt - timedelta(days=1),
                     "revenue": num(r.get("revenue")),
                     "published_at": pub_dt})                          # 公布時間（另一回事）
    rows.sort(key=lambda r: r["period"])
    # 區塊 as_of 代表「資料所屬期間」的結束時點，不是公布時間
    as_of = datetime.combine(rows[-1]["period_end"], time(23, 59, 59), tzinfo=TPE).astimezone(UTC) if rows else None
    latest_pub = rows[-1]["published_at"] if rows else None
    note = ""
    if rows:
        note = f"最新 {rows[-1]['period']}" + (f"（{latest_pub.astimezone(TPE):%m/%d} 公布）" if latest_pub else "")
    if skipped:
        note += f"；略過 {skipped} 筆沒有所屬月份的資料"
    sec = Section(REVENUE, "FinMind", SourceType.THIRD_PARTY, fetched_at, as_of=as_of, rows=rows,
                  meta={"unit": "TWD", "period_from": "revenue_year/revenue_month", "skipped": skipped,
                        "as_of_means": "period_end", "latest_published_at": latest_pub},
                  note=note)
    if not rows:
        sec.availability = Availability.UNAVAILABLE
    elif skipped or any(r["revenue"] is None for r in rows):
        sec.availability = Availability.PARTIAL
    return sec


# ════════════════════════════════════════════════
# 證交所（OFFICIAL）
# ════════════════════════════════════════════════
T86_FIELDS = {
    "外資": "外陸資買賣超股數(不含外資自營商)",
    "外資自營商": "外資自營商買賣超股數",
    "投信": "投信買賣超股數",
    "自營商": "自營商買賣超股數",
    "合計": "三大法人買賣超股數",
}


def twse_t86(payload: dict, symbol: str, fetched_at: datetime) -> Section:
    """證交所 T86 三大法人買賣超日報 → 單一股票（股 → 張）。上櫃股票不在 T86。"""
    if payload.get("stat") != "OK":
        raise ValueError(f"T86 沒有資料：{payload.get('stat')}")
    fields = payload.get("fields", [])
    idx = {f: i for i, f in enumerate(fields)}
    hit = [r for r in payload.get("data", []) if str(r[0]).strip() == symbol]
    d = datetime.strptime(payload["date"], "%Y%m%d").date()
    sec = Section(INSTITUTIONAL_OFFICIAL, "TWSE", SourceType.OFFICIAL, fetched_at, as_of=tpe_date_to_utc(d),
                  meta={"raw_unit": "shares", "normalized_unit": "lots", "conversion": "/1000"},
                  note=f"資料日 {d:%m/%d}")
    if not hit:
        sec.availability = Availability.UNAVAILABLE
        sec.note += "；證交所沒有這檔（可能是上櫃股票）"
        return sec
    row = hit[0]
    for key, f in T86_FIELDS.items():
        v = num(row[idx[f]]) if f in idx and idx[f] < len(row) else None
        sec.dp(key, None if v is None else v / 1000, note="單位：張")
    return sec


# ════════════════════════════════════════════════
# yfinance（THIRD_PARTY）
# ════════════════════════════════════════════════
def yfinance_daily(df, fetched_at: datetime, session: MarketSession = MarketSession.UNKNOWN,
                   today: Optional[date] = None) -> Section:
    """yfinance 日K（pandas DataFrame，index 為日期）→ 日K 區塊。

    NaN → None。盤中時今天這根還沒收完：分開放在 meta["live_bar"]，rows 只放已完成日K。
    """
    rows = []
    if df is not None and len(df):
        for idx, r in df.iterrows():
            rows.append({"date": idx.date() if hasattr(idx, "date") else idx,
                         "open": num(r.get("Open")), "high": num(r.get("High")), "low": num(r.get("Low")),
                         "close": num(r.get("Close")), "volume": num(r.get("Volume"))})
    live = None
    if rows and today is not None and rows[-1]["date"] == today and session != MarketSession.CLOSED:
        live = rows.pop()
    last = rows[-1]["date"] if rows else None
    sec = Section(DAILY, "yfinance", SourceType.THIRD_PARTY, fetched_at,
                  as_of=tpe_date_to_utc(last) if last else None, rows=rows,
                  meta={"live_bar": live, "completed_bars": len(rows), "volume_unit": "shares"},
                  note=f"已完成日K {len(rows)} 根；第三方資料")
    if not rows:
        sec.availability = Availability.UNAVAILABLE
    elif any(v is None for r in rows for v in (r["open"], r["high"], r["low"], r["close"])):
        sec.availability = Availability.PARTIAL
    return sec


def yfinance_intraday(df, fetched_at: datetime, reference_time: Optional[datetime] = None) -> Section:
    """yfinance 1 分K → 盤中K線區塊。延遲不寫死：用 reference_time（例如富果 lastUpdated）動態算。

    meta：latest_bar_time、reference_time、observed_delay_seconds（沒有基準就是 None＝延遲無法判斷）。
    """
    rows = []
    if df is not None and len(df):
        for idx, r in df.iterrows():
            t = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx
            if t.tzinfo is None:
                raise ValueError("yfinance 1 分K 時間沒有時區")
            rows.append({"time": t.astimezone(UTC), "open": num(r.get("Open")), "high": num(r.get("High")),
                         "low": num(r.get("Low")), "close": num(r.get("Close")), "volume": num(r.get("Volume"))})
    latest = rows[-1]["time"] if rows else None
    ref = require_aware(reference_time, "reference_time") if reference_time is not None else None
    delay = (ref - latest).total_seconds() if (ref is not None and latest is not None) else None
    sec = Section("盤中1分K", "yfinance", SourceType.THIRD_PARTY, fetched_at, as_of=latest, rows=rows,
                  meta={"latest_bar_time": latest, "reference_time": ref, "observed_delay_seconds": delay},
                  note="第三方資料；延遲程度無法判斷" if delay is None else "第三方資料")
    if not rows:
        sec.availability = Availability.UNAVAILABLE
    return sec


def describe_delay(seconds: Optional[float]) -> str:
    """給 UI 的白話：只描述這次實測，不是固定規則。"""
    if seconds is None:
        return "延遲程度無法判斷"
    return f"實測延遲約 {round(seconds / 60)} 分鐘"


YF_FUND_FIELDS = {
    # key: (yfinance 欄位, 單位說明)
    "eps": ("trailingEps", "元"),
    "pe": ("trailingPE", "倍"),
    "pb": ("priceToBook", "倍"),
    "roe": ("returnOnEquity", "小數比例（0.05 = 5%）"),
    "revenue_growth": ("revenueGrowth", "小數比例"),
    "payout_ratio": ("payoutRatio", "小數比例"),
    "dividend_yield_ttm": ("trailingAnnualDividendYield", "小數比例，近 12 個月"),
    "dividend_rate_ttm": ("trailingAnnualDividendRate", "元，近 12 個月"),
    "debt_to_equity": ("debtToEquity", "yfinance 原值（百分比數字，例如 45 = 45%）"),
}


def yfinance_fundamentals(info: dict, fetched_at: datetime) -> Section:
    """yfinance info → 基本面（只取語意明確的欄位，缺值 None）。"""
    info = info or {}
    sec = Section(FUNDAMENTALS, "yfinance", SourceType.THIRD_PARTY, fetched_at,
                  meta={k: v[1] for k, v in YF_FUND_FIELDS.items()})
    for key, (src, unit) in YF_FUND_FIELDS.items():
        sec.dp(key, num(info.get(src)), note=unit)
    missing = [k for k, p in sec.items.items() if p.value is None]
    if len(missing) == len(sec.items):
        sec.availability = Availability.UNAVAILABLE
    elif missing:
        sec.availability = Availability.PARTIAL
        sec.note = "缺：" + "、".join(missing)
    return sec


# ════════════════════════════════════════════════
# 組裝
# ════════════════════════════════════════════════
def build_bundle(symbol: str, fetched_at: datetime, *, asset_info: Optional[AssetInfo] = None,
                 market_session: MarketSession = MarketSession.UNKNOWN, fugle_quote_raw=None,
                 fugle_trades_raw=None, finmind_inst_raw=None, finmind_margin_raw=None,
                 finmind_revenue_raw=None, t86_raw=None, yf_daily_df=None, yf_info=None,
                 today: Optional[date] = None, failed: Optional[Dict[str, tuple]] = None) -> DataBundle:
    """把各來源原始資料組成一個 DataBundle。傳 None 代表這次沒抓；
    failed = {區塊名稱: (來源, 錯誤訊息)} 記錄抓取階段就失敗的來源。"""
    fetched_at = require_aware(fetched_at)
    b = DataBundle(symbol=symbol, asset_info=asset_info, market_session=market_session)
    for name, (src, msg) in (failed or {}).items():
        b.errors.append(SourceError(name, src, msg))
    if fugle_quote_raw is not None:
        b.add(QUOTE, "Fugle", lambda: fugle_quote(fugle_quote_raw, fetched_at))
        b.add(ORDER_BOOK, "Fugle", lambda: fugle_order_book(fugle_quote_raw, fetched_at))
    if fugle_trades_raw is not None:
        b.add(TRADES, "Fugle", lambda: fugle_trades(fugle_trades_raw, fetched_at))
    if finmind_inst_raw is not None:
        b.add(INSTITUTIONAL, "FinMind", lambda: finmind_institutional(finmind_inst_raw, fetched_at))
    if finmind_margin_raw is not None:
        b.add(MARGIN, "FinMind", lambda: finmind_margin(finmind_margin_raw, fetched_at))
    if finmind_revenue_raw is not None:
        b.add(REVENUE, "FinMind", lambda: finmind_revenue(finmind_revenue_raw, fetched_at))
    if t86_raw is not None:
        b.add(INSTITUTIONAL_OFFICIAL, "TWSE", lambda: twse_t86(t86_raw, symbol, fetched_at))
    if yf_daily_df is not None:
        b.add(DAILY, "yfinance", lambda: yfinance_daily(yf_daily_df, fetched_at, market_session, today))
    if yf_info is not None:
        b.add(FUNDAMENTALS, "yfinance", lambda: yfinance_fundamentals(yf_info, fetched_at))
    return b
