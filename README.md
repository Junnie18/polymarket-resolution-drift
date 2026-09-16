# Resolution-Boundary Drift Analysis — Polymarket

How quickly do Polymarket prices converge to the correct outcome (0 or 1)
in the final 72 hours before resolution, does that depend on liquidity
tier or category, how does it compare to a faster-moving external signal,
and is there an exploitable lag once realistic spread/slippage are
accounted for?

**Read [docs/findings.md](docs/findings.md) for the actual results and
writeup.** This README covers project structure and how to reproduce the
pipeline.

## TL;DR result

Niche/low-volume markets do converge later and flicker more than
flagship markets (confirmed, not assumed — see §2 of the findings). A
naive strategy that trades on that lag is a net loser in aggregate once
modeled spread/impact are applied (−6% to −10% ROI across 198 trades),
driven almost entirely by NBA in-game entries against an efficient
market; the one segment with a real, sensible edge in this sample is
Crypto (+24% ROI, n=24) and niche markets generally (roughly breakeven to
positive). Full honest breakdown, including limitations, in the findings
doc.

## Project structure

```
src/polydrift/          Library code
  http_cache.py            Shared HTTP client: retry/backoff + on-disk JSON cache
  gamma.py                 Gamma API client (market/event metadata)
  clob.py                  CLOB API client (minute-level price history)
  espn.py                  ESPN public site-API client (live win probability)
  categorize.py            Keyword-based market categorization
  nba_match.py              Polymarket <-> ESPN game matching
  convergence.py           Convergence metrics (threshold crossing, reversion, uncertain band)
  backtest.py              Late-game-correction strategy + modeled slippage

scripts/                 Pipeline, run in order (01 -> 06)
  01_collect_markets.py      Build candidate pool of resolved markets across tiers/categories
  02_collect_price_history.py  Stratified sample + 72h minute-level price pull
  03_convergence_analysis.py   Convergence metrics + tier/category summaries + plots
  04_collect_nba_markets.py    Resolved NBA moneyline markets (external-signal case study)
  05_external_signal_lag.py    Match to ESPN, measure signal lag
  06_backtest.py                Run the backtest under tight/wide spread scenarios

data/
  raw/                    Cached raw API responses (reproducibility; do not re-fetch to rerun analysis)
  processed/               All derived tables (candidates, sample, metrics, trades, summaries)
  processed/price_series/  Per-market 72h price series (one CSV per market_id)

docs/
  findings.md              The actual writeup: methodology, results, limitations, next steps
  figures/                  Generated plots

tests/                    Unit tests for the pure-function pieces (no network calls)
```

## Setup

Requires Python 3.9+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .          # installs the polydrift package for scripts/tests to import
```

## Running the pipeline end to end

Every script is idempotent and cache-aware: raw API responses are cached
under `data/raw/`, so rerunning a script after the first time only hits
the network for anything not already cached (nothing, if `data/raw/` is
already populated from this repo).

```bash
python3 scripts/01_collect_markets.py          # -> data/processed/market_candidates.csv
python3 scripts/02_collect_price_history.py    # -> data/processed/market_sample.csv, price_series/
python3 scripts/03_convergence_analysis.py     # -> data/processed/convergence_*.csv, docs/figures/
python3 scripts/04_collect_nba_markets.py      # -> data/processed/nba_markets.csv, price_series/
python3 scripts/05_external_signal_lag.py      # -> data/processed/external_signal_lag.csv
python3 scripts/06_backtest.py                 # -> data/processed/backtest_*.csv, docs/figures/
```

All outputs from the last full run are already committed in this repo,
so you can read `docs/findings.md` and the CSVs/figures under
`data/processed/` and `docs/figures/` without running anything.

## Tests / checks

```bash
source .venv/bin/activate
ruff check src scripts tests
pytest tests/ -q
```

Tests cover the pure-function analysis logic (convergence threshold
detection, backtest entry/slippage/P&L) with synthetic data — no network
access required, so they run in CI or offline.

## Data sources and honesty notes

- **Gamma API** (`https://gamma-api.polymarket.com`) — market/event
  metadata. Public, unauthenticated, no API key exists for the endpoints
  used.
- **CLOB API** (`https://clob.polymarket.com`) — `/prices-history` for
  minute-level price series. Public, unauthenticated. `/book` and
  `/trades` (order-book depth and trade-level fills) were tested and
  confirmed **not** accessible without an API key / for closed markets —
  this is why the backtest's spread/slippage is a documented *model*,
  not measured data (see `src/polydrift/backtest.py` docstring and
  `docs/findings.md` §4).
- **ESPN site API** (`https://site.api.espn.com`) — used as the
  faster-moving external signal for the NBA case study (live
  win-probability with wall-clock timestamps). Public, undocumented,
  no key required. A dedicated live-odds/sportsbook API would be a
  cleaner signal but requires a registered key; this is the best
  available free substitute, and is called out explicitly as such in the
  findings.
- Market **category** is a keyword heuristic on the question text, not
  the platform's own taxonomy (which requires a separate per-event API
  call) — see `src/polydrift/categorize.py` and the limitation noted in
  `docs/findings.md` §1.
