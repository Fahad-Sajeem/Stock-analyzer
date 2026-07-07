"""Layer 5 — Backtesting & validation (PLAN Section 10).

The most important layer: no setup ships to the live signal feed until it passes
the acceptance gates here. Custom event-loop engine (our rules are simple enough
that this is clearer and more auditable than a generic vectorized framework), with
a realistic India-specific cost model and look-ahead-free execution.
"""
