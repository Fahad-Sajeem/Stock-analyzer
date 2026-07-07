# Strategy Research Plan — Finding a Real Edge

> **Audience:** agents/developers doing strategy research on this codebase. Read
> [PLAN.md](PLAN.md) first (system design) and the Phase-5 verdict in
> [README.md](README.md). This document governs HOW we search for a profitable
> strategy without fooling ourselves.
> **Status:** plan approved-pending; no research phase started.

---

## 0. Where we stand (facts, not hopes)

1. The measurement apparatus works: full-universe (2,708 symbols, 10 yr) EOD data,
   honest cost model (~0.5–0.6% round trip), look-ahead-free simulator, IS/OOS
   split, acceptance gates.
2. **All four classic technical setups FAILED out-of-sample** (PF 0.80–0.98 =
   net-losing after costs), after in-sample tuning reached PF 1.15–1.40.
   Textbook overfitting; the setups have no durable standalone edge.
3. Known data gaps: no point-in-time fundamentals history, no results-announcement
   dates (Setup E dormant), survivorship bias (only current listings backfilled).
4. **The 2022–2026 OOS window is partially burned** — we have seen aggregate
   results on it once. Every additional peek degrades its evidential value.

## 1. Research contract (non-negotiable rules)

These rules exist because the failure mode of this work is not "no edge found" —
it is "fake edge found." An agent that violates these produces worthless results.

- **R-1. New data splits.**
  - `DEV` = 2016-07-01 → 2023-12-31. Unlimited experiments, walk-forward inside.
  - `HOLDOUT` = 2024-01-01 → 2026-06-30. **Budget: 3 evaluations TOTAL** across
    the entire research program (one per final candidate). A holdout run must be
    logged in RESEARCH_LOG.md *before* it is executed.
  - Live paper trading (60–90 days) is the final gate regardless of backtests.
- **R-2. Hypothesis before experiment.** Every experiment gets a RESEARCH_LOG.md
  entry BEFORE running: hypothesis, exact config, window, metric expected to move,
  kill threshold. Failures are logged too — an unlogged failure is data snooping.
- **R-3. Acceptance gates do not move.** OOS/HOLDOUT: PF ≥ 1.5, ≥ 300 trades
  (or ≥ 8 portfolio-years for portfolio strategies), max DD < 25%, ≥ 70% positive
  years. We do not lower gates to let a marginal strategy through; a strategy that
  needs a lower bar doesn't have an edge, it has a story.
- **R-4. Costs always on.** No experiment is ever evaluated pre-cost.
- **R-5. Point-in-time or it doesn't exist.** Any fundamental/event feature must
  carry an availability date (with a conservative lag) and be joined as-of.
  If we can't date it, we can't use it.
- **R-6. Survivorship honesty.** Our universe is current listings only. Absolute
  returns are inflated. Mitigations: always compare against the same-universe
  buy-and-hold benchmark (bias cancels partially in relative comparisons); keep
  the liquidity gate on; state the bias in every report.

## 2. Research directions, ranked by (evidence × feasibility)

### R1 — Cross-sectional momentum portfolio (apparatus sanity check + baseline)
**Hypothesis:** 6/12-month momentum with a skip-month, top-N (15–25) liquid names,
monthly rebalance, regime kill-switch (move to cash when Nifty < 200DMA), beats
same-universe buy-and-hold on risk-adjusted basis. This is the *most robustly
documented* anomaly in Indian equities (NSE momentum indices outperform over long
windows).
**Why first:** (a) if our apparatus cannot detect a KNOWN edge, the apparatus is
broken — this is a calibration test; (b) if it works, it is itself a deployable
baseline (not swing trading, but a real strategy the infra can serve).
**Method:** new portfolio-mode backtester path (monthly rebalance, position-level
costs, equity curve vs benchmark). DEV window only.
**Data needed:** none new. **Effort:** ~1–2 agent-days.
**Kill criterion:** if momentum top-quintile doesn't beat universe B&H in DEV by
≥ 3% CAGR with lower-or-similar DD, investigate apparatus for bugs before ANY
other research (the anomaly is too well-documented for a clean miss).

### R2 — Point-in-time fundamentals history (data foundation)
**Hypothesis (enabling, not tradeable):** Screener.in company pages expose ~10 yr
of annual P&L/balance-sheet and ~12 quarters of results per company. Scraping the
top ~800 liquid names gives a usable point-in-time fundamentals panel.
**Availability rule (conservative):** annual FY data usable from Oct 1 following
FY end; quarterly results usable 60 days after quarter end. (Real announcement
dates come in R4; these lags guarantee no look-ahead meanwhile.)
**Method:** extend `fetch_screener.py` to parse the P&L/quarters tables; new
`fundamentals_history` table (symbol, period, metrics, available_from); nightly
rate-limited scrape job with caching (~800 pages, ~1 req/2s ≈ 30 min/run).
**Effort:** ~2–4 agent-days (scraper fragility is the risk).
**Kill criterion:** if <500 symbols parse cleanly, shrink scope to Nifty-500
members rather than fight the long tail.

