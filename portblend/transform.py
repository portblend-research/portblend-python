"""
portblend.transform

Data preparation engine for local NAV series parsing and validation.

Strictly implements the specification defined in:
`doc/2_design/UI/robust_client_parsing_design.md`

Capabilities:
1. Multi-Format Input Support (.csv, .tsv, .txt, .xlsx, .xls, pandas.DataFrame, raw strings).
2. Auto Delimiter Detection (,, ;, \t, |).
3. Boundary & Table Start Row Detection (skips leading broker metadata lines).
4. Fuzzy Header Regex Matching for Date and NAV columns.
5. Multi-Format Date Normalization Pipeline (ISO, European dots, YYYYMMDD, textual months, time stripping).
6. Advanced Numeric Cleansing (currency symbols, thousand commas, %, spaces).
7. Footer & Malformed Line Skipping.
8. Chronological Ascending Sorting (oldest date -> newest date).
"""

import io
import re
from datetime import datetime, date
from pathlib import Path
from typing import Any, Union, Dict, List, Tuple

import pandas as pd


class DataTransformer:
    """
    Robust NAV dataset transformer and validator.
    Converts diverse file formats and DataFrames into a clean API payload dict.
    """

    # Fuzzy Regexes per robust_client_parsing_design.md
    DATE_REGEX = re.compile(
        r"\b(date|time|day|observation|obs_date|timestamp|period|week|month|tradedate|trade_date|nav_date|nav date)\b",
        re.IGNORECASE,
    )
    NAV_REGEX = re.compile(
        r"\b(nav|equity|value|close|price|index|balance|amount|cum_nav|cumnav|portfolio_value)\b",
        re.IGNORECASE,
    )
    CURRENCY_REGEX = re.compile(r"[$€£¥₹]|USD|EUR|GBP|INR|CHF", re.IGNORECASE)

    @classmethod
    def transform(
        cls,
        data: Union[str, Path, pd.DataFrame, Dict[str, Any]],
        series_name_fallback: str = "STRATEGY_1",
    ) -> Dict[str, Any]:
        """
        Transforms input data into structured API payload format:
        {
          "series_ids": ["STRAT_A", "STRAT_B"],
          "series_data": {
             "STRAT_A": [["2026-01-01", 100.0], ["2026-01-02", 101.5]],
             "STRAT_B": [["2026-01-01", 100.0], ["2026-01-02", 98.8]]
          }
        }
        """
        # Case 1: Already structured dict
        if isinstance(data, dict) and "series_ids" in data and "series_data" in data:
            return data

        # Case 2: pandas DataFrame
        if isinstance(data, pd.DataFrame):
            return cls._process_dataframe(data, series_name_fallback)

        # Case 3: Filepath, Directory Path, or Raw Text
        if isinstance(data, (str, Path)):
            str_data = str(data)
            path_obj = Path(str_data)

            # Case 3A: Directory path containing multiple strategy files
            if path_obj.is_dir():
                files = sorted([
                    f for f in path_obj.iterdir()
                    if f.is_file() and f.suffix.lower() in [".csv", ".tsv", ".txt", ".xlsx", ".xls"]
                ])
                if not files:
                    raise ValueError(f"No valid strategy files (.csv, .xlsx, etc.) found in directory: {path_obj}")

                combined_ids = []
                combined_data = {}
                for f in files:
                    try:
                        sub_res = cls.transform(f, series_name_fallback=f.stem)
                        for sid in sub_res["series_ids"]:
                            final_id = sid if sid not in combined_data else f"{f.stem}_{sid}"
                            combined_ids.append(final_id)
                            combined_data[final_id] = sub_res["series_data"][sid]
                    except Exception:
                        continue

                if not combined_ids:
                    raise ValueError(f"No valid NAV series could be extracted from files in directory: {path_obj}")

                return {
                    "series_ids": combined_ids,
                    "series_data": combined_data,
                }

            # Case 3B: Single file path on disk
            if path_obj.is_file():
                ext = path_obj.suffix.lower()

                # Excel Spreadsheet Handling (.xlsx / .xls)
                if ext in [".xlsx", ".xls"]:
                    df = pd.read_excel(str_data)
                    return cls._process_dataframe(df, path_obj.stem)

                # Text / Delimited File (.csv, .tsv, .txt)
                with open(str_data, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                return cls._process_raw_text(content, path_obj.stem)

            # Case 3C: Raw multi-line string text
            if "\n" in str_data or "," in str_data or "\t" in str_data:
                return cls._process_raw_text(str_data, series_name_fallback)

        raise ValueError(
            f"Unsupported data format or non-existent file path: {type(data)}."
        )

    @classmethod
    def _process_raw_text(cls, text: str, fallback_name: str) -> Dict[str, Any]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            raise ValueError("Input dataset is empty.")

        # 1. Delimiter Detection
        delimiter = cls._detect_delimiter(lines[:10])

        # 2. Boundary & Table Start Row Detection
        start_row_idx = cls._detect_table_start(lines, delimiter)

        # Parse CSV text from start_row_idx
        csv_buffer = io.StringIO("\n".join(lines[start_row_idx:]))
        df = pd.read_csv(csv_buffer, sep=delimiter, header=0 if start_row_idx >= 0 else None)
        return cls._process_dataframe(df, fallback_name)

    @classmethod
    def _detect_delimiter(cls, sample_lines: List[str]) -> str:
        candidates = [",", ";", "\t", "|"]
        scores = {c: 0 for c in candidates}
        for line in sample_lines:
            for c in candidates:
                scores[c] += line.count(c)
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else ","

    @classmethod
    def _detect_table_start(cls, lines: List[str], delimiter: str) -> int:
        for idx, line in enumerate(lines[:20]):
            parts = [p.strip() for p in line.split(delimiter)]
            if len(parts) < 2:
                continue

            # Check fuzzy regex match in headers
            header_date_match = any(cls.DATE_REGEX.search(p) for p in parts)
            header_nav_match = any(cls.NAV_REGEX.search(p) for p in parts)
            if header_date_match and header_nav_match:
                return idx

            # Check content heuristics (date cell + numeric cell)
            date_ok = False
            num_ok = False
            for p in parts:
                if not date_ok and cls.parse_date_cell(p) is not None:
                    date_ok = True
                elif not num_ok and cls.clean_numeric_cell(p) is not None:
                    num_ok = True

            if date_ok and num_ok:
                # Line is raw data row without headers
                return idx

        return 0

    @classmethod
    def _process_dataframe(cls, df: pd.DataFrame, fallback_name: str) -> Dict[str, Any]:
        if df.empty:
            raise ValueError("Input DataFrame is empty.")

        # Clean string columns
        df.columns = [str(c).strip() for c in df.columns]

        # 1. Detect Date Column
        date_col = None
        for col in df.columns:
            if cls.DATE_REGEX.search(col):
                date_col = col
                break

        if not date_col:
            # Fallback: scan columns for date cell compatibility
            for col in df.columns:
                sample_vals = df[col].dropna().head(5).astype(str)
                if any(cls.parse_date_cell(v) is not None for v in sample_vals):
                    date_col = col
                    break

        if not date_col:
            # Assume first column is date
            date_col = df.columns[0]

        # 2. Detect Strategy / NAV Columns
        value_cols = [c for c in df.columns if c != date_col]

        # Filter value columns using fuzzy regex or numeric test
        valid_val_cols = []
        for col in value_cols:
            if cls.NAV_REGEX.search(col):
                valid_val_cols.append(col)
            else:
                sample_vals = df[col].dropna().head(5).astype(str)
                if any(cls.clean_numeric_cell(v) is not None for v in sample_vals):
                    valid_val_cols.append(col)

        if not valid_val_cols:
            if len(df.columns) >= 2:
                valid_val_cols = [df.columns[1]]
            else:
                raise ValueError("Could not detect any numeric NAV value column in dataset.")

        # 3. Process and Clean Date-NAV tuples per strategy
        series_ids = []
        series_data = {}

        for val_col in valid_val_cols:
            strat_name = str(val_col).strip()
            # Clean fallback name if default generic header
            if strat_name.lower() in ["nav", "value", "price", "close", "0", "1", "unnamed: 1"]:
                strat_name = fallback_name

            # Avoid duplicate series_ids
            if strat_name in series_data:
                strat_name = f"{strat_name}_2"

            pts: List[Tuple[datetime, float]] = []

            for _, row in df.iterrows():
                raw_date = row[date_col]
                raw_val = row[val_col]

                # Footer skipping check (Total, Average, Disclaimer)
                if isinstance(raw_date, str) and any(
                    k in raw_date.lower() for k in ["total", "average", "disclaimer", "summary"]
                ):
                    break

                dt = cls.parse_date_cell(raw_date)
                val = cls.clean_numeric_cell(raw_val)

                if dt is not None and val is not None:
                    pts.append((dt, val))

            if len(pts) < 2:
                continue

            # 4. Strict Chronological Ascending Sorting Rule (oldest date -> newest date)
            pts.sort(key=lambda x: x[0])

            # Deduplicate identical date records (keep latest)
            date_map = {}
            for dt, val in pts:
                date_map[dt.strftime("%Y-%m-%d")] = val

            sorted_tuples = [[d, date_map[d]] for d in sorted(date_map.keys())]

            series_ids.append(strat_name)
            series_data[strat_name] = sorted_tuples

        if not series_ids:
            raise ValueError("No valid NAV series could be extracted from dataset (minimum 2 valid date-NAV rows required).")

        return {
            "series_ids": series_ids,
            "series_data": series_data,
        }

    @classmethod
    def parse_date_cell(cls, val: Any) -> Union[datetime, None]:
        """
        Advanced Multi-Format Date Normalization Pipeline.
        Handles ISO, European dots, YYYYMMDD, textual months, and trailing timestamps.
        """
        if pd.isna(val) or val is None:
            return None

        if isinstance(val, (datetime, date)):
            return datetime(val.year, val.month, val.day)

        val_str = str(val).strip()
        if not val_str:
            return None

        # Strip trailing time components (e.g. 12:00:00, T00:00:00Z)
        val_clean = re.split(r"[\sT]", val_str)[0].strip()

        # 1. ISO format: YYYY-MM-DD or YYYY/MM/DD
        m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", val_clean)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass

        # 2. European Dot format: DD.MM.YYYY or DD.MM.YY
        m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{2,4})$", val_clean)
        if m:
            try:
                year = int(m.group(3))
                if year < 100:
                    year += 2000
                return datetime(year, int(m.group(2)), int(m.group(1)))
            except ValueError:
                pass

        # 3. Compact YYYYMMDD
        m = re.match(r"^(\d{4})(\d{2})(\d{2})$", val_clean)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass

        # 4. Textual month format: DD-Mon-YYYY or YYYY-Mon-DD
        try:
            parsed = pd.to_datetime(val_str, errors="coerce")
            if not pd.isna(parsed):
                return datetime(parsed.year, parsed.month, parsed.day)
        except Exception:
            pass

        return None

    @classmethod
    def clean_numeric_cell(cls, val: Any) -> Union[float, None]:
        """
        Advanced Numeric Cleansing.
        Strips currency symbols, thousand separators, spaces, and % signs.
        """
        if pd.isna(val) or val is None:
            return None

        if isinstance(val, (int, float)):
            return float(val)

        val_str = str(val).strip()
        if not val_str:
            return None

        # Strip currency symbols, spaces, commas
        cleaned = cls.CURRENCY_REGEX.sub("", val_str)
        cleaned = cleaned.replace(",", "").replace(" ", "")

        has_percent = "%" in cleaned
        cleaned = cleaned.replace("%", "").strip()

        try:
            num = float(cleaned)
            if has_percent:
                num = num / 100.0
            return num
        except ValueError:
            return None
