"""AI-powered Expiry Risk & Redistribution Agent.

Predicts which inventory will likely expire before it can be sold, then
optimizes transfers of that at-risk stock to locations where forecast
demand can absorb it before expiry.
"""

__version__ = "0.1.0"

from expiry_agent.models import SKU_BATCH, Transfer, TransferPlan
from expiry_agent.pipeline import run_pipeline

__all__ = [
    "SKU_BATCH",
    "Transfer",
    "TransferPlan",
    "run_pipeline",
    "__version__",
]
