"""
TSAR News Sources — Extended news ingestion layer.

Provides specialized crypto news sources beyond the base NewsAggregator:
  - Whale Alert: Large on-chain transaction detection
  - Regulatory Feeds: SEC/CFTC/DOJ enforcement monitoring
  - Exploit Alerts: PeckShield/CertiK on-chain security alerts
  - Twitter Monitor: Crypto Twitter via Nitter/API
  - Social Monitor: Reddit/Discord crypto channels

Plus cross-cutting concerns:
  - LLM Verification: CRITICAL news verification via router
  - Accuracy Tracker: Per-source prediction accuracy in SQLite
"""

from __future__ import annotations

from src.tools.news_sources.whale_alert import WhaleAlertClient
from src.tools.news_sources.regulatory_feeds import RegulatoryFeedMonitor
from src.tools.news_sources.exploit_alerts import ExploitAlertMonitor
from src.tools.news_sources.twitter_monitor import TwitterCryptoMonitor
from src.tools.news_sources.social_monitor import SocialChannelMonitor
from src.tools.news_sources.llm_verification import LLMNewsVerifier
from src.tools.news_sources.accuracy_tracker import SourceAccuracyTracker

__all__ = [
    "WhaleAlertClient",
    "RegulatoryFeedMonitor",
    "ExploitAlertMonitor",
    "TwitterCryptoMonitor",
    "SocialChannelMonitor",
    "LLMNewsVerifier",
    "SourceAccuracyTracker",
]
