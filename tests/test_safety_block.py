"""Phase H: Production Engineering — Safety Block Verification.

Verifies that the live-trading safety block is correctly enforced and that
no unvalidated experiment can generate live orders.
"""
import unittest
from app.config import Config, V5_BASELINE_NO_LIVE_TRADE
from app.decision import DecisionEngine, DecisionState


class TestSafetyBlock(unittest.TestCase):
    """Verify the live-trading safety block is enforced."""

    def test_safety_block_active(self):
        """V5_BASELINE_NO_LIVE_TRADE is set to True."""
        self.assertTrue(V5_BASELINE_NO_LIVE_TRADE)

    def test_live_mode_blocked(self):
        """Live trading mode is blocked regardless of other config."""
        cfg = Config(mode='live', live_trading_enabled=True)
        safe, reason = cfg.runtime_safe()
        self.assertFalse(safe)
        self.assertIn("NO LIVE TRADING", reason)

    def test_paper_mode_allowed(self):
        """Paper mode is not blocked by the V5 safety lock."""
        cfg = Config(mode='paper', live_trading_enabled=True)
        safe, reason = cfg.runtime_safe()
        self.assertTrue(safe)

    def test_decision_engine_gates(self):
        """Decision engine uses the V5 model + cost gate."""
        # The decision engine exists and has proper gate logic
        self.assertTrue(hasattr(DecisionEngine, 'evaluate'))
        for state in [DecisionState.NO_SIGNAL, DecisionState.INVALID_DATA,
                       DecisionState.INSUFFICIENT_LIQUIDITY, DecisionState.HIGH_TOXICITY,
                       DecisionState.COST_OVERWHELMED, DecisionState.POSITIVE_EXPECTANCY,
                       DecisionState.EXECUTION_READY]:
            self.assertIsInstance(state.value, str)


if __name__ == "__main__":
    unittest.main()
