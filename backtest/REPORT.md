# PV Parity Backtest — `dm.signals` vs Portfolio Visualizer Dual Momentum Model

Engine: `src/dm/signals.py` (weights 33/33/34 over 1/3/6-month total returns). Universe: VFINX (US) / VGTSX (Intl) / VFITX (out-of-market). Prices: yfinance daily `auto_adjust=True` reduced to month-end closes. Anchors: 1996-12..2026-06 (355 signals, holdings for 1997-01..2026-07).

Ground truth: `backtest/ground_truth/*.json` parsed from `Model_Backtest_20260725202812.pdf`.

## Headline

| Metric | Value | Bar | Pass |
| --- | --- | --- | --- |
| Holdings match rate | **99.72%** (354/355) | >= 96% | YES |
| Matched-month return diffs < 20bps | 352/353 | mostly | YES |
| Full-period TWRR CAGR | **13.58%** (PV 13.52%) | within 0.5pp | YES |
| Chosen risk-free variant | `a_dtb3_prior_simple` | design default (a) preferred | YES |

## Risk-free variant comparison

| Variant | Series | Alignment | Compounding | Matches | Match rate | Bond months | Mean RF score (bps) | Max RF diff vs (a) (bps) | Signal diffs vs (a) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `a_dtb3_prior_simple` | DTB3 | prior | simple | 354/355 | 99.72% | 80 | 63.0 | 0.0 | 0 |
| `b_tb3ms_prior_simple` | TB3MS | prior | simple | 354/355 | 99.72% | 80 | 63.0 | 7.9 | 0 |
| `c_dtb3_prior_geom` | DTB3 | prior | geometric | 354/355 | 99.72% | 80 | 61.8 | 4.6 | 0 |
| `c_tb3ms_prior_geom` | TB3MS | prior | geometric | 354/355 | 99.72% | 80 | 61.8 | 7.0 | 0 |
| `d_dtb3_same_simple` | DTB3 | same | simple | 354/355 | 99.72% | 80 | 62.9 | 17.4 | 0 |
| `d_tb3ms_same_simple` | TB3MS | same | simple | 354/355 | 99.72% | 80 | 62.9 | 10.4 | 0 |
| `e_dtb3_same_geom` | DTB3 | same | geometric | 354/355 | 99.72% | 80 | 61.7 | 18.6 | 0 |
| `e_tb3ms_same_geom` | TB3MS | same | geometric | 354/355 | 99.72% | 80 | 61.7 | 10.9 | 0 |

PV holds VFITX in 80 of 355 months.

The variants are not degenerate — their risk-free scores differ by up to 18.6bps in individual months — yet **every variant produces an identical 355-month signal series**. The risk-free level simply never lands inside the gap between the winning equity score and zero excess in a way that any of these accrual conventions disagree about, so this backtest cannot discriminate between them. The design default (a) is therefore kept.

Variant definitions:

* `a_dtb3_prior_simple` — DTB3 sampled at the prior month end, rate/12, compounded (design default)
* `b_tb3ms_prior_simple` — TB3MS monthly average of the prior month, rate/12, compounded
* `c_dtb3_prior_geom` — DTB3 sampled at the prior month end, (1+rate)^(1/12)-1
* `c_tb3ms_prior_geom` — TB3MS monthly average of the prior month, (1+rate)^(1/12)-1
* `d_dtb3_same_simple` — DTB3 sampled at the same month end, rate/12, compounded
* `d_tb3ms_same_simple` — TB3MS monthly average of the same month, rate/12, compounded
* `e_dtb3_same_geom` — DTB3 sampled at the same month end, (1+rate)^(1/12)-1
* `e_tb3ms_same_geom` — TB3MS monthly average of the same month, (1+rate)^(1/12)-1

Selection rule: highest holdings match rate; ties resolved in favour of the design default (a). Chosen: `a_dtb3_prior_simple` — DTB3 sampled at the prior month end, rate/12, compounded (design default).

## Holdings mismatches

1 of 355 months (0.28%). `gap` is how far the decision was from flipping: the US-vs-Intl score gap for relative-momentum flips, or the winner's excess over the risk-free score for in/out-of-market flips. Gaps above 30bps are flagged suspicious.

| Month | Anchor | Predicted | PV | US score | Intl score | RF score | Gap (bps) | Kind | Suspicious |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2003-06 | 2003-05-30 | VGTSX | VFINX | +7.902% | +8.653% | +0.322% | 75.1 | relative | YES |

### Mismatch investigation

