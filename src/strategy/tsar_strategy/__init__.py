"""
VMPM — Valentine Money Printing Machine.

Multi-layer institutional trading strategy for TSAR.

Components:
  - SessionManager:     Tracks current session and liquidity behavior
  - FundamentalAnalyzer: Economic calendar integration and bias scoring
  - TrendDetector:      Multi-timeframe trend with HH/HL/LH/LL detection
  - LevelMapper:        S/R levels including Asian session, order blocks
  - EntryPipeline:      Full entry logic sequence
  - VMPMStrategy:       Main strategy class extending TSAR's BaseStrategy

Pipeline: News → Trend → S/R → Retest → RSI → Candlestick → Execute
"""

from src.strategy.vmpm.session_manager import SessionManager, SessionInfo
from src.strategy.vmpm.fundamental_analyzer import FundamentalAnalyzer, FundamentalBias
from src.strategy.vmpm.trend_detector import TrendDetector, TrendState
from src.strategy.vmpm.level_mapper import LevelMapper, SRLevel, MappedLevels
from src.strategy.vmpm.rsi_filter import RSIFilter, RSIResult, RSISignal, RSIState
from src.strategy.vmpm.candlestick_confirmer import CandlestickConfirmer, CandleResult
from src.strategy.vmpm.entry_pipeline import (
    EntryPipeline, PipelineResult, PipelineStage,
    StageResult, CandlePattern,
)
from src.strategy.vmpm.strategy import VMPMStrategy

__all__ = [
    "SessionManager",
    "SessionInfo",
    "FundamentalAnalyzer",
    "FundamentalBias",
    "TrendDetector",
    "TrendState",
    "LevelMapper",
    "SRLevel",
    "MappedLevels",
    "RSIFilter",
    "RSIResult",
    "RSISignal",
    "RSIState",
    "CandlestickConfirmer",
    "CandleResult",
    "EntryPipeline",
    "PipelineResult",
    "PipelineStage",
    "StageResult",
    "CandlePattern",
    "VMPMStrategy",
]
