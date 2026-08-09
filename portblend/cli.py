"""
portblend.cli

Command-Line Interface (CLI) for PortBlend.
Executable entrypoint registered via `pyproject.toml` console_scripts: `portblend`.

Commands:
  login      Save API key locally to ~/.portblend/config.json
  logout     Remove saved API key from ~/.portblend/config.json
  drawdown   Analyze a single strategy NAV series — drawdown dynamics (no login required)
  correlate  Compute pairwise strategy correlation matrix and ASCII heatmap table
  analyze    Execute SLSQP weight optimization to minimize drawdown depth
  demo       Interactive zero-key offline walkthrough on built-in sample dataset
  status     Check API connection health and rate limit quota status
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any

from tabulate import tabulate
from portblend.client import PortBlendClient
from portblend.transform import DataTransformer
from portblend.logging import setup_logger, log_insight

CONFIG_DIR = Path.home() / ".portblend"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load_config() -> Dict[str, Any]:
    cfg_path = Path(CONFIG_FILE)
    if cfg_path.is_file():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_config(config_data: Dict[str, Any]) -> None:
    cfg_dir = Path(CONFIG_DIR)
    cfg_path = Path(CONFIG_FILE)
    cfg_dir.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)



def get_stored_api_key() -> Optional[str]:
    # Environment variable takes precedence over config file
    env_key = os.environ.get("PORTBLEND_API_KEY")
    if env_key:
        return env_key
    cfg = load_config()
    return cfg.get("api_key")


def handle_login(args: argparse.Namespace) -> None:
    key = args.key.strip()
    if not key:
        print("Error: API Key cannot be empty.", file=sys.stderr)
        sys.exit(1)

    cfg = load_config()
    cfg["api_key"] = key
    save_config(cfg)
    print(f"[PORTBLEND] API Key successfully saved to {CONFIG_FILE}")


def handle_logout(args: argparse.Namespace) -> None:
    cfg_path = Path(CONFIG_FILE)
    if not cfg_path.is_file():
        print("[PORTBLEND] Already logged out — no saved API key found.")
        return

    cfg = load_config()
    if "api_key" not in cfg:
        print("[PORTBLEND] Already logged out — no API key was stored.")
        return

    del cfg["api_key"]
    save_config(cfg)
    print(f"[PORTBLEND] Logged out. API key removed from {CONFIG_FILE}")
    print("[PORTBLEND] Run 'portblend login --key <API_KEY>' to log back in.")


def handle_correlate(args: argparse.Namespace) -> None:
    api_key = get_stored_api_key()
    if not api_key:
        print("Error: No API Key found. Run 'portblend login --key <API_KEY>' or set PORTBLEND_API_KEY env var.", file=sys.stderr)
        sys.exit(1)

    client = PortBlendClient(api_key=api_key, base_url=args.url)
    try:
        df_corr = client.correlate(data=args.file)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(df_corr.to_json(indent=2))
    else:
        print("\nPairwise Strategy Correlation Matrix:")
        headers = ["Strategy"] + list(df_corr.columns)
        table_rows = []
        for row_label, row_data in df_corr.iterrows():
            row = [str(row_label)]
            for col in df_corr.columns:
                val = row_data[col]
                row.append(f"{val:+.2f}")
            table_rows.append(row)
        print(tabulate(table_rows, headers=headers, tablefmt="grid"))


def handle_drawdown(args: argparse.Namespace) -> None:
    """
    Drawdown Dynamics — single strategy analysis. Calls the public /api/dcd
    endpoint. No API key required (matches website guest-user behaviour).
    """
    import requests

    transformer = DataTransformer()
    payload_dict = DataTransformer.transform(args.file)

    # DCD endpoint expects a single series — take the first one
    series_ids = payload_dict["series_ids"]
    series_data = payload_dict["series_data"]

    if len(series_ids) == 0:
        print("Error: No strategy series found in the file.", file=sys.stderr)
        sys.exit(1)

    if len(series_ids) > 1:
        print(f"Note: File contains {len(series_ids)} strategies. Analyzing '{series_ids[0]}' only.")
        print("      For multi-strategy portfolio analysis use: portblend analyze")

    series_id = series_ids[0]
    raw_points = series_data[series_id]

    # Convert to DCD request format: [{"date": ..., "nav": ...}, ...]
    dcd_points = [{"date": str(p[0]), "nav": float(p[1])} for p in raw_points]

    dcd_payload = {
        "series_id": series_id,
        "series_data": dcd_points,
        "enable_weekly": True,
        "enable_daily": False,
    }

    base_url = args.url.rstrip("/")
    url = f"{base_url}/dcd"

    try:
        resp = requests.post(url, json=dcd_payload, timeout=60)
    except requests.RequestException as e:
        print(f"Error: Network error contacting PortBlend API: {e}", file=sys.stderr)
        sys.exit(1)

    if resp.status_code != 200:
        err = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        msg = err.get("detail", resp.text)
        print(f"Error: API returned HTTP {resp.status_code}: {msg}", file=sys.stderr)
        sys.exit(1)

    data = resp.json()

    if args.json:
        print(json.dumps(data, indent=2))
        return

    s = data.get("summary", {})
    episodes = data.get("episodes", [])
    period_stats = data.get("period_stats", {})

    print("\n" + "=" * 70)
    print(f"  PORTBLEND — Drawdown Dynamics: {series_id}")
    print("=" * 70)

    # Summary metrics
    print("\nStrategy Performance Summary:")
    summary_rows = [
        ["Total Return",       f"{s.get('total_return_pct', 0):.2f}%"],
        ["CAGR",               f"{s.get('cagr_pct', 0):.2f}%"],
        ["Max Drawdown",       f"{s.get('max_drawdown_pct', 0):.2f}%"],
        ["Avg Drawdown",       f"{s.get('avg_drawdown_pct', 0):.2f}%"],
        ["Max DD Duration",    f"{s.get('max_dd_duration', 0)} days"],
        ["Avg DD Duration",    f"{s.get('avg_dd_duration', 0):.1f} days"],
        ["Volatility",         f"{s.get('volatility', 0):.2f}%"],
        ["Total DD Episodes",  str(s.get('total_episodes', 0))],
        ["Positive Periods",   str(s.get('positive_periods', 0))],
        ["Negative Periods",   str(s.get('negative_periods', 0))],
    ]
    print(tabulate(summary_rows, headers=["Metric", "Value"], tablefmt="grid"))

    # Drawdown episodes
    if episodes:
        print(f"\nDrawdown Episodes ({len(episodes)} total):")
        ep_rows = [
            [e["start_date"], e["end_date"], f"{e['depth']:.2f}%",
             f"{e['duration']} days", "Yes" if e["recovered"] else "No"]
            for e in episodes[:10]  # show first 10
        ]
        print(tabulate(ep_rows,
                       headers=["Start", "End", "Depth", "Duration", "Recovered"],
                       tablefmt="grid"))
        if len(episodes) > 10:
            print(f"  ... and {len(episodes) - 10} more episodes. Use --json to see all.")

    # Yearly period stats
    yearly = period_stats.get("yearly", [])
    if yearly:
        print("\nYearly Performance:")
        yr_rows = [
            [r["period"], f"{r['return_pct']:.2f}%", f"{r['volatility']:.2f}%", f"{r['max_dd']:.2f}%"]
            for r in yearly
        ]
        print(tabulate(yr_rows,
                       headers=["Year", "Return", "Volatility", "Max DD"],
                       tablefmt="grid"))

    print("=" * 70 + "\n")


def handle_analyze(args: argparse.Namespace) -> None:
    import requests as _requests
    api_key = get_stored_api_key()

    if api_key:
        # Logged-in: use SDK -> /api/v1/blend (authenticated, full quota)
        client = PortBlendClient(api_key=api_key, base_url=args.url)
        result = client.blend(
            data=args.file,
            target=args.target,
            allow_cash=not args.no_cash,
        )
        if args.json:
            print(json.dumps(result.raw_response, indent=2))
        else:
            result.summary()
    else:
        # Guest: call /api/sii directly (public endpoint, free-tier quota).
        # /api/v1/blend requires get_api_key_user, so we bypass the SDK here.
        print("[PORTBLEND] Running as guest (free-tier). Log in for higher quota.")
        payload_dict = DataTransformer.transform(args.file)
        series_ids = payload_dict["series_ids"]
        equal_w = round(100.0 / len(series_ids), 2)
        weights = {s: equal_w for s in series_ids}
        sii_payload = {
            "series_ids": series_ids,
            "series_data": payload_dict["series_data"],
            "weights": weights,
            "allowed_rebalancing": ["monthly"],
            "target": args.target,
            "allow_cash": not args.no_cash,
            "enable_weekly": True,
            "enable_daily": False,
            "enable_contribution": True,
            "enable_dominance": True,
        }
        base_url = args.url.rstrip("/")
        try:
            resp = _requests.post(f"{base_url}/sii", json=sii_payload, timeout=120)
        except _requests.RequestException as e:
            print(f"Error: Network error: {e}", file=sys.stderr)
            sys.exit(1)
        if resp.status_code != 200:
            err = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            detail = err.get("detail", {})
            msg = detail.get("error", resp.text) if isinstance(detail, dict) else resp.text
            print(f"Error: API returned HTTP {resp.status_code}: {msg}", file=sys.stderr)
            sys.exit(1)
        if args.json:
            print(json.dumps(resp.json(), indent=2))
        else:
            data = resp.json()
            weights_out = data.get("weights", {})
            summaries = data.get("portfolio_summaries", {})
            print("\n" + "=" * 70)
            print("  PORTBLEND -- Strategy Blending & Optimization Summary (Guest)")
            print("=" * 70)
            if weights_out:
                print("\nOptimal Strategy Allocations:")
                w_rows = [[s, f"{w:.1f}%"] for s, w in weights_out.items()]
                print(tabulate(w_rows, headers=["Strategy", "Weight"], tablefmt="grid"))
            first_mode = next(iter(summaries), None)
            if first_mode and summaries[first_mode]:
                s = summaries[first_mode]
                print("\nPortfolio Performance Metrics:")
                m_rows = [
                    ["CAGR", f"{s.get('cagr_pct', 0):.2f}%"],
                    ["Max Drawdown", f"{s.get('max_drawdown_pct', 0):.2f}%"],
                    ["Avg Drawdown", f"{s.get('avg_drawdown_pct', 0):.2f}%"],
                    ["Volatility", f"{s.get('volatility', 0):.2f}%"],
                ]
                print(tabulate(m_rows, headers=["Metric", "Value"], tablefmt="grid"))
            print("=" * 70 + "\n")


def handle_demo(args: argparse.Namespace) -> None:
    print("=" * 70)
    print("  PORTBLEND — Strategy Blending & Correlation Matrix Demo")
    print("=" * 70)
    print("\n[Step 1/3] Loading sample multi-strategy NAV dataset...")
    print("  - Strategy A: Nifty Trend Follower")
    print("  - Strategy B: BankNifty Mean Reversion")
    print("  - Strategy C: Gold Momentum")

    print("\n[Step 2/3] Computing Pairwise Correlation Matrix...")
    demo_corr = [
        ["Nifty Trend", "+1.00", "-0.42", "+0.12"],
        ["BankNifty Reversal", "-0.42", "+1.00", "-0.15"],
        ["Gold Momentum", "+0.12", "-0.15", "+1.00"],
    ]
    print(tabulate(
        demo_corr,
        headers=["Strategy", "Nifty Trend", "BankNifty Reversal", "Gold Momentum"],
        tablefmt="grid"
    ))

    print("\n[INSIGHT] Pair (Nifty Trend, BankNifty Reversal) exhibits strong negative correlation (-0.42).")
    print("Combining these strategies creates an effective drawdown hedge.")

    print("\n[Step 3/3] Executing Minimum Drawdown Portfolio Optimization...")
    demo_weights = [
        ["Nifty Trend", "45.0%"],
        ["BankNifty Reversal", "35.0%"],
        ["Gold Momentum", "20.0%"],
    ]
    print(tabulate(demo_weights, headers=["Strategy", "Weight"], tablefmt="grid"))

    print("\nPerformance Impact:")
    print("  - Standalone Max Drawdown (Avg): -14.8%")
    print("  - Blended Portfolio Max Drawdown: -6.2%")
    print("  - Drawdown Reduction: 58.1%")

    print("\nRun 'portblend analyze --file your_data.csv' to process your own strategies!")
    print("=" * 70 + "\n")


def handle_status(args: argparse.Namespace) -> None:
    api_key = get_stored_api_key()
    if not api_key:
        print("[PORTBLEND] API Status: Not logged in. Run 'portblend login --key <API_KEY>'")
        return

    client = PortBlendClient(api_key=api_key, base_url=args.url)

    # Step 1 — Connectivity check (public endpoint, no auth)
    try:
        resp = client.session.get(f"{client.base_url}/health", timeout=10)
        if resp.status_code == 200:
            print(f"[PORTBLEND] Server:  Reachable ({client.base_url})")
        else:
            print(f"[PORTBLEND] Server:  Unreachable — HTTP {resp.status_code} ({client.base_url})")
            return
    except Exception as e:
        print(f"[PORTBLEND] Server:  Connection failed — {e}")
        return

    # Step 2 — API Key validation (authenticated endpoint)
    # GET /api/auth/tokens requires a valid Bearer pb_live_... token.
    # A 200 confirms the key is recognised by the server.
    # A 401 means the key is invalid, revoked, or the feature is not yet deployed.
    # A 404 means the token-management endpoints are not deployed on this server.
    try:
        auth_resp = client.session.get(f"{client.base_url}/auth/tokens", timeout=10)
        if auth_resp.status_code == 200:
            print(f"[PORTBLEND] API Key: Valid   — {api_key[:12]}...")
        elif auth_resp.status_code == 401:
            print(f"[PORTBLEND] API Key: INVALID or REVOKED — the server rejected this key (HTTP 401).")
            print(f"[PORTBLEND]          Run 'portblend login --key <NEW_KEY>' to update your key.")
        elif auth_resp.status_code == 404:
            print(f"[PORTBLEND] API Key: UNVERIFIABLE — authenticated API endpoints not found on this server (HTTP 404).")
            print(f"[PORTBLEND]          The API key feature may not yet be deployed to: {client.base_url}")
        else:
            print(f"[PORTBLEND] API Key: Check returned unexpected HTTP {auth_resp.status_code}.")
    except Exception as e:
        print(f"[PORTBLEND] API Key: Validation request failed — {e}")


def handle_examples(args: argparse.Namespace) -> None:
    """
    Prints ready-to-copy SDK and CLI code recipes and tutorial links.
    """
    recipes = """======================================================================
  PORTBLEND — CLI & Python SDK Discovery Recipes
