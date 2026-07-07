# Research Log — append-only experiment registry

> Contract: every experiment is logged HERE before it is run (hypothesis, exact
> config, window, expected effect, kill threshold). Failures stay forever.
> See RESEARCH_PLAN.md Section 1.

---

## EXP-001 | 2026-07-03 | R1 momentum-portfolio sanity check | REGISTERED (pre-run)

**Hypothesis:** A cross-sectional momentum portfolio — top 20 liquid NSE names by
blended 6m/12m momentum (skip-month), equal weight, monthly rebalance, with a
regime kill-switch (cash when Nifty50 < 200DMA) — beats the same-universe
equal-weight benchmark by ≥ 3pp CAGR with lower-or-similar max drawdown (≤ 1.1×
benchmark DD) on the DEV window. Rationale: most robustly documented anomaly in
Indian equities (NSE momentum indices).

**Exact config (declared before running):**
- Window: DEV only — rebalances from first month-end with ≥ 252 prior trading
  days in our panel (~2017-07, data starts 2016-07) through 2023-12-31.
- Universe at each rebalance: non-NaN close, close ≥ ₹20, 20-day median traded
  value (close × volume, adjustment-invariant) ≥ ₹3 cr, ≥ 252 days history.
- Score: 0.5 × (P[t−21]/P[t−126] − 1) + 0.5 × (P[t−21]/P[t−252] − 1).
- Portfolio: top 20 by score, equal weight, rebalance at month-end close.
- Costs: 0.30% per side (STT 0.10 + charges 0.05 + slippage 0.15) charged on
  entries and exits as turnover fraction of book. Benchmark charged NO costs
  (conservative against the strategy).
- Kill-switch: at rebalance, Nifty50 close < 200DMA → 100% cash for the month.
- Variants declared up front: (a) with kill-switch [primary], (b) without
  kill-switch [secondary], (c) equal-weight all-eligible benchmark, (d) Nifty50
  price return [reference].

**Expected effect:** variant (a) CAGR ≥ benchmark (c) + 3pp; DD(a) ≤ 1.1 × DD(c).

**Kill criterion (from RESEARCH_PLAN R1):** if top-20 momentum fails to beat the
same-universe benchmark by ≥ 3pp CAGR in DEV, treat the APPARATUS as suspect —
debug before any further research. (The anomaly is too well-documented for a
clean miss.)

**Known biases:** survivorship (current listings only) inflates BOTH strategy and
benchmark; relative comparison partially cancels it. Stated per contract R-6.

**Result (2026-07-03, DEV, 77 monthly rebalances, avg eligible universe 507):**

| Variant | CAGR | Max DD | Sharpe | Positive yrs | Final equity |
|---|---|---|---|---|---|
| (a) momentum + kill-switch [primary] | 18.4% | 39.8% | 0.80 | 57% | 2.95x |
| (b) momentum plain [secondary] | **25.9%** | 45.0% | **0.92** | 71% | 4.38x |
| (c) EW eligible universe [benchmark] | 16.9% | 47.4% | 0.79 | 71% | 2.72x |
| (d) Nifty 50 [reference] | 12.7% | 29.3% | 0.77 | 100% | 2.16x |

- **Primary hypothesis (a): FAIL** — edge vs benchmark +1.5pp < +3pp required.
- **Secondary (b): PASS both declared criteria** — edge **+9.0pp** CAGR, DD 45.0%
  ≤ 1.1 x 47.4%, and higher Sharpe (0.92 vs 0.79).
- **Apparatus sanity: CONFIRMED.** The apparatus clearly detects the documented
  momentum anomaly (+9pp over the same-survivorship benchmark, costs on). The R1
  kill criterion ("momentum fails to beat universe -> suspect the apparatus")
  is NOT triggered — momentum beat the universe decisively.
- **Diagnosis of (a)'s failure:** the 200DMA kill-switch went to cash in 17 of 77
  months and missed rebound months (classic whipsaw at monthly granularity);
  it did cut DD (39.8% vs 45.0%) but cost 7.5pp CAGR. The overlay as specified
  is a drag, not a benefit.
- Survivorship note (contract R-6): absolute CAGRs are inflated for (a), (b),
  (c) alike; the RELATIVE +9pp edge is the meaningful number.

**Decision:** R1 objective met (apparatus validated; baseline candidate =
momentum plain). Kill-switch refinement (e.g., breadth-based or with re-entry
hysteresis) would be a NEW pre-registered experiment — only worth doing before
the holdout stage if drawdown tolerance demands it. Proceed to R2
(point-in-time fundamentals) per plan; R3 will also test a quality tilt on this
baseline.

