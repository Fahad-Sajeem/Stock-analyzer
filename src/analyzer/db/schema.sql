-- ==========================================================================
-- Stock Analyzer — DuckDB schema (v1). See PLAN.md Section 13.
-- Idempotent: every table uses CREATE TABLE IF NOT EXISTS. Pipelines upsert on
-- primary keys so re-running a day's job never duplicates rows.
-- ==========================================================================

-- symbol master (identity tracked via ISIN; symbols get renamed over time)
CREATE TABLE IF NOT EXISTS symbols (
  isin          TEXT PRIMARY KEY,
  symbol        TEXT NOT NULL,
  name          TEXT,
  exchange      TEXT,
  sector        TEXT,
  industry      TEXT,
  mcap_cr       DOUBLE,
  listing_date  DATE,
  is_active     BOOLEAN DEFAULT TRUE,
  band_pct      INTEGER,
  surveillance  TEXT
);
CREATE INDEX IF NOT EXISTS idx_symbols_symbol ON symbols(symbol);

-- raw end-of-day OHLCV + delivery (ground truth from NSE bhavcopy)
CREATE TABLE IF NOT EXISTS prices_raw (
  symbol        TEXT,
  date          DATE,
  open          DOUBLE,
  high          DOUBLE,
  low           DOUBLE,
  close         DOUBLE,
  volume        BIGINT,
  traded_value  DOUBLE,
  delivery_qty  BIGINT,
  delivery_pct  DOUBLE,
  PRIMARY KEY (symbol, date)
);

-- corporate-action adjusted OHLCV; technical indicators read THIS table only
CREATE TABLE IF NOT EXISTS prices_adj (
  symbol        TEXT,
  date          DATE,
  open          DOUBLE,
  high          DOUBLE,
  low           DOUBLE,
  close         DOUBLE,
  volume        BIGINT,
  adj_factor    DOUBLE,
  PRIMARY KEY (symbol, date)
);

CREATE TABLE IF NOT EXISTS corporate_actions (
  symbol        TEXT,
  ex_date       DATE,
  action_type   TEXT,          -- SPLIT | BONUS | DIVIDEND | RIGHTS
  ratio         TEXT,          -- e.g. '1:1', '2:1'
  value         DOUBLE,        -- dividend amount, or numeric ratio factor
  PRIMARY KEY (symbol, ex_date, action_type)
);

-- point-in-time index membership (survivorship-bias fix, PLAN 10.1)
CREATE TABLE IF NOT EXISTS index_constituents (
  index_name    TEXT,
  symbol        TEXT,
  from_date     DATE,
  to_date       DATE,          -- NULL / far-future while still a member
  PRIMARY KEY (index_name, symbol, from_date)
);

-- NSE trading-holiday calendar (pipelines are holiday-aware)
CREATE TABLE IF NOT EXISTS holidays_nse (
  holiday_date  DATE PRIMARY KEY,
  description   TEXT
);

-- index / VIX EOD (benchmarks for regime + relative strength)
CREATE TABLE IF NOT EXISTS index_prices (
  index_name    TEXT,          -- NIFTY50 | NIFTY500 | INDIAVIX
  date          DATE,
  open          DOUBLE,
  high          DOUBLE,
  low           DOUBLE,
  close         DOUBLE,
  PRIMARY KEY (index_name, date)
);

CREATE TABLE IF NOT EXISTS fundamentals (
  symbol            TEXT,
  period            TEXT,      -- 'FY2025' | 'Q1FY26'
  period_end        DATE,
  sales             DOUBLE,
  ebitda            DOUBLE,
  net_profit        DOUBLE,
  eps               DOUBLE,
  cfo               DOUBLE,
  fcf               DOUBLE,
  debt              DOUBLE,
  equity            DOUBLE,
  roe               DOUBLE,
  roce              DOUBLE,
  interest_coverage DOUBLE,
  promoter_pct      DOUBLE,
  pledge_pct        DOUBLE,
  fii_pct           DOUBLE,
  dii_pct           DOUBLE,
  pe                DOUBLE,
  ev_ebitda         DOUBLE,
  source            TEXT,
  fetched_at        TIMESTAMP,
  PRIMARY KEY (symbol, period)
);

CREATE TABLE IF NOT EXISTS universe (
  symbol          TEXT,
  as_of           DATE,
  approved        BOOLEAN,
  quality_score   DOUBLE,
  reject_reasons  TEXT[],
  score_breakdown JSON,
  PRIMARY KEY (symbol, as_of)
);

CREATE TABLE IF NOT EXISTS indicators_daily (
  symbol          TEXT,
  date            DATE,
  ema20           DOUBLE,
  ema50           DOUBLE,
  sma200          DOUBLE,
  adx             DOUBLE,
  rsi             DOUBLE,
  macd            DOUBLE,
  macd_sig        DOUBLE,
  macd_hist       DOUBLE,
  atr             DOUBLE,
  atr_pct         DOUBLE,
  bb_width_pctile DOUBLE,
  vol_ratio       DOUBLE,
  obv_slope       DOUBLE,
  rs_pctile       DOUBLE,
  roc20           DOUBLE,
  roc60           DOUBLE,
  roc120          DOUBLE,
  dist_52wh       DOUBLE,
  supertrend      DOUBLE,
  in_base         BOOLEAN,
  base_days       INTEGER,
  wk_gate_trend   BOOLEAN,     -- weekly multi-timeframe gate (trend setups)
  wk_gate_mr      BOOLEAN,     -- weekly gate (mean-reversion)
  PRIMARY KEY (symbol, date)
);

