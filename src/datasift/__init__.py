"""datasift: summarize and filter tables with plain-English-style filters."""

from .core import describe_column, group, load, overview, save, select, sift, sort, summarize
from .query import QueryError, filter_rows, parse

__all__ = [
    "load", "save", "overview", "summarize", "describe_column",
    "filter_rows", "sift", "select", "sort", "group", "parse", "QueryError",
]
__version__ = "0.1.0"