### R3 — Quality/fundamental overlay on technicals (the original techno-funda thesis, tested properly)
**Hypothesis:** technical setups fail on the broad universe because most
signals fire on junk. Gating candidates on point-in-time quality (ROCE > 15%,
positive FCF, low pledge, earnings growth) lifts expectancy enough to matter.
Secondary hypothesis: quality-tilted momentum (R1 portfolio ∩ quality gate)
improves the R1 baseline.
**Depends on:** R2. **Method:** re-run DEV backtests of setups A/B/D and the R1
portfolio with the quality gate as-of each signal date; compare like-for-like.
**Effort:** ~1–2 agent-days once R2 lands.
**Kill criterion:** if quality gating moves setup PF by < +0.15 in DEV, the
overlay thesis is dead for setups (may still help the portfolio).

### R4 — Results calendar + PEAD (Setup E for real)
**Hypothesis:** post-earnings-announcement drift survives costs in India
(strong academic support; India's staggered results seasons help).
**Method:** ingest NSE board-meeting/results-date history (free archives) →
`results_calendar` table with actual announcement dates; activate Setup E
(`require_results_flag` stays true, flag now real); DEV backtest.
**Effort:** ~2–3 agent-days (historical announcement-date coverage is the risk;
fallback = forward-only collection + longer live validation).
**Kill criterion:** DEV PF < 1.2 → drop.

### R5 — ML ranking layer (last, because it needs everything above)
**Hypothesis:** no single setup rule has an edge, but a gradient-boosted model
over the full feature set (indicators, structure, regime, breadth, liquidity,
quality from R2, PEAD flags from R4) can rank signal candidates such that the
top decile has positive after-cost expectancy.
**Method:**
- Dataset builder: relax setup preconditions to generate ~20–50k historical
  candidate signals with features frozen at signal date + simulated outcomes
  (the runner already does 90% of this).
- Model: sklearn `HistGradientBoostingClassifier` (no new C deps) predicting
  P(T1 before SL); calibrate; threshold at top decile.
- Validation: **purged walk-forward CV** (train ≤ t, test t+embargo; embargo ≥
  45 days to kill overlapping-trade leakage; no same-symbol overlap across the
  boundary). Never a random split — random splits on overlapping windows are
  the classic quant-ML fraud-on-yourself.
**Effort:** ~3–5 agent-days.
**Kill criteria:** walk-forward AUC < 0.55, or top-decile after-cost expectancy
≤ 0 in ≥ half the folds → drop. No hyperparameter search beyond one small grid
declared in the log up front.

### Explicitly rejected directions (don't burn time)
- Intraday/HFT anything — wrong infrastructure, wrong cost regime.
- Options strategies — different risk machinery, out of scope here.
- More technical-setup permutations (candlestick combos, more indicators) —
  we just proved this class has no standalone edge; iterating within it is
  overfitting with extra steps.

## 3. Sequence & decision points

```
R1 momentum sanity (1-2d)
 ├─ FAIL → debug apparatus; halt research until resolved
 └─ PASS → R2 fundamentals data (2-4d)
            └─ R3 quality overlay (1-2d)  ──┐
               R4 PEAD (2-3d, parallel ok) ──┼─→ surviving candidates
               R5 ML ranking (3-5d, after) ─┘
                     │
                     ▼
        DECISION GATE: pick ≤ 3 candidates max
                     │
                     ▼
        One HOLDOUT run each (budget R-1) → gates (R-3)
                     │
                     ▼
        Survivors → validated_setups/strategies + 60-90d paper trading
```

Total effort to the decision gate: roughly **9–16 agent-days** of work.
Honest prior on outcomes: R1 pass ~80% (documented anomaly), R3 helps-setups
~30%, R4 works ~40%, R5 works ~25%. It is entirely possible the final answer is
"only the momentum portfolio survives" — that is a perfectly good outcome, and
better than a fake swing edge.

## 4. Deliverables & bookkeeping

- `RESEARCH_LOG.md` — append-only experiment registry. Entry format:
  `## EXP-NNN | date | direction | status`
  with: hypothesis, config/window, expected effect, kill threshold, result,
  decision. **Failures stay in the log forever.**
- Code goes in `src/analyzer/research/` (portfolio backtester, dataset builder,
  models) — kept separate from the production pipeline until something passes.
- `fundamentals_history` and `results_calendar` tables added to schema when R2/R4
  build them.
- Every phase ends with its log entries + a short results section appended to
  this file under "Findings".

## 5. Findings

### R1 — momentum sanity check: PASSED (EXP-001, 2026-07-03)
The apparatus detects the documented momentum anomaly clearly: top-20 blended
6/12m momentum, monthly rebalance, costs on, beat the same-survivorship
equal-weight universe by **+9.0pp CAGR** (25.9% vs 16.9%) with a higher Sharpe
(0.92 vs 0.79) over DEV (77 months, ~507 eligible names/rebalance).
**Apparatus validated; further research is on solid ground.**
Nuance: the pre-registered *primary* variant (with a Nifty-200DMA kill-switch)
failed its +3pp criterion — the kill-switch cut drawdown (39.8% vs 45.0%) but
cost 7.5pp CAGR through whipsaw (17/77 months in cash). Momentum plain is the
baseline candidate going forward. Full details: RESEARCH_LOG.md EXP-001.

*Next: R2 (point-in-time fundamentals data foundation).*

### R2 — fundamentals history: BUILT (EXP-002, 2026-07-03)
800/800 top-liquidity symbols scraped from Screener; 203k rows; ~12 yr annual
statements (739 syms), quarterlies (729), shareholding history (800); conservative
availability lags enforced on every row. Kill criterion (≥500) passed.

### R3 — quality overlay: MIXED, with a major methodological catch (EXP-003, 2026-07-03/04)
The naive result looked spectacular (momentum + quality: Sharpe 1.44 vs 0.92) —
but a **membership-bias control** (same strategy on the scraped-800 set WITHOUT
quality) showed **+16.7pp CAGR of pure survivorship artifact**: the scraped set is
chosen by today's liquidity, which is future information at historical rebalances.
Honest quality effect vs control: **max DD −13.1pp, vol −3.6pp, Sharpe +0.07,
CAGR −3.1pp** → quality is a real **risk reducer**, not an alpha machine.
For setups: only **Setup A (breakout)** survives the control (+0.30 PF, expectancy
×3.7, n=122); B and D fail the frozen +0.15 kill criterion → overlay-for-setups
thesis dead for them. Two candidates carried forward: quality-gated momentum
portfolio, quality-gated breakout. Membership bias largely evaporates in the
HOLDOUT window (membership is near-contemporaneous there). Details: EXP-003.

*Next: R4 (results calendar + PEAD) and R5 (ML ranking), then the decision gate.*

### R4 — PEAD: STRONGEST RESULT OF THE PROGRAM (EXP-004, 2026-07-04)
Real announcement dates ingested from the NSE board-meetings archive (78k
announcements, 2,732 symbols, 2016→today) — no proxy needed. Setup E (PEAD) on
the **full universe with real dates: DEV PF 1.51, +0.24R/trade, 54% win, DD 16%
(n=202)** — passes the R4 kill criterion and is the cleanest result we have (no
membership bias). Adding the quality gate: PF 1.96, 62.5% win, DD 11% (n=56,
membership caveat). YoY-confirmation variant inconclusive (data coverage).
Caveat: ~29 trades/yr means the ≥300-trade holdout gate cannot be met in 2.5
years — a strong holdout would still end as "promising, extend via paper
trading". **Three candidates now fill the holdout budget: quality-momentum
portfolio, quality-gated breakout, PEAD.**

### DECISION GATE — ALL THREE CANDIDATES FAILED (2026-07-04). PROGRAM CONCLUDED.
R5 was skipped by decision; the full 3-run holdout budget was spent on the
registered candidates. Results (2024-01→2026-06, verdicts final):
- **Momentum+quality: FAIL** — beat the benchmark on CAGR (9.3 vs 6.6) and
  Sharpe (0.46 vs 0.38) but max DD 27.2% breached the 25% cap by 2.2pp.
- **Breakout+quality: FAIL** — PF 1.32 < 1.5 (expectancy +0.167R, DD 9.2%, n=76).
- **PEAD plain: FAIL decisively** — PF 1.03; the DEV edge (1.51) did not persist
  (2024 +16R, 2025 −14R). The holdout did exactly its job.

**Bottom line: no strategy validated for real capital.** The honest deliverables
of this program: a validated measurement apparatus, point-in-time fundamentals +
results-calendar data assets, quantified bias traps (survivorship membership
+16.7pp; DEV→holdout decay), and three cleanly killed candidates. Forward path
(no holdout cost): observational paper-trade tracking of PEAD+quality (holdout
descriptive: PF 2.08, n=40 — a hypothesis, not a result) and momentum+quality;
revisit after 2+ quarters of live outcomes.