---

## EXP-002 | 2026-07-03 | R2 point-in-time fundamentals build | REGISTERED (pre-run)

**Type:** data foundation (enabling, not tradeable). No return metrics.

**Plan:** scrape Screener.in company pages (consolidated, standalone fallback)
for the **top 800 symbols by 1-year median traded value**. Parse: annual P&L
(~10 yr: sales, operating profit, OPM%, net profit, EPS), balance sheet
(equity capital, reserves, borrowings), cash flow (CFO), ratios (ROCE%),
quarterly results (~12 quarters), and quarterly shareholding (promoter/FII/DII%).
Store LONG format in a new `fundamentals_history` table.

**Point-in-time availability rules (conservative, contract R-5):**
- Annual statements: `available_from = period_end + 185 days` (FY Mar → ~Oct 1).
- Quarterly results: `available_from = period_end + 60 days`.
- Shareholding pattern: `available_from = period_end + 45 days`.
(Real announcement dates arrive in R4 and can tighten these; the lags above
guarantee no look-ahead meanwhile.)

**Mechanics:** ~1 req / 2 s, on-disk HTML cache (re-runs free), pandas.read_html
parsing anchored per section id.

**Kill criterion (from RESEARCH_PLAN R2):** if < 500 of 800 symbols parse
cleanly, shrink scope to current Nifty-500 members instead of fighting the tail.

**Result (2026-07-03): SUCCESS — 800/800 symbols scraped, 203,149 rows.**
Coverage: annual statements 739 symbols (~103k rows), quarterly results 729
(~73k rows), shareholding history 800 (~27k rows). Kill criterion (≥500) passed
with room. Annual history typically 12 years (FY2015–FY2026). HTML pages cached
on disk — refreshes are incremental. Note: 61 symbols lack annual-table parses
(mostly banks/holding companies with non-standard tables) — acceptable; they
simply fail the quality gate as "unverifiable" per the frozen definition.

---

## EXP-003 | 2026-07-03 | R3 quality overlay | REGISTERED (pre-run)

**Quality gate definition (frozen before running):** a symbol passes at an as-of
date iff, using ONLY ``fundamentals_history`` rows with ``available_from`` ≤
as-of: ROCE ≥ 15% **and** CFO > 0 (latest annual) **and** D/E proxy
(borrowings / (equity+reserves)) < 1.0 — or ≥ 1.0 allowed if ROCE ≥ 12
(financials proxy) **and** 3-yr sales CAGR > 5%. Missing/unverifiable = FAIL.
Snapshots monthly; signals join the latest month-end ≤ signal date.

**EXP-003a hypothesis (momentum + quality):** restricting the EXP-001 momentum
top-20 to quality-gated names improves risk-adjusted results — Sharpe(quality)
> Sharpe(plain) OR max DD lower by ≥ 5pp, while CAGR stays within 3pp of plain.
DEV window; same EW benchmark; costs on for both variants.

**EXP-003b hypothesis (setups + quality):** gating setups A/B/D signals on
point-in-time quality lifts DEV profit factor by ≥ +0.15 per setup
(RESEARCH_PLAN R3 kill criterion — below that, the overlay-for-setups thesis
is DEAD).

**Result (2026-07-03/04, DEV) — WITH the membership-bias control** (control =
same strategy restricted to the scraped-800 membership WITHOUT quality; the
scraped set is selected by TODAY's liquidity, i.e. future information at
historical rebalances, so the honest quality effect is quality-vs-control):

*EXP-003a momentum (77 months, costs on):*

| Variant | CAGR | Max DD | Sharpe | Vol |
|---|---|---|---|---|
| plain (full universe, EXP-001) | 25.9% | 45.0% | 0.92 | 30.0% |
| **member-only control (no quality)** | **42.6%** | 41.6% | 1.37 | 29.4% |
| quality-gated (avg 142 names pass) | 39.5% | **28.5%** | **1.44** | 25.8% |

- **Membership bias quantified: +16.7pp CAGR** (25.9 → 42.6) from nothing but
  "is in today's top-800" — a huge, pure survivorship artifact. Any naive
  reading of the quality numbers against the plain baseline is invalid.
- **Honest quality effect (vs control): max DD −13.1pp (41.6 → 28.5), vol
  −3.6pp, Sharpe +0.07, CAGR −3.1pp.** Quality is a genuine RISK REDUCER on
  this universe, not an alpha machine.
- Pre-registered criteria technically pass vs plain, but per contract R-6 the
  comparison that matters is vs control: DD improvement passes (≥5pp), CAGR
  within ~3pp passes at the boundary, Sharpe improvement is marginal.
  **Verdict: quality tilt = real but modest risk-adjusted improvement.**

