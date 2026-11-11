# datasift

**Summarize and filter CSV and Excel tables from the command line or Python, using filters that read like plain English.**

```bash
datasift filter counties.csv --where "state in (NC, SC, GA) and pop_change_pct > 15" --sort pop_change_pct --desc
```

Filtering a spreadsheet usually means clicking through menus one column at a time, and pandas means writing code like `df[(df["state"].isin(["NC", "SC"])) & (df["pop"] > 1000)]`. datasift sits in between: you write the filter as a short sentence, and it handles column names, data types and mistakes for you.

## Features

- **Summary of any table:** column types, missing values, unique counts, min/median/mean/max, and the most common value. You can also look closely at one column (percentiles or top values).
- **A readable filter language:** `=`, `!=`, `>`, `>=`, `<`, `<=`, `contains`, `startswith`, `endswith`, `in`, `between`, `is missing`, combined with `and`, `or`, `not` and parentheses.
- **Forgiving by design:**
  - Text comparisons ignore case and extra spaces.
  - Column names match regardless of case and spaces vs. underscores.
  - Values like `$100000` and `45%` are understood.
- **Helpful errors:** a typo like `stat = NC` gets `No column named 'stat'. Did you mean: state?`
- **Safe:** filters are tokenized and parsed by a hand-written recursive-descent parser, never passed to `eval()`, so a filter can't run code.
- **Pivot-table-style grouping:** group by one or more columns with `count`, `sum`, `mean`, `median`, `min`, `max`, `nunique` or `std`.
- **Sort, pick columns, keep the top N, and save** results to `.csv` or `.xlsx`.
- **Reads** `.csv`, `.tsv`, `.xlsx` and `.json`, keeps codes like ZIP and FIPS (`01001`) as text, and trims stray spaces.
- **Tested:** 48 pytest tests covering the parser, error messages, grouping, file handling and the CLI.

## Install

```bash
git clone https://github.com/<your-username>/datasift.git
cd datasift
pip install -e ".[dev]"
```

## Command-line examples

The examples use `examples/us_counties.csv`: 2010–2019 population change for 3,142 U.S. counties.

**Summarize a whole table**

```bash
datasift summary examples/us_counties.csv
```
```
examples/us_counties.csv: 3,142 rows x 19 columns (13 number, 5 text)
Missing cells: 0   Duplicate rows: 0

            column       type  filled missing_%  unique     min median    mean        max      most_common
              fips       text    3142       0.0    3142                                          01001 (1)
             state       text    3142       0.0      51                                           TX (254)
          pop_2019     number    3142       0.0    3088   86.00 25,726 104,468 10,039,107
    pop_change_pct     number    3142       0.0    2943  -33.55  -0.53    0.96     134.31
...
```

**Look closely at one column**

```bash
datasift summary examples/us_counties.csv --column pop_change_pct
```
```
percentiles:
     0%  -33.545
    25%  -4.202
    50%  -0.53
    75%  4.495
   100%  134.311
mean: 0.961
```

**Filter, sort and keep the top 5**

```bash
datasift filter examples/us_counties.csv \
  --where "state in (NC, SC, GA) and pop_change_pct > 15" \
  --columns state,county,pop_2019,pop_change_pct \
  --sort pop_change_pct --desc --top 5
```
```
35 of 3,142 rows match.

state    county  pop_2019  pop_change_pct
   GA   Forsyth    244252          38.212
   GA      Long     19559          34.205
   NC Brunswick    142820          32.156
   SC     Horry    354081          31.008
   GA     Bryan     39627          30.451
```

**Group like a pivot table**

```bash
datasift group examples/us_counties.csv --by state \
  --agg pop_2019:sum grew:mean \
  --where "state in (NC, SC, VA, GA, TN)" --sort grew_mean --desc
```
```
state  rows  pop_2019_sum  grew_mean
   TN    95       6829174      0.674
   GA   159      10617423      0.566
   NC   100      10488084      0.560
   SC    46       5148714      0.543
   VA   133       8535519      0.519
```
(`grew_mean` is the share of each state's counties that gained population.)

**Save results instead of printing:** add `--out results.xlsx` (or `.csv`) to `filter` or `group`.

## Python examples

```python
import datasift as ds

df = ds.load("examples/us_counties.csv")

ds.summarize(df)                                   # one row per column
ds.describe_column(df, "state")                    # top values for one column

nc_grads = ds.sift(
    df,
    where="state = NC and college_plus_pct > 35",
    columns=["county", "college_plus_pct", "pop_change_pct"],
    sort_by="college_plus_pct",
    descending=True,
)

by_density = ds.group(df, ["density_group"], ["pop_change_pct:median", "grew:mean"])
ds.save(by_density, "by_density.xlsx")
```

## Filter language reference

| Write | Meaning |
|---|---|
| `state = NC` | equals (ignores case and spaces) |
| `state != NC` | not equal |
| `pop > 100000`, `>=`, `<`, `<=` | number and date comparisons |
| `pop between 10000 and 50000` | inclusive range |
| `state in (NC, SC, VA)` | any of a list (brackets optional) |
| `state not in (NC, SC)` | none of a list |
| `county contains ville` | text contains (`not contains` also works) |
| `county startswith Mc` / `endswith ton` | text starts or ends with |
| `income is missing` / `is not missing` | blank cells |
| `a and b`, `a or b`, `not a`, `( … )` | combine conditions (`and` is applied before `or`) |
| `` `Median Income` > 50000 `` | backticks for column names with spaces |
| `county = "Prince George's"` | quotes for values with spaces or symbols |

Write large numbers without commas (`1000000`, not `1,000,000`).

## How it works

```
src/datasift/
├── query.py   # tokenizer, recursive-descent parser, evaluator → boolean mask
├── core.py    # load/save, summaries, sort/select/top, group-by
├── cli.py     # argparse command-line interface
└── __main__.py
tests/         # pytest suite (48 tests)
```

1. **Tokenize:** the filter text is split into tokens (names, values, operators, parentheses) with a regular expression.
2. **Parse:** a recursive-descent parser builds a small tree that respects precedence (`not` > `and` > `or`).
3. **Evaluate:** each condition becomes a pandas boolean mask, after converting the value to the column's type (number, date, true/false or text). The masks are combined with `&`, `|` and `~`.

## Run the tests

```bash
pytest
```
