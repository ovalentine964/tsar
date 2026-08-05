"""TSAR — ML Signal Scorer (H-012).

Lightweight XGBoost/LightGBM model for combining LLM signals with
statistical signals. Replaces pure LLM-based scoring with a hybrid
approach that learns from historical trade outcomes.

Features:
- Technical indicators (RSI, MACD, BB, ATR, volume ratio)
- Signal score from rule-based system
- LLM confidence (if available)
- Regime features (if available)

Target: Binary classification (profitable trade = 1, loss = 0)
or regression (P&L percentage).

Models are trained on closed trade history from TradeMemory.
"""

from __future__ import annotations

import json
import logging
import pickle
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from src.knowledge.trade_memory import TradeMemory

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# FEATURE DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════

FEATURE_COLUMNS = [
    "rsi",
    "macd_histogram",
    "bb_position",  # 0=lower band, 1=upper band
    "atr_pct",  # ATR as % of price
    "volume_ratio",  # current / average volume
    "signal_score",  # rule-based signal score
    "ema_alignment",  # 1 if price aligned with EMA, 0 otherwise
    "sr_proximity",  # distance to nearest S/R level (%)
    "side_buy",  # 1 for BUY, 0 for SELL
    "hour_of_day",  # 0-23
    "day_of_week",  # 0-6
]


@dataclass
class ScorerConfig:
    """ML scorer configuration."""

    model_type: str = "xgboost"  # "xgboost" or "lightgbm"
    min_training_samples: int = 30
    retrain_interval_hours: int = 24
    model_dir: str = "models/ml_scorer"
    feature_importance_threshold: float = 0.01


# ═══════════════════════════════════════════════════════════════════════
# ML SCORER
# ═══════════════════════════════════════════════════════════════════════


