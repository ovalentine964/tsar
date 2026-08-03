"""TSAR — Trading Super Agent Regime.

Knowledge store implementations for the TSAR trading system.
"""

from src.knowledge.db_pool import SQLitePool, get_pool
from src.knowledge.fts_search import MemoryRecall, SearchResult, format_fts_query
from src.knowledge.lesson_archive import LessonArchive
from src.knowledge.pattern_library import PatternLibrary
from src.knowledge.regime_state import (
    RegimeGraphSnapshot,
    RegimeStateStore,
    RegimeTransitionEdge,
    TemporalRegimeGraph,
)
from src.knowledge.strategy_genomes import StrategyGenomes
from src.knowledge.trade_memory import TradeMemory

# ChromaDB optional import (with numpy fallback)
try:
    from src.knowledge.chromadb_store import ChromaVectorStore, VectorSearchResult, is_chromadb_available
except ImportError:
    ChromaVectorStore = None  # type: ignore[assignment,misc]
    VectorSearchResult = None  # type: ignore[assignment,misc]
    is_chromadb_available = None  # type: ignore[assignment]

# Lightweight vector store (always available with numpy)
try:
    from src.knowledge.lightweight_vector_store import LightweightVectorStore
except ImportError:
    LightweightVectorStore = None  # type: ignore[assignment,misc]

# Knowledge graph
try:
    from src.knowledge.knowledge_graph import GraphEdge, GraphNode, GraphPath, KnowledgeGraph
except ImportError:
    KnowledgeGraph = None  # type: ignore[assignment,misc]
    GraphNode = None  # type: ignore[assignment,misc]
    GraphEdge = None  # type: ignore[assignment,misc]
    GraphPath = None  # type: ignore[assignment,misc]

# Heavy imports (require ccxt, openai, etc.) — wrapped in try/except so
# the core knowledge stores remain importable without those dependencies.
try:
    from src.knowledge.genome_mutator import GenomeMutator, MutationProposal, MutatorConfig
    from src.knowledge.rule_validator import RuleValidator, ValidatedRule
    from src.knowledge.shadow_extractor import ExtractionResult, ShadowExtractor, TradingRule
except ImportError:
    ShadowExtractor = None  # type: ignore[assignment,misc]
    TradingRule = None  # type: ignore[assignment,misc]
    ExtractionResult = None  # type: ignore[assignment,misc]
    RuleValidator = None  # type: ignore[assignment,misc]
    ValidatedRule = None  # type: ignore[assignment,misc]
    GenomeMutator = None  # type: ignore[assignment,misc]
    MutationProposal = None  # type: ignore[assignment,misc]
    MutatorConfig = None  # type: ignore[assignment,misc]

__all__ = [
    "SQLitePool",
    "get_pool",
    "TradeMemory",
    "StrategyGenomes",
    "RegimeStateStore",
    "TemporalRegimeGraph",
    "RegimeTransitionEdge",
    "RegimeGraphSnapshot",
    "PatternLibrary",
    "LessonArchive",
    "MemoryRecall",
    "SearchResult",
    "format_fts_query",
    "ChromaVectorStore",
    "VectorSearchResult",
    "is_chromadb_available",
    "LightweightVectorStore",
    "KnowledgeGraph",
    "GraphNode",
    "GraphEdge",
    "GraphPath",
    "ShadowExtractor",
    "TradingRule",
    "ExtractionResult",
    "RuleValidator",
    "ValidatedRule",
    "GenomeMutator",
    "MutationProposal",
    "MutatorConfig",
]
