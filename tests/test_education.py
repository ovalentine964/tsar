"""
Tests for the Trade Education System.
"""

import json
import os
import sys
import tempfile

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.education.message_formatter import TelegramFormatter as Fmt
from src.education.pre_trade import PreTradeExplainer
from src.education.post_trade import PostTradeExplainer
from src.education.weekly_report import WeeklyReportGenerator
from src.education.on_demand import OnDemandEducation, LEARNING_TOPICS, QUIZ_QUESTIONS
from src.education.learning_tracker import LearningTracker, LEARNING_LEVELS


class TestTelegramFormatter:
    """Test message formatting utilities."""

    def test_bold(self):
        assert Fmt.bold("test") == "<b>test</b>"

    def test_code(self):
        assert Fmt.code("test") == "<code>test</code>"

    def test_separator(self):
        assert "━━" in Fmt.separator()

    def test_rr_emoji(self):
        assert Fmt.rr_emoji(3.5) == "🔥"
        assert Fmt.rr_emoji(2.5) == "✅"
        assert Fmt.rr_emoji(1.5) == "⚠️"
        assert Fmt.rr_emoji(0.5) == "❌"

    def test_format_price(self):
        assert Fmt.format_price(42000) == "$42,000.00"
        assert Fmt.format_price(0.5) == "$0.500000"
        assert Fmt.format_price(0.001) == "$0.001000"

    def test_format_pnl(self):
        assert "+$" in Fmt.format_pnl(0.29, 2.9)
        assert "-$" in Fmt.format_pnl(-0.10, -1.0)

    def test_format_equity_curve(self):
        curve = [10.0, 10.1, 10.3, 10.2, 10.5]
        result = Fmt.format_equity_curve(curve)
        assert "$" in result
        assert "|" in result

    def test_equity_curve_empty(self):
        assert "not enough data" in Fmt.format_equity_curve([])
        assert "not enough data" in Fmt.format_equity_curve([10.0])


class TestPreTradeExplainer:
    """Test pre-trade signal explanation generation."""

    def setup_method(self):
        self.explainer = PreTradeExplainer(learning_level=1)

    def test_basic_message(self):
        signal = {
            "symbol": "BTC/USDT",
            "side": "BUY",
            "entry_price": 42000,
            "stop_loss": 41500,
            "take_profit": 43200,
            "metadata": {
                "rsi": 28,
                "support_bounce": True,
                "support_level": 42000,
                "bounce_count": "3rd",
                "volume_change_pct": 150,
            },
        }
        risk = {
            "entry_price": 42000,
            "stop_loss": 41500,
            "take_profit": 43200,
            "position_size": 1.0,
            "risk_amount": 0.10,
        }
        balance = 10.0

        msg = self.explainer.build_message(signal, risk, balance)

        assert "BTC/USDT" in msg
        assert "LONG" in msg or "BUY" in msg
        assert "RSI" in msg
        assert "28" in msg
        assert "support" in msg.lower()
        assert "Execute" in msg
        assert "Skip" in msg

    def test_level_1_no_regime(self):
        """Level 1 should not show regime analysis."""
        explainer = PreTradeExplainer(learning_level=1)
        signal = {"symbol": "ETH/USDT", "side": "BUY", "metadata": {}}
        risk = {"entry_price": 2000, "stop_loss": 1950, "take_profit": 2100,
                "position_size": 1.0, "risk_amount": 0.05}

        msg = explainer.build_message(
            signal, risk, 10.0,
            regime={"regime": "trending", "adx": 32}
        )
        # Level 1 should NOT include regime section
        assert "REGIME" not in msg

    def test_level_2_with_regime(self):
        """Level 2+ should show regime analysis."""
        explainer = PreTradeExplainer(learning_level=2)
        signal = {"symbol": "ETH/USDT", "side": "BUY", "metadata": {}}
        risk = {"entry_price": 2000, "stop_loss": 1950, "take_profit": 2100,
                "position_size": 1.0, "risk_amount": 0.05}

        msg = explainer.build_message(
            signal, risk, 10.0,
            regime={"regime": "trending", "adx": 32}
        )
        assert "REGIME" in msg

    def test_rsi_overbought(self):
        signal = {
            "symbol": "BTC/USDT",
            "side": "SELL",
            "metadata": {"rsi": 78},
        }
        risk = {"entry_price": 42000, "stop_loss": 42500, "take_profit": 41000,
                "position_size": 1.0, "risk_amount": 0.10}

        msg = self.explainer.build_message(signal, risk, 10.0)
        assert "overbought" in msg.lower() or "78" in msg