#### 2003-06 — we hold VGTSX, PV holds VFINX

**Verdict: Yahoo price/dividend data artifact at the window boundary, not an engine bug.**

PV's trade 13 holds VFINX for 2003-04..2003-06 and trade 14 switches to VGTSX on
2003-06-30; our engine switches one month early, at the 2003-05-30 anchor. The 1- and
3-month lookbacks are not decisive (US wins the 3-month, Intl the 1-month); the flip is
driven by the 6-month window, which runs from the **2002-11-29** close — and that close
is corrupt in Yahoo's mutual-fund NAV series:

* On 2002-11-29 (the half session after Thanksgiving) Yahoo repeats the 2002-11-27 NAV
  verbatim for both funds: VFINX 86.91 -> 86.91 and VGTSX 8.09 -> 8.09, while `^SP500TR`
  moved -0.266% that day. VFINX tracks `^SP500TR` to within 2bps in every surrounding
  month except Nov 2002 (+27.0bps) and Dec 2002 (-27.5bps) — the exact signature of one
  stale month-end print. The stale VFINX close is ~27bps too high, which understates our
  US 6-month return by ~27bps (ours 3.535% vs `^SP500TR` 3.868%).
* VGTSX's 2002-11-29 NAV is stale by the same mechanism, and foreign markets moved on the
  2002-11-28/11-29 sessions it should have captured (Nikkei +3.39%/+0.42%, FTSE
  +0.99%/-0.38%, DAX +0.44%/-1.20%; EFA +0.51% over the two days). A true 11/29 NAV
  ~0.5-1.0% above the stale 8.09 lowers our Intl 6-month return by roughly that much.
* Yahoo also carries three VGTSX dividends that break the fund's otherwise strictly
  annual December distribution pattern (1996-2007): 0.043 on 2002-11-29, 0.045 on
  2003-01-31 and 0.042 on 2003-02-28. The latter two sit inside this 6-month window and
  inflate the Intl 6-month return by ~124bps; dropping them alone cuts the score gap from
  75bps to ~33bps.

Stacking the three corrections closes ~72bps of the 75bps gap: the spurious dividends are
worth 0.34 x 124bps = 42bps, the stale VFINX close 0.34 x 27bps = 9bps, and a VGTSX
11/29 NAV 0.6% above the stale print (the EFA-implied figure, the most conservative of the
proxies above) 0.34 x 60bps = 20bps. Only the VGTSX NAV term is an estimate; the other two
are measured. That lands the decision on the knife edge PV came down on the other side of.
Every other cross-check at this point in the series is exact: our VFINX months
2003-04/05 reproduce PV to 0.4bps, our VGTSX months 2003-07..12 reproduce PV to <=0.5bps,
and compounding our VFINX 2003-04..06 returns gives +15.389% against PV's trade-13
figure of 15.39%. No change to `src/dm` is warranted.


## Calendar and robustness checks

* **Anchor dates vs PV trade dates**: all 96 PV trade dates equal the month-end trading day our engine anchored on that month (0 mismatches). PV and this backtest agree on what "month end" means, on every trade, for 30 years.
* **Holding blocks**: model 96 vs PV 96 contiguous holdings over 1997-01..2026-07.
* **Decision margins**: of 354 matched months, 28 sat within 30bps of flipping and 7 within 10bps. The margin is the smaller of the US-vs-Intl score gap and the winner's excess over the risk-free score.

Ten tightest matched months (most exposed to data noise):

| Month | Held | Margin (bps) | US score | Intl score | RF score |
| --- | --- | --- | --- | --- | --- |
| 2017-05 | VFINX | 0.2 | +6.527% | +6.525% | +0.159% |
| 2001-04 | VFITX | 1.6 | -12.411% | -12.394% | +1.516% |
| 2019-11 | VGTSX | 2.3 | +2.894% | +2.917% | +0.569% |
| 2000-12 | VFITX | 4.5 | -9.265% | -9.310% | +1.699% |
| 2020-03 | VFITX | 6.5 | -3.911% | -3.845% | +0.450% |
| 2025-03 | VGTSX | 7.8 | +1.285% | +1.363% | +1.235% |
| 2013-03 | VGTSX | 9.9 | +5.944% | +6.043% | +0.022% |
| 2025-04 | VFITX | 11.4 | -3.977% | +1.092% | +1.207% |
| 2019-06 | VFITX | 13.5 | -2.103% | -1.968% | +0.667% |
| 2011-08 | VFITX | 16.5 | -1.781% | -1.946% | +0.019% |

