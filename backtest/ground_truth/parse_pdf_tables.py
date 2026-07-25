"""Parse the Portfolio Visualizer report PDF into ground-truth JSON files.

Source of truth: ``Model_Backtest_20260725202812.pdf`` at the repo root.

    pages 20-24  "Model trades"                -> pv_trades.json, pv_holdings.json
    page  12     "Dual Momentum Model Returns"  -> pv_monthly_returns.json

The trades table is extracted with ``pdftotext -layout``. In that rendering each
date cell is too narrow for ``MM/DD/YYYY``, so the FINAL YEAR DIGIT of all three
dates wraps onto a continuation line directly below the trade row, e.g.::

        1 01/01/199 08/31/199 12/31/199 Initial Entry ... (VFINX) ...
          7         8         6

The three wrapped digits belong to the Start / End / Trade dates in that order,
and each is rendered at the same column as the start of its own date cell -- the
parser asserts that column alignment rather than trusting the order blindly.

Usage (from the repo root)::

    uv run python backtest/ground_truth/parse_pdf_tables.py            # parse + write
    uv run python backtest/ground_truth/parse_pdf_tables.py --check    # verify only

If ``pdftotext`` or the PDF is unavailable, ``--trades-txt`` / ``--returns-txt``
accept pre-extracted layout text instead.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
DEFAULT_PDF = REPO_ROOT / "Model_Backtest_20260725202812.pdf"

TRADES_PAGES = (20, 24)
RETURNS_PAGE = 12

# Holdings coverage required by the design contract.
HOLDINGS_START = (1997, 1)
HOLDINGS_END = (2026, 7)  # inclusive -> 355 months
RETURNS_START = (1997, 1)
RETURNS_END = (2026, 6)  # inclusive -> 354 months

EXPECTED_TRADE_COUNT = 96

TICKERS = ("VFINX", "VGTSX", "VFITX")

# " 1 01/01/199 08/31/199 12/31/199 Initial Entry ... (VFINX) ... "
TRADE_RE = re.compile(
    r"^\s*(?P<num>\d{1,3})\s+"
    r"(?P<start>\d{2}/\d{2}/\d{3})\s+"
    r"(?P<end>\d{2}/\d{2}/\d{3})\s+"
    r"(?P<trade>\d{2}/\d{2}/\d{3})\s+"
    r"(?P<type>Initial Entry|Signal|Open Trade)\b"
    r".*\((?P<ticker>" + "|".join(TICKERS) + r")\)"
)
CONT_RE = re.compile(r"^\s*\d(?:\s+\d){2}\s*$")

# "   1997      6.22%    0.79%  ...  33.19%   1.70%   $60,725   $81,604"
YEAR_RE = re.compile(r"^\s*(?P<year>(?:19|20)\d{2})\s+(?P<rest>-?\d+\.\d{2}%.*)$")
PCT_RE = re.compile(r"-?\d+\.\d{2}%")


# --------------------------------------------------------------------------
# text extraction
# --------------------------------------------------------------------------
def pdftotext_layout(pdf: Path, first_page: int, last_page: int) -> str:
    """Return ``pdftotext -layout`` output for a page range."""
    if shutil.which("pdftotext") is None:
        raise RuntimeError("pdftotext not found; pass --trades-txt/--returns-txt")
    if not pdf.exists():
        raise FileNotFoundError(f"PDF not found: {pdf}")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "page.txt"
        subprocess.run(
            [
                "pdftotext",
                "-layout",
                "-f",
                str(first_page),
                "-l",
                str(last_page),
                str(pdf),
                str(out),
            ],
            check=True,
            capture_output=True,
        )
        return out.read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------
# trades
# --------------------------------------------------------------------------
def _iso(mmddy: str, last_digit: str) -> str:
    """'01/01/199' + '7' -> '1997-01-01'."""
    month, day, year3 = mmddy.split("/")
    return f"{year3}{last_digit}-{month}-{day}"


def parse_trades(text: str) -> list[dict]:
    """Parse the Model trades table into a list of trade dicts."""
    lines = text.splitlines()
    trades: list[dict] = []
    i = 0
    while i < len(lines):
        m = TRADE_RE.match(lines[i])
        if not m:
            i += 1
            continue
        # find the continuation line holding the three wrapped year digits
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j >= len(lines) or not CONT_RE.match(lines[j]):
            raise ValueError(
                f"trade row {m.group('num')} has no continuation line: {lines[i]!r}"
            )
        cont = lines[j]

        digits = [(mm.start(), mm.group()) for mm in re.finditer(r"\d", cont)]
        if len(digits) != 3:
            raise ValueError(f"expected 3 wrapped digits, got {len(digits)}: {cont!r}")

        # column alignment check: wrapped digit k sits at the start column of date k
        for (col, _digit), field in zip(digits, ("start", "end", "trade"), strict=True):
            expected = m.start(field)
            if col != expected:
                raise ValueError(
                    f"trade {m.group('num')}: wrapped digit for {field} at col {col}, "
                    f"date cell starts at col {expected}"
                )

        trades.append(
            {
                "num": int(m.group("num")),
                "start": _iso(m.group("start"), digits[0][1]),
                "end": _iso(m.group("end"), digits[1][1]),
                "trade_date": _iso(m.group("trade"), digits[2][1]),
                "ticker": m.group("ticker"),
            }
        )
        i = j + 1
    return trades


# --------------------------------------------------------------------------
# monthly returns
# --------------------------------------------------------------------------
def parse_monthly_returns(text: str) -> tuple[dict[str, float], dict[int, float]]:
    """Return ({'YYYY-MM': decimal}, {year: reported_total_decimal})."""
    monthly: dict[str, float] = {}
    totals: dict[int, float] = {}
    for line in text.splitlines():
        m = YEAR_RE.match(line)
        if not m:
            continue
        year = int(m.group("year"))
        pcts = PCT_RE.findall(m.group("rest"))
        # trailing two percentages are the annual Total and Inflation columns
        if len(pcts) < 3:
            raise ValueError(f"unexpected returns row: {line!r}")
        months, total = pcts[:-2], pcts[-2]
        if len(months) > 12:
            raise ValueError(f"{year}: {len(months)} monthly values")
        for idx, pct in enumerate(months, start=1):
            monthly[f"{year}-{idx:02d}"] = round(float(pct.rstrip("%")) / 100.0, 6)
        totals[year] = round(float(total.rstrip("%")) / 100.0, 6)
    return monthly, totals


# --------------------------------------------------------------------------
# holdings
# --------------------------------------------------------------------------
def month_range(start: tuple[int, int], end: tuple[int, int]) -> list[str]:
    keys = []
    y, mo = start
    while (y, mo) <= end:
        keys.append(f"{y:04d}-{mo:02d}")
        mo += 1
        if mo == 13:
            y, mo = y + 1, 1
    return keys


def holdings_from_trades(trades: list[dict]) -> dict[str, str]:
    """Expand trades into a month -> ticker map (each trade covers start..end)."""
    holdings: dict[str, str] = {}
    for t in trades:
        sy, sm = int(t["start"][:4]), int(t["start"][5:7])
        ey, em = int(t["end"][:4]), int(t["end"][5:7])
        for key in month_range((sy, sm), (ey, em)):
            if key in holdings:
                raise ValueError(f"overlapping trades cover {key} (trade {t['num']})")
            holdings[key] = t["ticker"]
    return holdings


# --------------------------------------------------------------------------
# verification (design-doc spot-check anchors + internal consistency)
# --------------------------------------------------------------------------
TRADE_ANCHORS = [
    # num, start, end, trade_date, ticker  (None = not asserted)
    (1, "1997-01-01", "1998-08-31", "1996-12-31", "VFINX"),
    (8, None, None, "2000-09-29", "VFITX"),
    (50, None, None, "2016-01-29", "VFITX"),
    (96, "2026-07-01", "2026-07-31", "2026-06-30", "VGTSX"),
]
RETURN_ANCHORS = {
    "1997-01": 0.0622,
    "2008-06": -0.0899,
    "2020-11": 0.1293,
    "2026-06": -0.0096,
}
YEAR_TOTAL_ANCHORS = {
    1997: 0.3319,
    2003: 0.4866,
    2015: -0.0904,
    2022: -0.2140,
    2026: 0.0454,
}
TOTAL_TOLERANCE = 0.001  # 0.1 percentage points


def verify(
    trades: list[dict], holdings: dict[str, str], monthly: dict[str, float]
) -> list[str]:
    """Return a list of human-readable verification lines; raise on any failure."""
    log: list[str] = []
    by_num = {t["num"]: t for t in trades}

    assert len(trades) == EXPECTED_TRADE_COUNT, f"trade count {len(trades)}"
    log.append(f"PASS trade count == {EXPECTED_TRADE_COUNT}")

    for num, start, end, trade_date, ticker in TRADE_ANCHORS:
        t = by_num[num]
        for field, want in (
            ("start", start),
            ("end", end),
            ("trade_date", trade_date),
            ("ticker", ticker),
        ):
            if want is not None:
                assert t[field] == want, f"trade {num}.{field}: {t[field]} != {want}"
        log.append(
            f"PASS trade {num} anchor: {t['start']}..{t['end']} traded {t['trade_date']} {t['ticker']}"
        )

    # trades tile the timeline: next start is the day after the previous end
    from datetime import date, timedelta

    for a, b in zip(trades, trades[1:], strict=False):
        end = date.fromisoformat(a["end"])
        assert date.fromisoformat(b["start"]) == end + timedelta(days=1), (
            f"gap/overlap between trades {a['num']} and {b['num']}"
        )
        assert a["ticker"] != b["ticker"], (
            f"trades {a['num']}/{b['num']} repeat {a['ticker']}"
        )
        assert date.fromisoformat(a["trade_date"]) < date.fromisoformat(a["start"]), (
            f"trade {a['num']} trade_date is not before its start"
        )
    log.append(
        "PASS trades contiguous (each start == previous end + 1 day), no repeated consecutive ticker"
    )
    log.append(
        "PASS every trade_date precedes its holding period (end-of-prior-month signal)"
    )

    # start dates are month firsts, end dates are month ends
    for t in trades:
        assert t["start"][8:] == "01", f"trade {t['num']} start not a month first"
        e = date.fromisoformat(t["end"])
        assert (e + timedelta(days=1)).day == 1, f"trade {t['num']} end not a month end"
    log.append("PASS every trade starts on the 1st and ends on a month end")

    # holdings gapless + derived exactly from trades
    expected_months = month_range(HOLDINGS_START, HOLDINGS_END)
    assert list(holdings) == expected_months, "holdings not gapless / wrong range"
    assert len(holdings) == 355, f"{len(holdings)} holding months"
    log.append(
        f"PASS holdings gapless {expected_months[0]}..{expected_months[-1]} ({len(holdings)} months)"
    )

    for t in trades:
        months = month_range(
            (int(t["start"][:4]), int(t["start"][5:7])),
            (int(t["end"][:4]), int(t["end"][5:7])),
        )
        assert all(holdings[m] == t["ticker"] for m in months), (
            f"holdings disagree with trade {t['num']}"
        )
    covered = sum(
        len(
            month_range(
                (int(t["start"][:4]), int(t["start"][5:7])),
                (int(t["end"][:4]), int(t["end"][5:7])),
            )
        )
        for t in trades
    )
    assert covered == len(holdings), (
        f"trade months {covered} != holdings {len(holdings)}"
    )
    log.append(
        "PASS every holding month traces to exactly one trade (no overlap, full coverage)"
    )
    assert set(holdings.values()) <= set(TICKERS), "unexpected ticker"
    counts = {tk: sum(1 for v in holdings.values() if v == tk) for tk in TICKERS}
    log.append(f"INFO holding months by ticker: {counts}")

    # monthly returns gapless + anchors
    expected_ret_months = month_range(RETURNS_START, RETURNS_END)
    assert list(monthly) == expected_ret_months, (
        "monthly returns not gapless / wrong range"
    )
    assert len(monthly) == 354, f"{len(monthly)} monthly returns"
    log.append(
        f"PASS monthly returns gapless {expected_ret_months[0]}..{expected_ret_months[-1]} ({len(monthly)} entries)"
    )
    for key, want in RETURN_ANCHORS.items():
        assert abs(monthly[key] - want) < 1e-9, f"{key}: {monthly[key]} != {want}"
        log.append(f"PASS monthly return anchor {key} == {want}")

    # compounded monthly returns reproduce the reported annual totals
    for year, reported in YEAR_TOTAL_ANCHORS.items():
        acc = 1.0
        n = 0
        for key, r in monthly.items():
            if key.startswith(f"{year}-"):
                acc *= 1.0 + r
                n += 1
        compounded = acc - 1.0
        diff = compounded - reported
        assert abs(diff) <= TOTAL_TOLERANCE, (
            f"{year}: compounded {compounded:.4%} vs reported {reported:.2%}"
        )
        log.append(
            f"PASS {year} compounded {n} months = {compounded:+.4%} vs PV total {reported:+.2%} "
            f"(diff {diff * 100:+.3f}pp)"
        )
    return log


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    ap.add_argument(
        "--trades-txt", type=Path, help="pre-extracted layout text for pages 20-24"
    )
    ap.add_argument(
        "--returns-txt", type=Path, help="pre-extracted layout text for page 12"
    )
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument(
        "--check", action="store_true", help="parse and verify, write nothing"
    )
    args = ap.parse_args(argv)

    trades_text = (
        args.trades_txt.read_text(encoding="utf-8", errors="replace")
        if args.trades_txt
        else pdftotext_layout(args.pdf, *TRADES_PAGES)
    )
    returns_text = (
        args.returns_txt.read_text(encoding="utf-8", errors="replace")
        if args.returns_txt
        else pdftotext_layout(args.pdf, RETURNS_PAGE, RETURNS_PAGE)
    )

    trades = parse_trades(trades_text)
    monthly, reported_totals = parse_monthly_returns(returns_text)
    monthly = {
        k: v
        for k, v in monthly.items()
        if k in set(month_range(RETURNS_START, RETURNS_END))
    }
    holdings = holdings_from_trades(trades)

    # ---- structural invariants (fail loudly rather than write bad data) ----
    assert len(trades) == EXPECTED_TRADE_COUNT, f"{len(trades)} trades"
    assert [t["num"] for t in trades] == list(range(1, EXPECTED_TRADE_COUNT + 1))
    for a, b in zip(trades, trades[1:], strict=False):
        assert a["end"] < b["start"], f"trades {a['num']}/{b['num']} out of order"
    expected_months = month_range(HOLDINGS_START, HOLDINGS_END)
    assert list(holdings) == expected_months, "holdings are not gapless"
    holdings = {k: holdings[k] for k in expected_months}
    assert list(monthly) == month_range(RETURNS_START, RETURNS_END), (
        "monthly returns are not gapless"
    )

    for line in verify(trades, holdings, monthly):
        print(line)

    # every year: compounded monthly returns vs the report's Total column
    year_diffs = {
        y: math.prod(1.0 + r for k, r in monthly.items() if k.startswith(f"{y}-"))
        - 1.0
        - tot
        for y, tot in reported_totals.items()
    }
    worst_year = max(year_diffs, key=lambda y: abs(year_diffs[y]))
    print(
        f"INFO all {len(year_diffs)} years compounded vs reported total; "
        f"worst = {worst_year} {year_diffs[worst_year] * 100:+.3f}pp"
    )

    if args.check:
        print(
            f"OK: {len(trades)} trades, {len(holdings)} holding months, {len(monthly)} monthly returns"
        )
        return 0

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "pv_trades.json").write_text(json.dumps(trades, indent=2) + "\n")
    (args.out_dir / "pv_holdings.json").write_text(
        json.dumps(holdings, indent=2) + "\n"
    )
    (args.out_dir / "pv_monthly_returns.json").write_text(
        json.dumps(monthly, indent=2) + "\n"
    )
    print(
        f"wrote pv_trades.json ({len(trades)}), pv_holdings.json ({len(holdings)}), pv_monthly_returns.json ({len(monthly)}) -> {args.out_dir}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