*EXP-003b setups (DEV, PF ungated-full → member-only control → quality-gated):*

| Setup | full | control | quality | quality effect vs control | ≥ +0.15? |
|---|---|---|---|---|---|
| A breakout | 1.06 | 1.10 | **1.40** (n=122, exp 0.194R) | **+0.30** | ✅ PASS |
| B pullback | 1.15 | 1.18 | 1.28 (n=101) | +0.10 | ❌ FAIL |
| D squeeze | 1.05 | 1.11 | 1.15 (n=753) | +0.04 | ❌ FAIL |

- **Setup A (breakout) survives the control:** quality gating triples its
  expectancy (0.052 → 0.194R) and lifts PF +0.30 over the membership control.
  Caveat: n=122 in DEV is modest; and PF 1.40 is still below the 1.5 gate.
- B and D: the overlay-for-setups thesis is DEAD per the frozen kill criterion.

**Holdout note (for the decision gate):** membership bias mostly evaporates in
the HOLDOUT window (2024–2026) because "today's top-800 by 1-yr median traded
value" is nearly contemporaneous there. DEV numbers are inflated; holdout
numbers will be much closer to honest.

**Decision:** carry TWO candidates forward: (1) quality-gated momentum
portfolio (risk-reduction overlay confirmed), (2) quality-gated Setup-A
breakout (only surviving swing-trade candidate). Proceed to R4 (PEAD) and R5
(ML ranking) before spending any holdout budget.

---

## EXP-004 | 2026-07-04 | R4 results calendar + PEAD (Setup E) | REGISTERED (pre-run)

**Data branch decision rule (declared before probing):** prefer REAL results
announcement dates from the NSE board-meetings archive (purpose contains
"Results"). If historical coverage is insufficient — defined as < 5 years of
history OR < 400 of our 800 scraped symbols covered — fall back to the
**statutory-window proxy**: treat any bar inside [quarter_end, quarter_end+45d]
([+60d] for Q4) whose volume ≥ 2.5x average AND |gap or move| ≥ 2% as a
results-reaction day (SEBI LODR filing deadlines make these windows exhaustive).
Proxy risk: catches some non-earnings events inside results season — accepted
and disclosed.

**Setup E mechanics (as built in Phase 4, unchanged):** results-day reaction =
gap ≥ 2% or close ≥ +4%, volume ≥ 2.5x, close in top 30% of range, range ≤ 8%,
close > SMA200; entry above reaction-day high within 3 sessions; stop below
reaction-day low; standard levels/exits (T1 1.5R book-half, T2, 25-session
time stop); costs on.

**Variants (all declared now):**
- 004a: PEAD on price/volume reaction alone (no fundamentals).
- 004b: 004a + EXP-003 frozen quality gate at signal date.
- 004c: 004a + real fundamental confirmation from ``fundamentals_history``
  quarterlies (net-profit YoY ≥ 25% or sales YoY ≥ 10% for the just-reported
  quarter, joined point-in-time).

**Window:** DEV only. **Kill criterion (RESEARCH_PLAN R4):** best variant DEV
PF < 1.2 → drop PEAD.

**Result (2026-07-04):** Data branch = REAL dates (NSE board-meetings archive:
78,006 results announcements, 2,732 symbols, 2016-01→today; no proxy needed).
2,102 symbols had both announcements and indicator frames.

| Variant | n (DEV) | Win% | PF | Expectancy | Max DD |
|---|---|---|---|---|---|
| 004a plain PEAD | 202 | 54.0 | **1.51** | +0.24R | 16.1% |
| 004b + quality gate | 56 | 62.5 | **1.96** | +0.37R | 11.0% |
| 004c + YoY confirm | 2 | — | — | — | — |

- **004a PASSES the kill criterion decisively (1.51 ≥ 1.2)** — and, critically,
  this is the **cleanest result in the program**: full 2,102-symbol universe
  (NOT the scraped-800), real announcement dates, liquidity gate on, costs on.
  **No membership bias applies to 004a.**
- 004b: quality gating again lifts per-trade economics (PF 1.96, win 62.5%,
  DD 11%) — consistent with EXP-003b's Setup-A finding — but n=56 over 7 years
  (~8 trades/yr) is thin, and the quality gate inherits the scraped-800
  membership caveat.
- 004c: INCONCLUSIVE, not negative — n=2 because quarterly YoY needs both the
  current and year-ago quarter in the scraped panel; coverage too sparse. Do
  not treat as evidence against fundamental confirmation.
