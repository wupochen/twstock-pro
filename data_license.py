# -*- coding: utf-8 -*-
"""資料授權閘門（distribution_status）：這筆資料能不能顯示給「網站擁有者以外的人」。

背景（2026-10-07）：富果使用規範寫明「將交易資訊…傳送予第三人，應負違約及侵權之相關民、刑事責任」，
且不得出售、出租、轉讓、再授權交易資訊。yfinance 資料源（Yahoo）亦以個人、非商業用途為原則。
在拿到書面授權前，所有行情來源一律不得對外顯示。

規則集中在這裡，UI 不得各自判斷：輸出前一律呼叫 can_display(來源, 觀看者範圍)。
"""
from __future__ import annotations

from enum import Enum
from typing import Dict


class DistributionStatus(str, Enum):
    INTERNAL_ONLY = "INTERNAL_ONLY"              # 只限網站擁有者本人（開發、診斷、驗證）
    EXTERNAL_ALLOWED = "EXTERNAL_ALLOWED"        # 已取得書面授權，可顯示給其他使用者
    LICENSE_UNCONFIRMED = "LICENSE_UNCONFIRMED"  # 授權未確認：視同只限本人
    BLOCKED = "BLOCKED"                          # 任何人都不顯示


class ViewerScope(str, Enum):
    OWNER = "OWNER"        # 網站擁有者本人
    EXTERNAL = "EXTERNAL"  # 其他登入使用者、匿名訪客


# 改成 EXTERNAL_ALLOWED 之前，必須有資料商的書面回覆並記錄在 LICENSE_NOTES
SOURCE_DISTRIBUTION: Dict[str, DistributionStatus] = {
    "Fugle": DistributionStatus.LICENSE_UNCONFIRMED,
    "yfinance": DistributionStatus.INTERNAL_ONLY,
    "FinMind": DistributionStatus.LICENSE_UNCONFIRMED,
    "TWSE": DistributionStatus.LICENSE_UNCONFIRMED,
    "TPEx": DistributionStatus.LICENSE_UNCONFIRMED,
}

LICENSE_NOTES: Dict[str, str] = {
    "Fugle": "使用規範禁止傳送予第三人；已請使用者詢問企業／多人展示授權（2026-10-07）",
    "yfinance": "非官方套件；Yahoo 資料以個人、非商業用途為原則；只作內部驗證",
    "FinMind": "授權條款未查",
    "TWSE": "官方資料不等於可再散布；需逐資料集確認",
    "TPEx": "官方資料不等於可再散布；需逐資料集確認",
}


def status_of(source_name: str) -> DistributionStatus:
    """沒登記的來源一律當作 BLOCKED（寧可擋錯，不可漏放）。"""
    return SOURCE_DISTRIBUTION.get(source_name, DistributionStatus.BLOCKED)


def can_display(source_name: str, viewer: ViewerScope) -> bool:
    st = status_of(source_name)
    if st == DistributionStatus.BLOCKED:
        return False
    if viewer == ViewerScope.OWNER:
        return True
    return st == DistributionStatus.EXTERNAL_ALLOWED


def blocked_message(source_name: str) -> str:
    return f"這項資料（{source_name}）目前尚未取得對外顯示授權，只有網站擁有者可以看到。"
