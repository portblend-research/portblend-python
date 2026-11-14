# PortBlend Python SDK (`portblend`)

[![PyPI version](https://img.shields.io/badge/pypi-v0.2.0-blue.svg)](https://pypi.org/project/portblend/)
[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/portblend-research/portblend-python/blob/main/doc/examples/01_quickstart_portblend.ipynb)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

Official Python SDK and Command-Line Interface (`portblend`) for multi-series return correlation matrix calculation, constrained SLSQP weighting simulation, and quantitative drawdown analysis.

---

## 1. Quickstart — Python SDK Tutorial

### Installation
```bash
pip install portblend
```

### Code Example: Compute Correlation Matrix & Calculate Series Weights
```python
from portblend import PortBlendClient
import pandas as pd

# 1. Initialize PortBlend Client with Developer API Key
client = PortBlendClient(
    api_key="pb_live_abcdef1234567890",
    base_url="https://app.portblend.com/api"  # Or http://localhost:8000/api
)

# 2. Compute Pairwise Return Correlation Matrix
# Accepts CSV, TSV, Excel file path, pandas.DataFrame, or raw CSV text string
df_corr = client.correlate(data="path/to/series_navs.csv")
print("Pairwise Return Correlation Matrix:")
print(df_corr)

# 3. Compute Constrained Weights for Drawdown Protection (SLSQP)
result = client.blend(
    data="path/to/series_navs.csv",
    target="protection",  # "protection" | "efficiency" | "recovery" | "stability" | "downside_safety" | "risk_balance" | "buffered"
    allow_cash=True       # Allow allocation to synthetic CASH buffer
)

# 4. Print Educational Quantitative Summary
result.summary()

# 5. Access Calculated Weights Dictionary
print("Calculated Weights (%):", result.weights)
```

---

## 2. Optimization Targets

- `protection` (min_drawdown) — Cuts maximum portfolio loss depth to the absolute minimum.
- `efficiency` (max_sharpe) — Maximizes overall risk-adjusted return.
- `recovery` (max_calmar) — Maximizes return relative to maximum peak-to-trough drawdown.
- `stability` (min_volatility) — Minimizes daily portfolio price swings and variance.
- `downside_safety` (max_sortino) — Ignores upside gains, penalizing only negative losses.
- `risk_balance` (balanced_protection) — Balances drawdown and return dynamically using a scaled utility model.
- `buffered` (buffered_allocation) — Optimizes strategy blend first, then applies a cash buffer of up to 50%.

---

## 3. Quickstart — Command-Line Interface (CLI) Tutorial

### Login & Save API Key
```bash
portblend login --key pb_live_abcdef1234567890
```

### Calculate Strategy Correlation Matrix
```bash
portblend correlate --file strategies.csv
```

### Run Portfolio Weight Optimization
```bash
# Target Protection (min_drawdown) with CASH buffer allowed
portblend optimize --file strategies.csv --target protection

# Target Efficiency (max_sharpe) with 100% strategy allocation (no CASH)
portblend optimize --file strategies.csv --target efficiency --no-cash
```

---

> **Scope**: PortBlend is an analytical calculation tool to study historical portfolio drawdowns and asset correlation. All charts and blend simulations are mathematical models based on data entered by the user, provided for educational and research purposes.
