"""
TSAR Trade Education System
============================

Teaches Valentine WHY each trade is entered, won, or lost.

Five layers:
  L1: Pre-Trade  — "Here's what I see and why I want to enter"
  L2: Post-Trade — "Here's what happened and why"
  L3: Weekly     — "Here's what I'm learning"
  L4: On-Demand  — "Ask me anything about trades"
  L5: Progressive — "I'll teach you more over time"

Usage:
    from src.education import (
        PreTradeExplainer,
        PostTradeExplainer,
        WeeklyReportGenerator,
        OnDemandEducation,
        LearningTracker,
    )
"""

from src.education.learning_tracker import LearningTracker
from src.education.message_formatter import TelegramFormatter
from src.education.on_demand import OnDemandEducation
from src.education.post_trade import PostTradeExplainer
from src.education.pre_trade import PreTradeExplainer
from src.education.weekly_report import WeeklyReportGenerator

__all__ = [
    "PreTradeExplainer",
    "PostTradeExplainer",
    "WeeklyReportGenerator",
    "OnDemandEducation",
    "LearningTracker",
    "TelegramFormatter",
]