======================================================================

1. PYTHON SDK QUICKSTART
----------------------------------------------------------------------
  from portblend import PortBlendClient, DataTransformer

  # Initialize client
  client = PortBlendClient(api_key="pb_live_...", base_url="https://app.portblend.com/api")

  # 1A. Calculate Pairwise Correlation Matrix (returns pandas.DataFrame)
  df_corr = client.correlate(data="strategies.csv")  # file, DataFrame, or directory
  print(df_corr)

  # 1B. Optimize Portfolio Weights (returns BlendResult object)
  result = client.blend(
      data="strategies.csv",
      target="min_drawdown",  # "min_drawdown"|"max_sharpe"|"max_calmar"|"min_volatility"|"max_sortino"|"balanced_protection"|"buffered_allocation"
      allow_cash=True         # Allow synthetic CASH buffer allocation
  )
  result.summary()
  print("Optimal Weights:", result.weights)

2. CLI COMMAND RECIPES
----------------------------------------------------------------------
  # Authenticate
  portblend login --key pb_live_abcdef1234567890

  # Check API Connection & Key Validity
  portblend status

  # Single-Strategy Drawdown Dynamics (Public - No Key Required)
  portblend drawdown --file my_strategy.csv

  # Pairwise Strategy Correlation Matrix
  portblend correlate --file path/to/strategies.csv
  portblend correlate --file path/to/folder  # Process all CSVs in a directory

  # Portfolio Optimization
  portblend analyze --file strategies.csv --target min_drawdown
  portblend analyze --file strategies.csv --target max_sharpe --no-cash
  portblend analyze --file strategies.csv --json  # Machine-readable output

