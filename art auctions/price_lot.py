#!/usr/bin/env python3
"""
price_lot.py — Estimate exceedance probabilities for an auction lot.

Reads the normalized CSV in this folder, fits three views (empirical at two
cohort breadths plus a log-normal model), and prints calibrated probabilities
P(sold > strike) for a user-specified estimate band and strike list.

Usage:
    python3 price_lot.py --gbp-low 20 --gbp-high 30 \
                         --strikes 20 22 24 26 28 30 32 34 36 38 40 \
                         --fx 1.33

    # USD estimate instead of GBP:
    python3 price_lot.py --usd-low 26.6 --usd-high 39.9 \
                         --strikes 20 22 24 26 28 30 32 34 36 38 40

    # Artist adjustment (blue-chip / scarcity premium):
    python3 price_lot.py --gbp-low 20 --gbp-high 30 \
                         --strikes 30 32 34 36 38 40 --artist-bump 0.10

Strikes are interpreted in millions USD.
"""

import argparse
import csv
import math
import statistics as st
import sys
from pathlib import Path

CSV_PATH = Path(__file__).parent / "sothebys_auction_normalized.csv"


def load_rows():
    rows = []
    with open(CSV_PATH) as f:
        for r in csv.DictReader(f):
            rows.append({
                "lot": r["lot"],
                "artist": r["artist"],
                "mid": float(r["midpoint"]),
                "ratio": float(r["sold_over_mid"]),
                "logratio": float(r["log_sold_over_mid"]),
                "pos": float(r["norm_position"]),
            })
    return rows


def pick_cohorts(rows, target_mid):
    """Return three cohorts ordered from narrow-and-direct to broad-and-noisy.

    The narrowest cohort that still has n >= 8 is preferred as the primary anchor.
    """
    bands = [
        ("≥$25M",       lambda m: m >= 25_000_000),
        ("$10–25M",     lambda m: 10_000_000 <= m < 25_000_000),
        ("≥$10M",       lambda m: m >= 10_000_000),
        ("$2–10M",      lambda m: 2_000_000   <= m < 10_000_000),
        ("≥$2M",        lambda m: m >= 2_000_000),
        ("$500K–5M",    lambda m: 500_000     <= m < 5_000_000),
        ("≥$500K",      lambda m: m >= 500_000),
    ]
    if target_mid >= 10_000_000:
        primary = "≥$10M"
        secondary = "≥$2M"
        broad = "≥$500K"
    elif target_mid >= 2_000_000:
        primary = "$2–10M"
        secondary = "≥$2M"
        broad = "$500K–5M"
    else:
        primary = "$500K–5M"
        secondary = "≥$500K"
        broad = "≥$500K"
    chosen = {name: [r for r in rows if test(r["mid"])]
              for name, test in bands if name in (primary, secondary, broad)}
    return primary, secondary, broad, chosen


def lognormal_sf(ratio, mu, sigma):
    """Survival function of a log-normal with given log-mean / log-stdev."""
    z = (math.log(ratio) - mu) / sigma
    return 0.5 * math.erfc(z / math.sqrt(2))


def fit_lognormal(cohort):
    lrs = [r["logratio"] for r in cohort]
    if len(lrs) < 2:
        return None, None
    return st.mean(lrs), st.stdev(lrs)


def position_label(strike_usd_m, lo_usd, mid_usd, hi_usd):
    s = strike_usd_m * 1_000_000
    ratio = s / mid_usd
    if s < lo_usd * 0.92:
        return "far below low"
    if s < lo_usd * 0.99:
        return "just below low"
    if s < lo_usd * 1.02:
        return "at low"
    if s < mid_usd * 0.95:
        return "low half of band"
    if s < mid_usd * 1.05:
        return "near midpoint"
    if s < hi_usd * 0.95:
        return "upper half of band"
    if s < hi_usd * 1.02:
        return "at high"
    if s < hi_usd * 1.10:
        return "just above high"
    return "well above high"


