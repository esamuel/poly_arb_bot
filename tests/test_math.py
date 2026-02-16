import unittest
import numpy as np
import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from poly_arb_bot.engine.math import MarketMath


class TestMarketMath(unittest.TestCase):
    def test_bregman_divergence_zero(self):
        """Identical distributions should have zero divergence."""
        p = np.array([0.5, 0.5])
        q = np.array([0.5, 0.5])
        div = MarketMath.bregman_divergence(p, q)
        self.assertAlmostEqual(div, 0.0, places=8)

    def test_bregman_divergence_nonzero(self):
        """Different distributions should have positive divergence."""
        p = np.array([0.6, 0.4])
        q = np.array([0.5, 0.5])
        expected = 0.6 * np.log(1.2) + 0.4 * np.log(0.8)
        div = MarketMath.bregman_divergence(p, q)
        self.assertAlmostEqual(div, expected, places=5)
    
    def test_bregman_divergence_always_nonnegative(self):
        """Bregman divergence should always be >= 0."""
        rng = np.random.default_rng(42)
        for _ in range(100):
            p = rng.random(4)
            q = rng.random(4)
            div = MarketMath.bregman_divergence(p, q)
            self.assertGreaterEqual(div, 0.0)

    def test_frank_wolfe_simple_arbitrage(self):
        """Test: A=YES implies B=YES. Prices violate this -> optimizer fixes it."""
        # Dependency: A=YES implies B=YES.
        # Valid outcomes: (Y,Y), (N,Y), (N,N). Impossible: (Y,N).
        # Vector format: [A_Y, A_N, B_Y, B_N]
        valid_outcomes = np.array([
            [1, 0, 1, 0],  # Y, Y
            [0, 1, 1, 0],  # N, Y
            [0, 1, 0, 1]   # N, N
        ])
        
        # Prices imply A_Y = 0.6, B_Y = 0.4 -- violates P(A=Y) <= P(B=Y)
        current_prices = np.array([0.6, 0.4, 0.4, 0.6])
        
        mu_star = MarketMath.frank_wolfe_projection(current_prices, valid_outcomes)
        
        p_a_yes = mu_star[0]
        p_b_yes = mu_star[2]
        
        # The optimizer should enforce P(A=Y) <= P(B=Y)
        self.assertLessEqual(p_a_yes - p_b_yes, 0.01)
    
    def test_frank_wolfe_no_arb_when_consistent(self):
        """When prices are already consistent, profit should be near zero."""
        valid_outcomes = np.array([
            [1, 0, 1, 0],
            [0, 1, 1, 0],
            [0, 1, 0, 1]
        ])
        
        # Consistent prices: A_Y=0.3, A_N=0.7, B_Y=0.8, B_N=0.2
        # P(A=Y)=0.3 <= P(B=Y)=0.8 -> consistent
        current_prices = np.array([0.3, 0.7, 0.8, 0.2])
        
        mu_star = MarketMath.frank_wolfe_projection(current_prices, valid_outcomes)
        profit = MarketMath.calculate_profit(current_prices, mu_star)
        
        # Profit should be very small (near zero) for consistent prices
        self.assertLess(profit, 0.01)

    def test_estimate_dollar_profit(self):
        """Dollar profit estimation should account for fees."""
        current_prices = np.array([0.6, 0.4, 0.4, 0.6])
        mu_star = np.array([0.5, 0.5, 0.5, 0.5])
        
        raw_profit = MarketMath.calculate_profit(current_prices, mu_star)
        dollar_profit = MarketMath.estimate_dollar_profit(current_prices, mu_star, position_size=100)
        
        # Dollar profit should be less than raw * position due to fees
        self.assertLess(dollar_profit, raw_profit * 100)


if __name__ == '__main__':
    unittest.main()
