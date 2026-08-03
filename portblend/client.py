"""
portblend.client

High-level Python client interface for PortBlend API endpoints.
Provides full type annotations for IDE autocomplete in VS Code, PyCharm, and Cursor.
"""

from pathlib import Path
from typing import Union, Dict, Any, Optional
import requests
import pandas as pd

from portblend.transform import DataTransformer
from portblend.models import BlendResult
from portblend.logging import get_logger, log_insight


class PortBlendClient:
    """
    Client interface for interacting with the PortBlend API.

    Parameters:
        api_key (str): Your PortBlend developer API token (`pb_live_...`).
        base_url (str): API base endpoint URL (default: "https://app.portblend.com/api").
        timeout (float): Request timeout in seconds (default: 30.0).

    Examples:
        >>> from portblend import PortBlendClient
        >>> client = PortBlendClient(api_key="pb_live_abcdef1234567890")
        >>> df_corr = client.correlate("strategies.csv")
        >>> result = client.blend("strategies.csv", target="min_drawdown")
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://app.portblend.com/api",
        timeout: float = 120.0,
        guest_mode: bool = False,
    ):
        if not api_key and not guest_mode:
            raise ValueError("api_key cannot be empty.")

        self.api_key = api_key.strip() if api_key else ""
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.guest_mode = guest_mode

        self.session = requests.Session()
        headers = {"User-Agent": "PortBlend-Python-SDK/0.1.0"}
        if not guest_mode and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            headers["Content-Type"] = "application/json"
        self.session.headers.update(headers)
        self.logger = get_logger()

    def correlate(
        self,
        data: Union[str, Path, pd.DataFrame, Dict[str, Any]],
    ) -> pd.DataFrame:
        """
        Computes pairwise Pearson return correlation matrix across input strategies.

        Parameters:
            data: Filepath to CSV/Excel, pandas DataFrame, raw string, or payload dict.

        Returns:
            pandas.DataFrame: Color-coded or structured correlation matrix table.
        """
        self.logger.info("Validating local strategy NAV dataset...")
        payload = DataTransformer.transform(data)

        strategy_count = len(payload["series_ids"])
        self.logger.info(
            f"Connected to PortBlend API ({self.base_url}). "
            f"Processing {strategy_count} strategies..."
        )

        url = f"{self.base_url}/v1/correlate"
        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
            if resp.status_code == 404:
                # Fallback URL if version prefix omitted
                resp = self.session.post(f"{self.base_url}/correlate", json=payload, timeout=self.timeout)
        except requests.RequestException as e:
            raise RuntimeError(f"Network error contacting PortBlend API: {e}")

        if resp.status_code == 429:
            retry = resp.headers.get("Retry-After", "60")
            raise RuntimeError(f"API Rate Limit Exceeded (HTTP 429). Please retry after {retry} seconds.")

        if resp.status_code != 200:
            err_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            msg = err_data.get("detail", {}).get("error", resp.text) if isinstance(err_data.get("detail"), dict) else resp.text
            raise RuntimeError(f"PortBlend API error (HTTP {resp.status_code}): {msg}")

        res_json = resp.json()
        raw_cm = res_json.get("correlation_matrix", {})

        if res_json.get("correlation_insight"):
            log_insight(res_json["correlation_insight"])

        return pd.DataFrame(raw_cm)

    def blend(
        self,
        data: Union[str, Path, pd.DataFrame, Dict[str, Any]],
        target: str = "protection",
        allow_cash: bool = True,
        rebalance_frequency: str = "monthly",
    ) -> BlendResult:
        """
        Executes portfolio strategy weight optimization across 5 target choices.

        Parameters:
            data: Filepath to CSV/Excel, pandas DataFrame, raw string, or payload dict.
            target: Optimization target ("protection" | "efficiency" | "recovery" | "stability" | "downside_safety").
            allow_cash: If True (default), sum(w) <= 1.0 (remainder synthetic CASH). If False, 100% invested.
            rebalance_frequency: Rebalance schedule ("monthly" | "weekly" | "quarterly" | "yearly").

        Returns:
            BlendResult: Container holding optimal weights, metrics, and correlation matrix.
        """
        self.logger.info("Validating local strategy NAV dataset...")
        parsed_payload = DataTransformer.transform(data)
        series_ids = parsed_payload["series_ids"]

        # Default equal weights initial allocation
        equal_w = round(100.0 / len(series_ids), 2)
        weights = {s: equal_w for s in series_ids}

        blend_payload = {
            "series_ids": series_ids,
            "series_data": parsed_payload["series_data"],
            "weights": weights,
            "allowed_rebalancing": [rebalance_frequency],
            "target": target,
            "allow_cash": allow_cash,
            "enable_weekly": True,
            "enable_daily": True,
            "enable_contribution": True,
            "enable_dominance": True,
        }

        self.logger.info(
            f"Executing portfolio optimization on PortBlend API ({self.base_url}). Target: {target}..."
        )

        url = f"{self.base_url}/v1/blend"
        try:
            resp = self.session.post(url, json=blend_payload, timeout=self.timeout)
            if resp.status_code == 404:
                resp = self.session.post(f"{self.base_url}/sii", json=blend_payload, timeout=self.timeout)
        except requests.RequestException as e:
            raise RuntimeError(f"Network error contacting PortBlend API: {e}")

        if resp.status_code == 429:
            retry = resp.headers.get("Retry-After", "60")
            raise RuntimeError(f"API Rate Limit Exceeded (HTTP 429). Please retry after {retry} seconds.")

        if resp.status_code != 200:
            err_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            msg = err_data.get("detail", {}).get("error", resp.text) if isinstance(err_data.get("detail"), dict) else resp.text
            raise RuntimeError(f"PortBlend API error (HTTP {resp.status_code}): {msg}")

        result_data = resp.json()
        result_obj = BlendResult(result_data)

        if result_obj.correlation_insight:
            log_insight(result_obj.correlation_insight)

        return result_obj