- **Honest caveat for the decision gate:** PEAD generates ~29 trades/yr, so a
  2.5-yr holdout yields ~70 trades — it CANNOT meet the ≥300-trade gate on the
  holdout alone. Per contract R-3 the gate does not move; if holdout PF is
  strong but underpowered, the honest verdict is "promising, extend sample via
  paper trading", not a pass.

**Decision:** PEAD (004a, with 004b as a sizing/selection refinement) becomes
the THIRD candidate. Candidates now: (1) quality-gated momentum portfolio,
(2) quality-gated Setup-A breakout, (3) PEAD. That fills the 3-slot holdout
budget — raising the question of whether to run R5 (ML) at all before the
decision gate.

---

## DECISION GATE | 2026-07-04 | HOLDOUT evaluations 1-3 of 3 | REGISTERED (pre-run)

**R5 (ML) skipped by explicit decision** (user-approved): lowest prior, budget
full, better done post-launch on live outcomes. The 3-run holdout budget
(contract R-1) is spent HERE, once, on the following frozen candidates.
**Window: 2024-01-01 → 2026-06-30 for all three. Results are final — no
re-runs, no tuning afterward on this window.**

**Sample-size honesty (declared before seeing any result):** 2.5 holdout years
cannot satisfy the formal gates (≥300 trades / ≥8 portfolio-years). Therefore
NO candidate can formally PASS today. The possible outcomes are:
- **PROVISIONAL PASS** → metrics below → candidate proceeds to 60–90 day paper
  trading with real position tracking;
- **FAIL** → candidate killed permanently.

**HOLDOUT-1 — quality-gated momentum portfolio** (config: EXP-001 mechanics +
EXP-003 frozen quality gate; top 20, blended 6/12m skip-month, monthly, equal
weight, 0.30%/side):
Provisional pass = CAGR > EW-universe benchmark AND Sharpe > benchmark AND
max DD < 25%.

**HOLDOUT-2 — quality-gated Setup-A breakout** (current tuned config:
vol≥2.0, rs≥70, BULL-only + EXP-003 quality filter at signal date):
Provisional pass = PF ≥ 1.5 AND expectancy > +0.10R AND max DD < 25%
(n will be ~30; explicitly underpowered).

**HOLDOUT-3 — PEAD / Setup E** (EXP-004a plain, full universe, real dates —
THE candidate metric; 004b quality-gated numbers reported alongside as
descriptive only, not a second evaluation):
Provisional pass = PF ≥ 1.5 AND expectancy > +0.10R AND max DD < 25%
(n expected ~70).

**Membership-bias note:** the scraped-800 quality gate is near-contemporaneous
in this window, so the EXP-003 bias concern is materially smaller here.

**Results (2026-07-04) — FINAL, holdout budget spent:**

**HOLDOUT-1 momentum+quality: FAIL** (on the DD criterion only).
CAGR 9.3% vs benchmark 6.6% ✓ | Sharpe 0.46 vs 0.38 ✓ | **max DD 27.2% ≥ 25% ✗**.
Context: a much tougher window than DEV (Nifty CAGR just 4.0%). The strategy
kept a modest relative edge but blew the drawdown budget by 2.2pp. Per the
registered rule, FAIL is FAIL — logged without re-litigation.

**HOLDOUT-2 breakout+quality: FAIL** (on the PF criterion).
n=76 | **PF 1.32 < 1.5 ✗** | expectancy +0.167R ✓ | DD 9.2% ✓. All trades in
2024 (BULL-only setup; 2025-26 offered few BULL months). Positive but below bar.

**HOLDOUT-3 PEAD plain: FAIL** (clearly).
n=111 | **PF 1.03 ✗** | expectancy +0.017R ✗. The DEV PF of 1.51 did NOT
persist: 2024 +16.1R, 2025 −14.2R. A textbook demonstration of why the holdout
exists — this looked like our best candidate and was flat out-of-sample.
*Descriptive only (NOT a registered evaluation, NOT a pass):* PEAD+quality
showed PF 2.08, +0.44R, n=40, DD 3.4%, and held up better in 2025 (−1.5R).
Under this contract that is a HYPOTHESIS for forward (paper-trade) observation,
not a result — using it now to claim success would be exactly the selection
effect this log exists to prevent.

**PROGRAM CONCLUSION:** No candidate earned a provisional pass. **No strategy
is validated for real capital.** The system remains an analytics/screener tool;
all published signals keep the UNVALIDATED warning. Legitimate forward path
(costs no holdout budget): track PEAD+quality and momentum+quality signals in
live paper trading as OBSERVATIONAL data collection; revisit after 2+ quarters
of live outcomes.

---
