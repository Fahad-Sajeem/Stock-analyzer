# Stock Analyzer — Indian Swing-Trade Analyzer

A techno-funda hybrid that scans Indian equities (NSE), screens them on
fundamentals, analyzes technicals, and produces swing-trade signals with
entry / stop-loss / target levels.

**The full design lives in [PLAN.md](PLAN.md). Read it before contributing.**
Build order is Phases 1–7 (PLAN.md Section 12), each with a definition-of-done.

> ⚠️ Educational analytics, not investment advice. Securities markets are
> subject to market risks. Personal-use tool (see PLAN.md Section 16 on SEBI).

---

## Status

| Phase | Scope | State |
|-------|-------|-------|
| **1 — Foundations & Data Ingestion** | packaging, config, DuckDB schema, NSE client, bhavcopy EOD ingest, yfinance backfill, corporate-action adjustment, validation, trading calendar, CLI | ✅ **built & working** |
| **2 — Fundamental engine** | Layer 0 tradability filter, hard rejection rules, 0-100 quality score (banks/NBFC branch), yfinance + Screener fetchers, weekly universe job | ✅ **built & working** |
| **3 — Technical engine** | hand-rolled indicators, structure (S/R, bases), index/VIX ingest, market regime, relative strength, weekly gate | ✅ **built & working** |
| **4 — Setups & signals** | 5 setup scanners (A-E), candlestick confirmation, levels engine (entry/SL/T1/T2/R:R), composite score, regime + weekly gating, ranked publisher | ✅ **built & working** |
| **5 — Backtesting** | event-loop trade simulator (look-ahead-free), India cost model, IS/OOS metrics, acceptance gates, weekly-gate ablation, report cards | ✅ **built** — verdict: no setup passes (see below) |
| **6 — Risk, tracking & outputs** | position sizing + caps, correlation cap, gap stress, signal-outcome tracker (observational engine), plotly signal charts, daily markdown report, Telegram digest | ✅ **built & working** |
| **7 — Automation & dashboard** | `analyzer daily` full EOD pipeline, FastAPI dashboard (`analyzer serve`), live Setup-E via results calendar, research-quality tags on signals | ✅ **built & working** |
| 6.5 — News layer | macro/sector/stock news modifiers (PLAN §17) | ⬜ deferred (not needed for the observational run) |

