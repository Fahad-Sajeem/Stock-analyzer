"""Layer 2 — Technical analysis engine (PLAN Section 7).

Runs daily post-market on the approved universe. Indicators are hand-rolled in
pandas/numpy (no TA-Lib C dependency) so they are portable and golden-testable.
All technicals read ADJUSTED prices (prices_adj), never raw.
"""