## Monthly return diffs (model vs PV)

| Metric | Value |
| --- | --- |
| Months compared | 354 |
| Mean abs diff | 1.14 bps |
| Max abs diff | 139.7 bps |
| Months > 50bps | 1 |
| Matched-holding months | 353 |
| Matched mean abs diff | 0.74 bps |
| Matched max abs diff | 22.2 bps |
| Matched months > 20bps | 1 |
| Matched months > 50bps | 0 |
| Price-data-only mean abs diff (PV holdings, our prices) | 0.74 bps |
| Price-data-only max abs diff | 22.2 bps |

Ten largest monthly diffs:

| Month | Held | PV held | Model return | PV return | Diff (bps) |
| --- | --- | --- | --- | --- | --- |
| 2003-06 | VGTSX | VFINX | +2.66% | +1.26% | +139.7 |
| 2020-08 | VFINX | VFINX | +7.40% | +7.18% | +22.2 |
| 2020-09 | VFINX | VFINX | -4.01% | -3.81% | -19.6 |
| 2002-12 | VFITX | VFITX | +2.76% | +2.58% | +18.0 |
| 2002-11 | VFITX | VFITX | -1.48% | -1.32% | -15.6 |
| 2013-03 | VGTSX | VGTSX | +0.90% | +0.77% | +12.6 |
| 2001-06 | VFITX | VFITX | +0.40% | +0.30% | +9.8 |
| 2001-07 | VFITX | VFITX | +2.64% | +2.73% | -8.9 |
| 2009-08 | VGTSX | VGTSX | +3.42% | +3.50% | -7.5 |
| 2009-09 | VGTSX | VGTSX | +5.22% | +5.15% | +7.4 |

## Per-year returns

| Year | Months | Model | PV | Diff (pp) |
| --- | --- | --- | --- | --- |
| 1997 | 12 | +33.18% | +33.19% | -0.02 |
| 1998 | 12 | +14.93% | +14.93% | -0.00 |
| 1999 | 12 | +30.00% | +29.99% | +0.01 |
| 2000 | 12 | -0.67% | -0.69% | +0.02 |
| 2001 | 12 | +7.61% | +7.56% | +0.06 |
| 2002 | 12 | +3.27% | +3.24% | +0.03 |
| 2003 | 12 | +50.76% | +48.64% | +2.12 |
| 2004 | 12 | +19.16% | +19.16% | +0.00 |
| 2005 | 12 | +4.65% | +4.65% | +0.01 |
| 2006 | 12 | +22.39% | +22.41% | -0.01 |
| 2007 | 12 | +15.51% | +15.51% | -0.00 |
| 2008 | 12 | +2.38% | +2.34% | +0.04 |
| 2009 | 12 | +37.65% | +37.62% | +0.03 |
| 2010 | 12 | +14.47% | +14.45% | +0.03 |
| 2011 | 12 | +6.00% | +5.99% | +0.01 |
| 2012 | 12 | +16.04% | +16.04% | +0.01 |
| 2013 | 12 | +21.73% | +21.57% | +0.15 |
| 2014 | 12 | +13.52% | +13.49% | +0.03 |
| 2015 | 12 | -9.04% | -9.03% | -0.02 |
| 2016 | 12 | -1.32% | -1.33% | +0.01 |
| 2017 | 12 | +21.47% | +21.54% | -0.08 |
| 2018 | 12 | +4.61% | +4.63% | -0.02 |
| 2019 | 12 | +11.31% | +11.30% | +0.01 |
| 2020 | 12 | +22.21% | +22.23% | -0.01 |
| 2021 | 12 | +25.85% | +25.87% | -0.02 |
| 2022 | 12 | -21.40% | -21.41% | +0.01 |
| 2023 | 12 | +15.37% | +15.39% | -0.02 |
| 2024 | 12 | +20.06% | +20.06% | -0.00 |
| 2025 | 12 | +20.24% | +20.22% | +0.02 |
| 2026 | 6 | +4.55% | +4.56% | -0.01 |

## Full-period growth

| Metric | Model | PV |
| --- | --- | --- |
| Cumulative return (354 months) | 4,178.4% | 4,108.0% |
| TWRR CAGR | 13.58% | 13.52% |
| Growth of $10,000 | $427,844 | $420,805 |

PV's headline CAGR of 29.23% reflects $5,000 inflation-adjusted monthly contributions and is not comparable; TWRR (13.52%) is the cashflow-free figure this backtest reproduces.