**Everything deferred lives in one place: [PLAN.md Section 18 — Roadmap](PLAN.md#18-future-enhancements)**
(tiered by trigger: near-term operational time-bombs → when signals flow → the
~Jan 2027 re-evaluation → post-validation → research backlog).

## Setup

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"   # Windows
# source .venv/bin/activate && pip install -e ".[dev]" # POSIX
```

## Usage (Phase 1 CLI)

```bash
analyzer initdb                       # create/verify DuckDB schema
analyzer sync-symbols                 # refresh symbol master (SYMBOL<->ISIN) from NSE
analyzer ingest --date 2026-06-30     # ingest one day's EOD bhavcopy (default: today)
analyzer backfill --symbols RELIANCE TCS --years 5   # history via yfinance
analyzer backfill                     # backfill ALL symbols in the master (slow)
analyzer universe --limit 50 --show 20  # build approved universe (Layer 0 + fundamentals)
analyzer technicals --regime 10       # ingest indices, compute indicators + market regime
analyzer scan --date 2025-08-07 --reasons  # generate swing signals (entry/SL/T1/T2/R:R)
analyzer backtest                     # IS/OOS backtest + acceptance gates -> reports/backtest/
analyzer backtest --weekly-gate       # same, with the §7.6 weekly gate (ablation)
analyzer backfill --bulk              # full-universe backfill (chunked multi-ticker, fast)
analyzer tune --setup B_pullback_trend --limit-symbols 500  # in-sample grid search
analyzer status                       # row counts + recent job runs
```

```bash
analyzer daily                        # FULL evening pipeline: ingest -> indicators ->
                                      # regime -> signals -> outcomes -> charts -> report
analyzer track                        # update signal outcomes + live stats
analyzer report --date 2026-07-03     # rebuild a daily report
analyzer serve --port 8000            # dashboard at http://127.0.0.1:8000
analyzer backup                       # verified snapshot of DB + config + research log
```

Typical first-run order: `initdb` → `sync-symbols` → `backfill --bulk` →
`technicals` → `universe` → `daily`.

> **Cloud hosting:** the whole system fits Oracle Cloud's free tier (Ampere A1)
> — see **[DEPLOY.md](DEPLOY.md)**. The nightly pipeline uses incremental
> indicator recompute (only new dates), so it runs light on small instances.

### Scheduling the observational run (Windows)

Register the evening pipeline (19:00 IST, Mon–Fri) with Task Scheduler:

```powershell
schtasks /Create /TN "StockAnalyzerDaily" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 19:00 `
  /TR "D:\GitHub\PersonalGitHub\Claude\Stock-analyzer\.venv\Scripts\analyzer.exe daily"
```

The pipeline is idempotent (safe to re-run) and holiday-aware (skips non-trading
days). Telegram digests: set `notify.telegram_enabled: true` in config.yaml and
export `ANALYZER_TG_BOT_TOKEN` / `ANALYZER_TG_CHAT_ID`.

### Tracking YOUR holdings + intraday alerts (the "CG Power case")

Log your actual trades so the system watches them for you:

```bash
# Buying a SYSTEM SIGNAL: no --sl needed — the position links to the signal and
# inherits its stop/T1/T2; your fill-vs-signal slippage is recorded to `fills`.
analyzer position add CGPOWER 100 902

# Discretionary buy (no signal): you MUST state your stop.
analyzer position add CGPOWER 100 900 --sl 880

analyzer position list                            # holdings with live P&L
analyzer position set-sl CGPOWER 890              # tighten a stop (never widens)
analyzer position sell CGPOWER --price 897        # sell the whole position
analyzer position sell CGPOWER --qty 40 --price 950  # PARTIAL — rest stays tracked
analyzer watch --force                            # manual intraday check
```

Signal-linked buys are validated against the plan: an expired signal is refused
(stale setups are void), and paying >2% above the signal entry logs a
chase warning on the position.

Two watchers then cover every holding:
- **Intraday** — the `StockAnalyzerWatch` task runs every 15 min during market
  hours (9:15–15:35 IST) and alerts on Telegram when a holding **breaches your
  stop** or **drops > 3% vs previous close** (news-shock detector). One alert
  per position/type/day. Quote latency is ~15–30 min (yfinance) — realistic for
  a free feed, and far better than finding out after close.
- **Evening** — the daily report's "Open-position actions" section (stop
  breaches on close, T1 book-half instructions) is included in the Telegram
  digest.