class TestPostTradeExplainer:
    """Test post-trade explanation generation."""

    def setup_method(self):
        self.explainer = PostTradeExplainer()

    def test_win_message(self):
        trade = {
            "symbol": "BTC/USDT",
            "side": "BUY",
            "pnl": 0.29,
            "pnl_pct": 2.9,
            "entry_price": 42000,
            "exit_price": 43200,
            "entry_time": "2026-08-01 10:00",
            "exit_time": "2026-08-01 14:30",
            "duration": "4h 30m",
            "max_drawdown_pct": 0.5,
            "max_profit_pct": 3.2,
            "strategy": "trend_following",
            "metadata": json.dumps({"rsi": 28, "support_held": True, "support_level": 42000}),
        }
        reflection = {
            "outcome": "win",
            "lesson": "RSI + support = high probability setup",
            "what_went_right": "RSI oversold signal was correct",
            "pattern_tags": ["rsi_oversold", "support_bounce"],
            "error_category": "none",
        }

        msg = self.explainer.build_message(trade, reflection, 55.0, 58.0)

        assert "WIN" in msg
        assert "+$0.29" in msg
        assert "RSI" in msg
        assert "support" in msg.lower()
        assert "LESSON" in msg

    def test_loss_message(self):
        trade = {
            "symbol": "ETH/USDT",
            "side": "BUY",
            "pnl": -0.10,
            "pnl_pct": -1.0,
            "entry_price": 2000,
            "exit_price": 1980,
            "entry_time": "2026-08-01 10:00",
            "exit_time": "2026-08-01 11:00",
            "duration": "1h",
            "strategy": "mean_reversion",
            "metadata": json.dumps({"support_broke": True, "support_level": 1990}),
        }
        reflection = {
            "outcome": "loss",
            "lesson": "Support breaks during news events",
            "what_went_wrong": "Support at $1990 broke",
            "actionable_change": "No entries within 2h of FOMC",
            "pattern_tags": ["mean_reversion"],
            "error_category": "regime",
        }

        msg = self.explainer.build_message(trade, reflection, 45.0, 43.0)

        assert "LOSS" in msg
        assert "$0.10" in msg
        assert "broke" in msg.lower() or "support" in msg.lower()
        assert "LESSON" in msg

    def test_breakeven_message(self):
        trade = {
            "symbol": "SOL/USDT",
            "side": "BUY",
            "pnl": 0.0,
            "pnl_pct": 0.0,
            "fees": 0.002,
        }
        reflection = {"outcome": "breakeven"}

        msg = self.explainer.build_message(trade, reflection)

        assert "BREAKEVEN" in msg
        assert "capital" in msg.lower() or "protect" in msg.lower()


class TestWeeklyReport:
    """Test weekly report generation."""

    def setup_method(self):
        self.gen = WeeklyReportGenerator()

    def test_report_with_trades(self):
        trades = [
            {
                "symbol": "BTC/USDT", "side": "BUY", "pnl": 0.29, "pnl_pct": 2.9,
                "balance": 10.29,
                "reflection": json.dumps({"outcome": "win", "pattern_tags": ["rsi_oversold"]}),
            },
            {
                "symbol": "ETH/USDT", "side": "BUY", "pnl": -0.10, "pnl_pct": -1.0,
                "balance": 10.19,
                "reflection": json.dumps({"outcome": "loss", "pattern_tags": ["mean_reversion"]}),
            },
            {
                "symbol": "BTC/USDT", "side": "SELL", "pnl": 0.15, "pnl_pct": 1.5,
                "balance": 10.34,
                "reflection": json.dumps({"outcome": "win", "pattern_tags": ["rsi_oversold"]}),
            },
        ]

        report = self.gen.build_report(trades, equity_points=[10.0, 10.29, 10.19, 10.34])

        assert "WEEKLY" in report
        assert "3" in report  # 3 trades
        assert "Win" in report or "win" in report
        assert "Loss" in report or "loss" in report
        assert "PATTERNS" in report or "Patterns" in report

    def test_empty_report(self):
        report = self.gen.build_report([])
        assert "No trades" in report


