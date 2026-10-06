# -*- coding: utf-8 -*-
"""判斷引擎骨架（第二段 Gate 2.4 先行，GPT 平行工作 P-D：只做 skeleton）。

這裡只有「彙總規則」，沒有任何家族的多空判斷：
- 各家族怎麼投票（KD 金叉、法人買超、量比…）等 Gate 2.1／2.2 完成後才寫 family evaluator。
- 本檔接收已經投好的 FamilyVote，負責：
  1. 票數彙總 → 方向分級（v1 表格）
  2. 風險旗標 → 風險等級（v0：0 低／1 中／≥2 高）
  3. 可操作狀態的優先順序
  4. 必要資料、暖機根數、市場時段、0 與 None 的語意
  5. explain() 與 rule_version

三層彼此獨立：風險不扣方向分數，可操作不改方向。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Dict, List, Optional, Sequence

from pricing import ETF, ETF_EQUITY, UNKNOWN
from schema import (
    ACTIONABILITY_FLAGS,
    WARMUP_BARS,
    DAYTRADE_MAX_AGE_SECONDS,
    Actionability,
    Direction,
    FamilyVote,
    Horizon,
    HorizonResult,
    MarketSession,
    RiskLevel,
    risk_level_from_flags,
)

RULE_VERSION = "engine-skeleton-v0"

# ── v1 規格：各週期的方向家族（名稱固定，順序即顯示順序）──
FAMILIES: Dict[Horizon, List[str]] = {
    Horizon.DAYTRADE: ["盤中成交力道", "盤中趨勢", "量能"],
    Horizon.SHORT: ["趨勢", "動能", "量價", "法人籌碼"],
    Horizon.SWING: ["趨勢", "動能", "法人籌碼", "月營收趨勢"],
    Horizon.LONG: ["趨勢", "獲利", "成長", "估值", "財務"],
}
FAMILIES_LONG_ETF = ["指數趨勢", "折溢價", "規模", "流動性"]

# 必要家族：這些家族沒有資料（None）就直接「資料不足」，不看其他票
REQUIRED_FAMILIES: Dict[Horizon, List[str]] = {
    Horizon.DAYTRADE: ["盤中成交力道"],
    Horizon.SHORT: ["趨勢"],
    Horizon.SWING: ["趨勢"],
    Horizon.LONG: ["獲利", "成長"],   # v1：長線必要 EPS＋月營收
}
REQUIRED_FAMILIES_LONG_ETF = ["指數趨勢"]  # GPT：折溢價不是長線方向的必要條件

# 最少有效票數（取代「少於一半」的文字規則，避免 4 族只有 2 票也判偏多）
MIN_VALID_VOTES = {3: 2, 4: 3, 5: 3}

# ── 風險標記門檻（v1 規格；沿用第一段既有門檻，第三段回測驗證）──
RISK_RSI_OVERHEAT = 80.0          # RSI14 > 80
RISK_BIAS_MA20_PCT = 15.0         # 與 MA20 乖離 > 15%
RISK_MARGIN_3D_PCT = 10.0         # 融資 3 日增加 > 10%

# ── 可操作門檻（v1 規格）──
NO_CHASE_DAY_CHANGE_PCT = 7.0     # 方向偏多但當日已漲 ≥ 7% → 不宜追價
DAYTRADE_NO_NEW_ENTRY_AFTER = time(13, 0)

BULLISH = {Direction.BULL, Direction.LEAN_BULL}
BEARISH = {Direction.BEAR, Direction.LEAN_BEAR}


# ════════════════════════════════════════════════
# 1. 方向
# ════════════════════════════════════════════════
def grade_direction(net: int, valid: int) -> Direction:
    """v1 分級表，依「實際有效票數」：≤3 用三票表，4～5 用五票表。
    有效票數不足 MIN_VALID_VOTES 時不會進到這裡（直接資料不足）。"""
    if valid <= 3:
        if net >= 2:
            return Direction.BULL
        if net == 1:
            return Direction.LEAN_BULL
        if net == 0:
            return Direction.NEUTRAL
        if net == -1:
            return Direction.LEAN_BEAR
        return Direction.BEAR
    if net >= 3:
        return Direction.BULL
    if net >= 1:
        return Direction.LEAN_BULL
    if net == 0:
        return Direction.NEUTRAL
    if net >= -2:
        return Direction.LEAN_BEAR
    return Direction.BEAR


def normalize_votes(families: Sequence[str], votes: Sequence[FamilyVote]) -> List[FamilyVote]:
    """依規格家族排序；沒給的家族補 None（沒資料）；不認得的家族直接報錯。"""
    by_name = {}
    for v in votes:
        if v.family not in families:
            raise ValueError(f"未定義的家族：{v.family}（應為 {list(families)}）")
        if v.family in by_name:
            raise ValueError(f"家族重複投票：{v.family}")
        if v.vote not in (1, 0, -1, None):
            raise ValueError(f"票只能是 +1／0／−1／None：{v.family}={v.vote!r}")
        by_name[v.family] = v
    return [by_name.get(f) or FamilyVote(f, None, "沒有資料") for f in families]


def evaluate_direction(families: Sequence[str], votes: Sequence[FamilyVote],
                       required: Sequence[str] = ()) -> tuple[Direction, List[str]]:
    """回傳 (方向, 資料狀況說明)。0 是中性票、None 是沒資料，兩者不同。"""
    notes = []
    missing_required = [v.family for v in votes if v.family in required and v.vote is None]
    if missing_required:
        notes.append("缺必要資料：" + "、".join(missing_required))
        return Direction.INSUFFICIENT, notes
    valid = [v for v in votes if v.vote is not None]
    need = MIN_VALID_VOTES[len(families)]
    if len(valid) < need:
        notes.append(f"{len(families)} 個家族中只有 {len(valid)} 個有資料，至少要 {need} 個")
        return Direction.INSUFFICIENT, notes
    for v in votes:
        if v.vote is None:
            notes.append(f"{v.family}：沒有資料，不計入")
    net = sum(v.vote for v in valid)
    return grade_direction(net, len(valid)), notes


# ════════════════════════════════════════════════
# 2. 風險
# ════════════════════════════════════════════════
def risk_flags_from_values(rsi14: Optional[float] = None, bias_ma20_pct: Optional[float] = None,
                           margin_3d_pct: Optional[float] = None) -> List[str]:
    """v1 風險標記（只看門檻，不影響方向）。值為 None 代表沒資料，不產生旗標。"""
    flags = []
    if rsi14 is not None and rsi14 > RISK_RSI_OVERHEAT:
        flags.append(f"RSI {rsi14:.0f} 過熱")
    if bias_ma20_pct is not None and abs(bias_ma20_pct) > RISK_BIAS_MA20_PCT:
        side = "正" if bias_ma20_pct > 0 else "負"
        flags.append(f"MA20 {side}乖離 {bias_ma20_pct:+.1f}%")
    if margin_3d_pct is not None and margin_3d_pct > RISK_MARGIN_3D_PCT:
        flags.append(f"融資 3 日 {margin_3d_pct:+.1f}%")
    return flags


def evaluate_risk(flags: Sequence[str]) -> tuple[RiskLevel, List[str]]:
    """鎖停／暫停交易不計入風險等級（交給可操作）。"""
    risk_only = [f for f in flags if f not in ACTIONABILITY_FLAGS]
    return risk_level_from_flags(list(flags)), risk_only


# ════════════════════════════════════════════════
# 3. 可操作
# ════════════════════════════════════════════════
@dataclass
class TradeContext:
    market_session: MarketSession = MarketSession.UNKNOWN
    now_time: Optional[time] = None              # 台北時間
    locked_limit_up: bool = False
    locked_limit_down: bool = False
    data_age_seconds: Optional[float] = None     # 即時資料距今幾秒（當沖用）
    daytrade_eligible: Optional[bool] = None     # 是否為現股當沖標的（None = 不知道）
    day_change_pct: Optional[float] = None       # 今日漲跌幅 %
    completed_daily_bars: Optional[int] = None   # 已完成日K根數（不含今天）


def evaluate_actionability(horizon: Horizon, direction: Direction,
                           ctx: TradeContext) -> tuple[Actionability, str]:
    """優先順序（由上往下，先符合者為準）：
    1 暫停交易 → 無法正常交易
    2 鎖漲停／鎖跌停 → 無法正常交易
    3 當沖：非盤中 → 市場已收盤
    4 當沖：確定不是當沖標的 → 不可當沖
    5 方向資料不足／不適用 → 資料不足
    6 當沖：即時資料超過 60 秒或不知道新鮮度 → 資料不足
    7 當沖：13:00 以後 → 不宜新進場（剩餘時間太短）
    8 方向偏多且今日已漲 ≥ 7% → 不宜追價
    9 其他 → 可操作
    """
    if ctx.market_session == MarketSession.HALTED:
        return Actionability.NOT_TRADABLE, "暫停交易"
    if ctx.locked_limit_up:
        return Actionability.NOT_TRADABLE, "漲停鎖單，無法正常進場，等漲停打開或隔日重新評估"
    if ctx.locked_limit_down:
        return Actionability.NOT_TRADABLE, "跌停鎖單，無法正常出場，等跌停打開或隔日重新評估"
    if horizon == Horizon.DAYTRADE:
        if ctx.market_session != MarketSession.OPEN:
            return Actionability.MARKET_CLOSED, "目前不是盤中時間，當沖不適用"
        if ctx.daytrade_eligible is False:
            return Actionability.NO_DAYTRADE, "不是現股當沖標的"
    if direction in (Direction.INSUFFICIENT, Direction.NOT_APPLICABLE):
        return Actionability.INSUFFICIENT, "方向無法判斷"
    if horizon == Horizon.DAYTRADE:
        if ctx.data_age_seconds is None or ctx.data_age_seconds > DAYTRADE_MAX_AGE_SECONDS:
            return Actionability.INSUFFICIENT, f"即時資料超過 {DAYTRADE_MAX_AGE_SECONDS} 秒沒更新"
        if ctx.now_time is not None and ctx.now_time >= DAYTRADE_NO_NEW_ENTRY_AFTER:
            return Actionability.NO_NEW_ENTRY, "13:00 以後剩餘交易時間太短，不宜新進場"
    if direction in BULLISH and ctx.day_change_pct is not None and ctx.day_change_pct >= NO_CHASE_DAY_CHANGE_PCT:
        return Actionability.NO_CHASE, f"今日已漲 {ctx.day_change_pct:.1f}%，方向偏多但已漲多"
    return Actionability.OK, ""


# ════════════════════════════════════════════════
# 4. 單一週期總結
# ════════════════════════════════════════════════
def families_for(horizon: Horizon, asset_type: str = "STOCK", asset_subtype: Optional[str] = None) -> Optional[List[str]]:
    """回傳該週期的家族清單；None 代表此商品在此週期不支援。"""
    if asset_type == UNKNOWN:
        return None
    if asset_type == ETF:
        if horizon == Horizon.LONG:
            # v1：ETF 長線只支援「確認為股票型」的 ETF；債券／槓桿／反向／OTHER（代號推測無法確認）→ 尚未支援
            return FAMILIES_LONG_ETF if asset_subtype == ETF_EQUITY else None
        return FAMILIES[horizon]
    return FAMILIES[horizon]


def required_for(horizon: Horizon, asset_type: str = "STOCK") -> List[str]:
    if asset_type == ETF and horizon == Horizon.LONG:
        return REQUIRED_FAMILIES_LONG_ETF
    return REQUIRED_FAMILIES[horizon]


def evaluate_horizon(horizon: Horizon, votes: Sequence[FamilyVote], risk_flags: Sequence[str] = (),
                     ctx: Optional[TradeContext] = None, asset_type: str = "STOCK",
                     asset_subtype: Optional[str] = None) -> HorizonResult:
    ctx = ctx or TradeContext()
    families = families_for(horizon, asset_type, asset_subtype)
    risk_level, risk_only = evaluate_risk(risk_flags)

    if families is None:
        # 不知道 ≠ 不適用：UNKNOWN 是「商品類型未確認」→ 資料不足；
        # 已知但 v0 沒有模型的 ETF 子類型 → 不適用
        if asset_type == UNKNOWN:
            direction, reason = Direction.INSUFFICIENT, "商品類型未確認"
        else:
            direction, reason = Direction.NOT_APPLICABLE, f"v0 尚未支援此 ETF 子類型（{asset_subtype or '未確認'}）"
        return HorizonResult(horizon, direction, [], risk_level, risk_only,
                             Actionability.INSUFFICIENT, reason, data_status=[reason], rule_version=RULE_VERSION)

    norm = normalize_votes(families, votes)
    data_status: List[str] = []

    # 暖機根數（只看已完成日K；當沖不適用）
    need = WARMUP_BARS.get(horizon)
    if need is not None and (ctx.completed_daily_bars is None or ctx.completed_daily_bars < need):
        have = "未知" if ctx.completed_daily_bars is None else ctx.completed_daily_bars
        data_status.append(f"已完成日K {have} 根，少於 {need} 根暖機需求")
        direction = Direction.INSUFFICIENT
    else:
        direction, notes = evaluate_direction(families, norm, required_for(horizon, asset_type))
        data_status.extend(notes)

    action, action_reason = evaluate_actionability(horizon, direction, ctx)
    supports = [f"{v.family}：{v.reason}" if v.reason else v.family for v in norm if v.vote == 1]
    against = [f"{v.family}：{v.reason}" if v.reason else v.family for v in norm if v.vote == -1]
    return HorizonResult(horizon, direction, norm, risk_level, risk_only, action, action_reason,
                         supports=supports, against=against, data_status=data_status,
                         rule_version=RULE_VERSION)