3. INTERACTIVE TUTORIALS & RESOURCES
----------------------------------------------------------------------
  - Google Colab Notebook: https://colab.research.google.com/github/portblend-research/portblend-python/blob/main/doc/examples/01_quickstart_portblend.ipynb
  - Machine Documentation: https://app.portblend.com/llms.txt
  - Full API Specs:        https://app.portblend.com/llms-full.txt
======================================================================
"""
    print(recipes)


def main() -> None:
    setup_logger()

    parser = argparse.ArgumentParser(
        prog="portblend",
        description="PortBlend CLI — Strategy Correlation Matrix, Portfolio Blending & Drawdown Minimization Tool.",
        epilog="""
Tips & Target Options:
  - protection (min_drawdown): Cuts maximum portfolio loss depth to the absolute minimum.
  - efficiency (max_sharpe): Maximizes overall risk-adjusted return.
  - recovery (max_calmar): Maximizes return relative to maximum peak-to-trough drawdown.
  - stability (min_volatility): Minimizes daily portfolio price swings and variance.
  - downside_safety (max_sortino): Ignores upside gains, penalizing only negative losses.
  - risk_balance (balanced_protection): Balances drawdown and return dynamically.
  - buffered (buffered_allocation): Optimizes strategy blend first, then applies a cash buffer.

