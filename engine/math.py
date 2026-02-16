import numpy as np
import logging

logger = logging.getLogger(__name__)


class MarketMath:
    @staticmethod
    def bregman_divergence(p: np.ndarray, q: np.ndarray) -> float:
        """
        Calculate Bregman Divergence D(p || q).
        For prediction markets (Log-Linear Scoring Rule), this is effectively generalized KL Divergence.
        D(p || q) = sum(p_i * log(p_i / q_i) - p_i + q_i)
        
        Args:
            p: The valid probability vector (mu).
            q: The current market price vector (theta).
            
        Returns:
            The divergence value (scalar). Always >= 0.
        """
        epsilon = 1e-9
        p = np.clip(p, epsilon, 1.0 - epsilon)
        q = np.clip(q, epsilon, 1.0 - epsilon)
        
        result = np.sum(p * np.log(p / q) - p + q)
        
        # Numerical safety: divergence should be non-negative
        return max(0.0, float(result))

    @staticmethod
    def frank_wolfe_projection(current_prices: np.ndarray, valid_outcomes: np.ndarray, 
                                max_iter: int = 200, tol: float = 1e-7) -> np.ndarray:
        """
        Find the closest point mu* in the marginal polytope (Convex Hull of valid_outcomes) 
        to the current_prices theta using the Frank-Wolfe algorithm.
        
        Minimizes D(mu || theta) subject to mu in conv(valid_outcomes).
        
        Args:
            current_prices: Vector of current market prices (theta). Shape: (n_dim,)
            valid_outcomes: Matrix of valid outcome vectors. Shape: (n_outcomes, n_dim)
            max_iter: Maximum iterations.
            tol: Convergence tolerance.
            
        Returns:
            mu_star: The optimized arbitrage-free probability vector.
        """
        if valid_outcomes.shape[0] == 0:
            logger.warning("No valid outcomes provided to Frank-Wolfe.")
            return current_prices.copy()
        
        n_dim = current_prices.shape[0]
        epsilon = 1e-9
        
        # Initialization: uniform average of valid outcomes (centered start)
        mu = np.mean(valid_outcomes, axis=0).astype(float)
        
        # Ensure mu is in valid range
        mu = np.clip(mu, epsilon, 1.0 - epsilon)
        
        for t in range(max_iter):
            # Gradient of D(mu || theta) w.r.t. mu: log(mu) - log(theta)
            mu_safe = np.clip(mu, epsilon, 1.0 - epsilon)
            theta_safe = np.clip(current_prices, epsilon, 1.0 - epsilon)
            
            grad = np.log(mu_safe) - np.log(theta_safe)
            
            # Linear Oracle: find vertex s that minimizes <s, grad>
            dots = valid_outcomes @ grad
            best_idx = np.argmin(dots)
            s_t = valid_outcomes[best_idx].astype(float)
            
            # Convergence check (Duality Gap)
            duality_gap = np.dot(mu - s_t, grad)
            if duality_gap < tol:
                break
                
            # Step size: standard diminishing step
            gamma = 2.0 / (t + 2.0)
            
            # Update
            mu = (1 - gamma) * mu + gamma * s_t
            
            # Keep in valid range
            mu = np.clip(mu, epsilon, 1.0 - epsilon)
            
        return mu

    @staticmethod
    def calculate_profit(current_prices: np.ndarray, mu_star: np.ndarray) -> float:
        """
        The theoretical maximum arbitrage profit is D(mu_star || theta).
        This represents the "distance" between market prices and the nearest 
        consistent probability distribution.
        """
        return MarketMath.bregman_divergence(mu_star, current_prices)
    
    @staticmethod
    def estimate_dollar_profit(current_prices: np.ndarray, mu_star: np.ndarray, 
                                position_size: float, fee_rate: float = 0.02) -> float:
        """
        Estimate actual dollar profit after fees.
        
        Args:
            current_prices: Current market prices.
            mu_star: Fair value prices.
            position_size: Dollar amount per leg.
            fee_rate: Exchange fee rate (default 2%).
            
        Returns:
            Estimated dollar profit after fees.
        """
        raw_profit = MarketMath.calculate_profit(current_prices, mu_star)
        gross_dollar = raw_profit * position_size
        fees = position_size * fee_rate * 2  # Fee on both entry and exit
        return gross_dollar - fees
