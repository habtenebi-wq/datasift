import pandas as pd
import pytest

import datasift as ds
from datasift import QueryError
from datasift.cli import main


@pytest.fixture
def csv_file(tmp_path):
    path = tmp_path / "counties.csv"
    path.write_text(
        "fips,state,county,pop,change_pct\n"
        "37183, NC ,Wake,1100000,22.6\n"
        "37063,NC,Durham,320000,18.5\n"
        "45045,SC,Greenville,520000,15.0\n"
        "01001,AL,Autauga,55000,2.0\n"
        "37095,NC,Hyde,4900,-15.0\n"
    )
    return path


def test_load_trims_spaces_and_keeps_leading_zeros(csv_file):
    df = ds.load(csv_file)
    assert list(df["state"].unique()) == ["NC", "SC", "AL"]
    assert "01001" in set(df["fips"])


def test_load_excel_round_trip(tmp_path, csv_file):
    df = ds.load(csv_file)
    out = ds.save(df, tmp_path / "out.xlsx")
    again = ds.load(out)
    assert len(again) == len(df) and list(again.columns) == list(df.columns)


def test_load_rejects_unknown_type(tmp_path):
    bad = tmp_path / "data.pdf"
    bad.write_text("x")
    with pytest.raises(ValueError, match="Unsupported"):
        ds.load(bad)


def test_summarize(csv_file):
    table = ds.summarize(ds.load(csv_file)).set_index("column")
    assert table.loc["pop", "type"] == "number"
    assert table.loc["pop", "max"] == 1_100_000
    assert table.loc["state", "most_common"] == "NC (3)"
    assert ds.overview(ds.load(csv_file))["rows"] == 5


def test_describe_column(csv_file):
    info = ds.describe_column(ds.load(csv_file), "STATE")   # case doesn't matter
    assert info["top_values"]["NC"] == 3


def test_sift_sort_top_select(csv_file):
    out = ds.sift(ds.load(csv_file), "state = NC", columns=["county", "pop"],
                  sort_by="pop", descending=True, top=2)
    assert list(out.columns) == ["county", "pop"]
    assert list(out["county"]) == ["Wake", "Durham"]


def test_group_matches_pandas(csv_file):
    df = ds.load(csv_file)
    out = ds.group(df, ["state"], ["pop:sum", "change_pct:mean"]).set_index("state")
    expected = df.groupby("state")["pop"].sum()
    assert out.loc["NC", "rows"] == 3
    assert out.loc["NC", "pop_sum"] == expected["NC"]
    assert out.loc["NC", "change_pct_mean"] == pytest.approx(df[df.state == "NC"].change_pct.mean())


@pytest.mark.parametrize("spec, message", [
    (["pop"], "column:function"),
    (["pop:total"], "Unknown function"),
    (["county:sum"], "isn't a number"),
])
def test_group_errors(csv_file, spec, message):
    with pytest.raises(QueryError, match=message):
        ds.group(ds.load(csv_file), ["state"], spec)


def test_cli_filter_and_save(csv_file, tmp_path, capsys):
    out = tmp_path / "nc.csv"
    code = main(["filter", str(csv_file), "-w", "state = NC and change_pct > 0",
                 "-s", "pop", "--desc", "-o", str(out)])
    assert code == 0
    assert "2 of 5 rows match" in capsys.readouterr().out
    assert list(pd.read_csv(out)["county"]) == ["Wake", "Durham"]


def test_cli_group(csv_file, capsys):
    assert main(["group", str(csv_file), "-b", "state", "-a", "pop:sum", "-s", "pop_sum", "--desc"]) == 0
    printed = capsys.readouterr().out
    assert printed.index("NC") < printed.index("SC") < printed.index("AL")


def test_cli_summary(csv_file, capsys):
    assert main(["summary", str(csv_file)]) == 0
    assert "5 rows x 5 columns" in capsys.readouterr().out


def test_cli_reports_errors_without_crashing(csv_file, capsys):
    assert main(["filter", str(csv_file), "-w", "stat = NC"]) == 1
    assert "Did you mean: state" in capsys.readouterr().err
