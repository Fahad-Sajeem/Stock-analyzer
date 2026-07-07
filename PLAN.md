# Indian Stock Market Swing-Trade Analyzer — Master Build Plan

> **Audience:** AI agents and developers building this system. Read this entire document before writing code.
> **Goal:** A system that scans **every listed Indian stock (NSE + BSE)**, combines **fundamental screening** with **technical analysis**, and outputs **actionable swing-trade signals** — each with a precise **entry point, exit target(s), and stop-loss**.
> **Trading style targeted:** Swing trading (holding period ~2 days to 6 weeks).
> **Status:** Planning complete. No code written yet. Build in phase order (Section 12).

---

## Table of Contents

1. [Case Study: Fundamental vs. Technical — Which Wins for Swing Trading?](#1-case-study)
2. [Chosen Approach: The Techno-Funda Hybrid](#2-chosen-approach)
3. [Scope & Universe Definition](#3-scope--universe)
4. [Data Sources (Indian Market Specific)](#4-data-sources)
5. [System Architecture](#5-system-architecture)
6. [Layer 1 — Fundamental Screening Engine](#6-fundamental-screening-engine)
7. [Layer 2 — Technical Analysis Engine](#7-technical-analysis-engine)
8. [Layer 3 — Signal Generation: Entry, Exit, Stop-Loss](#8-signal-generation)
9. [Layer 4 — Risk Management & Position Sizing](#9-risk-management)
10. [Layer 5 — Backtesting & Validation](#10-backtesting)
11. [Tech Stack Decision](#11-tech-stack)
12. [Phased Build Plan (Agent Task Breakdown)](#12-phased-build-plan)
13. [Database Schema](#13-database-schema)
14. [UI / Output Specification](#14-ui--output)
15. [Scheduling & Automation](#15-scheduling)
16. [Pitfalls, Compliance & Disclaimers](#16-pitfalls--compliance)
17. [Layer 6 — News & Event Intelligence Module](#17-news-module)
18. [Roadmap — Deferred & Future Work](#18-future-enhancements)

---

<a id="1-case-study"></a>
## 1. Case Study: Fundamental vs. Technical — Which Wins for Swing Trading?

### 1.1 What each method actually answers

| Question | Fundamental Analysis | Technical Analysis |
|---|---|---|
| **WHAT to buy** (quality of business) | ✅ Excellent | ❌ Blind to business quality |
| **WHEN to buy/sell** (timing) | ❌ Nearly useless for 2–6 week horizons | ✅ This is its entire purpose |
| **Entry / Exit / Stop-loss levels** | ❌ Cannot produce them | ✅ Directly produces them |
| **Avoiding value traps / junk rallies** | ✅ Filters out garbage | ❌ Will happily signal a fraud stock |
| **Reacting to earnings/news** | Slow (quarterly data) | Fast (price reacts in minutes) |
| **Time horizon it works on** | 1–5+ years | Minutes to months |

### 1.2 Case evidence from the Indian market

**Case A — Technical-only failure mode (Yes Bank, 2018–2020):**
Yes Bank repeatedly printed "oversold bounce" and "falling wedge breakout" technical setups on its way from ₹400 to ₹10. Every dip-buy technical signal was a trap because the *fundamentals* (NPA divergence, governance failure) were deteriorating. A fundamental filter (falling ROE, rising NPAs, auditor red flags, promoter pledging) would have excluded it from the tradeable universe entirely. **Lesson: technicals without a quality filter feed you falling knives.**

**Case B — Fundamental-only failure mode (ITC, 2017–2020):**
ITC was fundamentally cheap (low P/E, high ROCE, huge FCF) for years while the price went sideways/down for 3+ years. A fundamentals-only swing trader would have been dead money through dozens of missed opportunities elsewhere. **Lesson: cheap can stay cheap; fundamentals give no timing signal, which is fatal for a 2–6 week holding period.**

**Case C — Hybrid success mode (Tata Motors, 2020–2023; Defence/Railway PSUs, 2022–2024):**
Stocks where improving fundamentals (deleveraging, order-book growth, margin expansion) *coincided with* technical breakouts (52-week-high breakouts on volume, golden crosses) produced the strongest and cleanest swing moves — trends that ran for months with shallow pullbacks. Momentum studies on Indian equities (e.g., NSE momentum indices — Nifty200 Momentum 30 historically outperforming Nifty 50) consistently show that **momentum in quality names is one of the most persistent anomalies in Indian markets**.

### 1.3 Verdict (this decision is final for this project)

> **Neither alone. Use fundamentals as a FILTER (what is allowed to be traded) and technicals as the TRIGGER (when to enter, where to exit, where the stop goes).**

Rationale specific to swing trading:
- Swing trades live or die on **timing and levels** → technicals are mandatory and are the primary engine.
- Indian small/midcaps carry elevated governance risk (pledged promoters, circular trading, SME manipulation) → a fundamental quality gate is mandatory to keep junk out of the signal pool.
- Fundamentals change quarterly; technicals change daily → run the fundamental screen **weekly/quarterly**, the technical scan **daily after market close**.

Weighting in the final composite score: **Technical 65% / Fundamental 25% / Volume-Momentum confirmation 10%** (tunable via config, see Section 8.6).

---

<a id="2-chosen-approach"></a>
## 2. Chosen Approach: The Techno-Funda Hybrid

The system is a **funnel**. Each layer shrinks the universe:

```
~5,000+ listed stocks (NSE + BSE)
        │
        ▼  LAYER 0: Tradability filter (liquidity, price band, listing age)
~1,200 tradeable stocks
        │
        ▼  LAYER 1: Fundamental quality gate (runs weekly)
~300–500 "approved universe" stocks
        │
        ▼  LAYER 2: Technical setup scanner (runs daily, post-market)
~10–40 stocks showing an active setup
        │
        ▼  LAYER 3: Signal generator (ranks, computes entry/SL/targets)
Top 5–15 ranked trade candidates with Entry / SL / T1 / T2 / R:R
        │
        ▼  LAYER 4: Risk manager (position size, portfolio caps)
Final actionable watchlist (published to dashboard/report)
```

Key design principles:
1. **Post-market batch system, not real-time.** Swing trading needs end-of-day (EOD) data. This kills 90% of infrastructure complexity and cost. Intraday/live data is a Phase-8 enhancement only.
2. **Everything is backtested before it is trusted.** No indicator or rule ships without a backtest report (Section 10).
3. **Config-driven rules.** All thresholds (RSI levels, ATR multipliers, ROE minimums) live in one `config.yaml` — never hardcoded.
4. **Explainable signals.** Every signal must carry human-readable reasons ("Breakout above 52-week high on 2.8× volume; ROE 22%; sector RS rank 3/21").

---

<a id="3-scope--universe"></a>
## 3. Scope & Universe Definition

### 3.1 Stock universe
- **Primary:** All NSE-listed equities (~2,000 actively traded). NSE has better liquidity and data availability.
- **Secondary:** BSE-only listings (~3,000 more) — include only those passing liquidity filters; most will be filtered out.
- **Excluded outright:** SME platform stocks (NSE Emerge / BSE SME) — manipulation risk and 5% circuits make them unsuitable; stocks in GSM/ESM surveillance stages; suspended stocks; stocks under ASM Stage ≥ 2 (flag ASM Stage 1 as a warning, don't exclude).

### 3.2 Layer 0 — Tradability filter (hard gates, run daily)
| Filter | Threshold | Why |
|---|---|---|
| Median 20-day traded value | ≥ ₹3 crore/day | Must be able to enter/exit ₹1–5L position without slippage |
| Price | ≥ ₹20 | Sub-₹20 stocks are circuit-prone and manipulated |
| Listing age | ≥ 200 trading days | Need history for 200-DMA and ATR |
| Circuit filter | Not in 5% band (prefer 10%/20%/no-band) | 5% band stocks gap through stops |
| Surveillance | Not in GSM, ESM, ASM ≥2 | Regulatory trading restrictions |
| Market cap | ≥ ₹500 crore | Governance/liquidity floor (configurable) |

### 3.3 Benchmarks & sector mapping
- Benchmark index: **Nifty 500** (breadth) and **Nifty 50** (regime detection).
- Map every stock to its **NSE sector index** (Nifty Bank, Nifty IT, Nifty Pharma, Nifty Auto, Nifty Metal, Nifty FMCG, Nifty Energy, Nifty Realty, Nifty PSU Bank, etc.) for relative-strength ranking.

---

<a id="4-data-sources"></a>
## 4. Data Sources (Indian Market Specific)

### 4.1 Recommended stack (free → paid tiers)

| Data need | Primary (free) | Fallback | Paid upgrade (later) |
|---|---|---|---|
| EOD OHLCV (NSE) | **NSE Bhavcopy** (official daily file, free, complete) | `yfinance` with `.NS` suffix | Zerodha Kite Connect Historical API (₹2,000/mo) |
| Historical OHLCV backfill | `yfinance` (10+ yrs daily) | NSE Bhavcopy archives | TrueData / Global Datafeeds |
| Fundamentals (ratios, financials) | **Screener.in export** + `yfinance` `.info` | Moneycontrol scraping (fragile) | Tickertape API / CMOTS / Trendlyne API |
| Corporate actions (splits/bonus/dividends) | NSE corporate actions CSV (official) | yfinance actions | Kite Connect |
| Index constituents & sector indices | NSE indices CSV downloads (official) | niftyindices.com | — |
| Shareholding pattern (FII/DII/promoter/pledge) | BSE/NSE filings (quarterly XBRL) | Trendlyne/Screener scrape | Prime Database |
| Bulk/block deals, delivery % | NSE daily reports (free CSV) | — | — |
| Surveillance lists (ASM/GSM/ESM) | NSE website daily CSV | — | — |
| Results calendar | NSE corporate announcements | Screener.in | — |

### 4.2 Critical implementation notes for agents

1. **NSE website blocks naive scrapers.** All NSE downloads need: browser-like headers (`User-Agent`, `Accept-Language`), a warm-up request to `nseindia.com` to obtain cookies, rate limiting (≥1–2 s between requests), and retry with exponential backoff. Build ONE shared `NseClient` class that handles this; never call NSE endpoints directly elsewhere. Libraries that already handle this (verify current maintenance status at build time): `nselib`, `nsepython`, `jugaad-data`.
2. **Bhavcopy is the ground truth for EOD.** NSE publishes a daily bhavcopy (all stocks' OHLCV + delivery data) around 6–7 PM IST. The daily pipeline ingests this ONE file instead of making 2,000 per-symbol requests. Historical bhavcopies are archived and downloadable for backfill.
3. **Always adjust prices for splits/bonuses.** Store BOTH raw and adjusted OHLCV. Technical indicators run on adjusted data. Un-adjusted data will produce false "crash" signals on every bonus issue (common in India).
4. **yfinance symbol format:** NSE = `RELIANCE.NS`, BSE = `RELIANCE.BO`. yfinance is convenient but rate-limited and occasionally wrong on Indian corporate actions — use it for backfill and cross-validation, not as the primary daily source.
5. **Screener.in** allows logged-in users to export fundamentals; it also has consistent HTML structure per company page (`screener.in/company/{SYMBOL}/consolidated/`). Prefer **consolidated** financials; fall back to standalone if consolidated is absent. Cache aggressively (fundamentals change quarterly — refetch on result dates + weekly sweep, not daily).
6. **Data validation layer is mandatory** (Section 5): check for zero-volume days, OHLC integrity (`high ≥ max(open,close)`, `low ≤ min(open,close)`), price continuity (>30% day moves flagged unless circuit/news), missing trading days vs. NSE holiday calendar (maintain `holidays_nse.csv`).

---

<a id="5-system-architecture"></a>
## 5. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        SCHEDULER (cron / APScheduler)            │
│   Daily 7:00 PM IST: EOD pipeline   Weekly Sun: fundamentals     │
└──────────────┬──────────────────────────────┬───────────────────┘
               ▼                              ▼
┌──────────────────────────┐    ┌──────────────────────────────┐
│   INGESTION SERVICE      │    │   FUNDAMENTAL SERVICE        │
│  - NseClient (bhavcopy,  │    │  - Screener/yfinance fetch   │
│    delivery, ASM/GSM,    │    │  - Ratio computation         │
│    corporate actions)    │    │  - Quality score (0–100)     │
│  - yfinance backfill     │    │  - Universe approve/reject   │
│  - Validation layer      │    └──────────────┬───────────────┘
└──────────────┬───────────┘                   │
               ▼                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                DATABASE (DuckDB or PostgreSQL+Timescale)         │
│  prices_raw │ prices_adj │ fundamentals │ scores │ signals │     │
│  universe │ sectors │ corporate_actions │ backtest_results       │
└──────────────┬──────────────────────────────────────────────────┘
               ▼
┌──────────────────────────┐    ┌──────────────────────────────┐
│  TECHNICAL ENGINE        │    │  MARKET REGIME MODULE        │
│  - Indicator computation │    │  - Nifty50 vs 50/200 DMA     │
│    (vectorized, all      │    │  - Breadth (% above 200DMA)  │
│    stocks at once)       │    │  - India VIX level           │
│  - Setup scanners        │    │  → regime: BULL/NEUTRAL/BEAR │
│    (breakout, pullback,  │    └──────────────┬───────────────┘
│    mean-reversion)       │                   │
└──────────────┬───────────┘                   │
               ▼                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SIGNAL GENERATOR                              │
│  composite score → rank → entry/SL/T1/T2 → R:R filter →          │
│  regime gate → position size → publish                           │
└──────────────┬──────────────────────────────────────────────────┘
               ▼
┌──────────────────────────┐    ┌──────────────────────────────┐
│  OUTPUT LAYER            │    │  BACKTESTER (offline)        │
│  - Web dashboard (charts)│    │  - vectorbt / custom engine  │
│  - Daily report (MD/PDF) │    │  - walk-forward validation   │
│  - Telegram/email alerts │    │  - per-setup stats           │
└──────────────────────────┘    └──────────────────────────────┘
```

> **Note:** Phase 6.5 adds a **NEWS & EVENT SERVICE** (Section 17) — it ingests announcements/RSS/macro proxies into `news_events`/`sentiment_daily` and feeds the **Market Regime Module** (RISK_OFF override) and the **Signal Generator** (score modifiers, vetoes, warnings).

**Design rules:**
- Each box = one Python module/package with a clean interface. No cross-imports except through the DB or defined service interfaces.
- The pipeline must be **idempotent**: re-running a day's job must not duplicate rows (upsert on `(symbol, date)`).
- Every job writes to a `job_runs` log table (started, finished, rows written, errors) for observability.

---

<a id="6-fundamental-screening-engine"></a>
## 6. Layer 1 — Fundamental Screening Engine

Purpose: **not** to find "value stocks" — it is to certify that a stock is *safe enough and strong enough to swing trade*. Runs weekly (Sunday) + on result announcements.

### 6.1 Hard rejection rules (any one → stock excluded from universe)

| Rule | Threshold | Rationale (India-specific) |
|---|---|---|
| Promoter pledge | > 25% of promoter holding pledged | Pledge invocation causes overnight crashes (Zee, Yes Bank pattern) |
| Debt/Equity | > 2.0 (non-financials) | Leverage blowup risk; exclude banks/NBFCs from this rule |
| Interest coverage | < 2.0 (non-financials) | Solvency stress |
| Consecutive loss years | Net loss in 2 of last 3 FYs | Junk filter (allow turnaround override if last 2 quarters profitable) |
| Auditor resignation / qualified opinion in last 12 mo | Any | Governance red flag |
| Promoter holding trend | Fell > 5 percentage points in last 2 quarters (non-dilution) | Insiders exiting |
| Contingent liabilities | > 50% of net worth | Hidden leverage |

### 6.2 Quality score (0–100) for surviving stocks

| Component | Weight | Metric & scoring |
|---|---|---|
| **Profitability** | 25 | ROE and ROCE, 3-yr average. ROCE ≥20% → full points; 12–20% linear; <12% → 0. Banks: use ROA ≥1.2% and ROE. |
| **Growth** | 25 | Sales CAGR (3yr) and EPS growth (TTM YoY). ≥15% → full; scale down to 0 at 0%. Recent quarter acceleration = bonus. |
| **Earnings quality** | 15 | CFO/EBITDA ≥ 0.7 over 3 yrs; positive FCF in ≥2 of 3 yrs. |
| **Balance sheet** | 15 | D/E < 0.5 full points; declining debt trend bonus; working-capital days trend. |
| **Ownership** | 10 | Promoter holding ≥ 45% & stable/rising; FII+DII stake rising QoQ = bonus; pledge = 0 already required <25%, but any pledge >0 costs points. |
| **Valuation sanity** | 10 | NOT a value screen — just penalize insanity: P/E > 3× sector median or EV/EBITDA > 40 → lose points. Swing trades can ride expensive stocks, but extremes reverse violently. |

**Universe admission:** Quality score ≥ 50 → "approved universe". Score also feeds the composite signal score (Section 8.6).

### 6.3 Earnings-event handling (critical for swing trades)
- Maintain a results calendar. **Rule: no NEW entry within 3 trading days before a scheduled result** (binary-event gap risk). Existing positions: flag "results upcoming" warning on the dashboard.
- After results: refresh fundamentals for that stock within 24h; a big earnings beat + price/volume surge is itself a tradeable setup — see **Setup E** (§7.3).

---

<a id="7-technical-analysis-engine"></a>
## 7. Layer 2 — Technical Analysis Engine

Runs daily post-market on the approved universe. All computation **vectorized** across all stocks (pandas/polars groupby, or numpy over a 3-D array) — never a per-stock Python loop over rows.

### 7.1 Indicator set (compute and store daily for every stock)

**Trend:**
- EMA 20, EMA 50, SMA 200 (+ slope of each over 20 days)
- ADX(14) — trend strength; DI+/DI− direction
- Supertrend (10, 3) — trailing stop reference

**Momentum:**
- RSI(14) — regime-aware use (see setups)
- MACD (12,26,9) — line, signal, histogram + histogram slope
- Rate of Change: 20-day, 60-day, 120-day returns (momentum ranking)
- **Relative Strength vs Nifty 500** = (stock 63-day return − index 63-day return); percentile-rank across universe daily. *(This is relative strength, NOT RSI.)*

**Volatility:**
- ATR(14) and ATR% (ATR/close) — position sizing + stop placement
- Bollinger Bands (20, 2) + BB width percentile (squeeze detection)

**Volume:**
- 20-day average volume; today's volume ratio vs. that average
- OBV and its 20-day slope
- **Delivery % vs its own 20-day average** (India-specific edge: high delivery + price rise = genuine accumulation; high volume + low delivery = churn/speculation)

**Structure (computed from raw OHLC):**
- 52-week high/low distance; 20-day (monthly) high/low
- Swing highs/lows via fractal method (pivot = bar with 2 lower highs on both sides) → support/resistance levels
- Gap detection (open vs. prior close > 2%)
- Consolidation/base detection: N-day range tightness (e.g., 15-day high-low range < 8%) — precondition for breakout setups

### 7.2 Chart generation (the "graphs" requirement)
For every published signal, auto-generate an annotated candlestick chart:
- Candles + volume panel + delivery% overlay
- EMA20/50, SMA200 lines
- Marked: entry line (green), stop-loss line (red), T1/T2 (blue dashed), detected support/resistance, the pattern zone (e.g., base rectangle)
- Library: **`plotly`** (interactive, embeds in web dashboard) with `mplfinance` as static-PNG fallback for reports/Telegram.
- Interactive dashboard alternative: **TradingView Lightweight Charts** (free, MIT) embedded in the web UI — best-in-class panning/zooming; feed it OHLCV JSON from our API.

### 7.3 The four setup scanners (each is an independent module)

**SETUP A — Momentum Breakout (primary; works best in BULL regime)**
Conditions (all must hold):
1. Close crosses above the 60-day high (or 52-week high for stronger variant)
2. Breakout-day volume ≥ 1.5× 20-day average (≥2× = stronger grade)
3. Prior consolidation: 15+ day base with range < 12%
4. Close > EMA20 > EMA50 > SMA200 (stacked trend alignment)
5. RS percentile vs universe ≥ 70
6. Delivery% today ≥ its 20-day average (genuine buying)
7. Not extended: close ≤ 4% above the breakout level (don't chase)

**SETUP B — Pullback to Trend (buy-the-dip in an uptrend)**
1. Long-term uptrend: close > SMA200, SMA200 slope positive, RS percentile ≥ 60
2. Pullback: price retraces to EMA20–EMA50 zone (touch or close within 1.5%)
3. Pullback depth ≤ 38.2% Fibonacci of the prior upswing; pullback volume < average (selling exhausting)
4. Trigger: first day that closes above the prior day's high with RSI(14) turning up from 40–55 zone
5. ADX ≥ 20 (there is a trend to pull back within)

**SETUP C — Range/Mean-Reversion (only in NEUTRAL regime; disabled in BEAR)**
1. Stock in a defined 3+ month range (range edges from fractal S/R clustering)
2. Price within 2% of range support; RSI(14) < 35; BB lower band touch
3. Trigger: bullish reversal candle (hammer/bullish engulfing) closing back above support
4. Extra gate: quality score ≥ 65 (mean reversion only on high-quality names — junk that falls keeps falling)

**SETUP D — Volatility Squeeze Breakout**
1. BB width in bottom 15th percentile of its own 1-year history (squeeze)
2. Trigger: close outside upper BB with volume ≥ 1.5× average
3. Direction filter: only long if close > SMA200
4. (Squeezes resolve violently; this catches moves Setup A's base rule misses)

**SETUP E — Earnings Momentum / Post-Earnings Drift (PEAD)**
1. Company announced quarterly results within the last 2 sessions
2. Results-day reaction: gap-up ≥ 2% OR close ≥ +4%, volume ≥ 2.5× 20-day average, close in top 30% of the day's range (gains held, not faded)
3. Fundamental confirmation from the post-result refresh: EPS YoY growth ≥ 25% and sales YoY ≥ 10% (no free consensus-estimate data exists for India — the price/volume reaction IS the surprise proxy)
4. Close > SMA200; quality score ≥ 60; RS percentile ≥ 50
5. Entry: buy above the results-day high within the next 3 sessions; SL below the results-day low (natural structure). **Skip if results-day range > 8%** — the stop would be too wide
6. Rationale: post-earnings-announcement drift is one of the best-documented anomalies globally and works well in India's 4 staggered results seasons
7. By construction this setup is exempt from the §6.3 "no entry 3 days before results" rule — the binary event just resolved

**Bearish variants** of A/B (breakdown, rally-to-resistance) are computed and published as *"avoid / exit if held"* flags — the system is long-only for trade signals in v1 (shorting via futures is Phase 8+; SEBI intraday-only rules make cash shorting impractical for swing).

### 7.4 Candlestick pattern module (confirmation only, never standalone)
Detect on trigger day: bullish/bearish engulfing, hammer, shooting star, doji at S/R, morning/evening star. Implement with `pandas-ta` / TA-Lib pattern functions or hand-rolled rules. Patterns add/subtract confirmation points in scoring; they never generate a signal alone.

### 7.5 Market regime module (gates everything)
Computed daily from index data:
- **BULL:** Nifty 50 close > 50DMA > 200DMA and % of Nifty500 stocks above their 200DMA > 55%
- **BEAR:** Nifty 50 close < 200DMA or breadth < 35%
- **NEUTRAL:** everything else
- India VIX > 22 → halve all position sizes regardless of regime

Regime effects: BULL → all long setups active, full size. NEUTRAL → setups A/B/D at 70% size, C active. BEAR → **no new long entries** except Setup C on quality ≥ 80 names at half size; dashboard banner: "Bear regime — capital preservation mode."

### 7.6 Multi-timeframe (weekly) confirmation gate

Resample adjusted daily data to weekly bars; compute weekly 10-EMA and 40-week SMA. Store gate flags per stock daily.
- **Gate for trend setups (A, B, D, E):** weekly close > 10-week EMA **and** 10-week EMA ≥ its value 4 weeks ago (rising). Daily signals failing this gate are demoted to grade C (watch-only) — daily strength against a weekly downtrend is usually a bear-market rally.
- **Gate for Setup C (mean reversion):** weekly close > 40-week SMA — never catch knives inside weekly downtrends.
- **Must be ablation-tested in Phase 5** (each setup run with vs. without the gate). Keep the gate only where it improves out-of-sample profit factor or max drawdown; expectation is it filters roughly a third of false daily breakouts.

---

<a id="8-signal-generation"></a>
## 8. Layer 3 — Signal Generation: Entry, Exit, Stop-Loss

This is the deliverable the user asked for. Every rule here must be deterministic and backtestable.

### 8.1 Entry point
Two entry styles per signal (publish both):
- **Aggressive entry:** next day, buy at/above the trigger level — for Setup A: the breakout close; for Setup B: prior day's high + 0.05%. Use a stop-limit style instruction: "Buy above ₹X, valid till ₹X × 1.02; do not chase beyond +2%."
- **Conservative entry:** buy on a retest — Setup A: limit order at the breakout level (old resistance = new support), valid 5 sessions; Setup B/C: at the signal close.
- Every signal carries an **expiry**: if not triggered within 5 trading sessions, the signal is void (stale setups fail).

### 8.2 Stop-loss (ATR-based, structure-aware)
```
technical_stop = min(recent_swing_low, base_low)          # structure
volatility_stop = entry_price − 2.0 × ATR(14)             # noise buffer
stop_loss = max(technical_stop − 0.25×ATR, volatility_stop)  # the tighter sensible one
hard_cap: if stop distance > 8% of entry → REJECT the signal (too loose for swing)
min_floor: if stop distance < 1.5% → widen to 1.5% (avoid noise stop-outs)
```
- Stops are **closing-basis for decision, hard for execution guidance**: publish "SL ₹X (exit if day closes below; hard exit if trades 1% below intraday)".
- **Never widen a stop after entry. Ever.** The system must enforce this in position tracking.

### 8.3 Targets & exits
- **T1 = entry + 1.5 × risk** (risk = entry − SL). Action at T1: book 50%, move SL to breakeven.
- **T2 = entry + 3 × risk**, or the next major structural resistance (fractal S/R cluster / measured move of the base height), whichever is nearer.
- **Trailing exit for the runner (after T1):** trail with Supertrend(10,3) or below each new confirmed swing low; exit remainder on close below EMA20 or trailing level.
- **Time stop:** if trade is neither at T1 nor stopped after 15 trading sessions → exit (capital efficiency; dead swing trades rot).
- **Event exit:** scheduled results in ≤2 days and trade < T1 → exit or explicitly flag "hold through results = discretionary risk."

### 8.4 Reward:Risk gate
- Compute R:R to T2 at signal time. **Publish only if R:R ≥ 2.0.** (This single filter removes most bad trades.)

### 8.5 Signal record (exact output contract)
Every published signal is a JSON/DB row:
```json
{
  "signal_id": "2026-07-02-RELIANCE-A",
  "date": "2026-07-02",
  "symbol": "RELIANCE", "exchange": "NSE",
  "setup": "A_momentum_breakout",
  "direction": "LONG",
  "composite_score": 87.4,
  "grade": "A",
  "entry_aggressive": 3012.0, "entry_conservative": 2965.0,
  "entry_valid_till": "2026-07-09",
  "stop_loss": 2871.0, "stop_basis": "swing low 2882 − 0.25×ATR; 4.7% risk",
  "t1": 3223.0, "t2": 3435.0, "rr_to_t2": 3.0,
  "time_stop_sessions": 15,
  "atr_pct": 2.1, "quality_score": 78, "rs_percentile": 91,
  "regime": "BULL",
  "suggested_risk_pct": 1.0,
  "reasons": [
    "Breakout above 60d high 2995 on 2.3x volume",
    "23-session base, 7.8% range",
    "Delivery 61% vs 44% avg — genuine accumulation",
    "Sector (Energy) RS rank 4/21", "Quality 78/100; no pledge"
  ],
  "warnings": ["Results due 2026-07-18"],
  "chart_path": "charts/2026-07-02/RELIANCE.html"
}
```

### 8.6 Composite score & ranking (0–100)
```
composite = 0.40 × setup_strength      # setup-specific: volume ratio, base tightness, breakout cleanliness
          + 0.25 × momentum_rs         # RS percentile + 20/60d ROC blend
          + 0.25 × quality_score       # from fundamental layer
          + 0.10 × volume_delivery     # delivery% surge + OBV slope
```
Grades: A ≥ 80, B 65–79, C 50–64 (C published as "watch only", not tradeable). Publish max **15 signals/day**, ranked; if more qualify, keep highest scores with a max of 3 per sector (diversification).

---

<a id="9-risk-management"></a>
## 9. Layer 4 — Risk Management & Position Sizing

Published alongside every signal, parameterized by user capital `C` (config):
- **Risk per trade:** 1% of C (0.5% for grade B, in BEAR/high-VIX halved).
- **Position size** = `(C × risk%) / (entry − stop_loss)`, capped at 15% of C in any single stock and at 5% of the stock's 20-day average daily traded value (liquidity cap).
- **Portfolio caps:** max 8 open positions; max 3 per sector; max total open risk 5% of C.
- **Position tracker module:** ingests which signals the user actually took (manual entry or CSV), then monitors daily: SL hit / T1 hit (auto-instruct "book 50%, SL→BE") / time stop / trailing updates. Produces a daily "actions required" section in the report.
- **Correlation cap (sector caps are not enough):** before accepting a new position, compute 60-day daily-return correlation between the candidate and every open position. If correlation > 0.7 with ≥ 2 open positions → reject (or require grade A and halve size). Total open risk across any correlated cluster (pairwise corr > 0.7) ≤ 2% of C. Rationale: 8 positions across 3 sectors can still be one hidden bet (rate-sensitives, commodity plays, dollar earners).
- **Gap-risk stress test (daily):** report the portfolio P&L if every open position gaps −5% / −10% through its stop overnight. If the −5% scenario loses > 4% of C → banner warning and block new entries until back under the limit.
- **Slippage feedback loop:** the tracker records actual fill price vs. signal entry (`fills` table). A monthly job compares realized slippage against the modeled 0.15%/side and recalibrates the backtest cost model with live numbers.

---

<a id="10-backtesting"></a>
## 10. Layer 5 — Backtesting & Validation

**Nothing ships to the signal feed until backtested. This is the difference between the "best one" and a toy.**

### 10.1 Engine
- Use **`vectorbt`** (fast, vectorized, handles portfolios) as primary; validate 2–3 sample strategies against **`backtesting.py`** for cross-checking logic. If vectorbt licensing/maintenance is a problem at build time, build a custom event-loop backtester (~500 lines) — our rules are simple enough.
- Data: adjusted EOD from our own DB, **survivorship-bias corrected**. This is mandatory, not best-effort: build the point-in-time index-constituent history (`index_constituents` table — who was in the Nifty 500 on any given date, reconstructed from NSE index-change announcements) and backtest against membership *as of the trade date*. Backfill delisted stocks where data is obtainable; where it isn't, quantify the residual bias in the report.

### 10.2 Realistic cost model (India-specific)
Per round-trip on delivery equity: brokerage (₹0 discount brokers) + STT 0.1% each side + exchange charges + GST + stamp duty + **slippage 0.15%/side** (more for low-liquidity names — scale slippage by 1/liquidity). Total modeled cost: **~0.5–0.6% per round trip**. Any strategy that dies under this cost load is dead — better to know now.

### 10.3 Protocol
1. In-sample: 2015–2021. Out-of-sample: 2022–today. **Never tune on out-of-sample.**
2. Walk-forward: re-tune params yearly, test on the following year, rolling.
3. Per-setup metrics required: total trades (need ≥300 for significance), win rate, avg R, profit factor, max drawdown, CAGR vs Nifty 500, exposure %, results by regime, results by market-cap bucket, results by year.
4. **Acceptance gates to ship a setup:** profit factor ≥ 1.5 out-of-sample, max DD < 25%, ≥300 trades, positive in ≥70% of years.
5. Monte-Carlo shuffle of trade order for drawdown confidence intervals.
6. Store every backtest run + config hash in `backtest_results` (reproducibility).

### 10.4 Ongoing validation
- **Paper-trade the live signal feed for 60 days minimum** before anyone risks money. Auto-track every published signal's outcome (T1/T2/SL/time-stop hit) in a `signal_outcomes` table → live win-rate dashboard. This also catches data bugs backtests miss.

### 10.5 Live decay monitoring & auto-disable

Edges decay as they get crowded — a setup that backtested well can stop working. Per setup, maintain rolling statistics over the last 60 closed signal outcomes:
- Rolling profit factor < 1.0, **or** rolling win rate below the backtest's 5th-percentile bootstrap band → setup auto-demoted to **watch-only** + Telegram alert with the stats.
- Re-enabling is manual, after a written review: was it regime, a data bug, or genuine decay?
- Monthly per-setup report on `/performance`: rolling PF, win rate, avg R plotted against backtest expectation bands.

---

<a id="11-tech-stack"></a>
## 11. Tech Stack Decision

| Component | Choice | Why |
|---|---|---|
| Language | **Python 3.12+** | Ecosystem for finance (pandas, vectorbt, TA libs); agent-friendly |
| Package/env | `uv` | Fast, reproducible |
| Dataframes | **polars** (pipeline) + pandas (interop with TA libs) | 2,000 stocks × 10 yrs daily is fine in-memory; polars for speed |
| Database | **DuckDB** (v1) → PostgreSQL+TimescaleDB when multi-user | DuckDB = zero-ops single file, blazing analytical queries, perfect for EOD scale (~5M rows/yr) |
| TA indicators | `pandas-ta` (pure python, easy) ; TA-Lib optional (C dep, faster) | Avoid hard C dependency in v1 |
| Backtesting | `vectorbt` + custom validation | See §10.1 |
| Charts | Plotly + TradingView Lightweight Charts (web), mplfinance (static) | See §7.2 |
| API layer | **FastAPI** | Serves dashboard + JSON signals |
| Dashboard | **Next.js or plain React + Lightweight Charts**; v1 acceptable: FastAPI + Jinja/HTMX | Don't over-invest in UI before signals are validated |
| Scheduler | APScheduler in-process (v1); cron/Windows Task Scheduler wrapper | Simple |
| Alerts | Telegram bot (python-telegram-bot) + email (SMTP) | Swing traders live on Telegram |
| Config | single `config.yaml` + pydantic-settings validation | All thresholds centralized |
| Tests | pytest; golden-file tests for indicators (verify against known values) | Indicator bugs = silent money loss |
| Logging | structlog → file + console; job_runs table | Debuggability |

**Project layout:**
```
stock-analyzer/
├── config.yaml                  # every threshold lives here
├── pyproject.toml
├── src/analyzer/
│   ├── data/          # nse_client.py, bhavcopy.py, yfinance_backfill.py,
│   │                  # corporate_actions.py, fundamentals_fetch.py, validation.py
│   ├── db/            # schema.sql, repository.py (all SQL isolated here)
│   ├── fundamentals/  # ratios.py, quality_score.py, hard_filters.py
│   ├── technicals/    # indicators.py, structure.py (S/R, bases), regime.py
│   ├── setups/        # base.py (interface), breakout.py, pullback.py,
│   │                  # mean_reversion.py, squeeze.py
│   ├── signals/       # scoring.py, levels.py (entry/SL/targets), publisher.py
│   ├── risk/          # position_sizing.py, portfolio_limits.py, tracker.py
│   ├── backtest/      # engine.py, costs.py, reports.py, walk_forward.py
│   ├── charts/        # plotly_chart.py, lightweight_feed.py
│   ├── api/           # fastapi app, routes
│   ├── news/          # ingest_rss.py, ingest_announcements.py, proxies.py,
│   │                  # rules_classifier.py, llm_classifier.py, sentiment.py
│   ├── jobs/          # daily_eod.py, weekly_fundamentals.py, orchestrator.py
│   └── notify/        # telegram.py, email.py, report_md.py
├── tests/
├── charts/            # generated output
└── reports/           # daily markdown/PDF reports
```

---

<a id="12-phased-build-plan"></a>
## 12. Phased Build Plan (Agent Task Breakdown)

Build strictly in order. Each phase has a **definition of done (DoD)**. Do not start a phase until the previous DoD passes.

### Phase 1 — Foundations & Data Ingestion (est. 3–5 agent-days)
- [ ] 1.1 Repo scaffold, `pyproject.toml` (uv), `config.yaml` skeleton, pydantic settings, structlog, pytest wiring
- [ ] 1.2 DuckDB schema (Section 13) + `repository.py` with upsert helpers + `job_runs` logging
- [ ] 1.3 `NseClient`: session/cookie warm-up, headers, rate-limit, retries; download today's bhavcopy, delivery data, ASM/GSM/ESM lists, corporate actions, NSE holiday calendar
- [ ] 1.4 Historical backfill: 10 years EOD for all NSE symbols via bhavcopy archives (primary) + yfinance (gap fill); symbol-master table with ISIN mapping (symbols change names — track via ISIN)
- [ ] 1.5 Corporate-action adjuster → `prices_adj` table; unit tests with known split cases (e.g., verify a known 1:1 bonus adjusts correctly)
- [ ] 1.6 Validation layer + data-quality report job
- [ ] 1.7 Point-in-time index-constituent history (Nifty 500 + sector indices, reconstructed from NSE index-change announcements) → `index_constituents`
- [ ] 1.8 Delisted-stock archive backfill (best-effort) + daily cross-source reconciliation job (bhavcopy vs. yfinance close; alert on >0.5% unexplained divergence — catches silent corporate-action errors)
- **DoD:** One command backfills and validates ≥1,800 NSE symbols × 10 yrs; daily job idempotently ingests today's bhavcopy in <10 min; tests pass.

### Phase 2 — Fundamental Engine (est. 3–4 agent-days)
- [ ] 2.1 Fundamentals fetcher (Screener.in consolidated + yfinance fallback), cached, rate-limited
- [ ] 2.2 Shareholding/pledge ingestion (quarterly), results-calendar ingestion
- [ ] 2.3 Hard rejection rules (§6.1) + quality score (§6.2), banks/NBFC branch logic
- [ ] 2.4 Weekly universe job → `universe` table with approve/reject + reasons
- **DoD:** Universe report lists every stock with score + reasons; spot-check 20 known names (e.g., a quality large-cap scores >70; a known pledged/loss-making stock is rejected).

### Phase 3 — Technical Engine (est. 4–5 agent-days)
- [ ] 3.1 Vectorized indicator computation for full universe (§7.1) → `indicators_daily` table; golden-file tests (compare RSI/ATR/MACD outputs against hand-verified values)
- [ ] 3.2 Structure module: fractal swings, S/R clustering, base/consolidation detection, 52-wk levels
- [ ] 3.3 Market regime module (§7.5) incl. India VIX ingestion
- [ ] 3.4 Relative-strength percentile ranking + sector RS ranks
- [ ] 3.5 Weekly resampling + multi-timeframe gate flags per stock (§7.6)
- **DoD:** Full-universe daily indicator run completes in <5 min; regime history 2015–today matches known market phases (BEAR flagged for Mar 2020, etc.).

### Phase 4 — Setups & Signal Generation (est. 4–5 agent-days)
- [ ] 4.1 Setup interface (`Setup.scan(date) → list[RawSignal]`) + implement Setups A, B, C, D, E (§7.3)
- [ ] 4.2 Candlestick confirmation module (§7.4)
- [ ] 4.3 Levels engine: entry/SL/T1/T2 per §8.1–8.3, R:R gate, signal expiry
- [ ] 4.4 Composite scoring + ranking + sector caps + regime gating (§8.6)
- [ ] 4.5 Signal publisher → `signals` table + JSON contract (§8.5)
- **DoD:** Running the scanner on a chosen historical date reproduces sensible, explainable signals; every signal has entry/SL/T1/T2/R:R and ≥3 human-readable reasons.

### Phase 5 — Backtesting (est. 5–7 agent-days) ← **most important phase**
- [ ] 5.1 Cost model (§10.2), fill logic (next-day open/stop-limit semantics matching §8.1)
- [ ] 5.2 vectorbt harness replaying each setup over 2015–2021 in-sample
- [ ] 5.3 Walk-forward + out-of-sample runs; per-setup report cards (§10.3)
- [ ] 5.4 Tune config against in-sample only; freeze; verify out-of-sample vs acceptance gates (§10.3.4)
- [ ] 5.5 Kill or fix any setup failing gates. Document results in `reports/backtest/`
- [ ] 5.6 Ablation runs: each setup with vs. without the weekly multi-timeframe gate (§7.6); keep the gate per-setup only where it improves OOS profit factor or drawdown
- **DoD:** Written backtest report per setup with all required metrics; only gate-passing setups enabled in `config.yaml`.

### Phase 6 — Risk, Tracking & Outputs (est. 3–4 agent-days)
- [ ] 6.1 Position sizing + portfolio caps incl. correlation cap & gap-risk stress test (§9)
- [ ] 6.2 Position tracker + daily "actions required" engine (SL/T1/trailing/time-stop) + `fills` recording for the slippage feedback loop
- [ ] 6.3 Chart generation (annotated Plotly per signal) (§7.2)
- [ ] 6.4 Daily markdown report (regime banner, new signals, open-position actions, watchlist) + Telegram/email push
- **DoD:** After the daily job, a complete report with charts lands in `reports/` and (if configured) Telegram.

### Phase 6.5 — News & Event Intelligence (est. 3–4 agent-days) — see Section 17
- [ ] 6.5a **Rules + proxies (no LLM):** corporate-announcement ingestion & category mapping; RSS ingestion (Moneycontrol/ET/Reuters/Google News); keyword rule classifier; quantitative macro proxies (crude, USDINR, VIX, GIFT Nifty gap); `news_events` + `sentiment_daily` tables; signal-modifier rules (§17.4) wired into signal generator with RISK_OFF regime override
- [ ] 6.5b **LLM stage (`gpt-4o-mini`):** batch classification of rule-unresolved headlines, strict-JSON prompt, confidence filter, cost logging, circuit breaker (rules-only fallback on API failure)
- **DoD:** A simulated "war headline day" (inject test events) flips the system to RISK_OFF with the cause in the report banner; a stock-level raid event vetoes that stock's pending signal; LLM outage does not block the pipeline.

### Phase 7 — Dashboard & Automation (est. 4–6 agent-days)
- [ ] 7.1 FastAPI: `/signals`, `/universe`, `/stock/{symbol}` (full analysis), `/regime`, `/performance`
- [ ] 7.2 Web dashboard: signal table (sortable), Lightweight-Charts stock page with levels drawn, signal-outcome performance page
- [ ] 7.3 Scheduler: daily 7:00 PM IST pipeline, Sunday fundamentals, holiday-aware; failure alerts to Telegram
- [ ] 7.4 60-day paper-trading mode: auto-track every signal outcome → `signal_outcomes`, live stats page
- [ ] 7.5 Live decay monitor (§10.5): rolling per-setup stats, auto watch-only demotion, Telegram alert
- [ ] 7.6 "Why NOT" explorer (`/whynot/{symbol}`), weekend deep-dive report, Telegram position-logging (reply "took RELIANCE 100 @ 3010" to open a tracked position), monthly slippage recalibration job
- **DoD:** System runs hands-free for a week; dashboard shows signals, charts, and live hit-rate.

### Phase 8 — Enhancements (post-validation only)
Intraday refinement via broker API (Kite Connect) for better entries; F&O short signals; sector-rotation model; ML ranking layer (gradient boosting on setup features vs. outcomes — only after ≥1,000 tracked signals); news/sentiment ingestion; multi-user support (Postgres migration).

---

<a id="13-database-schema"></a>
## 13. Database Schema (DuckDB, v1)

```sql
-- symbol master (track identity via ISIN; symbols get renamed)
CREATE TABLE symbols (
  isin TEXT PRIMARY KEY, symbol TEXT NOT NULL, name TEXT, exchange TEXT,
  sector TEXT, industry TEXT, mcap_cr DOUBLE, listing_date DATE,
  is_active BOOLEAN, band_pct INTEGER, surveillance TEXT
);

CREATE TABLE prices_raw (
  symbol TEXT, date DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
  volume BIGINT, traded_value DOUBLE, delivery_qty BIGINT, delivery_pct DOUBLE,
  PRIMARY KEY (symbol, date)
);

CREATE TABLE prices_adj (  -- corporate-action adjusted; technicals read this
  symbol TEXT, date DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
  volume BIGINT, adj_factor DOUBLE, PRIMARY KEY (symbol, date)
);

CREATE TABLE corporate_actions (
  symbol TEXT, ex_date DATE, action_type TEXT, ratio TEXT, value DOUBLE,
  PRIMARY KEY (symbol, ex_date, action_type)
);

CREATE TABLE fundamentals (
  symbol TEXT, period TEXT, period_end DATE,          -- 'FY2025','Q1FY26'
  sales DOUBLE, ebitda DOUBLE, net_profit DOUBLE, eps DOUBLE,
  cfo DOUBLE, fcf DOUBLE, debt DOUBLE, equity DOUBLE, roe DOUBLE, roce DOUBLE,
  interest_coverage DOUBLE, promoter_pct DOUBLE, pledge_pct DOUBLE,
  fii_pct DOUBLE, dii_pct DOUBLE, pe DOUBLE, ev_ebitda DOUBLE,
  source TEXT, fetched_at TIMESTAMP, PRIMARY KEY (symbol, period)
);

CREATE TABLE universe (
  symbol TEXT, as_of DATE, approved BOOLEAN, quality_score DOUBLE,
  reject_reasons TEXT[], score_breakdown JSON, PRIMARY KEY (symbol, as_of)
);

CREATE TABLE indicators_daily (
  symbol TEXT, date DATE,
  ema20 DOUBLE, ema50 DOUBLE, sma200 DOUBLE, adx DOUBLE, rsi DOUBLE,
  macd DOUBLE, macd_sig DOUBLE, atr DOUBLE, atr_pct DOUBLE,
  bb_width_pctile DOUBLE, vol_ratio DOUBLE, obv_slope DOUBLE,
  rs_pctile DOUBLE, roc20 DOUBLE, roc60 DOUBLE, dist_52wh DOUBLE,
  supertrend DOUBLE, in_base BOOLEAN, base_days INTEGER,
  PRIMARY KEY (symbol, date)
);

CREATE TABLE regime_daily (
  date DATE PRIMARY KEY, regime TEXT, nifty_close DOUBLE,
  breadth_above_200dma DOUBLE, india_vix DOUBLE
);

CREATE TABLE signals (
  signal_id TEXT PRIMARY KEY, date DATE, symbol TEXT, setup TEXT,
  direction TEXT, grade TEXT, composite_score DOUBLE,
  entry_aggressive DOUBLE, entry_conservative DOUBLE, entry_valid_till DATE,
  stop_loss DOUBLE, t1 DOUBLE, t2 DOUBLE, rr DOUBLE,
  suggested_risk_pct DOUBLE, reasons TEXT[], warnings TEXT[],
  payload JSON, chart_path TEXT
);

CREATE TABLE signal_outcomes (
  signal_id TEXT PRIMARY KEY, triggered BOOLEAN, trigger_date DATE,
  outcome TEXT,               -- T1_HIT, T2_HIT, SL_HIT, TIME_STOP, EXPIRED
  exit_date DATE, realized_r DOUBLE, mfe_r DOUBLE, mae_r DOUBLE
);

CREATE TABLE positions (
  position_id TEXT PRIMARY KEY, signal_id TEXT, symbol TEXT, qty INTEGER,
  entry_price DOUBLE, entry_date DATE, current_sl DOUBLE, status TEXT,
  booked_pct DOUBLE, notes TEXT
);

CREATE TABLE backtest_results (
  run_id TEXT PRIMARY KEY, run_at TIMESTAMP, setup TEXT, config_hash TEXT,
  period_start DATE, period_end DATE, sample TEXT,   -- IS / OOS / WF
  n_trades INTEGER, win_rate DOUBLE, avg_r DOUBLE, profit_factor DOUBLE,
  max_dd DOUBLE, cagr DOUBLE, exposure DOUBLE, report_path TEXT
);

CREATE TABLE index_constituents (   -- point-in-time index membership (survivorship fix)
  index_name TEXT, symbol TEXT, from_date DATE, to_date DATE,
  PRIMARY KEY (index_name, symbol, from_date)
);

CREATE TABLE fills (                -- actual executions for slippage recalibration
  position_id TEXT, side TEXT, fill_date DATE,
  signal_price DOUBLE, actual_price DOUBLE, slippage_bps DOUBLE
);

CREATE TABLE job_runs (
  job TEXT, started TIMESTAMP, finished TIMESTAMP, status TEXT,
  rows_written INTEGER, error TEXT
);
```

---

<a id="14-ui--output"></a>
## 14. UI / Output Specification

### Daily report (markdown + Telegram digest), generated ~7:30 PM IST:
1. **Regime banner:** `BULL | Nifty 25,412 (+0.6%) | Breadth 62% | VIX 13.2`
2. **New signals table:** rank, symbol, setup, grade, entry (both), SL, T1, T2, R:R, risk %, chart link, top reason
3. **Open-position actions:** "TATAPOWER: T1 hit — book 50%, move SL to 412 (breakeven)"
4. **Watchlist (grade C / forming setups):** stocks 1 condition away from a signal
5. **Warnings:** results this week for held/signalled names; ASM additions

### Dashboard pages:
- **/signals** — today's ranked table, filters (setup, sector, grade)
- **/stock/SYMBOL** — interactive chart with entry/SL/T1/T2 drawn, indicator panel, fundamental scorecard, signal history for that stock
- **/performance** — live signal hit-rate, equity curve of followed signals, per-setup stats, comparison vs Nifty 500
- **/universe** — approved list with quality scores and reject reasons (searchable)
- **/whynot/SYMBOL** — the "why NOT" explorer: for any stock, show every filter/gate it currently fails (liquidity? quality score? no setup? weekly gate? R:R?) — builds trust in the system and surfaces data bugs fast

---

<a id="15-scheduling"></a>
## 15. Scheduling & Automation (IST)

| Time | Job |
|---|---|
| Trading days 18:45 | Wait/poll for bhavcopy availability |
| Trading days 19:00 | Full EOD pipeline: ingest → validate → indicators → regime → scan → signals → charts → report → alerts (target < 20 min end-to-end) |
| Trading days 08:30 | Pre-market note: gaps vs. signals, actions reminder |
| Sunday 10:00 | Fundamentals refresh + universe rebuild + data-quality audit |
| Saturday 18:00 | Weekend deep-dive report: sector rotation map (sector RS ranks + trend), regime outlook, decay-monitor stats, coming-week results calendar & watchlist |
| Quarterly (results season) | Daily fundamentals refresh for companies that reported |
| First Sat of month | Full backfill integrity check; symbol-master sync; holiday calendar refresh |

All jobs holiday-aware via `holidays_nse` table. Any job failure → Telegram alert with traceback summary.

---

<a id="16-pitfalls--compliance"></a>
## 16. Pitfalls, Compliance & Disclaimers

**Engineering pitfalls (agents: read twice):**
1. **Look-ahead bias** — the #1 backtest killer. A signal computed from day T's close can only be acted on at day T+1's open. The backtester must enforce this at the engine level, not per-strategy.
2. **Survivorship bias** — backtesting only today's listed stocks inflates results. Document it; mitigate with point-in-time universes where possible.
3. **Unadjusted prices** — every Indian bonus/split season will spray false signals. Adjusted table is the only input to technicals.
4. **Overfitting** — every parameter added must justify itself out-of-sample. Prefer round, robust thresholds (RSI 40–55 zone, 2×ATR) over optimized ones (RSI 43.7).
5. **NSE scraping fragility** — endpoints change; isolate ALL NSE access in `NseClient`, add health checks, and keep yfinance fallback paths tested.
6. **Circuit limits** — a stock locked at upper circuit cannot be bought; at lower circuit cannot be sold (stop-loss won't fill). Signal generator must check band proximity; cost model must simulate gap-through-stop fills at actual open.
7. **Timezone** — everything IST (`Asia/Kolkata`); yfinance returns UTC-based dates — normalize on ingest.

**Compliance (India / SEBI):**
- Publishing buy/sell recommendations to the **public** requires SEBI Research Analyst (RA) registration. For **personal use** this system is fine. If it's ever offered to others, output must be repositioned as "screener/analytics" (levels as informational analytics, not advice) or an RA license obtained. **v1 is a personal-use tool. Every report footer carries: "Educational analytics, not investment advice. Securities markets are subject to market risks."**
- No automated order placement in v1 (that adds broker-API compliance and algo-trading approval considerations under SEBI's algo framework). The system *suggests*; the human *executes*.

---

<a id="17-news-module"></a>
## 17. Layer 6 — News & Event Intelligence Module

News moves Indian stocks at three distinct levels, and the system must handle each differently:

| Tier | Examples | Effect on system |
|---|---|---|
| **MACRO** (country/global) | War outbreak, border escalation, election results, RBI surprise, Union Budget, global crash, crude/USDINR shock | Overrides regime → RISK_OFF mode |
| **SECTOR** | PLI schemes, export bans/duties, GST changes, commodity price swings, sector regulation (e.g., RBI action on NBFCs) | Sector sentiment score → composite score modifier ±, sector block |
| **STOCK** | Order wins, ED/IT raids, auditor/CFO resignation, pledge invocation, ratings action, fraud allegations | Signal veto / exit flag / bonus points |

### 17.1 Design philosophy (read before building)

1. **News is a MODIFIER and VETO — never an entry trigger.** Price + volume remain the only entry triggers. Rationale: news sentiment cannot be rigorously backtested (free historical news archives don't exist at quality), so it is confined to roles with limited downside: blocking trades, tightening stops, adding warnings, and adjusting scores by bounded amounts.
2. **Price already discounts news.** A war headline shows up in India VIX, Nifty gaps, and breadth within minutes. The regime module (§7.5) is already a slow-safe macro-news detector. This layer adds *speed* (act the evening before, not 3 days into the drawdown) and *explanation* (the report says WHY the system went risk-off).
3. **Rules before LLM.** ~75% of relevant events are classifiable without any model call (see 17.3). The LLM handles only the ambiguous remainder. **Chosen LLM: OpenAI `gpt-4o-mini`** — batch classification once daily; at ~300–800 headlines/day × ~200 tokens each, expected cost is **under ₹300/month (~$1–3)**; use the OpenAI Batch API (50% discount, results within 24h — fine for a post-market pipeline). If cost must be zero, the rules-only mode (17.3 Stage 1) still delivers most of the value.

### 17.2 Data sources (free)

| Source | Content | Notes |
|---|---|---|
| **NSE/BSE corporate announcements** | Official stock-level filings, **pre-categorized** (results, order wins, pledge, resignations, board meetings) | Structured — mostly no NLP needed; poll via `NseClient` |
| RSS feeds: Moneycontrol, Economic Times Markets, Business Standard, LiveMint, Reuters India | Macro + sector + stock headlines | Free, stable; store headline + timestamp + URL |
| Google News RSS (`news.google.com/rss/search?q=...`) | Per-sector and macro keyword queries ("RBI policy", "India border", sector names) | Rate-limit politely |
| **Quantitative news proxies (no NLP at all)** | India VIX, GIFT Nifty overnight gap, Brent crude 5-day %, USDINR 5-day %, US VIX, gold spike | These *numerically* detect macro shocks — often faster and more reliable than headlines |

### 17.3 Processing pipeline (daily, post-market, before signal generation)

**Stage 0 — Dedup & relevance prefilter (no LLM):** drop duplicates (fuzzy title match), drop non-market noise (sports, entertainment) via keyword blocklist.

**Stage 1 — Rule classifier (no LLM):**
- Corporate announcements: map NSE/BSE category codes directly to `event_type` (ORDER_WIN, PLEDGE, RESIGNATION, RESULTS, RATING…) with fixed sentiment.
- Headlines: keyword/pattern rules for high-signal terms — "war", "strike", "sanctions", "raid", "default", "fraud", "downgrade", "rate hike", "ban", "record order", "stake sale". Assign tier, sentiment (−2…+2), affected sector via keyword→sector map.
- Quantitative proxies: crude +8% in 5d → negative for OMC/paints/aviation/tyres, positive for upstream oil; USDINR +2% → negative importers, positive IT/pharma. Pure arithmetic, always on.

**Stage 2 — LLM classifier (`gpt-4o-mini`, only unresolved items):** headlines that passed the prefilter but matched no rule. One batched call, strict JSON output:
```json
{"tier": "MACRO|SECTOR|STOCK", "event_type": "...", "sectors": ["..."],
 "symbols": ["..."], "sentiment": -2, "confidence": 0.8}
```
Discard results with confidence < 0.6. Log every call + cost to `job_runs`. **Circuit breaker:** if the LLM API is down, the pipeline proceeds rules-only — LLM classification must never block signal generation.

**Stage 3 — Aggregation:** roll events into `sentiment_daily` scores: MACRO score (3-day decay-weighted), per-sector score (5-day), per-stock event flags.

### 17.4 How news modifies signals (exact rules)

| Condition | Action |
|---|---|
| MACRO score ≤ −6 **AND** price confirmation (Nifty gap-down > 1% or VIX +15% in 2d) | Regime override → **RISK_OFF**: no new entries 3 sessions, tighten all trailing stops to 1.5×ATR, report banner states the cause |
| MACRO score ≤ −6, no price confirmation yet | WARNING banner only; halve position sizes on new signals |
| Sector score ≤ −5 | Block new signals in that sector for 3 sessions |
| Sector score ≥ +5 | +5 composite-score bonus for that sector's signals ("sector tailwind" reason) |
| Stock-level negative event (raid, resignation, pledge invocation, default, fraud) | **VETO** any pending signal; if position held → "exit / tighten stop" action in daily report |
| Stock-level positive event + price/volume surge same day | +5 composite bonus, tag "news catalyst" in reasons |
| Any news adjustment applied | Must appear in the signal's `reasons`/`warnings` array — explainability is mandatory |

Bounded influence: news can add/subtract at most **±5 composite points** and can veto/block — it can never push a sub-threshold setup above the publish line by itself.

### 17.5 Schema additions

```sql
CREATE TABLE news_events (
  event_id TEXT PRIMARY KEY, published_at TIMESTAMP, source TEXT,
  headline TEXT, url TEXT, tier TEXT, event_type TEXT,
  sentiment INTEGER, confidence DOUBLE, symbols TEXT[], sectors TEXT[],
  classified_by TEXT   -- 'RULES' | 'LLM' | 'PROXY'
);

CREATE TABLE sentiment_daily (
  date DATE, scope TEXT,        -- 'MACRO' | 'SECTOR' | 'STOCK'
  scope_key TEXT,               -- '', sector name, or symbol
  score DOUBLE, n_events INTEGER,
  PRIMARY KEY (date, scope, scope_key)
);
```

### 17.6 Validation (since backtesting isn't possible)

Tag every signal that a news rule modified (`news_adjusted = true` in payload). After 60–90 days of live tracking, compare outcomes of news-vetoed vs. published signals and news-boosted vs. normal signals in `signal_outcomes`. If vetoes aren't avoiding losses, loosen them; if boosts aren't outperforming, remove them. **The news layer must earn its keep with live data or be reduced to warnings-only.**

### 17.7 Build placement — Phase 6.5

Build AFTER Phase 5 (backtesting) proves the core price-based system, alongside Phase 6. Reason: news polish on an unvalidated signal engine is wasted effort. Rules + proxies first (6.5a), LLM stage last (6.5b) — ship rules-only if 4o-mini integration is deferred.

---

<a id="18-future-enhancements"></a>
## 18. Roadmap — Deferred & Future Work

> **Status note (2026-07-06):** Phases 1–7 are built; the strategy-research
> program concluded with NO validated strategy (see RESEARCH_LOG.md); the system
> is running as an **observational instrument** (scheduled daily pipeline +
> intraday watcher + position ledger + Telegram bot + weekly backups). This
> section is the single authoritative backlog: everything deferred, with its
> trigger for when to do it. Agents: work top-to-bottom within a tier; do not
> start a lower tier to avoid a harder item in a higher one.

### Tier A — Near-term operational (small; do soon, some are time-bombs)

1. **Results-calendar refresh job** ⚠ *live gap*: `results_calendar` was ingested
   once (through 2026-07-03). Board meetings are announced days ahead, so
   without a refresh, **live Setup E stops firing as the data ages**. Add a
   weekly step to the daily/Sunday pipeline calling
   `analyzer.research.results_calendar.run_ingest(from_year=<current>)`
   (idempotent upsert; one quarter window is enough). ~30 min of work.
2. **Holiday-calendar refresh** ⚠ *time-bomb*: `holidays_nse.csv` is seeded only
   through 2026. From Jan 2027 the trading calendar will treat NSE holidays as
   trading days (harmless-ish for ingest — bhavcopy just won't exist — but the
   intraday watcher and session math degrade). Add 2027 rows before year-end,
   or better: a job that scrapes the official NSE holiday list annually.
3. **Version control**: this repo is NOT a git repository. `git init`, commit,
   push to a private GitHub repo (code + docs only; `.gitignore` already
   excludes data/backups). This is also offsite code backup.
4. **Telegram credentials** (user-only, ~3 min): BotFather token + chat id +
   `setx` env vars + `notify.telegram_enabled: true`. Until then no alert
   reaches the phone. Then: test with one `send_telegram` call; run
   `analyzer bot` as a persistent process.
5. **Headless scheduling**: current Windows tasks run only while logged in.
   Either register with stored credentials (`schtasks /RU ... /RP`) or migrate
   to Oracle (DEPLOY.md) where cron has no such limitation.
6. **Oracle migration** itself (DEPLOY.md is complete): A1 instance, `scp` the
   DB, cron the three wrappers, Object-Storage backup bucket, then DISABLE the
   Windows tasks (single-writer rule).

### Tier B — When signals start flowing (regime leaves BEAR)

7. **News & Event Intelligence, Tier A** (full spec: Section 17; build 6.5a
   only): NSE/BSE announcement categories + RSS ingestion into `news_events`,
   keyword rules, quantitative macro proxies (crude/USDINR/VIX/GIFT gap),
   RISK_OFF regime override, **sector/stock warnings on HELD positions** (the
   CG Power case: "govt allows Chinese-linked firms into power tenders" →
   evening flag on held power stocks). Also starts the un-backfillable news
   dataset that §17.6 validation needs. **No LLM in this tier.**
8. **News Tier B — LLM classifier** (spec §17.3 stage 2, gpt-4o-mini, ~$1-3/mo):
   only after Tier A runs and the rules-unclassified residue looks worth it.
9. **"Why NOT" explorer** (`/whynot/{symbol}`, spec in Section 14): for any
   symbol, show which gate/filter it currently fails. Best debugging tool for
   "why is the system quiet?" questions during the observational run.
10. **Weekend deep-dive report** (spec Section 15): sector-rotation map, regime
    outlook, decay-monitor stats, coming-week results calendar.

### Tier C — At the re-evaluation checkpoint (~Jan 2027, ≥2 quarters of live outcomes)

11. **Observational verdict**: analyze `signal_outcomes` sliced by the
    `research-quality-gate` tag. Primary hypotheses, pre-registered in
    RESEARCH_LOG.md: (a) **PEAD+quality** (holdout-descriptive PF 2.08, n=40 —
    a hypothesis, NOT a result), (b) momentum+quality watchlist. Honest
    outcomes include "still inconclusive".
12. **EXP-004c retry** (PEAD + fundamental YoY confirmation): was inconclusive
    (n=2) purely from quarterly-panel coverage; by 2027 the panel has more
    quarters. Pre-register before running.
13. **Momentum kill-switch refinement** (from EXP-001): breadth-based or
    hysteresis regime filter instead of raw 200DMA — only if drawdown tolerance
    demands it; pre-register.
14. **R5 — ML ranking layer** (spec in RESEARCH_PLAN.md): HistGradientBoosting
    over setup features vs outcomes, purged walk-forward, embargo ≥45d. Needs
    enough live outcomes to be non-laughable; was skipped at the decision gate
    for budget reasons, not disproven. Also the later **ML exit optimization**
    (P(further upside) at T1) belongs here.
15. **Research-data honesty upgrades** (needed before ANY new historical
    research): populate `index_constituents` point-in-time membership (table
    exists, never filled), delisted-stock backfill, pledge-% ingestion (task
    2.2 remnant — the pledge hard-filter still cannot fire on live data).

### Tier D — Only if a strategy validates (live, gates passed)

16. **Broker integration (Zerodha Kite Connect)**: GTT orders (entry+SL+target
    natively), one-click from dashboard. Also enables real-time quotes for the
    watcher (kills the ~15-min yfinance delay). ₹500+/mo — not before an edge
    pays for it.
17. **Trade-journal / broker-import module** (design already drafted: Zerodha
    tradebook CSV adapter → FIFO lot reconstruction → signal matching →
    execution-quality + discipline-audit reports; `fills`/`positions` tables
    and slippage loop already exist as foundations).
18. **F&O module**: futures shorts (cash shorting is intraday-only in India),
    option-selling overlays on held positions.
19. **Position-sizing automation**: wire §9 sizing output into the signal →
    order flow (currently informational only).

### Tier E — Research backlog (ideas, unranked; pre-register before testing)

20. **Sector rotation overlay** — overweight top-3 RS sectors.
21. **Bulk/block & insider (SAST) deal signals** — free NSE CSVs; promoter
    buying + technical setup = score bonus.
22. **FII/DII daily flows** — sustained FII selling as a regime dampener.
23. **Overhead supply check** — volume-profile node above entry penalizes
    breakouts into supply.
24. **Options OI sentiment** — OI buildup/PCR at key strikes for F&O names.
25. **Regime-specific parameter sets** — separate tuned profiles per regime.
26. **News-signal interaction study** — once Tier-B news data has accumulated
    alongside outcomes: do news-flagged signals over/under-perform? (§17.6.)

### Tier F — Scale (only if the system ever serves more than one user)

27. **PostgreSQL/Timescale migration** (kills the DuckDB single-writer limits),
    dashboard authentication, multi-user position ledgers — and the SEBI
    Research Analyst question (Section 16) stops being theoretical: **publishing
    signals to others without RA registration is not legal in India.**

---

## Quick-Start Order for Agents

```
1. Read this file fully.
2. Build Phase 1 (data). Verify DoD.
3. Build Phase 2 (fundamentals) and Phase 3 (technicals) — parallelizable.
4. Build Phase 4 (signals). Verify on historical dates.
5. Build Phase 5 (backtest). DO NOT SKIP. Kill failing setups.
6. Build Phases 6, 6.5, 7 (risk, outputs, news layer, dashboard, automation).
7. Run 60-day paper validation before any real money.
```

*Document version 1.0 — 2026-07-02. All thresholds herein are starting values; the backtest (Phase 5) is the final authority on every number.*
