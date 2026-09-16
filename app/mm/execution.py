"""V20 compatibility boundary for the authoritative execution lifecycle.

The canonical lifecycle implementation remains in :mod:`app.execution`.
This module re-exports the actual lifecycle types so V20 production controls
have one execution state implementation and do not fork lifecycle semantics.
"""

from app.execution import (  # noqa: F401
    ExecutionResult,
    LiveExecution,
    OrderStateManager,
    PaperExecution,
    SimulatedExchange,
)

__all__ = [
    "ExecutionResult",
    "LiveExecution",
    "OrderStateManager",
    "PaperExecution",
    "SimulatedExchange",
]
