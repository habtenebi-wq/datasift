"""Loading, summarizing, sorting and grouping tables."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .query import QueryError, filter_rows, resolve_column

AGGREGATIONS = ("count", "sum", "mean", "median", "min", "max", "nunique", "std")


# --- Loading and saving ----------------------------------------------------

def load(path: str | Path, sheet: str | int | None = None) -> pd.DataFrame:
    """Read a CSV, TSV, Excel or JSON file into a DataFrame."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No file at {path}")
    ext = path.suffix.lower()
    if ext in (".csv", ".tsv", ".txt"):
        sep = "," if ext == ".csv" else "\t"
        df = pd.read_csv(path, sep=sep)
        df = _keep_leading_zeros(df, pd.read_csv(path, sep=sep, dtype=str))
    elif ext in (".xlsx", ".xlsm", ".xls"):
        df = pd.read_excel(path, sheet_name=0 if sheet is None else sheet)
    elif ext == ".json":
        df = pd.read_json(path)
    else:
        raise ValueError(f"Unsupported file type {ext!r}. Use .csv, .tsv, .xlsx or .json.")
    df.columns = [str(c).strip() for c in df.columns]
    # Trim stray spaces in text columns (e.g. " NC" -> "NC").
    for col in df.select_dtypes(include=["object", "string"]).columns:
        df[col] = df[col].astype("string").str.strip()
    return df


def _keep_leading_zeros(df: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    """Codes like ZIPs and FIPS ("01001") look like numbers but must stay text."""
    for col in df.columns:
        if pd.api.types.is_integer_dtype(df[col]):
            text = raw[col].dropna()
            if text.str.match(r"^0\d").any():
                df[col] = raw[col].astype("string")
    return df


def save(df: pd.DataFrame, path: str | Path) -> Path:
    """Write a DataFrame to .csv or .xlsx, depending on the extension."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".csv":
        df.to_csv(path, index=False)
    elif ext == ".xlsx":
        df.to_excel(path, index=False)
    else:
        raise ValueError("Save as .csv or .xlsx.")
    return path


# --- Summaries ---------------------------------------------------------------

def _kind(s: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(s):
        return "true/false"
    if pd.api.types.is_numeric_dtype(s):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "date"
    return "text"


def overview(df: pd.DataFrame) -> dict:
    """Headline facts about the whole table."""
    return {
        "rows": len(df),
        "columns": df.shape[1],
        "missing_cells": int(df.isna().sum().sum()),
        "duplicate_rows": int(df.duplicated().sum()),
        "number_columns": int(sum(_kind(df[c]) == "number" for c in df.columns)),
        "text_columns": int(sum(_kind(df[c]) == "text" for c in df.columns)),
    }


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """One row per column: type, missing values, unique values and key stats."""
    rows = []
    n = len(df)
    for col in df.columns:
        s = df[col]
        kind = _kind(s)
        missing = int(s.isna().sum())
        row = {
            "column": col,
            "type": kind,
            "filled": n - missing,
            "missing_%": round(100 * missing / n, 1) if n else 0.0,
            "unique": int(s.nunique(dropna=True)),
            "min": None, "median": None, "mean": None, "max": None, "most_common": None,
        }
        if kind == "number" and s.notna().any():
            row.update(min=s.min(), median=s.median(), mean=round(float(s.mean()), 3), max=s.max())
        elif s.notna().any():
            top = s.value_counts().head(1)
            row["most_common"] = f"{top.index[0]} ({top.iloc[0]})"
        rows.append(row)
    return pd.DataFrame(rows)


def describe_column(df: pd.DataFrame, column: str, top: int = 10) -> dict:
    """A closer look at one column."""
    col = resolve_column(df, column)
    s = df[col]
    info = {"column": col, "type": _kind(s), "filled": int(s.notna().sum()),
            "missing": int(s.isna().sum()), "unique": int(s.nunique())}
    if info["type"] == "number":
        q = s.quantile([0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0])
        info["percentiles"] = {f"{int(p * 100)}%": round(float(v), 3) for p, v in q.items()}
        info["mean"] = round(float(s.mean()), 3)
        info["std"] = round(float(s.std()), 3)
    else:
        counts = s.value_counts().head(top)
        info["top_values"] = {str(k): int(v) for k, v in counts.items()}
    return info


# --- Shaping results ---------------------------------------------------------

def select(df: pd.DataFrame, columns: list[str] | None) -> pd.DataFrame:
    if not columns:
        return df
    return df[[resolve_column(df, c) for c in columns]]


def sort(df: pd.DataFrame, by: str | None, descending: bool = False) -> pd.DataFrame:
    if not by:
        return df
    return df.sort_values(resolve_column(df, by), ascending=not descending, na_position="last")


def head(df: pd.DataFrame, n: int | None) -> pd.DataFrame:
    return df if n is None else df.head(n)


def parse_aggs(specs: list[str] | None) -> list[tuple[str, str]]:
    """Turn ["pop_2019:sum", "pop_change_pct:mean"] into (column, function) pairs."""
    pairs = []
    for spec in specs or []:
        if ":" not in spec:
            raise QueryError(f"Write aggregations as column:function, like pop_2019:sum (got {spec!r}).")
        col, func = (part.strip() for part in spec.rsplit(":", 1))
        if func not in AGGREGATIONS:
            raise QueryError(f"Unknown function {func!r}. Choose from: {', '.join(AGGREGATIONS)}.")
        pairs.append((col, func))
    return pairs


def group(df: pd.DataFrame, by: list[str], aggs: list[str] | None = None) -> pd.DataFrame:
    """Group rows (like an Excel pivot table) and summarize each group.

    Always includes a row count; add more with specs like "pop_2019:sum".
    """
    keys = [resolve_column(df, b) for b in by]
    grouped = df.groupby(keys, dropna=False)
    out = grouped.size().rename("rows").to_frame()
    for col, func in parse_aggs(aggs):
        real = resolve_column(df, col)
        if func not in ("count", "nunique") and not pd.api.types.is_numeric_dtype(df[real]):
            raise QueryError(f"Can't take the {func} of {real!r} because it isn't a number column.")
        out[f"{real}_{func}"] = grouped[real].agg(func)
    return out.reset_index()


def sift(df: pd.DataFrame, where: str | None = None, columns: list[str] | None = None,
         sort_by: str | None = None, descending: bool = False, top: int | None = None) -> pd.DataFrame:
    """Filter, pick columns, sort and keep the first N rows in one call."""
    out = filter_rows(df, where)
    out = sort(out, sort_by, descending)
    out = head(out, top)
    return select(out, columns)
