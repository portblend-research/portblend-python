"""
portblend.models

Data models and container objects for PortBlend SDK results.
"""

from typing import Dict, Any, Optional
import pandas as pd
from tabulate import tabulate

from portblend.logging import log_insight


class BlendResult:
    """
    Result container returned by `PortBlendClient.blend()`.

    Provides convenient properties for weights, performance metrics,
    correlation matrix as pandas.DataFrame, and educational summary output.
    """

    def __init__(self, raw_response: Dict[str, Any]):
        self.raw_response = raw_response
        self.weights: Dict[str, float] = raw_response.get("weights", {})
        self.metrics: Dict[str, float] = raw_response.get("metrics", {})
        self.correlation_insight: str = raw_response.get("correlation_insight", "")

        # Convert correlation_matrix dict to pandas DataFrame automatically
        raw_cm = raw_response.get("correlation_matrix", {})
        if raw_cm:
            self.correlation_matrix: pd.DataFrame = pd.DataFrame(raw_cm)
        else:
            self.correlation_matrix: pd.DataFrame = pd.DataFrame()

    @property
    def max_drawdown(self) -> float:
        """Maximum portfolio drawdown percentage (e.g. -0.062 for -6.2%)."""
        return self.metrics.get("max_drawdown", 0.0)

    @property
    def annual_return(self) -> float:
        """Annualized portfolio return percentage."""
        return self.metrics.get("annual_return", 0.0)

    @property
    def sharpe_ratio(self) -> float:
        """Portfolio Sharpe Ratio."""
        return self.metrics.get("sharpe_ratio", 0.0)

    @property
    def drawdown_reduction(self) -> float:
        """Percentage reduction in portfolio drawdown depth due to diversification."""
        return self.metrics.get("drawdown_reduction_pct", 0.0)

    def summary(self) -> None:
        """
        Prints a clean, educational synthesis of portfolio blending results in the terminal.
        """
        print("\n" + "=" * 70)
        print("  PORTBLEND — Strategy Blending & Optimization Summary")
        print("=" * 70)

        # 1. Weights Table
        print("\nOptimal Strategy Allocations:")
        w_rows = [[strat, f"{w:.1f}%"] for strat, w in self.weights.items()]
        print(tabulate(w_rows, headers=["Strategy", "Weight"], tablefmt="grid"))

        # 2. Performance Metrics
        print("\nPortfolio Performance Metrics:")
        m_rows = []
        if "annual_return" in self.metrics:
            v = self.metrics['annual_return']
            val_str = f"{v:.2f}%" if abs(v) > 1.0 else f"{v * 100:.2f}%"
            m_rows.append(["Annualized Return", val_str])
        if "max_drawdown" in self.metrics:
            v = self.metrics['max_drawdown']
            val_str = f"{v:.2f}%" if abs(v) > 1.0 else f"{v * 100:.2f}%"
            m_rows.append(["Max Drawdown Depth", val_str])
        if "sharpe_ratio" in self.metrics:
            m_rows.append(["Sharpe Ratio", f"{self.metrics['sharpe_ratio']:.2f}"])
        if "drawdown_reduction_pct" in self.metrics:
            v = self.metrics['drawdown_reduction_pct']
            val_str = f"{v:.1f}%" if abs(v) > 1.0 else f"{v * 100:.1f}%"
            m_rows.append(["Drawdown Reduction", val_str])

        if m_rows:
            print(tabulate(m_rows, headers=["Metric", "Value"], tablefmt="grid"))

        # 3. Correlation Insight Log
        if self.correlation_insight:
            print("\nQuantitative Risk Insight:")
            log_insight(self.correlation_insight)

        print("=" * 70 + "\n")