CREATE TABLE IF NOT EXISTS regime_daily (
  date                DATE PRIMARY KEY,
  regime              TEXT,    -- BULL | NEUTRAL | BEAR | RISK_OFF
  nifty_close         DOUBLE,
  breadth_above_200dma DOUBLE,
  india_vix           DOUBLE
);

CREATE TABLE IF NOT EXISTS signals (
  signal_id           TEXT PRIMARY KEY,
  date                DATE,
  symbol              TEXT,
  setup               TEXT,
  direction           TEXT,
  grade               TEXT,
  composite_score     DOUBLE,
  entry_aggressive    DOUBLE,
  entry_conservative  DOUBLE,
  entry_valid_till    DATE,
  stop_loss           DOUBLE,
  t1                  DOUBLE,
  t2                  DOUBLE,
  rr                  DOUBLE,
  suggested_risk_pct  DOUBLE,
  reasons             TEXT[],
  warnings            TEXT[],
  payload             JSON,
  chart_path          TEXT
);
CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(date);

CREATE TABLE IF NOT EXISTS signal_outcomes (
  signal_id     TEXT PRIMARY KEY,
  triggered     BOOLEAN,
  trigger_date  DATE,
  outcome       TEXT,          -- T1_HIT | T2_HIT | SL_HIT | TIME_STOP | EXPIRED
  exit_date     DATE,
  realized_r    DOUBLE,
  mfe_r         DOUBLE,        -- max favorable excursion (R)
  mae_r         DOUBLE         -- max adverse excursion (R)
);

CREATE TABLE IF NOT EXISTS positions (
  position_id   TEXT PRIMARY KEY,
  signal_id     TEXT,
  symbol        TEXT,
  qty           INTEGER,
  entry_price   DOUBLE,
  entry_date    DATE,
  current_sl    DOUBLE,
  status        TEXT,          -- OPEN | PARTIAL | CLOSED
  booked_pct    DOUBLE,
  notes         TEXT
);

-- actual broker executions (slippage feedback loop, PLAN 9)
CREATE TABLE IF NOT EXISTS fills (
  position_id   TEXT,
  side          TEXT,          -- BUY | SELL
  fill_date     DATE,
  signal_price  DOUBLE,
  actual_price  DOUBLE,
  slippage_bps  DOUBLE
);

CREATE TABLE IF NOT EXISTS backtest_results (
  run_id        TEXT PRIMARY KEY,
  run_at        TIMESTAMP,
  setup         TEXT,
  config_hash   TEXT,
  period_start  DATE,
  period_end    DATE,
  sample        TEXT,          -- IS | OOS | WF
  n_trades      INTEGER,
  win_rate      DOUBLE,
  avg_r         DOUBLE,
  profit_factor DOUBLE,
  max_dd        DOUBLE,
  cagr          DOUBLE,
  exposure      DOUBLE,
  report_path   TEXT
);

-- point-in-time fundamentals history (RESEARCH_PLAN R2; long format)
CREATE TABLE IF NOT EXISTS fundamentals_history (
  symbol         TEXT,
  period         TEXT,          -- 'FY2024' | 'Q2024-06' | 'SH2024-06'
  period_end     DATE,
  freq           TEXT,          -- 'A' | 'Q' | 'SH'
  metric         TEXT,          -- sales, net_profit, eps, opm_pct, borrowings, ...
  value          DOUBLE,
  available_from DATE,          -- point-in-time availability (conservative lag)
  source         TEXT,
  fetched_at     TIMESTAMP,
  PRIMARY KEY (symbol, period, metric)
);

-- results/board-meeting announcement dates (RESEARCH_PLAN R4; enables PEAD)
CREATE TABLE IF NOT EXISTS results_calendar (
  symbol        TEXT,
  announce_date DATE,
  purpose       TEXT,
  source        TEXT,          -- 'nse_bm'
  PRIMARY KEY (symbol, announce_date)
);

-- news layer (PLAN Section 17)
CREATE TABLE IF NOT EXISTS news_events (
  event_id      TEXT PRIMARY KEY,
  published_at  TIMESTAMP,
  source        TEXT,
  headline      TEXT,
  url           TEXT,
  tier          TEXT,          -- MACRO | SECTOR | STOCK
  event_type    TEXT,
  sentiment     INTEGER,       -- -2 .. +2
  confidence    DOUBLE,
  symbols       TEXT[],
  sectors       TEXT[],
  classified_by TEXT           -- RULES | LLM | PROXY
);

CREATE TABLE IF NOT EXISTS sentiment_daily (
  date          DATE,
  scope         TEXT,          -- MACRO | SECTOR | STOCK
  scope_key     TEXT,          -- '' | sector | symbol
  score         DOUBLE,
  n_events      INTEGER,
  PRIMARY KEY (date, scope, scope_key)
);

-- intraday alert dedupe (one alert per position/type/day)
CREATE TABLE IF NOT EXISTS alerts_log (
  alert_date  DATE,
  symbol      TEXT,
  alert_type  TEXT,           -- STOP_BREACH | SHARP_DROP
  detail      TEXT,
  sent_at     TIMESTAMP,
  PRIMARY KEY (alert_date, symbol, alert_type)
);

-- observability: every pipeline job logs a row here
CREATE TABLE IF NOT EXISTS job_runs (
  job           TEXT,
  started       TIMESTAMP,
  finished      TIMESTAMP,
  status        TEXT,          -- OK | ERROR | RUNNING
  rows_written  INTEGER,
  error         TEXT
);