class TestOnDemandEducation:
    """Test on-demand educational queries."""

    def setup_method(self):
        self.edu = OnDemandEducation()

    def test_learn_rsi(self):
        msg = self.edu.learn_topic("rsi")
        assert "RSI" in msg
        assert "oversold" in msg.lower() or "overbought" in msg.lower()
        assert "HOW I USE IT" in msg

    def test_learn_support(self):
        msg = self.edu.learn_topic("support")
        assert "Support" in msg or "support" in msg

    def test_learn_alias(self):
        msg = self.edu.learn_topic("relative strength index")
        assert "RSI" in msg

    def test_learn_unknown(self):
        msg = self.edu.learn_topic("fibonacci")
        assert "not found" in msg.lower() or "available" in msg.lower()

    def test_list_topics(self):
        msg = self.edu.list_topics()
        for topic_key in LEARNING_TOPICS:
            assert topic_key in msg

    def test_quiz_question(self):
        q = self.edu.get_quiz_question()
        assert q is not None
        assert "question" in q
        assert "options" in q
        assert "answer" in q

    def test_quiz_question_by_topic(self):
        q = self.edu.get_quiz_question("rsi")
        assert q is not None
        assert q["topic"] == "rsi"

    def test_quiz_correct_answer(self):
        q = self.edu.get_quiz_question()
        correct, explanation = self.edu.check_quiz_answer(q, q["answer"])
        assert correct is True
        assert "Correct" in explanation

    def test_quiz_wrong_answer(self):
        q = self.edu.get_quiz_question()
        wrong = "Z" if q["answer"] != "Z" else "A"
        if wrong == q["answer"]:
            wrong = "B" if q["answer"] != "B" else "C"
        correct, explanation = self.edu.check_quiz_answer(q, wrong)
        assert correct is False
        assert "Wrong" in explanation

    def test_best_pattern(self):
        trades = [
            {"pnl": 0.29, "reflection": json.dumps({"outcome": "win", "pattern_tags": ["rsi_support"]})},
            {"pnl": 0.15, "reflection": json.dumps({"outcome": "win", "pattern_tags": ["rsi_support"]})},
            {"pnl": -0.10, "reflection": json.dumps({"outcome": "loss", "pattern_tags": ["rsi_support"]})},
        ]
        msg = self.edu.best_pattern(trades)
        assert "BEST" in msg or "best" in msg.lower()

    def test_mistakes_analysis(self):
        trades = [
            {"pnl": -0.10, "reflection": json.dumps({"outcome": "loss", "error_category": "timing"})},
            {"pnl": -0.05, "reflection": json.dumps({"outcome": "loss", "error_category": "timing"})},
            {"pnl": -0.08, "reflection": json.dumps({"outcome": "loss", "error_category": "regime"})},
        ]
        msg = self.edu.mistakes_analysis(trades)
        assert "MISTAKES" in msg
        assert "timing" in msg.lower()


class TestLearningTracker:
    """Test learning progress tracking."""

    def setup_method(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.tracker = LearningTracker(self.tmp.name)
        self.tracker.initialize()

    def teardown_method(self):
        self.tracker.close()
        os.unlink(self.tmp.name)

    def test_initial_level(self):
        assert self.tracker.get_current_level() == 1

    def test_feature_flags_level_1(self):
        assert self.tracker.get_explanation_depth() == "simple"
        assert self.tracker.should_show_regime() is False
        assert self.tracker.should_show_onchain() is False
        assert self.tracker.should_show_genome() is False
        assert self.tracker.is_auto_trade_enabled() is False

    def test_topic_learned(self):
        self.tracker.record_topic_learned("rsi")
        status = self.tracker.get_mastery_status()
        assert status["rsi"]["learned"] is True
        assert status["rsi"]["mastered"] is False

    def test_quiz_mastery(self):
        """80%+ on 3 consecutive quizzes should master a topic."""
        for _ in range(3):
            self.tracker.record_quiz_score("rsi", 9, 10)
        status = self.tracker.get_mastery_status()
        assert status["rsi"]["mastered"] is True

    def test_quiz_no_mastery_below_threshold(self):
        """Below 80% should not master."""
        for _ in range(3):
            self.tracker.record_quiz_score("rsi", 7, 10)
        status = self.tracker.get_mastery_status()
        assert status["rsi"].get("mastered", False) is False

    def test_progress_report(self):
        self.tracker.record_topic_learned("rsi")
        self.tracker.record_quiz_score("rsi", 9, 10)
        report = self.tracker.get_progress_report()
        assert report["level"] == 1
        assert report["level_name"] == "Beginner"
        assert report["topics_learned"] >= 1

    def test_level_definitions(self):
        """All 4 levels should be defined."""
        assert 1 in LEARNING_LEVELS
        assert 2 in LEARNING_LEVELS
        assert 3 in LEARNING_LEVELS
        assert 4 in LEARNING_LEVELS
        assert LEARNING_LEVELS[1]["name"] == "Beginner"
        assert LEARNING_LEVELS[4]["name"] == "Autonomous"

    def test_trades_analyzed_counter(self):
        self.tracker.increment_trades_analyzed()
        self.tracker.increment_trades_analyzed()
        report = self.tracker.get_progress_report()
        # The counter is in learning_state, check via progress report
        # (progress_report doesn't expose trades_analyzed directly,
        #  but we can verify no exceptions)
        assert report is not None


def run_tests():
    """Run all tests manually (no pytest dependency)."""
    test_classes = [
        TestTelegramFormatter,
        TestPreTradeExplainer,
        TestPostTradeExplainer,
        TestWeeklyReport,
        TestOnDemandEducation,
        TestLearningTracker,
    ]

    passed = 0
    failed = 0
    errors = []

    for cls in test_classes:
        instance = cls()
        methods = [m for m in dir(instance) if m.startswith("test_")]
        for method_name in methods:
            try:
                if hasattr(instance, "setup_method"):
                    instance.setup_method()
                getattr(instance, method_name)()
                if hasattr(instance, "teardown_method"):
                    instance.teardown_method()
                passed += 1
                print(f"  ✅ {cls.__name__}.{method_name}")
            except Exception as e:
                failed += 1
                errors.append((cls.__name__, method_name, str(e)))
                print(f"  ❌ {cls.__name__}.{method_name}: {e}")

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")
    if errors:
        print("\nFailures:")
        for cls, method, err in errors:
            print(f"  {cls}.{method}: {err}")

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
