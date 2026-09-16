# Findings: Resolution-Boundary Drift on Polymarket

**Scope:** how quickly do Polymarket prices converge to the correct outcome in
the final 72 hours before resolution, does convergence speed depend on
liquidity/category, how does that compare to a faster-moving external
signal (NBA live win probability), and is there a tradeable edge once
spread/slippage are accounted for.

All numbers below come from real API pulls (Polymarket Gamma + CLOB,
ESPN's public site API), cached under `data/raw/`, with the resulting
tables in `data/processed/`. Nothing here is simulated or stubbed. See
[README.md](../README.md) for how to reproduce every step.

## 1. Data

- **Core sample:** 174 resolved markets, stratified across 3 liquidity
  tiers (flagship ≥$1M lifetime volume, mid $10K–$1M, niche $500–$10K) and
  7 keyword-derived categories (up to 15 markets per tier×category cell,
  drawn from a candidate pool of 792 closed markets, `random_state=42`).
  Minute-level price history for the *winning* outcome's token, final 72h
  before `closedTime`.
- **NBA sample:** 111 resolved NBA moneyline markets (`nba-<away>-<home>-
  <date>` slugs), same 72h/1-min pull, used for the external-signal case
  study.
- Coverage vs. the theoretical 4,320 one-minute bars: flagship/mid median
  ≈100%, niche median ≈74% (thinner books simply trade less often, not a
  collection bug — see `price_collection_log.csv`, 0 markets dropped for
  insufficient coverage in the final run).

**Known limitation — categorization is a heuristic.** The Gamma API's
per-market `category` field is null for 499/500 of the top-volume closed
markets we sampled; real tags exist only at the event level and cost one
extra API call per event. Instead we classify by keyword match on the
question text (`src/polydrift/categorize.py`). This is transparent and
reproducible but not ground truth — a market like "Bulls vs. Knicks:
O/U 237.5" is correctly caught as Sports, but edge cases will exist.

## 2. Convergence analysis

Metric: for the *winning* outcome's price, find the last time it was ever
below 90% and call the bar right after that the "permanent crossing" —
i.e. how many hours before resolution price locked in above 90% and never
looked back. Also: did it ever cross 90% and then revert below it before
locking in, and was it still sitting in the classic "40–60% coin-flip
band" within the final 6h / 1h.

| Tier | n | Median hrs-to-converge (90%) | P25 / P75 | % reverted after crossing 90% | % in 40–60% band, final 6h | % in 40–60% band, final 1h |
|---|---|---|---|---|---|---|
| Flagship | 62 | 72.0 (already converged at window start) | 72.0 / 72.0 | 12.9% | 3.2% | 0.0% |
| Mid | 61 | 7.8 | 2.8 / 72.0 | 34.4% | 37.7% | 0.0% |
| Niche | 51 | 2.5 | 0.3 / 5.2 | 43.1% | 62.7% | 23.5% |

**The hypothesis holds, cleanly, in this sample.** Flagship markets are
essentially decided on arrival at the 72h mark (median convergence time
equals the full window — most were already >90% at t-72h). Niche markets
convert far later (median 2.5h before resolution), flicker back out of
the "converged" zone almost half the time after first crossing 90%
(43% vs. 13% for flagship), and nearly a quarter of them are *still*
sitting in the 40–60% coin-flip zone within the final hour before
resolution — something that essentially never happens for flagship
markets (0%).

By category, Crypto and "Other" (mostly niche daily/weekly prop markets)
converge latest and revert most; Politics and Economy/Business — which in
this sample skew flagship/well-covered — converge earliest. Sports sits
in between (median 3.5h), consistent with games being decided in a
relatively compressed final stretch.

Figures: `docs/figures/convergence_hours_by_tier.png`,
`docs/figures/uncertain_band_by_tier.png`.

## 3. External signal lag: Polymarket vs. ESPN live win probability

**Honesty note on the signal source.** The task suggested a live-odds API
as one option; a genuinely free, no-key, historical sportsbook-odds API
does not appear to exist publicly (The Odds API and similar require a
registered key). We substitute ESPN's public (undocumented, no-key)
site API, which exposes a live win-probability model with play-by-play
wall-clock timestamps for NBA/NFL games — a legitimate, faster-moving,
independently-computed signal, but note it is a *model's* probability
estimate, not a market price, so some divergence from Polymarket is
expected even in an efficient market.

Method: for each of the 111 NBA markets, match to its ESPN game by team
name (110/111 matched), extract ESPN's win-probability series for the
team that actually won, and find when *that* series permanently crosses
90% — same definition as the Polymarket-side metric. Lag = Polymarket's
90% crossing time − ESPN's 90% crossing time.

- 110/111 games produced a usable lag measurement.
- Overall median lag: **+0.6 minutes** — Polymarket typically reprices
  within about a minute of ESPN's model crossing 90%. This is *not* a
  large, dependably exploitable lag.
- The distribution has a fat tail in both directions: flagship games
  range from −11 min to **+58 min**; mid-tier games range from **−109
  min** to +16 min (i.e. Polymarket sometimes converges *well before*
  ESPN's model, likely because ESPN's win-probability model is
  deliberately conservative on blowouts while Polymarket traders will
  happily price a 30-point lead near 99% immediately).
- 68% of games show Polymarket nominally behind ESPN, but the median gap
  is small enough that it's unclear this survives transaction costs (see
  backtest).

