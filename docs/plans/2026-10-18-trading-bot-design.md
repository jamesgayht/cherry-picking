# Trading Bot — Design (DRAFT, pending approval)

Date: 2026-10-18
Status: Draft — awaiting review. TradingView data integration deferred (see §7).

## 1. Goals

1. **Daily research agent** — pre-market brief: market overview, news & catalysts, watchlist scan, summaries of user-specified sources.
2. **Strategy research agent** — find swing strategies, guide + run Python backtests, promote validated rules to `config/rules/`.
3. **Entry scanner** — check watchlist against pre-configured, backtest-derived entry rules; send alerts.

**Scope decisions**
| Decision | Choice |
|---|---|
| Markets | US stocks/ETFs + crypto |
| Style | Swing (days–weeks) — 4H / Daily timeframes |
| Execution | **Alert only.** No order placement of any kind. |
| Backtesting | Python (vectorbt or backtesting.py), walk-forward |
| Delivery | Telegram (push brief + signals), Google Sheets (logs/tables) |
| Research cadence | Scheduled pre-market + manual on demand |
| TradingView data | **Open** — isolated behind a data-provider interface |

## 2. Architecture (Approach C: split by determinism)

```
              ┌──────────── LLM (judgment) ────────────┐   ┌──── Deterministic Python ────┐
 schedule ──► │ research-analyst subagent              │──►│ fetch_news / calendar / ohlcv │
 /research    │   reads workflows/daily_research.md    │   │ market_overview, sources      │
              │                                        │   └──────────────┬───────────────┘
 /strategy ─► │ strategy-researcher subagent           │──►│ run_backtest / walk_forward   │
              │   proposes → tests → promotes rules    │   │ → backtests/<id>/report.json  │
              └───────────────────┬────────────────────┘   └──────────────┬───────────────┘
                                  │ (human approves promotion)            │
                                  ▼                                       │
                         config/rules/<id>.yaml ◄─────────────────────────┘
                                  │
 cron/launchd ──► tools/signals/scan.py (NO LLM) ──► match? ──► telegram_send + sheets_append
                                  │
                         optional: entry-scanner subagent adds context/commentary on /scan
```

Key principle: **rule evaluation never depends on an LLM.** Same data + same rules = same signal, every time.

## 3. Directory structure

```
.claude/
  agents/
    research-analyst.md       # daily brief
    strategy-researcher.md    # strategy discovery + backtest guidance
    entry-scanner.md          # runs scan, explains matches, never trades
  commands/
    research.md               # /research  → manual daily brief
    strategy.md               # /strategy <idea> → research + backtest
    backtest.md               # /backtest <strategy_id>
    scan.md                   # /scan → run entry scanner now
config/                       # PERSISTENT, git-tracked
  watchlist.yaml              # tickers per market + timeframe
  sources.yaml                # newsletters / RSS / YouTube / X to summarize
  risk.yaml                   # per-trade risk %, max open signals, etc. (for alert sizing)
  rules/<strategy_id>.yaml    # promoted entry rules (only via promote workflow)
backtests/<strategy_id>/<date>/  # report.json, equity.csv, params.json (evidence for promotion)
workflows/
  daily_research.md
  strategy_research.md
  backtest_strategy.md
  promote_rules.md
  scan_entries.md
  setup_telegram.md
  setup_google_sheets.md
tools/
  common/      config.py (load yaml/.env), log.py, io.py (JSON stdout contract)
  data/        fetch_ohlcv.py (provider: yfinance|ccxt|tradingview*), fetch_news.py,
               fetch_calendar.py, fetch_sources.py (RSS, YouTube transcripts)
  analysis/    indicators.py, market_overview.py, watchlist_state.py
  backtest/    run_backtest.py, walk_forward.py, report.py
  signals/     evaluate_rules.py, scan.py
  delivery/    telegram_send.py, sheets_append.py
tests/         unit tests for indicators, rule evaluation, backtest determinism
docs/plans/    design docs
.tmp/          disposable
```

## 4. Agents

### research-analyst (scheduled ~08:00 ET weekdays + crypto weekend digest; or `/research`)
1. `market_overview.py` — SPY/QQQ/IWM, sector ETFs, VIX, DXY, BTC/ETH, dominance; key levels.
2. `fetch_calendar.py` — macro events (CPI, FOMC, NFP), earnings for watchlist names (next 10 days).
3. `fetch_news.py` — headlines per watchlist ticker + market-wide.
4. `fetch_sources.py` — items from `config/sources.yaml` since last run.
5. `watchlist_state.py` — trend, distance to rule triggers ("near setup").
6. LLM synthesizes: **≤ 300-word Telegram brief** + full brief row in Sheets `Research` tab.
Rule: every claim cites its source; no price predictions stated as fact.

