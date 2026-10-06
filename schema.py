"""
台股戰情室：第二階段資料物件與判斷引擎介面（v1 規格，只有結構與少量明確規則，沒有多空判斷邏輯）

- 判斷結果固定三層：方向（Direction）／風險（Risk）／可操作（Actionability），彼此不互相加減分。
- 每個數字用 DataPoint 包裝，帶來源、時間、是否估算。
- 時間規範：as_of、fetched_at 一律使用 timezone-aware datetime；內部存 UTC，畫面再轉 Asia/Taipei。
  naive datetime（沒有時區）一律拒絕，避免 age_seconds 算錯。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from typing import Any, Optional


class SourceType(str, Enum):
    OFFICIAL = "OFFICIAL"        # 證交所、櫃買、公開資訊觀測站
    VENDOR = "VENDOR"            # 行情授權供應商（富果）
    THIRD_PARTY = "THIRD_PARTY"  # 第三方資料服務（FinMind、yfinance）
    INTERNAL = "INTERNAL"        # 本站自行計算


class DataKind(str, Enum):
    RAW = "RAW"     # 原始資料
    CALC = "CALC"   # Python 計算
    EST = "EST"     # 推估
    AI = "AI"       # AI 解讀


class MarketSession(str, Enum):
    PRE_OPEN = "PRE_OPEN"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    HALTED = "HALTED"
    UNKNOWN = "UNKNOWN"


class Direction(str, Enum):
    BULL = "偏多"
    LEAN_BULL = "中性偏多"
    NEUTRAL = "中性"
    LEAN_BEAR = "中性偏空"
    BEAR = "偏空"
    INSUFFICIENT = "資料不足"
    NOT_APPLICABLE = "不適用"


class RiskLevel(str, Enum):
    LOW = "低"
    MEDIUM = "中"
    HIGH = "高"


class Actionability(str, Enum):
    OK = "可操作"
    WAIT_PULLBACK = "等待回測"
    NO_CHASE = "不宜追價"
    NO_NEW_ENTRY = "不宜新進場"   # 當沖 13:00 後：剩餘交易時間太短（不是價格太高）
    NOT_TRADABLE = "無法正常交易"
    NO_DAYTRADE = "不可當沖"
    MARKET_CLOSED = "市場已收盤"
    INSUFFICIENT = "資料不足"


class Horizon(str, Enum):
    DAYTRADE = "當沖"
    SHORT = "短線"
    SWING = "波段"
    LONG = "長線"


@dataclass
class DataPoint:
    value: Any
    source_name: str
    source_type: SourceType
    data_kind: DataKind
    as_of: Optional[datetime] = None       # 資料本身的時間（例如成交時間、盤後日期）
    fetched_at: Optional[datetime] = None  # 本站抓取時間
    is_estimated: bool = False
    note: str = ""

    def __post_init__(self):
        for name in ("as_of", "fetched_at"):
            v = getattr(self, name)
            if v is not None and (v.tzinfo is None or v.utcoffset() is None):
                raise ValueError(f"DataPoint.{name} 必須是 timezone-aware datetime")

    @property
    def missing(self) -> bool:
        return self.value is None

    def age_seconds(self, now: datetime) -> Optional[float]:
        if self.as_of is None:
            return None
        if now.tzinfo is None:
            raise ValueError("now 必須是 timezone-aware datetime")
        return (now - self.as_of).total_seconds()


# ---- 明確規則（規格寫死，不可變成黑盒）----

# 已完成日K的最少根數：只是指標暖機所需的資料量，
# 不代表策略新增 MA60／MA120／MA300 這類條件。
WARMUP_BARS = {Horizon.SHORT: 60, Horizon.SWING: 120, Horizon.LONG: 300}

# 當沖即時資料新鮮度上限（只在盤中適用；收盤後走 MARKET_CLOSED，不算資料過期）
DAYTRADE_MAX_AGE_SECONDS = 60

OPEN_TIME = time(9, 0)
OPENING_RANGE_READY = time(9, 30)
CLOSE_TIME = time(13, 30)


def opening_range_available(now_time: time) -> bool:
    """09:30 前開盤 30 分鐘區間尚未形成 → 該家族投票必須是 None（null）。"""
    return now_time >= OPENING_RANGE_READY


# 不計入風險等級、直接交給「可操作」處理的旗標
ACTIONABILITY_FLAGS = {"漲停鎖單", "跌停鎖單", "暫停交易"}


def risk_level_from_flags(flags: list[str]) -> RiskLevel:
    """v0：0 個風險旗標 → 低；1 個 → 中；2 個以上 → 高（鎖停等旗標不計，交給可操作狀態）。"""
    n = len([f for f in flags if f not in ACTIONABILITY_FLAGS])
    if n == 0:
        return RiskLevel.LOW
    if n == 1:
        return RiskLevel.MEDIUM
    return RiskLevel.HIGH


@dataclass
class FamilyVote:
    family: str
    vote: Optional[int]          # +1 / 0 / -1 / None（None = 沒有資料，0 = 中性，兩者不同）
    reason: str = ""
    inputs: list[DataPoint] = field(default_factory=list)


@dataclass
class HorizonResult:
    horizon: Horizon
    direction: Direction
    votes: list[FamilyVote]
    risk_level: RiskLevel
    risk_flags: list[str]
    actionability: Actionability
    action_reason: str = ""
    supports: list[str] = field(default_factory=list)   # 支持理由
    against: list[str] = field(default_factory=list)    # 反方理由
    data_status: list[str] = field(default_factory=list)
    rule_version: str = "v0"

    def explain(self) -> str:
        """給新手看的票數說明（不得寫成勝率）。"""
        valid = [v for v in self.votes if v.vote is not None]
        pos = sum(1 for v in valid if v.vote > 0)
        neg = sum(1 for v in valid if v.vote < 0)
        return f"{len(valid)} 個有效家族中，{pos} 個支持偏多、{neg} 個支持偏空。"