def calibrate(strike_ratio, mid_usd, fits, artist_bump=0.0):
    """Blend empirical and log-normal evidence into a single calibrated probability.

    Rules of thumb baked in:
      - Floor (ratio < 0.85): lean toward higher-of-empirical-and-model.
        Real-world guarantee dynamics typically lift this above the model.
      - Body (0.85 ≤ ratio ≤ 1.10): average the model and the primary empirical.
      - Tail (ratio > 1.10): lean toward lower-of-model-and-narrowest-empirical,
        because the broader empirical cohorts inherit small-lot tail behavior.
    Artist bump shifts the entire curve in log-ratio space (positive = bullish).
    """
    primary_emp = fits["primary_emp"]
    secondary_emp = fits["secondary_emp"]
    broad_emp = fits["broad_emp"]
    model = fits["model_p"]

    # Apply artist bump in log-space by translating the strike ratio
    adj_ratio = strike_ratio / math.exp(artist_bump)

    # If artist bump is non-zero, recompute the model with shifted ratio
    if artist_bump != 0.0:
        mu, sigma = fits["model_params"]
        model = lognormal_sf(adj_ratio, mu, sigma)
        # Empirical signals don't get a direct shift; we re-evaluate them at
        # the shifted ratio level using the same cohort.
        primary_emp = sum(1 for r in fits["primary_cohort"] if r["ratio"] > adj_ratio) / max(1, len(fits["primary_cohort"]))
        secondary_emp = sum(1 for r in fits["secondary_cohort"] if r["ratio"] > adj_ratio) / max(1, len(fits["secondary_cohort"]))

    if strike_ratio < 0.85:
        # Floor zone: weight higher of model + primary, plus small guarantee bump
        base = max(model, primary_emp)
        return min(0.99, base + 0.02)
    if strike_ratio <= 1.10:
        # Body: equally weight model and primary empirical
        return 0.5 * model + 0.5 * primary_emp
    # Tail: thin out broader-cohort signal (it's contaminated by small-lot lots)
    return 0.6 * model + 0.4 * primary_emp


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--gbp-low", type=float, help="Low estimate in £M GBP")
    grp.add_argument("--usd-low", type=float, help="Low estimate in $M USD")
    ap.add_argument("--gbp-high", type=float, help="High estimate in £M GBP (if --gbp-low)")
    ap.add_argument("--usd-high", type=float, help="High estimate in $M USD (if --usd-low)")
    ap.add_argument("--fx", type=float, default=1.33, help="GBP/USD rate (default 1.33)")
    ap.add_argument("--strikes", type=float, nargs="+", required=True,
                    help="Strike levels in $M USD")
    ap.add_argument("--artist-bump", type=float, default=0.0,
                    help="Log-ratio shift for artist-specific adjustment. "
                         "+0.10 ≈ ~10%% multiplicative upside; -0.10 ≈ haircut")
    args = ap.parse_args()

    if args.gbp_low is not None:
        if args.gbp_high is None:
            ap.error("--gbp-high required with --gbp-low")
        lo_usd = args.gbp_low * args.fx * 1_000_000
        hi_usd = args.gbp_high * args.fx * 1_000_000
        band_label = f"£{args.gbp_low}–{args.gbp_high}M at FX {args.fx}"
    else:
        if args.usd_high is None:
            ap.error("--usd-high required with --usd-low")
        lo_usd = args.usd_low * 1_000_000
        hi_usd = args.usd_high * 1_000_000
        band_label = f"${args.usd_low}–{args.usd_high}M USD"

    mid_usd = (lo_usd + hi_usd) / 2

    rows = load_rows()
    primary_name, secondary_name, broad_name, cohorts = pick_cohorts(rows, mid_usd)
    primary, secondary, broad = cohorts[primary_name], cohorts[secondary_name], cohorts[broad_name]

    mu, sigma = fit_lognormal(primary if len(primary) >= 5 else secondary)
    if mu is None:
        mu, sigma = fit_lognormal(broad)

    print(f"\nLot estimate: {band_label}")
    print(f"  Low ${lo_usd:>14,.0f}    Mid ${mid_usd:>14,.0f}    High ${hi_usd:>14,.0f}")
    print(f"\nCohorts used (n):")
    print(f"  primary   = {primary_name:<14}  n={len(primary)}")
    print(f"  secondary = {secondary_name:<14}  n={len(secondary)}")
    print(f"  broad     = {broad_name:<14}  n={len(broad)}")
    print(f"  log-normal fit on primary: μ={mu:+.3f}, σ={sigma:.3f}")
    if args.artist_bump:
        print(f"  artist bump: {args.artist_bump:+.2f} log-ratio")

    print(f"\n{'strike':<10} {'ratio':>6}  {'pos':<22}  "
          f"{'emp/' + primary_name:>14}  {'emp/' + secondary_name:>14}  "
          f"{'model':>8}  {'CALIB':>7}")
    print("-" * 100)
    for strike_m in args.strikes:
        s_usd = strike_m * 1_000_000
        ratio = s_usd / mid_usd
        pos = position_label(strike_m, lo_usd, mid_usd, hi_usd)

        kp = sum(1 for r in primary if r["ratio"] > ratio)
        ks = sum(1 for r in secondary if r["ratio"] > ratio)
        pp = kp / len(primary) if primary else 0
        ps = ks / len(secondary) if secondary else 0
        pm = lognormal_sf(ratio, mu, sigma)

        fits = {
            "primary_emp": pp,
            "secondary_emp": ps,
            "broad_emp": sum(1 for r in broad if r["ratio"] > ratio) / max(1, len(broad)),
            "model_p": pm,
            "model_params": (mu, sigma),
            "primary_cohort": primary,
            "secondary_cohort": secondary,
        }
        cal = calibrate(ratio, mid_usd, fits, args.artist_bump)
        print(f">${strike_m:<6.2f}M  {ratio:>6.2f}  {pos:<22}  "
              f"{pp:>9.0%} ({kp}/{len(primary)})  {ps:>9.0%} ({ks}/{len(secondary)})  "
              f"{pm:>7.0%}  {cal:>6.0%}")


if __name__ == "__main__":
    main()
