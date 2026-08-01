"""
Python backends — Day1 implementations using pure Python libraries.

These are the default backends for all interfaces:
  - CcxtGateway: exchange connectivity via ccxt REST API
  - CcxtExecEngine: order execution via ccxt REST API
  - PandasTAEngine: technical indicators via pandas-ta
  - PythonRiskEngine: deterministic risk rules
  - OllamaProvider: local LLM via Ollama
  - DeepSeekProvider: cloud LLM via DeepSeek API
  - OpenAIProvider: cloud LLM via OpenAI API
"""

from src.backends.python.ccxt_exec_engine import CcxtExecEngine
from src.backends.python.ccxt_gateway import CcxtGateway
from src.backends.python.deepseek_provider import DeepSeekProvider
from src.backends.python.ollama_provider import OllamaProvider
from src.backends.python.openai_provider import OpenAIProvider
from src.backends.python.pandas_ta_engine import PandasTAEngine
from src.backends.python.paper_execution_engine import PaperExecutionEngine
from src.backends.python.python_risk_engine import PythonRiskEngine

__all__: list[str] = [
    "CcxtGateway",
    "CcxtExecEngine",
    "DeepSeekProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "PandasTAEngine",
    "PaperExecutionEngine",
    "PythonRiskEngine",
]
