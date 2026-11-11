"""A small, safe filter language for pandas DataFrames.

Examples:
    state = NC
    pop_change_pct > 10 and state in (NC, SC, GA)
    county contains "ville" or county startswith Mc
    college_plus_pct between 20 and 40
    not (density_2010 < 50) and foreign_born_pct is not missing
    `Total Sales` >= 1000            # backticks for names with spaces

Nothing is passed to eval(): the text is split into tokens and parsed by
hand, so a filter can only read columns, never run code.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

import pandas as pd


class QueryError(ValueError):
    """Raised when a filter can't be understood or doesn't match the data."""


# --- Tokenizing -----------------------------------------------------------

TOKEN_RE = re.compile(
    r"""
    \s*(?:
        (?P<lparen>\() |
        (?P<rparen>\)) |
        (?P<comma>,) |
        (?P<op>>=|<=|!=|==|=|>|<) |
        (?P<string>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*') |
        (?P<name>`[^`]+`) |
        (?P<word>[^\s(),=<>!"'`]+)
    )""",
    re.VERBOSE,
)

KEYWORDS = {"and", "or", "not", "in", "between", "is", "missing",
            "contains", "startswith", "endswith"}


@dataclass
class Token:
    kind: str   # lparen, rparen, comma, op, string, name, word, keyword
    text: str
    pos: int


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    text = text.rstrip()
    while pos < len(text):
        m = TOKEN_RE.match(text, pos)
        if not m or m.end() == pos:
            raise QueryError(f"Can't read the filter near: {text[pos:pos + 15]!r}")
        kind = m.lastgroup
        raw = m.group(kind)
        start = m.start(kind)
        if kind == "string":
            raw = re.sub(r"\\(.)", r"\1", raw[1:-1])
        elif kind == "name":
            raw = raw[1:-1]
        elif kind == "word" and raw.lower() in KEYWORDS:
            kind, raw = "keyword", raw.lower()
        tokens.append(Token(kind, raw, start))
        pos = m.end()
    return tokens


# --- Parsing into a tree ----------------------------------------------------

@dataclass
class Condition:
    column: str
    op: str            # =, !=, >, >=, <, <=, contains, startswith, endswith, in, between, missing
    values: list
    negate: bool = False


@dataclass
class Not:
    child: object


@dataclass
class BoolOp:
    op: str            # "and" / "or"
    left: object
    right: object


class Parser:
    """Recursive-descent parser.

    expr      := and_expr ("or" and_expr)*
    and_expr  := not_expr ("and" not_expr)*
    not_expr  := "not" not_expr | "(" expr ")" | condition
    """

    def __init__(self, text: str):
        self.text = text
        self.tokens = tokenize(text)
        self.i = 0

    # helpers
    def peek(self) -> Token | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self) -> Token:
        tok = self.peek()
        if tok is None:
            raise QueryError("The filter ends too early.")
        self.i += 1
        return tok

    def is_kw(self, word: str) -> bool:
        tok = self.peek()
        return tok is not None and tok.kind == "keyword" and tok.text == word

    def expect_kw(self, word: str) -> None:
        if not self.is_kw(word):
            got = self.peek().text if self.peek() else "the end"
            raise QueryError(f"Expected '{word}' but found {got!r}.")
        self.i += 1

    # grammar
    def parse(self):
        if not self.tokens:
            raise QueryError("The filter is empty.")
        node = self.expr()
        if self.peek() is not None:
            raise QueryError(f"Unexpected {self.peek().text!r}. Did you forget 'and' or 'or'?")
        return node

    def expr(self):
        node = self.and_expr()
        while self.is_kw("or"):
            self.i += 1
            node = BoolOp("or", node, self.and_expr())
        return node

    def and_expr(self):
        node = self.not_expr()
        while self.is_kw("and"):
            self.i += 1
            node = BoolOp("and", node, self.not_expr())
        return node

    def not_expr(self):
        if self.is_kw("not"):
            self.i += 1
            return Not(self.not_expr())
        tok = self.peek()
        if tok is not None and tok.kind == "lparen":
            self.i += 1
            node = self.expr()
            if not self.peek() or self.peek().kind != "rparen":
                raise QueryError("Missing a closing ')'.")
            self.i += 1
            return node
        return self.condition()

    def value(self):
        tok = self.take()
        if tok.kind not in ("string", "word", "name"):
            raise QueryError(f"Expected a value but found {tok.text!r}.")
        return tok.text

    def condition(self) -> Condition:
        col_tok = self.take()
        if col_tok.kind not in ("word", "name", "string"):
            raise QueryError(f"Expected a column name but found {col_tok.text!r}.")
        column = col_tok.text
        tok = self.take()

        if tok.kind == "op":
            op = "=" if tok.text == "==" else tok.text
            return Condition(column, op, [self.value()])

        if tok.kind != "keyword":
            raise QueryError(f"Expected a comparison after {column!r} but found {tok.text!r}.")

        negate = False
        word = tok.text
        if word == "not":                       # "x not in (...)", "x not contains y"
            negate = True
            word = self.take().text
        if word in ("contains", "startswith", "endswith"):
            return Condition(column, word, [self.value()], negate)
        if word == "in":
            return Condition(column, "in", self.value_list(), negate)
        if word == "between":
            low = self.value()
            self.expect_kw("and")
            return Condition(column, "between", [low, self.value()], negate)
        if word == "is":
            if self.is_kw("not"):
                self.i += 1
                negate = not negate
            self.expect_kw("missing")
            return Condition(column, "missing", [], negate)
        raise QueryError(f"Don't know how to use {word!r} after {column!r}.")

    def value_list(self) -> list:
        values = []
        if self.peek() and self.peek().kind == "lparen":
            self.i += 1
            while True:
                values.append(self.value())
                nxt = self.take()
                if nxt.kind == "rparen":
                    break
                if nxt.kind != "comma":
                    raise QueryError("Separate list items with commas, like (NC, SC).")
        else:  # unbracketed: state in NC, SC, VA
            values.append(self.value())
            while self.peek() and self.peek().kind == "comma":
                self.i += 1
                values.append(self.value())
        return values


def parse(text: str):
    return Parser(text).parse()


# --- Evaluating against a DataFrame ----------------------------------------

def resolve_column(df: pd.DataFrame, name: str) -> str:
    """Match a column name, ignoring case and spaces/underscores; suggest fixes."""
    if name in df.columns:
        return name

    def norm(s: str) -> str:
        return re.sub(r"[\s_]+", "", str(s)).lower()

    matches = [c for c in df.columns if norm(c) == norm(name)]
    if len(matches) == 1:
        return matches[0]
    close = difflib.get_close_matches(name, [str(c) for c in df.columns], n=3, cutoff=0.5)
    hint = f" Did you mean: {', '.join(close)}?" if close else ""
    raise QueryError(f"No column named {name!r}.{hint}")


def _convert(series: pd.Series, raw: str, column: str):
    if pd.api.types.is_bool_dtype(series):
        low = raw.lower()
        if low in ("true", "yes", "1"):
            return True
        if low in ("false", "no", "0"):
            return False
        raise QueryError(f"{column!r} is true/false, so {raw!r} doesn't fit.")
    if pd.api.types.is_numeric_dtype(series):
        try:
            return float(raw.replace(",", "").replace("$", "").rstrip("%"))
        except ValueError:
            raise QueryError(f"{column!r} holds numbers, but {raw!r} isn't a number.") from None
    if pd.api.types.is_datetime64_any_dtype(series):
        try:
            return pd.to_datetime(raw)
        except (ValueError, TypeError):
            raise QueryError(f"{column!r} holds dates, but {raw!r} isn't a date.") from None
    return raw


def _text(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip().str.casefold()


def _eval_condition(df: pd.DataFrame, cond: Condition) -> pd.Series:
    col = resolve_column(df, cond.column)
    s = df[col]

    if cond.op == "missing":
        mask = s.isna() | (s.astype("string").str.strip() == "")
    elif cond.op in ("contains", "startswith", "endswith"):
        needle = cond.values[0].casefold()
        text = _text(s)
        if cond.op == "contains":
            mask = text.str.contains(needle, regex=False)
        elif cond.op == "startswith":
            mask = text.str.startswith(needle)
        else:
            mask = text.str.endswith(needle)
    elif cond.op == "in":
        vals = [_convert(s, v, col) for v in cond.values]
        if isinstance(vals[0], str):
            mask = _text(s).isin([v.strip().casefold() for v in vals])
        else:
            mask = s.isin(vals)
    elif cond.op == "between":
        low, high = (_convert(s, v, col) for v in cond.values)
        if isinstance(low, str):
            raise QueryError(f"'between' needs numbers or dates, but {col!r} holds text.")
        mask = s.between(low, high)
    else:
        val = _convert(s, cond.values[0], col)
        left = s
        if isinstance(val, str):            # text compares ignore case and outer spaces
            left, val = _text(s), val.strip().casefold()
            if cond.op in (">", ">=", "<", "<="):
                raise QueryError(f"{col!r} holds text; use =, !=, contains, startswith or in.")
        ops = {"=": left.eq, "!=": left.ne, ">": left.gt, ">=": left.ge,
               "<": left.lt, "<=": left.le}
        mask = ops[cond.op](val)

    mask = mask.fillna(False).astype(bool)
    return ~mask if cond.negate else mask


def evaluate(df: pd.DataFrame, node) -> pd.Series:
    if isinstance(node, Condition):
        return _eval_condition(df, node)
    if isinstance(node, Not):
        return ~evaluate(df, node.child)
    if isinstance(node, BoolOp):
        left, right = evaluate(df, node.left), evaluate(df, node.right)
        return (left & right) if node.op == "and" else (left | right)
    raise TypeError(f"Unknown node: {node!r}")


def filter_rows(df: pd.DataFrame, where: str | None) -> pd.DataFrame:
    """Return the rows of df that match the filter text."""
    if not where or not where.strip():
        return df
    return df[evaluate(df, parse(where))]
