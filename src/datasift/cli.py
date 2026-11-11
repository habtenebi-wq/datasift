"""Command-line interface.

    datasift summary  FILE [--column COL]
    datasift filter   FILE [--where EXPR] [--columns A,B] [--sort COL] [--desc] [--top N] [--out PATH]
    datasift group    FILE --by A[,B] [--agg COL:FUNC ...] [--where EXPR] [--sort COL] [--desc] [--top N] [--out PATH]
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from . import core
from .query import QueryError, filter_rows


def _split(text: str | None) -> list[str] | None:
    return [part.strip() for part in text.split(",") if part.strip()] if text else None


def _num(v) -> str:
    if pd.isna(v):
        return ""
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,.2f}"


def _show(df: pd.DataFrame, limit: int = 50) -> str:
    with pd.option_context("display.max_columns", 20, "display.width", 160,
                           "display.max_colwidth", 40, "display.float_format", "{:,.3f}".format):
        shown = df.head(limit).to_string(index=False)
    more = f"\n... {len(df) - limit:,} more rows (use --top or --out)" if len(df) > limit else ""
    return shown + more


def cmd_summary(args) -> None:
    df = core.load(args.file, args.sheet)
    if args.column:
        info = core.describe_column(df, args.column)
        for key, value in info.items():
            if isinstance(value, dict):
                print(f"{key}:")
                for k, v in value.items():
                    print(f"  {k:>24}  {v:,}" if isinstance(v, (int, float)) else f"  {k:>24}  {v}")
            else:
                print(f"{key}: {value}")
        return
    ov = core.overview(df)
    print(f"{args.file}: {ov['rows']:,} rows x {ov['columns']} columns "
          f"({ov['number_columns']} number, {ov['text_columns']} text)")
    print(f"Missing cells: {ov['missing_cells']:,}   Duplicate rows: {ov['duplicate_rows']:,}\n")
    table = core.summarize(df)
    for col in ("min", "median", "mean", "max"):
        table[col] = table[col].map(_num)
    table["missing_%"] = table["missing_%"].map(lambda v: f"{v:.1f}")
    table["most_common"] = table["most_common"].fillna("")
    print(_show(table, limit=200))


def cmd_filter(args) -> None:
    df = core.load(args.file, args.sheet)
    out = core.sift(df, args.where, _split(args.columns), args.sort, args.desc, args.top)
    print(f"{len(filter_rows(df, args.where)):,} of {len(df):,} rows match.\n")
    _finish(out, args)


def cmd_group(args) -> None:
    df = core.load(args.file, args.sheet)
    df = filter_rows(df, args.where)
    out = core.group(df, _split(args.by), args.agg)
    out = core.head(core.sort(out, args.sort, args.desc), args.top)
    _finish(out, args)


def _finish(out: pd.DataFrame, args) -> None:
    if args.out:
        path = core.save(out, args.out)
        print(f"Saved {len(out):,} rows to {path}")
    else:
        print(_show(out))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="datasift", description="Summarize and filter CSV/Excel tables.")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp):
        sp.add_argument("file", help="a .csv, .tsv, .xlsx or .json file")
        sp.add_argument("--sheet", help="Excel sheet name (default: first sheet)")

    s = sub.add_parser("summary", help="overview of every column, or one column with --column")
    common(s)
    s.add_argument("--column", "-c", help="look closely at one column")
    s.set_defaults(func=cmd_summary)

    f = sub.add_parser("filter", help="keep rows that match a filter")
    common(f)
    f.add_argument("--where", "-w", help='e.g. "state = NC and pop_change_pct > 10"')
    f.add_argument("--columns", help="comma-separated columns to show")
    f.add_argument("--sort", "-s", help="column to sort by")
    f.add_argument("--desc", action="store_true", help="sort largest first")
    f.add_argument("--top", "-n", type=int, help="keep only the first N rows")
    f.add_argument("--out", "-o", help="save to .csv or .xlsx instead of printing")
    f.set_defaults(func=cmd_filter)

    g = sub.add_parser("group", help="group rows and summarize each group (like a pivot table)")
    common(g)
    g.add_argument("--by", "-b", required=True, help="comma-separated columns to group by")
    g.add_argument("--agg", "-a", nargs="+", help="column:function, e.g. pop_2019:sum pop_change_pct:mean")
    g.add_argument("--where", "-w", help="filter rows before grouping")
    g.add_argument("--sort", "-s", help="column of the result to sort by, e.g. rows or pop_2019_sum")
    g.add_argument("--desc", action="store_true")
    g.add_argument("--top", "-n", type=int)
    g.add_argument("--out", "-o")
    g.set_defaults(func=cmd_group)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (QueryError, FileNotFoundError, ValueError) as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