### strategy-researcher (`/strategy`, `/backtest`)
1. Clarify hypothesis (edge, market, timeframe) → write `backtests/<id>/hypothesis.md` **before** testing.
2. Translate to a parametrized rule spec (same YAML schema as `config/rules/`).
3. `run_backtest.py` in-sample → `walk_forward.py` out-of-sample.
4. Produce report vs. promotion gate (§5). Log to Sheets `Backtests` tab.
5. If it passes, **propose** promotion; user approves; `promote_rules.md` writes `config/rules/<id>.yaml`.

### entry-scanner (cron after US close + every 4H for crypto; or `/scan`)
- `scan.py` loads `config/rules/*.yaml` (status: active), fetches OHLCV, evaluates on **closed candles only**.
- Match → Telegram alert + Sheets `Signals` row. Dedupe: one alert per (rule, ticker, candle).
- The subagent (on `/scan`) may add context (upcoming earnings, news) but cannot change the signal.

## 5. Rule schema & promotion gate

```yaml
# config/rules/ema_pullback_daily.yaml
id: ema_pullback_daily
status: active            # draft | active | retired
markets: [us_equity, crypto]
timeframe: 1d
universe: watchlist       # or explicit list
entry:
  all:
    - close > ema(close, 200)
    - ema(close, 20) > ema(close, 50)
    - low <= ema(close, 20) * 1.01
    - rsi(close, 14) < 45
filters:
  - not earnings_within_days(5)      # equities only
exit:                       # included in alert as suggested levels
  stop: entry - 2 * atr(14)
  target: entry + 3 * atr(14)
  time_stop_bars: 15
evidence:
  backtest: backtests/ema_pullback_daily/2026-10-20/report.json
  oos_profit_factor: 1.42
  oos_trades: 138
  max_drawdown_pct: 14.8
```

**Promotion gate (defaults — tune later):**
- Out-of-sample (walk-forward) profit factor ≥ 1.3, ≥ 100 OOS trades across universe
- Fees + slippage modeled (equities 0.05%/side, crypto 0.1%/side + spread)
- Max drawdown ≤ 25%; performance stable across neighboring params (no cliff-edge optimum)
- No lookahead: signals on bar *t* close, entries at bar *t+1* open
- Hypothesis written before testing; number of variants tried is logged

## 6. Delivery formats

**Telegram signal**
```
🟢 ENTRY SETUP — AAPL (1D)  rule: ema_pullback_daily
Close 228.40 | Entry ≈ next open | Stop 221.10 (−3.2%) | Target 239.35 (+4.8%)
Size @1% risk on $X: N shares   | Backtest OOS PF 1.42, 138 trades
⚠ Earnings in 12 days. Alert only — not an order.
```
**Google Sheets tabs:** `Research` (daily briefs), `Signals` (every alert + later outcome), `Backtests` (one row per run), `Strategies` (pipeline: idea → testing → active → retired).

## 7. Open question: TradingView data (deferred)

TradingView has no official data API. `fetch_ohlcv.py` takes `--provider`, so this decision doesn't block anything:
- **Default now:** yfinance (equities, free, fine for daily/4H) + ccxt (crypto, free).
- **Option A — Hybrid (recommended later):** Pine Script mirrors a promoted rule → TV alert → webhook → `scan.py` re-verifies with provider data before alerting. Requires paid TV plan + public endpoint (e.g. Cloudflare Tunnel).
- **Option B — Unofficial libs** (tvdatafeed / tradingview-ta): fragile, against TV ToS.
- **Option C — TV for charting only.**

## 8. Safety rules (to add to CLAUDE.md)

- The system **never places orders.** No broker order endpoints are called, even if a broker connector is available.
- Rules in `config/rules/` change only through `workflows/promote_rules.md` with explicit user approval.
- Paid APIs: ask before running loops that consume credits.
- Alerts must include "Alert only — not an order" and the rule's backtest evidence.

## 9. Build phases

| Phase | Deliverable | Done when |
|---|---|---|
| 0 Foundation | git, venv, `tools/common`, `telegram_send.py`, `sheets_append.py`, setup workflows | test message hits Telegram + Sheets |
| 1 Research | data tools, `research-analyst`, `/research`, schedule | brief arrives pre-market for 3 days |
| 2 Backtesting | backtest + walk-forward tools, `strategy-researcher`, `/strategy`, `/backtest` | one sample strategy fully reported |
| 3 Scanner | rule evaluator, `scan.py`, `entry-scanner`, cron/launchd | known historical setup reproduces an alert |
| 4 TradingView | per §7 decision | — |

## 10. Inputs needed from the user

- Watchlist (stocks/ETFs + crypto pairs)
- Research sources (newsletter/RSS/YouTube/X)
- Telegram bot token + chat id (via @BotFather), Google Sheet to use
- Account size / risk % for position-size hints (optional)
- Timezone (assumed America/New_York for scheduling)