Examples:
  - Run 'portblend optimize --file data.csv --target protection'
  - Run 'portblend optimize --file data.csv --target efficiency'
  - Run 'portblend examples' to display copy-pasteable CLI & SDK code recipes.
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available Commands")

    # Login
    login_parser = subparsers.add_parser("login", help="Save PortBlend API key locally to ~/.portblend/config.json")
    login_parser.add_argument("--key", "-k", required=True, help="PortBlend API token (e.g. pb_live_abcdef...)")

    # Logout
    subparsers.add_parser("logout", help="Remove saved API key from local config")

    # Drawdown Dynamics (public — no login required)
    drawdown_parser = subparsers.add_parser("drawdown", help="Analyze single-strategy drawdown dynamics (public — no login required)")
    drawdown_parser.add_argument("--file", "-f", required=True, help="Path to local NAV CSV, TSV, or Excel file")
    drawdown_parser.add_argument("--url", default="https://app.portblend.com/api", help="API base URL")
    drawdown_parser.add_argument("--json", action="store_true", help="Return raw JSON output")

    # Correlate
    corr_parser = subparsers.add_parser("correlate", help="Compute pairwise strategy correlation matrix (file or directory folder)")
    corr_parser.add_argument("--file", "-f", required=True, help="Path to local NAV CSV, TSV, Excel file, or directory folder")
    corr_parser.add_argument("--url", default="https://app.portblend.com/api", help="API base URL")
    corr_parser.add_argument("--json", action="store_true", help="Return raw JSON output")

    # Analyze / Blend / Optimize
    analyze_parser = subparsers.add_parser(
        "analyze",
        aliases=["optimize"],
        help="Execute portfolio weight optimization across 7 targets (alias: optimize)",
    )
    analyze_parser.add_argument("--file", "-f", required=True, help="Path to local NAV CSV, TSV, Excel file, or directory folder")
    analyze_parser.add_argument(
        "--target", "-t",
        default="protection",
        choices=["protection", "efficiency", "recovery", "stability", "downside_safety", "risk_balance", "buffered", "balanced_protection", "buffered_allocation"],
        help="Optimization target: protection (min_drawdown), efficiency (max_sharpe), recovery (max_calmar), stability (min_volatility), downside_safety (max_sortino), risk_balance (balanced_protection), buffered (buffered_allocation)"
    )
    analyze_parser.add_argument("--no-cash", action="store_true", help="Force 100% strategy allocation (no synthetic CASH buffer)")
    analyze_parser.add_argument("--url", default="https://app.portblend.com/api", help="API base URL")
    analyze_parser.add_argument("--json", action="store_true", help="Return raw JSON output")

    # Demo
    demo_parser = subparsers.add_parser("demo", help="Run interactive zero-key offline walkthrough")

    # Status
    status_parser = subparsers.add_parser("status", help="Check API connection & key status")
    status_parser.add_argument("--url", default="https://app.portblend.com/api", help="API base URL")

    # Examples
    examples_parser = subparsers.add_parser("examples", help="Display copy-pasteable SDK and CLI code recipes & Colab links")

    args = parser.parse_args()

    if args.command == "login":
        handle_login(args)
    elif args.command == "logout":
        handle_logout(args)
    elif args.command == "drawdown":
        handle_drawdown(args)
    elif args.command == "correlate":
        handle_correlate(args)
    elif args.command in ["analyze", "optimize"]:
        handle_analyze(args)
    elif args.command == "demo":
        handle_demo(args)
    elif args.command == "status":
        handle_status(args)
    elif args.command == "examples":
        handle_examples(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
