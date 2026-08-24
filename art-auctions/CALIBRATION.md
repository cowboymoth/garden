# Auction Lot Pricing — Methodology Notes

## What this is

A small framework for estimating **P(hammer price > strike)** for an auction lot,
calibrated against three Sotheby's sales that together cover 298 ratio'd lots:

| sale | n (ratio'd) | character |
|---|---|---|
| Contemporary Day Auction (15 May 2026) | 248 | broad, mostly small lots; well-populated $25K–$2M |
| Mnuchin "Collector at Heart" Evening (14 May 2026) | 9 | single-collector evening sale; strong outcomes |
| Modern Evening Auction (19 May 2026) | 41 | typical evening sale; balanced high-end |

The combined dataset is in `sothebys_auction_normalized.csv` (one row per
sold lot with numeric estimates). Lots marked "Estimate Upon Request" or "Bidding
is closed" at snapshot time are excluded from the normalized stats.

## The core ratio

For each lot we compute two scale-free quantities:

- **`sold_over_mid`** = sold price / midpoint of estimate band
- **`norm_position`** = (sold − low) / (high − low) — 0 at low, 1 at high, >1 above

`sold_over_mid` is the primary working unit because it's symmetric in log-space
and behaves better statistically. The data are heavy right-tailed in raw space
but reasonably log-normal once you bucket by lot size.

## Three lenses on each strike

For any candidate strike (in $M USD), we compute:

1. **Empirical (primary cohort)** — fraction of comparable lots that sold above
   that ratio. Cohort breadth is chosen by target midpoint:
   - Target ≥ $10M → primary cohort is `≥$10M` (n=9)
   - Target $2–10M → primary cohort is `$2–10M` (n=29)
   - Target < $2M → primary cohort is `$500K–5M` (n=77)

2. **Empirical (secondary, broader cohort)** — sanity-check using a wider band.
   Useful for noticing when the primary cohort is too sparse to trust.

3. **Log-normal model** — fit `log(ratio)` to a normal on the primary cohort,
   take its survival function at `log(strike / midpoint)`.

## Calibration rules

Three regimes by strike ratio, codified in `price_lot.py:calibrate()`:

### Floor zone — ratio < 0.85 (below the low estimate)

```
P_cal = min(0.99,  max(model, primary_emp) + 0.02)
```

We take the *higher* of model and empirical, then add a small guarantee bump.
The guarantee bump reflects the structural reality that high-end lots almost
always carry a third-party guarantee or irrevocable bid, set near the low
estimate — so the floor at the low is more robust than the raw model implies.
Capped at 99% to retain residual uncertainty.

### Body — 0.85 ≤ ratio ≤ 1.10 (within or just past the estimate band)

```
P_cal = 0.5 * model + 0.5 * primary_emp
```

Equal-weight blend. In this zone the model and the primary cohort empirical
typically agree within 5–10 points, and the average is a sensible compromise.

### Tail — ratio > 1.10 (materially above the high estimate)

```
P_cal = 0.6 * model + 0.4 * primary_emp
```

We slightly down-weight the empirical relative to the model. Why: the broader
cohorts get contaminated by small-lot tail behavior (small lots have fatter
right tails — a $5K lot jumping to $50K is routine; a $5M lot jumping to $50M
isn't). The log-normal fit on the narrow cohort accounts for this; the raw
empirical doesn't.

## Why the cohort breadth matters

Empirical "% of lots that beat their high estimate" by midpoint:

| band | % above high | median ratio |
|---|---|---|
| <$25K | 61% | 1.64× |
| $25–100K | 60% | 1.39× |
| $100–500K | 66% | 1.42× |
| $500K–2M | 55% | 1.21× |
| $2M–10M | 38% | 1.07× |
| $10M–25M | 33% | 1.02× |
| > $25M | 0% (3/3) | 0.98× |

The pattern is monotonic and economically sensible:

- **Smaller lots** have many bidders, low bid increments, and modest price
  anchoring → fat right tails.
- **Larger lots** have thin bidder pools (single-digit serious bidders globally),
  large bid increments, and heavy price anchoring via comparables / guarantees
  → tight distributions centered on the midpoint.

Using a one-size-fits-all empirical estimate for a $30M lot would massively
overstate the tail. The cohort-by-midpoint approach corrects for this.

## Trend slope (for very out-of-data extrapolation)

Across the full combined dataset:

```
log(sold / midpoint) = +c − 0.080 * log(midpoint)   (r = −0.29)
```

Every doubling of estimate is associated with ~5–6% less overshoot. **Important
caveat:** this slope was fit mostly on sub-$2M lots, so extrapolating it 3–4
doublings beyond the cohort center can over-correct. The Mnuchin Rothko at
$85M midpoint sold at ratio 1.01, but the trend model would have predicted
~0.80. So `price_lot.py` uses the trend slope only implicitly via cohort
selection, not as an aggressive correction.

## Artist / lot-specific adjustments

The `--artist-bump` flag shifts the entire curve in log-ratio space:

| signal | suggested bump |
|---|---|
| Blue-chip scarce artist with recent record (e.g. Klimt portrait) | +0.10 |
| Strong single-owner provenance (Mnuchin, Rockefeller, etc.) | +0.05 |
| Fresh-to-market work | +0.05 |
| Recently re-offered / known to have been shopped | −0.10 |
| Condition issues or difficult restitution history | −0.10 |
| Publicly guaranteed at the low estimate | (no shift, but caps upside; deduct ~5 points from tail) |

Bumps stack additively in log-space. A bump of +0.10 corresponds to roughly
+10% multiplicative shift in expected sold/midpoint ratio.

## Known limitations

1. **n=9 in the ≥$10M cohort.** Even with the Modern Evening Sale data, the
   high-end is sparse. The log-normal σ on this cohort is 0.131 — probably too
   tight given the sample. The model is therefore somewhat overconfident in
   its tails for very expensive lots. The calibration partly compensates with
   the floor bump and the 0.6/0.4 tail blend, but treat anything ratio > 1.20
   for $25M+ lots as roughly ±10 points uncertain.
2. **No guarantee status field.** We can't see which lots carried published
   guarantees / irrevocable bids. The floor-zone +0.02 bump is a flat estimate
   of the guarantee-induced lift; in reality, guaranteed lots have a much
   firmer floor (close to 100% above low) and unguaranteed lots have a softer
   one (~75%).
3. **Snapshot bias.** 73 lots in the day sale were "Bidding is closed" or had
   no result yet at snapshot time. These are systematically the higher-end and
   slower-bidding lots in that sale; their inclusion might widen the tail.
4. **One sale week.** The whole calibration is from May 2026 sales. Market
   conditions shift; treat the calibration as appropriate for "current"
   conditions and re-fit if the market mood changes (e.g., after a major
   underperforming evening sale or a public correction).

## How to use the script

```
python3 price_lot.py --gbp-low LOW --gbp-high HIGH \
                     --strikes S1 S2 S3 ... \
                     [--fx 1.33] \
                     [--artist-bump +0.10]
```

Strikes and outputs are always in $M USD. The script prints both the three
lenses and a single calibrated probability column. The intent is for you
(or me) to see the inputs to the calibration, not just the answer — so you can
override with judgment when the data is sparse or when external information
(provenance, condition, pre-sale press) materially shifts the prior.

## Worked example: £20–30M GBP lot at FX 1.33

```
$ python3 price_lot.py --gbp-low 20 --gbp-high 30 \
                       --strikes 30 34 38 40

  Low $26,600,000   Mid $33,250,000   High $39,900,000
  primary cohort = ≥$10M (n=9)
  log-normal: μ=-0.004, σ=0.131

  strike    ratio    pos                   emp/≥$10M    model   CALIB
  > $30M    0.90    low half of band       78% (7/9)    78%     78%
  > $34M    1.02    near midpoint          33% (3/9)    42%     38%
  > $38M    1.14    at high                22% (2/9)    15%     18%
  > $40M    1.20    at high                 0% (0/9)     7%      4%
```

With a Klimt-style artist bump (`--artist-bump 0.10`), the upper-strike
probabilities lift ~5–10 points, pulling the curve closer to a blue-chip
scarcity scenario.

## Extending the dataset

To add a new sale:
1. Drop the sale PDF into this folder.
2. Use PyMuPDF (`pip install pymupdf` via system python) to extract text.
3. Parse each lot as: lot number → artist → title (possibly multi-line) →
   "Estimate: LO - HI USD" → "Lot Sold: X USD" / "Bidding is closed" /
   "Estimate Upon Request".
4. Append to `sothebys_auction.csv` with a unique lot prefix (e.g. `M` for
   Mnuchin, `E` for Evening, `D` could be for next Day sale) to avoid
   collisions.
5. Rebuild `sothebys_auction_normalized.csv` (filter out EUR / Bidding-closed
   rows and recompute midpoint, ratio, log-ratio).
6. Re-run any of the historical scenarios through `price_lot.py` — outputs
   automatically reflect the updated dataset.
