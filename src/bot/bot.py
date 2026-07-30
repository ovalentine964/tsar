"""TSAR Telegram Bot — Interactive Trading Partner.

Transforms the Telegram bot from a notification system into a full
interactive trading partner with:

  BEFORE TRADE — Discussion with rationale, approve/reject/modify
  AFTER TRADE  — Detailed reports with lessons and flywheel updates
  INTERACTIVE  — /discuss, /why, /performance, /regime, /strategy,
                 /flywheel, /ask commands for market conversation

Architecture:
  - Inline keyboard buttons for approve/reject/modify on trade proposals
  - Callback query handling for button presses
  - Trade proposal state machine (PENDING → APPROVED/REJECTED/MODIFIED)
  - Rich HTML formatting with emoji and structured layout
  - Wired to all TSAR agents: SignalScout, RiskGuardian, TradePhilosopher,
    FlywheelOrchestrator, RegimeDetector, StrategyGeneticist
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════
# TRADE PROPOSAL STATE
# ═══════════════════════════════════════════════════════════════════════

TRADE_STATE_PENDING = "pending"
TRADE_STATE_APPROVED = "approved"
TRADE_STATE_REJECTED = "rejected"
TRADE_STATE_MODIFIED = "modified"
TRADE_STATE_EXPIRED = "expired"


class TradeProposal:
    """Represents a trade awaiting user approval.

    Tracks the full lifecycle from signal detection through
    user decision to execution or rejection.
    """

    def __init__(
        self,
        proposal_id: str,
        signal_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        score: float,
        strategy: str,
        reasoning: str,
        metadata: dict[str, Any],
        risk_decision: dict[str, Any] | None = None,
        ttl_seconds: int = 300,
    ) -> None:
        self.proposal_id = proposal_id
        self.signal_id = signal_id
        self.symbol = symbol
        self.side = side
        self.entry_price = entry_price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.score = score
        self.strategy = strategy
        self.reasoning = reasoning
        self.metadata = metadata
        self.risk_decision = risk_decision
        self.state = TRADE_STATE_PENDING
        self.created_at = time.time()
        self.ttl_seconds = ttl_seconds
        self.decided_at: float | None = None
        self.modification_request: str | None = None
        self.telegram_message_id: int | None = None

    @property
    def is_expired(self) -> bool:
        return (
            self.state == TRADE_STATE_PENDING
            and (time.time() - self.created_at) > self.ttl_seconds
        )

    @property
    def risk_reward(self) -> float:
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit - self.entry_price)
        return reward / risk if risk > 0 else 0.0

    @property
    def pnl_potential_pct(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        return abs(self.take_profit - self.entry_price) / self.entry_price * 100

    def approve(self) -> None:
        self.state = TRADE_STATE_APPROVED
        self.decided_at = time.time()

    def reject(self, reason: str = "") -> None:
        self.state = TRADE_STATE_REJECTED
        self.decided_at = time.time()
        if reason:
            self.modification_request = reason

    def modify(self, request: str) -> None:
        self.state = TRADE_STATE_MODIFIED
        self.decided_at = time.time()
        self.modification_request = request

    def expire(self) -> None:
        self.state = TRADE_STATE_EXPIRED
        self.decided_at = time.time()


# ═══════════════════════════════════════════════════════════════════════
# INTERACTIVE BOT
# ═══════════════════════════════════════════════════════════════════════


class TsarBot:
    """Interactive Telegram trading partner.

    Transforms TSAR from a notification bot into a conversational
    trading interface where the user can:
    - Discuss trades before execution
    - Approve/reject/modify trade proposals via inline buttons
    - Query system state, performance, and reasoning
    - Ask questions about markets and strategy
    """

    def __init__(self, token: str, chat_id: str, tsar_system: Any = None) -> None:
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.system = tsar_system
        self.offset = 0

        # SECURITY: Authorized chat ID whitelist
        self._allowed_chat_ids: set[str] = {str(chat_id)}
        extra_ids = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "")
        for cid in extra_ids.split(","):
            cid = cid.strip()
            if cid:
                self._allowed_chat_ids.add(cid)
        logger.info(
            "Telegram bot initialized with %d authorized chat ID(s)",
            len(self._allowed_chat_ids),
        )

        # Trade proposal state
        self._proposals: dict[str, TradeProposal] = {}  # proposal_id → TradeProposal
        self._proposal_expiry_task: asyncio.Task | None = None

        # Pending discussion context (for /discuss and /ask)
        self._discussion_context: dict[str, Any] = {}

    # ── Messaging ────────────────────────────────────────────

    async def send_message(
        self,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str = "HTML",
    ) -> dict[str, Any] | None:
        """Send a message, optionally with inline keyboard.

        Args:
            text: Message text (HTML formatted).
            reply_markup: Inline keyboard markup dict.
            parse_mode: Parse mode (HTML or Markdown).

        Returns:
            API response dict or None on failure.
        """
        payload: dict[str, Any] = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"{self.base_url}/sendMessage", json=payload
                )
                data = await resp.json()
                if not data.get("ok"):
                    logger.error("sendMessage failed: %s", data)
                return data
        except Exception:
            logger.exception("Failed to send message")
            return None

    async def edit_message(
        self,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        """Edit an existing message (e.g., after button press)."""
        payload: dict[str, Any] = {
            "chat_id": self.chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            async with aiohttp.ClientSession() as session:
                await session.post(f"{self.base_url}/editMessageText", json=payload)
        except Exception:
            logger.exception("Failed to edit message")

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        """Answer a callback query (dismiss the loading indicator)."""
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    f"{self.base_url}/answerCallbackQuery",
                    json={"callback_query_id": callback_id, "text": text},
                )
        except Exception:
            logger.exception("Failed to answer callback")

    # ── Trade Proposal Lifecycle ─────────────────────────────

    async def propose_trade(
        self,
        signal_data: dict[str, Any],
        risk_decision: dict[str, Any] | None = None,
    ) -> str:
        """Present a trade proposal to the user for discussion/approval.

        This is the BEFORE TRADE flow — shows the full rationale,
        risk assessment, and provides approve/reject/modify buttons.

        Args:
            signal_data: Signal data from SignalScout.
            risk_decision: Risk decision from RiskGuardian (if available).

        Returns:
            proposal_id for tracking.
        """
        import uuid

        proposal_id = f"prop-{uuid.uuid4().hex[:8]}"
        proposal = TradeProposal(
            proposal_id=proposal_id,
            signal_id=signal_data.get("signal_id", "unknown"),
            symbol=signal_data.get("symbol", "BTC/USDT"),
            side=signal_data.get("side", "BUY"),
            entry_price=signal_data.get("entry_price", 0),
            stop_loss=signal_data.get("stop_loss", 0),
            take_profit=signal_data.get("take_profit", 0),
            score=signal_data.get("score", 0),
            strategy=signal_data.get("strategy", "unknown"),
            reasoning=signal_data.get("reasoning", ""),
            metadata=signal_data.get("metadata", {}),
            risk_decision=risk_decision,
        )
        self._proposals[proposal_id] = proposal

        # Build the rich trade proposal message
        msg = self._format_trade_proposal(proposal)

        # Build inline keyboard
        keyboard = self._build_proposal_keyboard(proposal_id)

        # Send with inline buttons
        result = await self.send_message(msg, reply_markup=keyboard)
        if result and result.get("ok"):
            proposal.telegram_message_id = result["result"]["message_id"]

        logger.info(
            "Trade proposal %s sent: %s %s %s entry=%.2f",
            proposal_id, proposal.symbol, proposal.side,
            proposal.strategy, proposal.entry_price,
        )
        return proposal_id

    def _format_trade_proposal(self, proposal: TradeProposal) -> str:
        """Format a trade proposal as rich HTML.

        Shows: symbol, side, entry/target/stop, R:R, reasoning,
        risk assessment, and Kelly fraction.
        """
        side_emoji = "🟢" if proposal.side.upper() == "BUY" else "🔴"
        side_label = "LONG" if proposal.side.upper() == "BUY" else "SHORT"

        # Risk-reward
        rr = proposal.risk_reward
        rr_label = f"1:{rr:.1f}"

        # P&L potential
        pnl_pct = proposal.pnl_potential_pct

        # Score bar
        score_pct = int(proposal.score * 100)
        score_bar = "█" * (score_pct // 10) + "░" * (10 - score_pct // 10)

        # Risk assessment from RiskGuardian
        risk_lines = []
        if proposal.risk_decision:
            rd = proposal.risk_decision
            if rd.get("approved"):
                risk_lines.append("✅ Risk Guardian: APPROVED")
            else:
                risk_lines.append("❌ Risk Guardian: VETOED")
                for reason in rd.get("rejection_reasons", []):
                    risk_lines.append(f"  ⚠️ {reason}")
            for warning in rd.get("warnings", []):
                risk_lines.append(f"  ⚡ {warning}")

        # Position sizing
        metadata = proposal.metadata
        vol_factor = metadata.get("vol_position_factor", 1.0)
        vol_regime = metadata.get("volatility_regime", "unknown")

        # Kelly fraction (half-Kelly default)
        kelly = 0.25  # Conservative default
        risk_pct = 2.0  # 2% risk per trade

        # Build message
        lines = [
            f"🤖 <b>TSAR wants to open a trade:</b>",
            "",
            f"{side_emoji} <b>{proposal.symbol} {side_label}</b>",
            f"📊 Strategy: {proposal.strategy}",
            "",
            f"💰 Entry: ${proposal.entry_price:,.2f}",
            f"🎯 Target: ${proposal.take_profit:,.2f} (+{pnl_pct:.1f}%)",
            f"🛑 Stop: ${proposal.stop_loss:,.2f} (-{abs(proposal.entry_price - proposal.stop_loss) / proposal.entry_price * 100:.1f}%)",
            f"📊 R:R = {rr_label}",
            "",
            f"<b>Signal Strength:</b> {score_pct}%",
            f"<code>[{score_bar}]</code>",
            "",
            "<b>Why this trade:</b>",
        ]

        # Reasoning bullets
        if proposal.reasoning:
            for part in proposal.reasoning.split("|"):
                part = part.strip()
                if part:
                    lines.append(f"• {part}")

        # Additional metadata insights
        rsi = metadata.get("rsi")
        if rsi is not None:
            lines.append(f"• RSI({metadata.get('rsi_period', 14)}) = {rsi:.1f}")

        patterns = metadata.get("patterns_detected", [])
        if patterns:
            lines.append(f"• Patterns: {', '.join(patterns[:3])}")

        if vol_regime != "unknown":
            lines.append(f"• Volatility regime: {vol_regime} (factor: {vol_factor:.2f})")

        # Multi-TF confluence
        mtf = metadata.get("score_breakdown", {}).get("multi_timeframe", 0)
        if mtf > 0:
            lines.append(f"• Multi-TF confluence: {mtf:.2f}")

        # MACD
        macd_hist = metadata.get("macd_histogram", 0)
        if macd_hist != 0:
            direction = "bullish" if macd_hist > 0 else "bearish"
            lines.append(f"• MACD histogram: {direction} ({macd_hist:.4f})")

        lines.append("")
        lines.append(f"<b>Risk:</b> {risk_pct}% of portfolio")
        lines.append(f"<b>Kelly fraction:</b> {kelly:.2f} (conservative)")

        # Risk Guardian assessment
        if risk_lines:
            lines.append("")
            lines.append("<b>Risk Assessment:</b>")
            lines.extend(risk_lines)

        lines.append("")
        lines.append("<i>Do you want to:</i>")

        return "\n".join(lines)

    def _build_proposal_keyboard(self, proposal_id: str) -> dict[str, Any]:
        """Build inline keyboard for trade proposal.

        Three buttons: Approve, Reject, Modify
        """
        return {
            "inline_keyboard": [
                [
                    {"text": "✅ Approve", "callback_data": f"approve:{proposal_id}"},
                    {"text": "❌ Reject", "callback_data": f"reject:{proposal_id}"},
                    {"text": "📝 Modify", "callback_data": f"modify:{proposal_id}"},
                ],
                [
                    {"text": "💬 Discuss", "callback_data": f"discuss:{proposal_id}"},
                    {"text": "📊 Details", "callback_data": f"details:{proposal_id}"},
                ],
            ]
        }

    async def handle_callback_query(self, callback: dict[str, Any]) -> None:
        """Handle inline keyboard button presses.

        Routes to approve/reject/modify/discuss/details handlers.
        """
        callback_id = callback.get("id", "")
        data = callback.get("data", "")
        message = callback.get("message", {})
        message_id = message.get("message_id")

        if not data or ":" not in data:
            await self.answer_callback(callback_id, "Invalid action")
            return

        action, proposal_id = data.split(":", 1)
        proposal = self._proposals.get(proposal_id)

        if not proposal:
            await self.answer_callback(callback_id, "⚠️ Proposal expired or not found")
            return

        if proposal.state != TRADE_STATE_PENDING:
            await self.answer_callback(callback_id, f"Already {proposal.state}")
            return

        if action == "approve":
            await self._handle_approve(callback_id, proposal, message_id)
        elif action == "reject":
            await self._handle_reject(callback_id, proposal, message_id)
        elif action == "modify":
            await self._handle_modify(callback_id, proposal, message_id)
        elif action == "discuss":
            await self._handle_discuss(callback_id, proposal)
        elif action == "details":
            await self._handle_details(callback_id, proposal)
        else:
            await self.answer_callback(callback_id, "Unknown action")

    async def _handle_approve(
        self,
        callback_id: str,
        proposal: TradeProposal,
        message_id: int | None,
    ) -> None:
        """User approved the trade — execute it."""
        proposal.approve()
        await self.answer_callback(callback_id, "✅ Trade approved! Executing...")

        # Update the message to show approved state
        if message_id:
            approved_msg = self._format_approved_trade(proposal)
            await self.edit_message(message_id, approved_msg)

        # Trigger execution via the system
        if self.system:
            try:
                await self._execute_proposal(proposal)
            except Exception:
                logger.exception("Failed to execute approved proposal %s", proposal.proposal_id)
                await self.send_message(
                    f"❌ Failed to execute trade {proposal.symbol} {proposal.side}. "
                    "Check logs for details."
                )

        logger.info("Trade APPROVED: %s %s %s", proposal.symbol, proposal.side, proposal.proposal_id)

    async def _handle_reject(
        self,
        callback_id: str,
        proposal: TradeProposal,
        message_id: int | None,
    ) -> None:
        """User rejected the trade."""
        proposal.reject()
        await self.answer_callback(callback_id, "❌ Trade rejected")

        if message_id:
            rejected_msg = (
                f"❌ <b>Trade REJECTED</b>\n\n"
                f"{proposal.symbol} {proposal.side.upper()} — {proposal.strategy}\n"
                f"Entry: ${proposal.entry_price:,.2f}\n\n"
                f"<i>Rejected by user at {datetime.now(UTC).strftime('%H:%M:%S UTC')}</i>"
            )
            await self.edit_message(message_id, rejected_msg)

        logger.info("Trade REJECTED: %s %s %s", proposal.symbol, proposal.side, proposal.proposal_id)

    async def _handle_modify(
        self,
        callback_id: str,
        proposal: TradeProposal,
        message_id: int | None,
    ) -> None:
        """User wants to modify parameters — prompt for input."""
        await self.answer_callback(callback_id, "📝 Send your modification...")

        # Store context for the next message
        self._discussion_context = {
            "type": "modify",
            "proposal_id": proposal.proposal_id,
            "awaiting_input": True,
        }

        await self.send_message(
            f"📝 <b>Modify Trade: {proposal.symbol} {proposal.side.upper()}</b>\n\n"
            "Send your modification request. Examples:\n"
            "• \"Move stop to 66500\"\n"
            "• \"Reduce size to 1%\"\n"
            "• \"Change target to 69000\"\n"
            "• \"Cancel\" to abort\n\n"
            "<i>Waiting for your input...</i>"
        )

    async def _handle_discuss(
        self,
        callback_id: str,
        proposal: TradeProposal,
    ) -> None:
        """User wants to discuss the trade — provide deeper analysis."""
        await self.answer_callback(callback_id, "💬 Analyzing...")

        # Build discussion message with deeper analysis
        msg = await self._build_discussion(proposal)
        await self.send_message(msg)

    async def _handle_details(
        self,
        callback_id: str,
        proposal: TradeProposal,
    ) -> None:
        """Show detailed technical analysis for the trade."""
        await self.answer_callback(callback_id, "📊 Loading details...")

        msg = self._format_detailed_analysis(proposal)
        await self.send_message(msg)

    # ── Trade Execution ──────────────────────────────────────

    async def _execute_proposal(self, proposal: TradeProposal) -> None:
        """Execute an approved trade proposal through the TSAR pipeline.

        Sends the signal through the RiskGuardian → ExecutionSniper pipeline.
        """
        if not self.system:
            logger.warning("No TSAR system available for execution")
            return

        # Publish the signal for execution
        from src.comms.events import CloudEvent

        event = CloudEvent(
            source="tsar:bot:telegram",
            type="tsar.signal.approved.v1",
            data={
                "signal_id": proposal.signal_id,
                "symbol": proposal.symbol,
                "side": proposal.side,
                "entry_price": proposal.entry_price,
                "stop_loss": proposal.stop_loss,
                "take_profit": proposal.take_profit,
                "score": proposal.score,
                "strategy": proposal.strategy,
                "reasoning": proposal.reasoning,
                "metadata": proposal.metadata,
                "approved_by": "user_telegram",
                "proposal_id": proposal.proposal_id,
            },
        )

        # Route through the event bus
        if hasattr(self.system, "publish_event"):
            await self.system.publish_event(
                stream="signals",
                event_type="tsar.signal.approved.v1",
                data=event.data,
                priority=1,
            )

    # ── After Trade — Detailed Report ────────────────────────

    async def send_trade_report(self, trade_data: dict[str, Any]) -> None:
        """Send a detailed post-trade report.

        Shows: result, duration, what happened, lesson learned,
        and flywheel update.
        """
        msg = self._format_trade_report(trade_data)
        await self.send_message(msg)

    def _format_trade_report(self, trade: dict[str, Any]) -> str:
        """Format a detailed post-trade report.

        Includes: result, duration, price action summary,
        lesson learned, and flywheel update.
        """
        pnl = trade.get("pnl", 0)
        pnl_pct = trade.get("pnl_pct", 0)
        is_win = pnl >= 0

        emoji = "✅" if is_win else "❌"
        result_label = f"+${pnl:.2f} (+{pnl_pct:.1f}%)" if is_win else f"-${abs(pnl):.2f} ({pnl_pct:.1f}%)"

        symbol = trade.get("symbol", "Unknown")
        side = trade.get("side", "Unknown")
        side_label = "LONG" if side.upper() == "BUY" else "SHORT"

        entry = trade.get("entry_price", 0)
        exit_price = trade.get("exit_price", 0)
        duration = trade.get("duration_str", "N/A")

        # Build report
        lines = [
            f"{emoji} <b>Trade CLOSED — {symbol} {side_label}</b>",
            "",
            f"💰 Result: {result_label}",
            f"⏱️ Duration: {duration}",
            f"📊 Entry: ${entry:,.2f} → Exit: ${exit_price:,.2f}",
            "",
        ]

        # What happened
        lines.append("<b>What happened:</b>")
        exit_reason = trade.get("exit_reason", "unknown")
        if exit_reason == "take_profit":
            lines.append(f"• Price hit target at ${trade.get('take_profit', 0):,.2f}")
        elif exit_reason == "stop_loss":
            lines.append(f"• Price hit stop-loss at ${trade.get('stop_loss', 0):,.2f}")
        elif exit_reason == "trailing_stop":
            lines.append("• Trailing stop triggered")
        else:
            lines.append(f"• Position closed: {exit_reason}")

        # Volume and news context
        if trade.get("volume_confirmed"):
            lines.append("• Volume confirmed the move")
        if trade.get("major_news"):
            lines.append(f"• News event: {trade.get('major_news')}")

        # Lesson from TradePhilosopher
        reflection = trade.get("reflection")
        if reflection:
            lines.append("")
            lines.append("<b>Lesson learned:</b>")
            if isinstance(reflection, str):
                import json
                try:
                    reflection = json.loads(reflection)
                except json.JSONDecodeError:
                    reflection = {"lesson": reflection}

            lesson = reflection.get("lesson", "No lesson extracted")
            lines.append(f"• {lesson}")

            pattern_tags = reflection.get("pattern_tags", [])
            if pattern_tags:
                lines.append(f"• Pattern: \"{', '.join(pattern_tags)}\"")

            what_right = reflection.get("what_went_right")
            if what_right:
                lines.append(f"• What went right: {what_right}")

            what_wrong = reflection.get("what_went_wrong")
            if what_wrong:
                lines.append(f"• What went wrong: {what_wrong}")

            error_cat = reflection.get("error_category")
            if error_cat and error_cat != "none":
                lines.append(f"• Error category: {error_cat}")

            actionable = reflection.get("actionable_change")
            if actionable:
                lines.append(f"• Recommended change: {actionable}")

        # Flywheel update
        flywheel = trade.get("flywheel_update")
        if flywheel:
            lines.append("")
            lines.append("<b>Flywheel update:</b>")
            if flywheel.get("genome_updated"):
                lines.append("• Strategy genome updated")
            if flywheel.get("pattern_confidence_change"):
                change = flywheel["pattern_confidence_change"]
                lines.append(f"• Pattern confidence: {change.get('from', 0):.2f} → {change.get('to', 0):.2f}")
            if flywheel.get("lesson_stored"):
                lines.append(f"• Lesson stored: \"{flywheel['lesson_stored'][:80]}\"")

        return "\n".join(lines)

    def _format_approved_trade(self, proposal: TradeProposal) -> str:
        """Format message for an approved trade."""
        side_label = "LONG" if proposal.side.upper() == "BUY" else "SHORT"
        return (
            f"✅ <b>Trade APPROVED — {proposal.symbol} {side_label}</b>\n\n"
            f"💰 Entry: ${proposal.entry_price:,.2f}\n"
            f"🎯 Target: ${proposal.take_profit:,.2f}\n"
            f"🛑 Stop: ${proposal.stop_loss:,.2f}\n"
            f"📊 R:R = 1:{proposal.risk_reward:.1f}\n\n"
            f"<i>Approved by user at {datetime.now(UTC).strftime('%H:%M:%S UTC')}</i>\n"
            f"<i>Executing via TSAR pipeline...</i>"
        )

    # ── Discussion Builder ───────────────────────────────────

    async def _build_discussion(self, proposal: TradeProposal) -> str:
        """Build a deeper discussion message for a trade proposal.

        Queries regime, strategy, and knowledge stores for context.
        """
        lines = [
            f"💬 <b>Trade Discussion: {proposal.symbol} {proposal.side.upper()}</b>",
            "",
        ]

        # Query regime context
        if self.system:
            try:
                from src.tools.knowledge import KnowledgeTools
                db_path = os.environ.get("TSAR_DB_PATH", "./data/tsar.db")
                kt = KnowledgeTools(db_path)

                # Regime
                regime = kt.get_global_regime()
                if regime:
                    lines.append(f"<b>Current Regime:</b> {regime.get('regime', 'unknown')}")
                    lines.append(f"  Confidence: {regime.get('confidence', 0):.0%}")
                    lines.append("")

                # Recent lessons for this symbol
                symbol_lessons = kt.get_lessons_for_symbol(proposal.symbol)
                if symbol_lessons:
                    lines.append(f"<b>Relevant Lessons ({len(symbol_lessons)}):</b>")
                    for lesson in symbol_lessons[:3]:
                        lines.append(f"• {lesson.get('content', '')[:100]}")
                    lines.append("")

                # Matching patterns
                patterns = kt.get_active_patterns()
                if patterns:
                    lines.append(f"<b>Active Patterns ({len(patterns)}):</b>")
                    for p in patterns[:3]:
                        lines.append(f"• {p.get('name', 'unknown')} (confidence: {p.get('confidence', 0):.0%})")

                kt.close()
            except Exception:
                logger.debug("Discussion context query failed", exc_info=True)

        # Signal breakdown
        breakdown = proposal.metadata.get("score_breakdown", {})
        if breakdown:
            lines.append("")
            lines.append("<b>Score Breakdown:</b>")
            for component, score in breakdown.items():
                lines.append(f"• {component}: {score:.3f}")

        lines.append("")
        lines.append(
            "<i>Use the buttons below to approve, reject, or modify this trade.</i>"
        )

        return "\n".join(lines)

    def _format_detailed_analysis(self, proposal: TradeProposal) -> str:
        """Format detailed technical analysis for a trade."""
        meta = proposal.metadata

        lines = [
            f"📊 <b>Detailed Analysis: {proposal.symbol}</b>",
            "",
            "<b>Technical Indicators:</b>",
        ]

        # RSI
        rsi = meta.get("rsi")
        if rsi is not None:
            rsi_state = "oversold" if rsi < 30 else "overbought" if rsi > 70 else "neutral"
            lines.append(f"• RSI: {rsi:.1f} ({rsi_state})")

        # MACD
        macd_hist = meta.get("macd_histogram", 0)
        if macd_hist:
            lines.append(f"• MACD histogram: {macd_hist:.4f}")

        # Bollinger
        bb_upper = meta.get("bb_upper", 0)
        bb_lower = meta.get("bb_lower", 0)
        if bb_upper and bb_lower:
            lines.append(f"• Bollinger: [{bb_lower:,.2f} — {bb_upper:,.2f}]")

        # ATR
        atr = meta.get("atr", 0)
        if atr:
            lines.append(f"• ATR: {atr:.2f}")

        # EMA trend
        ema = meta.get("ema_trend", 0)
        if ema:
            trend = "above" if proposal.entry_price > ema else "below"
            lines.append(f"• EMA(50): {ema:,.2f} (price {trend})")

        # Volatility
        vol_regime = meta.get("volatility_regime", "unknown")
        if vol_regime != "unknown":
            lines.append(f"• Volatility: {vol_regime}")

        # Patterns
        patterns = meta.get("patterns_detected", [])
        if patterns:
            lines.append("")
            lines.append("<b>Detected Patterns:</b>")
            for p in patterns:
                lines.append(f"• {p}")

        # Score breakdown
        breakdown = meta.get("score_breakdown", {})
        if breakdown:
            lines.append("")
            lines.append("<b>Signal Score Components:</b>")
            for component, score in breakdown.items():
                bar_len = int(score * 20)
                bar = "█" * bar_len + "░" * (20 - bar_len)
                lines.append(f"• {component}: <code>[{bar}]</code> {score:.3f}")

        return "\n".join(lines)

    # ── Security ─────────────────────────────────────────────

    def _is_authorized(self, msg: dict[str, Any]) -> bool:
        """Check if the message sender is in the chat whitelist."""
        chat = msg.get("chat", {})
        chat_id = str(chat.get("id", ""))
        return chat_id in self._allowed_chat_ids

    # ── Polling Loop ─────────────────────────────────────────

    async def poll_loop(self) -> None:
        """Main polling loop — handles messages and callback queries.

        Routes:
        - Text messages starting with / → command handler
        - Callback queries → inline button handler
        - Other text → discussion context handler
        """
        # Start proposal expiry checker
        self._proposal_expiry_task = asyncio.create_task(self._expiry_loop())

        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    resp = await session.get(
                        f"{self.base_url}/getUpdates",
                        params={"offset": self.offset, "timeout": 30},
                    )
                    data = await resp.json()

                    for update in data.get("result", []):
                        self.offset = update["update_id"] + 1

                        # Handle callback queries (inline button presses)
                        if "callback_query" in update:
                            callback = update["callback_query"]
                            # SECURITY: Check authorization
                            callback_msg = callback.get("message", {})
                            if self._is_authorized(callback_msg):
                                await self.handle_callback_query(callback)
                            continue

                        # Handle text messages
                        msg = update.get("message", {})
                        text = msg.get("text", "")

                        if not self._is_authorized(msg):
                            logger.warning(
                                "Unauthorized message from chat_id=%s",
                                msg.get("chat", {}).get("id"),
                            )
                            continue

                        if text.startswith("/"):
                            await self.handle_command(text, msg)
                        elif self._discussion_context.get("awaiting_input"):
                            await self._handle_freeform_input(text, msg)

            except Exception:
                logger.exception("Poll loop error")
                await asyncio.sleep(5)

    async def _expiry_loop(self) -> None:
        """Background task to expire stale trade proposals."""
        while True:
            try:
                await asyncio.sleep(30)
                now = time.time()
                for pid, proposal in list(self._proposals.items()):
                    if proposal.is_expired:
                        proposal.expire()
                        logger.info("Trade proposal %s expired", pid)
                        if proposal.telegram_message_id:
                            await self.edit_message(
                                proposal.telegram_message_id,
                                f"⏰ <b>Trade EXPIRED</b>\n\n"
                                f"{proposal.symbol} {proposal.side.upper()} — {proposal.strategy}\n"
                                f"<i>Proposal expired after {proposal.ttl_seconds}s without response</i>",
                            )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Expiry loop error")

    async def _handle_freeform_input(self, text: str, msg: dict[str, Any]) -> None:
        """Handle freeform text input (for modify requests and /ask)."""
        ctx = self._discussion_context
        self._discussion_context = {}  # Clear context

        if ctx.get("type") == "modify":
            proposal_id = ctx.get("proposal_id")
            proposal = self._proposals.get(proposal_id)
            if proposal and proposal.state == TRADE_STATE_PENDING:
                if text.lower() in ("cancel", "abort", "nvm", "nevermind"):
                    await self.send_message("📝 Modification cancelled. Trade proposal still pending.")
                    return

                proposal.modify(text)
                await self.send_message(
                    f"📝 <b>Modification noted:</b> {text}\n\n"
                    "The trade parameters have been updated. "
                    "Please review the modified proposal."
                )
                # Re-propose with modifications noted
                logger.info("Trade %s modified: %s", proposal_id, text)

        elif ctx.get("type") == "ask":
            # Handle /ask follow-up
            await self._handle_ask_question(text)

    # ── Command Handler ──────────────────────────────────────

    async def handle_command(self, text: str, msg: dict[str, Any] | None = None) -> None:
        """Route Telegram commands to handlers.

        Commands:
        /start     — Start trading
        /stop      — Emergency stop (kill switch)
        /status    — System status
        /pnl       — P&L summary
        /positions — Open positions
        /risk      — Risk state
        /regime    — Current market regime
        /flywheel  — Flywheel health
        /performance — Detailed performance analysis
        /strategy  — Current strategy and genome
        /discuss   — Discuss a specific trade
        /why       — Why was a trade taken
        /ask       — Ask TSAR anything
        /help      — Show available commands
        """
        from src.bot.commands import handle_command

        parts = text.split()
        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        try:
            if cmd == "/ask" and not args:
                # Prompt for question
                self._discussion_context = {"type": "ask", "awaiting_input": True}
                await self.send_message(
                    "❓ <b>Ask TSAR anything</b>\n\n"
                    "Send your question about markets, strategy, or trading.\n"
                    "Examples:\n"
                    "• \"Why are we in bull regime?\"\n"
                    "• \"What's the best setup for BTC right now?\"\n"
                    "• \"How is the flywheel performing?\""
                )
                return

            if cmd == "/help":
                await self._send_help()
                return

            response = await handle_command(cmd, args)
            await self.send_message(response)

        except Exception as e:
            logger.error("Command %s failed: %s", cmd, e)
            await self.send_message(f"❌ Error executing {cmd}: {e!s}")

    async def _handle_ask_question(self, question: str) -> None:
        """Handle an /ask question with context from TSAR subsystems.

        Aggregates context from regime, strategy, performance, and
        knowledge stores to provide an informed answer.
        """
        lines = [f"❓ <b>Your question:</b> {question}", ""]

        try:
            from src.tools.knowledge import KnowledgeTools
            db_path = os.environ.get("TSAR_DB_PATH", "./data/tsar.db")
            kt = KnowledgeTools(db_path)

            # Search knowledge stores for relevant context
            try:
                await kt.init_fts()
                search_results = await kt.search(question, limit=5)
                if search_results:
                    lines.append("<b>Relevant knowledge:</b>")
                    for r in search_results[:3]:
                        lines.append(f"• [{r.get('store', '?')}] {r.get('content', '')[:120]}")
                    lines.append("")
            except Exception:
                logger.debug("FTS search failed for /ask", exc_info=True)

            # Add regime context
            regime = kt.get_global_regime()
            if regime:
                lines.append(f"<b>Current regime:</b> {regime.get('regime', 'unknown')}")

            # Add performance context
            stats = kt.trade_memory.get_trade_stats()
            if stats.get("trade_count", 0) > 0:
                lines.append(
                    f"<b>Performance:</b> {stats['trade_count']} trades, "
                    f"WR {stats['win_rate']:.0%}, P&L {stats['total_pnl']:.2f}"
                )

            kt.close()

        except Exception:
            logger.debug("Ask context aggregation failed", exc_info=True)

        lines.append("")
        lines.append(
            "<i>For deeper analysis, use /performance, /regime, or /strategy.</i>"
        )

        await self.send_message("\n".join(lines))

    async def _send_help(self) -> None:
        """Send the help message with all available commands."""
        help_text = (
            "🏰 <b>TSAR Interactive Trading Partner</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            "<b>📊 Monitoring:</b>\n"
            "/status — System health and state\n"
            "/pnl — P&L summary\n"
            "/positions — Open positions\n"
            "/risk — Risk assessment\n\n"

            "<b>🌊 Analysis:</b>\n"
            "/regime — Current market regime\n"
            "/strategy — Active strategy & genome\n"
            "/flywheel — Self-improvement health\n"
            "/performance — Detailed performance\n\n"

            "<b>💬 Interactive:</b>\n"
            "/discuss [trade_id] — Discuss a trade\n"
            "/why [trade_id] — Why was this trade taken?\n"
            "/ask — Ask TSAR anything\n\n"

            "<b>⚙️ Control:</b>\n"
            "/start — Resume trading\n"
            "/stop — Emergency stop\n"
            "/help — This message\n\n"

            "<b>🔘 Inline Buttons:</b>\n"
            "When TSAR proposes a trade, use the buttons to:\n"
            "✅ Approve — Execute the trade\n"
            "❌ Reject — Skip this trade\n"
            "📝 Modify — Change parameters\n"
            "💬 Discuss — Get deeper analysis\n"
            "📊 Details — Full technical breakdown\n"
        )
        await self.send_message(help_text)

    # ── Risk Alerts ──────────────────────────────────────────

    async def send_risk_alert(self, level: str, message: str) -> None:
        """Send a risk alert with appropriate severity formatting."""
        emoji_map = {
            "LOW": "🟡",
            "MEDIUM": "🟠",
            "HIGH": "🔴",
            "CRITICAL": "🚨",
        }
        emoji = emoji_map.get(level, "⚠️")
        await self.send_message(f"{emoji} <b>RISK [{level}]</b>\n{message}")

    # ── Notification Helpers ─────────────────────────────────

    async def send_flywheel_notification(self, flywheel_data: dict[str, Any]) -> None:
        """Send a flywheel cycle completion notification."""
        runs = flywheel_data.get("run_id", 0)
        rules = flywheel_data.get("rules_extracted", 0)
        validated = flywheel_data.get("rules_validated", 0)
        proposals = flywheel_data.get("mutations_proposed", 0)
        applied = flywheel_data.get("mutations_applied", 0)

        msg = (
            f"🔄 <b>Flywheel Cycle #{runs} Complete</b>\n\n"
            f"📝 Rules extracted: {rules}\n"
            f"✅ Rules validated: {validated}\n"
            f"🧬 Mutations proposed: {proposals}\n"
            f"📈 Mutations applied: {applied}\n"
        )

        outcome = flywheel_data.get("outcome", "")
        if outcome == "success":
            msg += "\n🟢 Pipeline: All steps completed successfully"
        elif outcome == "no_rules":
            msg += "\n🟡 Pipeline: No new rules to process"
        else:
            msg += f"\n🔴 Pipeline: {outcome}"

        await self.send_message(msg)

    async def send_regime_change(self, regime_data: dict[str, Any]) -> None:
        """Send a regime change notification."""
        regime = regime_data.get("regime", "unknown")
        confidence = regime_data.get("confidence", 0)
        emoji_map = {
            "STRONG_TREND_UP": "🟢📈",
            "STRONG_TREND_DOWN": "🔴📉",
            "RANGING": "↔️",
            "HIGH_VOLATILITY": "🌊",
            "UNCERTAIN": "❓",
        }
        emoji = emoji_map.get(regime, "🔄")
        await self.send_message(
            f"{emoji} <b>Regime Change Detected</b>\n\n"
            f"New regime: {regime}\n"
            f"Confidence: {confidence:.0%}\n"
        )
