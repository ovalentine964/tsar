"""
Pre-Trade Explainer
====================

Builds plain-language explanations for trade signals before entry.
Adapts detail level based on Valentine's learning progress.
"""

from __future__ import annotations

from typing import Any

from src.education.message_formatter import TelegramFormatter as Fmt


class PreTradeExplainer:
    """Build pre-trade signal explanations.

    Generates Telegram-formatted messages that explain:
      - WHY the signal was generated (indicators, patterns)
      - THE SETUP (entry, SL, TP, R:R)
      - POSITION sizing and risk
      - Regime, on-chain, genome context (progressive)
    """

    # ── Reason Templates (Month 1-3: Simple) ─────────────────────────
    SIMPLE_REASONS: dict[str, str] = {
        "rsi_oversold": "RSI at {value} (oversold — price dropped too fast, likely to bounce)",
        "rsi_overbought": "RSI at {value} (overbought — price rose too fast, likely to pull back)",
        "support_bounce": "Price bounced off {level} support ({nth} time this period)",
        "resistance_reject": "Price rejected at {level} resistance ({nth} time this period)",
        "volume_spike": "Volume spike (+{pct}% — big {side}ers stepping in)",
        "macd_crossover": "MACD just crossed {direction} (momentum shifting)",
        "ema_cross": "EMA({fast}) crossed above EMA({slow}) (trend turning {direction})",
        "bollinger_squeeze": "Bollinger Bands squeezing — big move coming",
        "bollinger_touch_lower": "Price touched lower Bollinger Band (oversold)",
        "bollinger_touch_upper": "Price touched upper Bollinger Band (overbought)",
    }

    # ── Reason Templates (Month 3-6: Intermediate) ───────────────────
    INTERMEDIATE_REASONS: dict[str, str] = {
        "regime_trending": "Market regime: TRENDING (ADX at {adx} — strong directional move)",
        "regime_ranging": "Market regime: RANGING (ADX at {adx} — sideways, use mean reversion)",
        "regime_volatile": "Market regime: VOLATILE (ADX at {adx} — unpredictable, reduce size)",
        "whale_accumulation": "On-chain: Whale accumulation detected (+{amount} BTC moved to cold storage)",
        "whale_distribution": "On-chain: Whale distribution detected (-{amount} BTC moved to exchanges)",
        "correlation_btc_low": "BTC correlation: LOW ({corr}) — independent move, higher alpha",
        "correlation_btc_high": "BTC correlation: HIGH ({corr}) — following BTC, watch BTC levels",
        "funding_rate_extreme": "Funding rate: {rate}% ({direction} — crowd is {direction}, contrarian signal)",
    }

    # ── Reason Templates (Month 6+: Advanced) ────────────────────────
    ADVANCED_REASONS: dict[str, str] = {
        "genome_mutation": "Strategy mutated: {mutation} (expected +{improvement}% improvement)",
        "pattern_library_match": "Pattern match: '{pattern}' ({confidence}% confidence, {win_rate}% historical WR)",
        "cross_timeframe": "Multi-TF alignment: {timeframes} all showing {direction}",
        "liquidity_zone": "Liquidity zone detected at {level} (stop hunt likely)",
    }

    def __init__(self, learning_level: int = 1) -> None:
        self._level = learning_level

    # ── Public API ────────────────────────────────────────────────────

    def build_message(
        self,
        signal: dict[str, Any],
        risk: dict[str, Any],
        balance: float,
        regime: dict[str, Any] | None = None,
        onchain: dict[str, Any] | None = None,
        genome: dict[str, Any] | None = None,
    ) -> str:
        """Build the full pre-trade signal message.

        Args:
            signal: Signal data from SignalScout.
            risk: Risk decision from RiskGuardian.
            balance: Current account balance.
            regime: Regime analysis (level 2+).
            onchain: On-chain signals (level 2+).
            genome: Strategy genome data (level 3+).

        Returns:
            Telegram HTML formatted message.
        """
        lines: list[str] = []

        # Header
        symbol = signal.get("symbol", "???")
        direction = signal.get("side", "LONG").upper()
        direction_emoji = "🟢" if direction == "LONG" else "🔴"
        lines.append(f"{Fmt.CHART} {Fmt.bold(f'TRADE SIGNAL: {symbol} {direction_emoji} {direction}')}")
        lines.append(Fmt.separator())

        # Reasons
        lines.append(Fmt.section_header(Fmt.LIGHTBULB, "WHY I'M ENTERING"))
        reasons = self._build_reasons(signal)
        for reason in reasons:
            lines.append(Fmt.bullet(reason))

        # Regime (level 2+)
        if self._level >= 2 and regime:
            lines.append(self._build_regime_section(regime))

        # On-chain (level 2+)
        if self._level >= 2 and onchain:
            lines.append(self._build_onchain_section(onchain))

        # Setup
        lines.append(self._build_setup_section(signal, risk))

        # Position
        lines.append(self._build_position_section(signal, risk, balance))

        # Genome (level 3+)
        if self._level >= 3 and genome:
            lines.append(self._build_genome_section(genome))

        # Confidence (level 3+)
        if self._level >= 3:
            confidence = signal.get("confidence", 0)
            lines.append(Fmt.section_header(Fmt.BRAIN, "CONFIDENCE"))
            lines.append(Fmt.bullet(f"{confidence}/100"))

        lines.append(Fmt.separator())

        # Buttons hint
        if self._level >= 3:
            lines.append("[✅ Execute] [❌ Skip] [📖 Explain More] [🔧 Modify] [🤖 Full Auto]")
        else:
            lines.append("[✅ Execute] [❌ Skip] [📖 Explain More]")

        return "\n".join(lines)

    # ── Internal Builders ─────────────────────────────────────────────

    def _build_reasons(self, signal: dict[str, Any]) -> list[str]:
        """Build plain-language reasons from signal analysis."""
        reasons: list[str] = []
        metadata = signal.get("metadata", {})
        indicators = signal.get("indicators", {})

        # RSI
        rsi = indicators.get("rsi") or metadata.get("rsi")
        if rsi is not None:
            if rsi < 30:
                reasons.append(self.SIMPLE_REASONS["rsi_oversold"].format(value=f"{rsi:.0f}"))
            elif rsi > 70:
                reasons.append(self.SIMPLE_REASONS["rsi_overbought"].format(value=f"{rsi:.0f}"))

        # Support/Resistance
        if metadata.get("support_bounce"):
            level = Fmt.format_price(metadata.get("support_level", 0))
            nth = metadata.get("bounce_count", "3rd")
            reasons.append(self.SIMPLE_REASONS["support_bounce"].format(level=level, nth=nth))
        elif metadata.get("resistance_reject"):
            level = Fmt.format_price(metadata.get("resistance_level", 0))
            nth = metadata.get("reject_count", "3rd")
            reasons.append(self.SIMPLE_REASONS["resistance_reject"].format(level=level, nth=nth))

        # Volume
        vol_change = metadata.get("volume_change_pct")
        if vol_change is not None and vol_change > 50:
            side = "buy" if signal.get("side", "").upper() == "BUY" else "sell"
            reasons.append(self.SIMPLE_REASONS["volume_spike"].format(pct=f"{vol_change:.0f}", side=side))

        # MACD
        macd_hist = indicators.get("macd_histogram")
        if macd_hist is not None:
            direction = "bullish" if macd_hist > 0 else "bearish"
            reasons.append(self.SIMPLE_REASONS["macd_crossover"].format(direction=direction))

        # Bollinger
        if metadata.get("bollinger_squeeze"):
            reasons.append(self.SIMPLE_REASONS["bollinger_squeeze"])

        # Fallback: use signal reasoning text
        if not reasons:
            reasoning = signal.get("reasoning", "")
            if reasoning:
                for part in reasoning.split("|"):
                    part = part.strip()
                    if part:
                        reasons.append(part)
            else:
                reasons.append("Multiple indicators aligned for this setup")

        return reasons

    def _build_regime_section(self, regime: dict[str, Any]) -> str:
        """Build regime analysis section (level 2+)."""
        lines = [Fmt.section_header("🔍", "REGIME ANALYSIS")]
        regime_type = regime.get("regime", "unknown").upper()
        adx = regime.get("adx", 0)
        lines.append(Fmt.bullet(f"Current regime: {regime_type} (ADX: {adx:.0f})"))

        trend = regime.get("trend_strength", "moderate")
        lines.append(Fmt.bullet(f"Trend strength: {trend}"))

        vol_state = regime.get("volatility_state", "normal")
        lines.append(Fmt.bullet(f"Volatility: {vol_state}"))
        return "\n".join(lines)

    def _build_onchain_section(self, onchain: dict[str, Any]) -> str:
        """Build on-chain signals section (level 2+)."""
        lines = [Fmt.section_header(Fmt.LINK, "ON-CHAIN SIGNALS")]

        if onchain.get("whale_accumulation"):
            amount = onchain.get("whale_amount", 0)
            lines.append(Fmt.bullet(f"Whale accumulation: +{amount} BTC moved to cold storage"))
        elif onchain.get("whale_distribution"):
            amount = onchain.get("whale_amount", 0)
            lines.append(Fmt.bullet(f"Whale distribution: -{amount} BTC moved to exchanges"))

        funding = onchain.get("funding_rate")
        if funding is not None:
            direction = "longs pay shorts" if funding > 0 else "shorts pay longs"
            lines.append(Fmt.bullet(f"Funding rate: {funding:.4f}% ({direction})"))

        if not any([onchain.get("whale_accumulation"), onchain.get("whale_distribution"), funding]):
            lines.append(Fmt.bullet("No significant on-chain signals"))

        return "\n".join(lines)

    def _build_setup_section(self, signal: dict[str, Any], risk: dict[str, Any]) -> str:
        """Build the trade setup section."""
        lines = [Fmt.section_header(Fmt.RULER, "THE SETUP")]

        entry = signal.get("entry_price", risk.get("entry_price", 0))
        sl = risk.get("stop_loss", signal.get("stop_loss", 0))
        tp = risk.get("take_profit", signal.get("take_profit", 0))

        lines.append(Fmt.bullet(f"Entry: {Fmt.format_price(entry)}"))
        lines.append(Fmt.bullet(f"Stop Loss: {Fmt.format_price(sl)}"))
        lines.append(Fmt.bullet(f"Take Profit: {Fmt.format_price(tp)}"))

        # Risk/Reward
        risk_amount = abs(entry - sl) if entry and sl else 0
        reward_amount = abs(tp - entry) if tp and entry else 0
        rr = reward_amount / risk_amount if risk_amount > 0 else 0
        rr_emoji = Fmt.rr_emoji(rr)
        lines.append(Fmt.bullet(f"Risk/Reward: {rr:.1f}:1 {rr_emoji}"))

        return "\n".join(lines)

    def _build_position_section(
        self, signal: dict[str, Any], risk: dict[str, Any], balance: float
    ) -> str:
        """Build the position sizing section."""
        lines = [Fmt.section_header(Fmt.MONEY, "POSITION")]

        position_size = risk.get("position_size", 0)
        risk_amount = risk.get("risk_amount", 0)
        position_pct = (position_size / balance * 100) if balance > 0 else 0
        risk_pct = (risk_amount / balance * 100) if balance > 0 else 0

        lines.append(Fmt.bullet(f"Size: ${position_size:.2f} ({position_pct:.1f}% of ${balance:.2f})"))
        lines.append(Fmt.bullet(f"Risk: ${risk_amount:.2f} ({risk_pct:.1f}% of balance)"))
        lines.append(Fmt.bullet(f"Max loss if stopped: -${risk_amount:.2f}"))

        return "\n".join(lines)

    def _build_genome_section(self, genome: dict[str, Any]) -> str:
        """Build strategy genome section (level 3+)."""
        lines = [Fmt.section_header(Fmt.DNA, "STRATEGY")]

        name = genome.get("strategy_name", "unknown")
        generation = genome.get("generation", 0)
        win_rate = genome.get("win_rate", 0)
        total_trades = genome.get("total_trades", 0)
        avg_rr = genome.get("avg_rr", 0)

        lines.append(Fmt.bullet(f"Strategy: {name} (Gen {generation})"))
        lines.append(Fmt.bullet(f"Historical: {win_rate:.0f}% WR over {total_trades} trades"))
        lines.append(Fmt.bullet(f"Avg R:R achieved: {avg_rr:.1f}:1"))

        mutation = genome.get("last_mutation")
        if mutation:
            lines.append(Fmt.bullet(f"Last mutation: {mutation}"))

        return "\n".join(lines)