**Telegram setup (once, ~3 minutes):**
1. In Telegram, talk to `@BotFather` → `/newbot` → copy the bot token.
2. Send any message to your new bot, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`.
3. Set env vars (user-level): `setx ANALYZER_TG_BOT_TOKEN "<token>"` and
   `setx ANALYZER_TG_CHAT_ID "<chat id>"`.
4. In config.yaml set `notify.telegram_enabled: true`.
Until then, alerts are still evaluated and written to `logs/watch_*.log` and
`alerts_log` — nothing is lost, just not pushed.

**Log trades by texting the bot (two-way).** Run `analyzer bot` (one instance,
long-running) and message your bot directly:

```
buy CGPOWER 100 902           → logs a buy; stop taken from the signal if one exists
buy CGPOWER 100 902 sl 880    → discretionary buy with an explicit stop
sell CGPOWER 950              → sells the whole position at 950
sell CGPOWER 40 950          → PARTIAL: sells 40, keeps 60 tracked (also = "book half at T1")
sl CGPOWER 910               → tightens the stop (never widens)
list                         → holdings with live P&L
help
```

Security: the bot only obeys messages from your `ANALYZER_TG_CHAT_ID` — anyone
else who finds the bot is ignored. Keep the daily/watch schedulers and the bot
as separate processes (the bot polls continuously; run just one instance). On
Linux, run it as a systemd service (see DEPLOY.md); on Windows, an at-logon
scheduled task or a terminal window.

### The observational run (why this exists)

All strategies FAILED holdout validation (see RESEARCH_LOG.md) — so the system
publishes signals **to collect live outcomes, not to be traded**. Every signal
carries an UNVALIDATED warning plus a `research-quality-gate` tag; the tracker
replays each signal against subsequent real prices using the exact backtest
semantics and accumulates results in `signal_outcomes`. After 2+ quarters, the
live dataset supports an honest re-evaluation (especially of the PEAD+quality
hypothesis, holdout-descriptive PF 2.08 on n=40).

### Backtest verdict (Phase 5) — READ THIS
Validated on the **full ~2,700-symbol NSE universe** (10 years), with each setup's
parameters **tuned on the in-sample window only** (2015–2021) then validated
out-of-sample (2022–2026). **No setup passes** the acceptance gates (profit factor
≥ 1.5, ≥300 trades, max DD < 25%, ≥70% positive years):

| Setup | In-sample PF (tuned) | Out-of-sample PF | Verdict |
|---|---|---|---|
| Breakout (A) | 1.15 | **0.98** | ❌ |
| Pullback (B) | 1.40 | **0.80** | ❌ |
| Squeeze (D) | 1.13 | **0.81** | ❌ |
| Mean-rev (C) | ~0 trades | 0.32 | ❌ |

**The key finding: in-sample tuning reached PF 1.15–1.40, but every setup collapses
to PF 0.80–0.98 out-of-sample (net-losing after costs) — a clean, honest
demonstration of overfitting.** Simple published technical swing setups have no
durable edge on the broad Indian universe once realistic costs (~0.5% round-trip)
are modeled. This is the system working exactly as designed: Phase 5 exists to stop
unvalidated setups from being trusted. `config.signals.validated_setups` is
**empty**; every published signal carries an `UNVALIDATED` warning.
**Do not trade these signals with real money.**

A formal research program followed — see **[RESEARCH_PLAN.md](RESEARCH_PLAN.md)**
and **[RESEARCH_LOG.md](RESEARCH_LOG.md)**. Outcome (2026-07-04): the apparatus
was validated (it detects the documented momentum anomaly, +9pp CAGR in DEV),
point-in-time fundamentals (800 symbols) and a real results calendar (78k
announcement dates) were built, and three candidates (quality-momentum portfolio,
quality-gated breakout, PEAD) went to a pre-registered 3-run holdout —
**all three FAILED their frozen criteria** (momentum breached the DD cap;
breakout PF 1.32 < 1.5; PEAD's DEV edge decayed to PF 1.03). **No strategy is
validated for real capital; every published signal carries an UNVALIDATED
warning.** The honest deliverable is the measurement apparatus + data assets +
three cleanly killed candidates — not a profitable strategy.

### Known gaps (Phase 2)
- Promoter holding uses a yfinance proxy; **real shareholding-pattern / pledge /
  results-calendar ingestion (task 2.2) is not yet built** — so the pledge
  hard-filter can't fire on live data until that lands. Deterministic scoring &
  filter logic are fully unit-tested; the fetchers are the fragile part.

All thresholds live in [`config.yaml`](config.yaml) — never hardcode numbers.

## Architecture (Phase 1 modules)

```
src/analyzer/
├── config.py            # typed config loader (pydantic) — reads config.yaml
├── logging_setup.py     # structlog console/JSON logging
├── cli.py               # command-line entry point
├── db/
│   ├── schema.sql       # DuckDB schema (18 tables, idempotent)
│   └── repository.py    # the ONLY place SQL lives; upsert + job_runs logging
├── data/
│   ├── nse_client.py    # hardened NSE gateway (cookies, retry, rate-limit, cache)
│   ├── bhavcopy.py      # daily EOD ingest (OHLCV + delivery %)
│   ├── symbols.py       # symbol master from EQUITY_L.csv (ISIN identity)
│   ├── calendar.py      # NSE trading calendar + holiday seed
│   ├── adjust.py        # corporate-action price adjustment -> prices_adj
│   ├── validation.py    # OHLC integrity / big-move / gap checks
│   └── yfinance_backfill.py  # historical backfill (cross-validation source)
├── fundamentals/
│   ├── models.py        # FundamentalInputs contract + QualityResult
│   ├── ratios.py        # CAGR / YoY / ratio helpers (pure)
│   ├── hard_filters.py  # §6.1 rejection rules (pure)
│   ├── quality_score.py # §6.2 0-100 score, banks/NBFC branch (pure)
│   ├── tradability.py   # Layer 0 gates from price DB
│   ├── fetch_yfinance.py# yfinance -> FundamentalInputs (fallback source)
│   └── fetch_screener.py# Screener.in top-ratios parser (preferred, fragile)
├── technicals/
│   ├── indicators.py    # EMA/SMA/RSI/ATR/ADX/MACD/Bollinger/OBV/Supertrend/ROC (pure)
│   ├── structure.py     # fractal swings, S/R clustering, base detection, 52w (pure)
│   ├── compute.py       # per-symbol indicators + cross-sectional RS -> indicators_daily
│   └── regime.py        # BULL/BEAR/NEUTRAL from Nifty + breadth + VIX
├── setups/
│   ├── base.py          # RawSignal, regime-aware active-setup selector
│   ├── breakout.py / pullback.py / mean_reversion.py / squeeze.py / earnings_momentum.py
│   └── candlesticks.py  # confirmation patterns (never a trigger alone)
├── signals/
│   ├── levels.py        # entry / stop-loss / T1 / T2 / R:R gate (§8.2-8.4)
│   ├── scoring.py       # composite score + grade (§8.6)
│   └── publisher.py     # scan -> gate -> levels -> score -> rank -> signals table
├── backtest/
│   ├── costs.py         # India round-trip cost model (STT + charges + slippage)
│   ├── engine.py        # event-loop single-trade simulator (look-ahead-free)
│   ├── metrics.py       # win rate / profit factor / max DD / CAGR + acceptance gates
│   ├── runner.py        # replay setups over history (reuses live scanners)
│   └── reports.py       # per-setup markdown report cards
├── risk/
│   ├── position_sizing.py  # sizing + capital/liquidity/sector/correlation/gap caps
│   └── tracker.py       # signal-outcome tracker (observational engine) + actions
├── charts/plotly_chart.py  # annotated candlestick per signal -> charts/
├── notify/
│   ├── report.py        # daily markdown report
│   └── telegram.py      # digest push (no extra deps; env-var credentials)
├── api/app.py           # FastAPI dashboard (signals/regime/performance/universe)
├── research/            # research programme code (see RESEARCH_PLAN/LOG)
│   ├── momentum.py / quality_panel.py / fundamentals_history.py
│   ├── results_calendar.py / r3_quality_overlay.py / r3_control.py / r4_pead.py
│   └── decision_gate.py
└── jobs/
    ├── ingest.py        # daily ingest + backfill orchestration
    ├── universe.py      # weekly universe job -> universe table
    ├── technicals.py    # indices -> indicators -> regime
    ├── signals.py       # daily signal generation
    ├── backtest.py      # IS/OOS backtest orchestration + gates
    ├── tune.py          # in-sample-only grid search
    └── daily.py         # the full evening pipeline (analyzer daily)
```

## Data sources

- **Primary EOD:** NSE `sec_bhavdata_full` bhavcopy (OHLCV + delivery in one file).
- **Symbol master:** NSE `EQUITY_L.csv` (ISIN is the stable key).
- **Backfill / cross-check:** yfinance (`.NS`). Not the primary daily feed.
- All NSE access is funneled through `NseClient`; if NSE changes an endpoint,
  that is the single file to fix.

## Tests

```bash
.venv/Scripts/python.exe -m pytest -q
```

Includes golden tests for corporate-action adjustment (a known 1:1 bonus must
halve pre-ex-date prices without firing a false crash), idempotent upserts, the
trading calendar, and the bhavcopy parser.

## Design invariants (do not break)

1. **Adjusted prices only** feed technicals (`prices_adj`), never raw.
2. **Idempotent pipelines** — re-running a day upserts, never duplicates.
3. **All SQL in `repository.py`**; all NSE access in `nse_client.py`.
4. **Config-driven** — every threshold in `config.yaml`.
5. **Every job logs** to `job_runs` (observability).
