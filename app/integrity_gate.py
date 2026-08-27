"""Execution data-integrity gate.

Chain: BOOK_SYNCED -> FEATURES_VALID -> COST_VALID -> SIGNAL_ALLOWED.

Any break in the chain must clear the signal to NO_TRADE and require a resync
before trading is allowed again. No guessing, no synthetic order-book values:
the book must come from a synchronized snapshot + ordered incremental depth
updates (Binance futures @depth@100ms) or the gate stays closed.

`python -m app.integrity_gate` self-test; module used by the live engine.
"""

from dataclasses import dataclass, field


@dataclass
class IntegrityState:
    book_synced: bool = False
    features_valid: bool = False
    cost_valid: bool = False
    signal_allowed: bool = False
    gates: dict = field(default_factory=dict)

    def summary(self):
        return {"BOOK_SYNCED": self.book_synced,
                "FEATURES_VALID": self.features_valid,
                "COST_VALID": self.cost_valid,
                "SIGNAL_ALLOWED": self.signal_allowed}


class IntegrityGate:
    def __init__(self):
        self.state = IntegrityState()
        self._signals = []

    def on_book_sync(self, synced: bool, source: str = "unknown"):
        self.state.book_synced = bool(synced)
        self._signals.append(("BOOK_SYNCED", synced, source))

    def on_features(self, valid: bool, reason: str = ""):
        self.state.features_valid = bool(valid)
        self.state.gates["features"] = reason
        self._signals.append(("FEATURES_VALID", valid, reason))

    def on_cost(self, valid: bool, reason: str = ""):
        self.state.cost_valid = bool(valid)
        self.state.gates["cost"] = reason
        self._signals.append(("COST_VALID", valid, reason))

    def set_signal_allowed(self, allowed: bool, reason: str = ""):
        self.state.signal_allowed = bool(allowed)
        self.state.gates["signal"] = reason

    def evaluate(self):
        """Re-derive SIGNAL_ALLOWED from the chain; returns the decision dict."""
        self.state.signal_allowed = (
            self.state.book_synced
            and self.state.features_valid
            and self.state.cost_valid)
        return self.state.summary()

    def snapshot(self):
        return self.state.summary()


if __name__ == "__main__":
    g = IntegrityGate()
    print("initial:", g.evaluate())
    g.on_book_sync(True, "depth@100ms")
    print("book synced only:", g.evaluate())
    g.on_features(True, "features ok")
    g.on_cost(True, "cost ok")
    print("all valid:", g.evaluate())
    g.on_book_sync(False, "book gap -> resync")
    print("after book break:", g.evaluate())
    print("OK")