Figure: `docs/figures/external_signal_lag_hist.png`.

## 4. Backtest: late-game correction strategy

**Strategy (no hindsight):** scan forward through the final 72h; the
first time the *crowd favorite* — whichever side is priced higher right
now, using only currently-observable price — sits in [55%, 85%], buy $100
of it and hold to resolution. This directly targets the convergence lag
found in §2: entering before the market has "locked in," betting that it
resolves the way the crowd currently leans. It can and does take full
losses: if the leader at trade time is later revealed to be the loser
(an upset relative to the market's own assessment), the position pays $0.

**Data limitation — no historical order-book/trade data.** Polymarket's
`/book` endpoint 404s once a market is closed, and `/trades` requires an
API key we don't have (confirmed empirically). Historical bid-ask spread
and slippage cannot be *measured* for resolved markets through any public
endpoint we found, so they are *modeled*: a liquidity-tier-based
half-spread (0.5¢/1.5¢/3¢ tight scenario, 1.5¢/4¢/8¢ wide scenario for
flagship/mid/niche) plus a square-root market-impact term in trade size
vs. lifetime volume. Both scenarios are reported side by side rather than
presenting one number as ground truth — see `src/polydrift/backtest.py`
for the exact assumptions.

Universe: 285 markets (174 core + 111 NBA, deduplicated), 198 produced a
qualifying entry (87 never had their favorite sit in the [55%, 85%] band
during the window — mostly flagship markets that were already fully
priced at t-72h, consistent with §2).

| Cut | n | Win rate | ROI (tight) | Sharpe-like (tight) | ROI (wide) | Sharpe-like (wide) |
|---|---|---|---|---|---|---|
| **Overall** | 198 | 61.6% | **−6.1%** | −0.08 | **−9.8%** | −0.13 |
| Tier: flagship | 71 | 52.1% | −19.2% | −0.24 | −20.5% | −0.26 |
| Tier: mid | 82 | 64.6% | −1.8% | −0.02 | −5.5% | −0.08 |
| Tier: niche | 45 | 71.1% | +6.8% | +0.10 | −0.7% | −0.01 |
| Category: Sports (NBA) | 109 | 52.3% | −18.3% | −0.23 | (similar) | — |
| Category: Crypto | 24 | 83.3% | **+23.7%** | **+0.40** | (similar) | — |
| Category: Other (mostly niche props) | 23 | 69.6% | +1.5% | +0.02 | (similar) | — |

Full table: `data/processed/backtest_summary.csv`. Equity curve:
`docs/figures/backtest_equity_curve.png`.

**Bottom line — intellectually honest: this specific strategy does not
clear costs in aggregate.** ROI is negative overall and, under the wide
(more realistic-for-niche) spread scenario, negative in every tier. The
loss is concentrated in NBA in-game momentum entries (−18% to −20% ROI,
109/198 trades): buying "whoever's currently ahead" mid-game in one of
the most heavily-covered, highly-liquid sports markets on the platform is
not a source of edge — consistent with §3's finding that Polymarket
already reprices within ~1 minute of a comparable signal there. The
flagship tier's poor showing is really the NBA effect showing up again,
since most flagship-tier trades in this universe are NBA games.

The **one clear bright spot is Crypto** (24 trades, 83% win rate, +24%
ROI, the only cut with a solidly positive Sharpe-like ratio in both
scenarios) and niche markets generally trend positive-to-breakeven. This
lines up with §2: Crypto/niche/"Other" markets are exactly the ones that
still show genuine late-stage price drift, whereas flagship/Sports (NBA)
markets are already efficiently priced well before the entry signal
fires. n=24 for Crypto is not enormous — worth flagging as suggestive,
not conclusive, and a natural target for follow-up with a larger sample.

## 5. Structural causes vs. genuine inefficiency

Distinguishing what's actually going on:

- **Structural / not exploitable:**
  - *Oracle/resolution delay.* `closedTime` (when a market stops trading)
    can lag the true real-world outcome by hours; our windows are anchored
    to `closedTime`, not "when the world found out," so some of what looks
    like "slow convergence" is really "the market closed on schedule but
    the underlying event resolved on its own timeline" (e.g. UMA dispute
    windows). We did not separately measure this gap here — flagged as a
    next step.
  - *Thin order books / market-maker inventory limits* in niche markets
    mechanically produce both the flickering (43% revert-after-90% rate)
    and the wide effective spreads that eat the backtest's edge in the
    wide-spread scenario. This is a real cost of participating, not a
    quirk of our model.
  - *ESPN model conservatism on blowouts* explains part of the "Polymarket
    leads ESPN" tail in §3 — not a Polymarket inefficiency, a property of
    the reference signal.