class MLScorer:
    """ML-based signal scorer combining LLM and statistical signals.

    Trains on historical trade outcomes to learn which feature
    combinations predict profitable trades. Used to re-score or
    validate signals from the SignalScout.

    Usage::

        scorer = MLScorer(trade_memory, config)
        await scorer.train()  # Train on historical data
        score = scorer.predict(features)  # Score a new signal
    """

    def __init__(
        self,
        trade_memory: TradeMemory,
        config: ScorerConfig | None = None,
    ) -> None:
        self._memory = trade_memory
        self._config = config or ScorerConfig()
        self._model: Any = None
        self._feature_importance: dict[str, float] = {}
        self._last_train_time: float = 0.0
        self._training_samples: int = 0
        self._model_path = Path(self._config.model_dir) / "scorer.pkl"

    @property
    def is_trained(self) -> bool:
        return self._model is not None

    @property
    def training_samples(self) -> int:
        return self._training_samples

    async def train(self, force: bool = False) -> dict[str, Any]:
        """Train or retrain the model on historical trade data.

        Args:
            force: Force retrain even if recently trained.

        Returns:
            Training metrics dict.
        """
        # Check if retrain needed
        hours_since = (time.time() - self._last_train_time) / 3600
        if not force and hours_since < self._config.retrain_interval_hours:
            return {"status": "skipped", "reason": "recently trained"}

        # Fetch training data
        X, y = self._prepare_training_data()
        if len(X) < self._config.min_training_samples:
            logger.info(
                "ML scorer: insufficient data (%d < %d)",
                len(X),
                self._config.min_training_samples,
            )
            return {
                "status": "insufficient_data",
                "samples": len(X),
                "min_required": self._config.min_training_samples,
            }

        # Train model
        metrics = self._fit_model(X, y)
        self._last_train_time = time.time()
        self._training_samples = len(X)

        # Save model
        self._save_model()

        logger.info(
            "ML scorer trained: %d samples, accuracy=%.3f, features=%d",
            len(X),
            metrics.get("accuracy", 0),
            len(FEATURE_COLUMNS),
        )
        return metrics

    def predict(self, features: dict[str, float]) -> tuple[float, dict[str, float]]:
        """Predict probability of profitable trade.

        Args:
            features: Dict mapping feature names to values.

        Returns:
            Tuple of (probability, feature_contributions).
            probability: 0-1, likelihood of profitable trade.
            feature_contributions: Per-feature contribution to prediction.
        """
        if self._model is None:
            # No model trained — return neutral score
            return 0.5, {}

        x = np.array([[features.get(f, 0.0) for f in FEATURE_COLUMNS]])

        try:
            proba = self._model.predict_proba(x)[0]
            score = float(proba[1])  # Probability of class 1 (profitable)
        except Exception:
            score = float(self._model.predict(x)[0])
            score = max(0.0, min(1.0, score))

        # Feature contributions (approximate via feature importance)
        contributions = {}
        for _i, fname in enumerate(FEATURE_COLUMNS):
            importance = self._feature_importance.get(fname, 0.0)
            contributions[fname] = round(importance * features.get(fname, 0.0), 4)

        return max(0.0, min(1.0, score)), contributions

    def score_signal(self, signal_metadata: dict[str, Any]) -> float:
        """Score a signal from SignalScout metadata.

        Extracts features from signal metadata and returns ML score.

        Args:
            signal_metadata: Signal.metadata dict from SignalScout.

        Returns:
            ML confidence score 0-1.
        """
        features = {
            "rsi": signal_metadata.get("rsi", 50.0),
            "macd_histogram": signal_metadata.get("macd_histogram", 0.0),
            "bb_position": self._compute_bb_position(signal_metadata),
            "atr_pct": self._compute_atr_pct(signal_metadata),
            "volume_ratio": signal_metadata.get("volume_ratio", 1.0),
            "signal_score": signal_metadata.get("score", 0.5),
            "ema_alignment": 1.0 if signal_metadata.get("ema_trend", 0) > 0 else 0.0,
            "sr_proximity": signal_metadata.get("sr_proximity_pct", 0.0),
            "side_buy": 1.0 if signal_metadata.get("side", "buy") == "buy" else 0.0,
            "hour_of_day": datetime.now(UTC).hour,
            "day_of_week": datetime.now(UTC).weekday(),
        }
        score, _ = self.predict(features)
        return score

    # ── Internal ──────────────────────────────────────────────────────

    def _prepare_training_data(self) -> tuple[np.ndarray, np.ndarray]:
        """Prepare feature matrix and labels from trade history."""
        closed_trades = self._memory.list_trades(status="CLOSED", limit=2000)

        X_rows: list[list[float]] = []
        y_vals: list[int] = []

        for trade in closed_trades:
            meta = getattr(trade, "metadata", {}) or {}
            if not isinstance(meta, dict):
                try:
                    meta = json.loads(meta) if isinstance(meta, str) else {}
                except (json.JSONDecodeError, TypeError):
                    meta = {}

            row = [
                meta.get("rsi", 50.0),
                meta.get("macd_histogram", 0.0),
                self._compute_bb_position(meta),
                self._compute_atr_pct(meta),
                meta.get("volume_ratio", 1.0),
                getattr(trade, "signal_score", 0.5) or 0.5,
                1.0 if meta.get("ema_trend", 0) > 0 else 0.0,
                meta.get("sr_proximity_pct", 0.0),
                1.0 if getattr(trade, "side", "buy") == "buy" else 0.0,
                self._extract_hour(trade),
                self._extract_dow(trade),
            ]
            X_rows.append(row)

            pnl = getattr(trade, "realized_pnl", 0.0) or 0.0
            y_vals.append(1 if pnl > 0 else 0)

        return np.array(X_rows), np.array(y_vals)

    def _fit_model(self, X: np.ndarray, y: np.ndarray) -> dict[str, Any]:
        """Fit the ML model to training data."""
        try:
            if self._config.model_type == "lightgbm":
                return self._fit_lightgbm(X, y)
            else:
                return self._fit_xgboost(X, y)
        except ImportError:
            logger.warning(
                "%s not installed, falling back to logistic regression",
                self._config.model_type,
            )
            return self._fit_sklearn_fallback(X, y)

    def _fit_xgboost(self, X: np.ndarray, y: np.ndarray) -> dict[str, Any]:
        """Train XGBoost classifier."""
        import xgboost as xgb
        from sklearn.model_selection import cross_val_score

        self._model = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            eval_metric="logloss",
            use_label_encoder=False,
            random_state=42,
        )
        self._model.fit(X, y)

        # Cross-validation accuracy
        cv_scores = cross_val_score(self._model, X, y, cv=min(5, len(X) // 5), scoring="accuracy")

        # Feature importance
        importances = self._model.feature_importances_
        self._feature_importance = dict(zip(FEATURE_COLUMNS, importances.tolist(), strict=False))

        return {
            "status": "trained",
            "model": "xgboost",
            "accuracy": float(np.mean(cv_scores)),
            "accuracy_std": float(np.std(cv_scores)),
            "samples": len(X),
            "feature_importance": self._feature_importance,
        }

    def _fit_lightgbm(self, X: np.ndarray, y: np.ndarray) -> dict[str, Any]:
        """Train LightGBM classifier."""
        import lightgbm as lgb
        from sklearn.model_selection import cross_val_score

        self._model = lgb.LGBMClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            verbose=-1,
        )
        self._model.fit(X, y)

        cv_scores = cross_val_score(self._model, X, y, cv=min(5, len(X) // 5), scoring="accuracy")

        importances = self._model.feature_importances_
        self._feature_importance = dict(zip(FEATURE_COLUMNS, importances.tolist(), strict=False))

        return {
            "status": "trained",
            "model": "lightgbm",
            "accuracy": float(np.mean(cv_scores)),
            "accuracy_std": float(np.std(cv_scores)),
            "samples": len(X),
            "feature_importance": self._feature_importance,
        }

    def _fit_sklearn_fallback(self, X: np.ndarray, y: np.ndarray) -> dict[str, Any]:
        """Fallback to sklearn LogisticRegression if XGBoost/LightGBM unavailable."""
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import cross_val_score
        from sklearn.preprocessing import StandardScaler

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        self._model = LogisticRegression(random_state=42, max_iter=1000)
        self._model.fit(X_scaled, y)

        cv_scores = cross_val_score(
            self._model, X_scaled, y, cv=min(5, len(X) // 5), scoring="accuracy"
        )

        coefs = np.abs(self._model.coef_[0])
        self._feature_importance = dict(
            zip(FEATURE_COLUMNS, (coefs / coefs.sum()).tolist(), strict=False)
        )

        # Wrap to handle scaling in predict
        original_model = self._model
        self._model = _ScaledModel(original_model, scaler)

        return {
            "status": "trained",
            "model": "logistic_regression_fallback",
            "accuracy": float(np.mean(cv_scores)),
            "accuracy_std": float(np.std(cv_scores)),
            "samples": len(X),
            "feature_importance": self._feature_importance,
        }

    def _save_model(self) -> None:
        """Persist trained model to disk."""
        try:
            self._model_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._model_path, "wb") as f:
                pickle.dump(
                    {
                        "model": self._model,
                        "feature_importance": self._feature_importance,
                        "training_samples": self._training_samples,
                        "trained_at": time.time(),
                    },
                    f,
                )
            logger.info("ML scorer model saved to %s", self._model_path)
        except Exception:
            logger.warning("Failed to save ML scorer model", exc_info=True)

    def load_model(self) -> bool:
        """Load a previously trained model from disk.

        Returns:
            True if model loaded successfully.
        """
        try:
            if not self._model_path.exists():
                return False
            with open(self._model_path, "rb") as f:
                data = pickle.load(f)
            self._model = data["model"]
            self._feature_importance = data.get("feature_importance", {})
            self._training_samples = data.get("training_samples", 0)
            self._last_train_time = data.get("trained_at", 0)
            logger.info("ML scorer model loaded (%d samples)", self._training_samples)
            return True
        except Exception:
            logger.warning("Failed to load ML scorer model", exc_info=True)
            return False

    @staticmethod
    def _compute_bb_position(meta: dict[str, Any]) -> float:
        """Compute position within Bollinger Bands (0=lower, 1=upper)."""
        upper = meta.get("bb_upper", 0)
        lower = meta.get("bb_lower", 0)
        price = meta.get("entry_price", meta.get("price", 0))
        if upper and lower and upper != lower:
            return max(0.0, min(1.0, (price - lower) / (upper - lower)))
        return 0.5

    @staticmethod
    def _compute_atr_pct(meta: dict[str, Any]) -> float:
        """Compute ATR as percentage of price."""
        atr = meta.get("atr", 0)
        price = meta.get("entry_price", meta.get("price", 0))
        if price and price > 0:
            return atr / price
        return 0.0

    @staticmethod
    def _extract_hour(trade: Any) -> float:
        """Extract hour of day from trade timestamp."""
        ts = getattr(trade, "created_at", None) or getattr(trade, "timestamp", None)
        if ts and hasattr(ts, "hour"):
            return float(ts.hour)
        return 12.0  # default

    @staticmethod
    def _extract_dow(trade: Any) -> float:
        """Extract day of week from trade timestamp."""
        ts = getattr(trade, "created_at", None) or getattr(trade, "timestamp", None)
        if ts and hasattr(ts, "weekday"):
            return float(ts.weekday())
        return 3.0  # default (Wednesday)


class _ScaledModel:
    """Wrapper to apply StandardScaler before prediction."""

    def __init__(self, model: Any, scaler: Any) -> None:
        self._model = model
        self._scaler = scaler

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self._model.predict(self._scaler.transform(X))

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return self._model.predict_proba(self._scaler.transform(X))