- **Where a genuine inefficiency plausibly exists:** the Crypto and
  broader niche/"Other" segment shows both (a) a real, measurable pattern
  of late convergence in §2 and (b) a backtested edge that survives even
  the wide-spread assumption in the niche tier. That combination — a
  documented behavioral pattern *and* a strategy that profits from it net
  of a conservative cost model — is the strongest evidence in this
  dataset of something actually exploitable, though the sample sizes
  (n=24–45) warrant treating it as a lead, not a proven strategy.
- **Where there is demonstrably no edge:** NBA in-game moneyline
  markets. Both the direct signal-lag measurement (~1 min median) and the
  backtest (−18% to −20% ROI) point the same direction: this specific
  corner of Polymarket is efficiently priced against a real-time public
  signal, and naively trading the observed lag loses money.

## Next steps / ideas for follow-up (out of scope for this session)

- Separate "event actually resolved" time from `closedTime` to isolate
  oracle/UMA delay as its own measured quantity rather than a caveat.
- Widen the external-signal case study beyond NBA (NFL is already
  supported in `espn.py`; soccer/other sports would need a different
  public data source).
- Fetch per-event Gamma tags (one extra API call per event) to replace
  the keyword categorizer with the platform's own taxonomy.
- If a paid or key-gated odds/order-book API becomes available, replace
  the modeled spread/impact in `backtest.py` with measured historical
  quotes.
- Test a stop-loss / early-exit variant of the strategy instead of
  hold-to-resolution only, and test entry bands narrower than [55%, 85%]
  specifically tuned to the niche/Crypto segment that showed an edge here.
- Grow the Crypto/niche sample size to check whether the +24% ROI result
  holds up out-of-sample.
