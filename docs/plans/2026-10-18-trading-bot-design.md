# Trading Bot — Design

Date: 2026-10-18
Status: Overview approved 2026-10-18. Revised 2026-10-25: backtesting reframed as adversarial (§4, §5). TradingView data integration deferred (see §7).

## 1. Goals

1. **Daily research agent** — pre-market brief: market overview, news & catalysts, watchlist scan, summaries of user-specified sources.
2. **Strategy research agent** — find swing strategies and run Python backtests whose job is to **find the gaps** in each strategy, not to confirm it. A strategy reaches `config/rules/` only after it survives a deliberate attempt to break it.
   *Why:* AI-generated backtests tend to validate whatever idea they are given (overfitting, flattering benchmarks, skipped failure regimes, metric-first reporting). The default verdict is **reject**, and the burden of proof sits on the strategy.
3. **Entry scanner** — check watchlist against pre-configured, backtest-derived entry rules; send alerts.

**Scope decisions**
| Decision | Choice |
|---|---|
| Markets | US stocks/ETFs + crypto |
| Style | Swing (days–weeks) — 4H / Daily timeframes |
| Execution | **Alert only.** No order placement of any kind. |
| Backtesting | Python (vectorbt or backtesting.py). Adversarial: an independent critic and mandatory kill tests (§5) |
| Delivery | Telegram (push brief + signals), Google Sheets (logs/tables) |
| Research cadence | Scheduled pre-market + manual on demand |
| User timezone | Asia/Singapore — all schedules in `config/schedule.yaml` |
| Watchlist | Maintained in TradingView, exported to `config/watchlist.txt` |
| Research sources | `config/sources.yaml` — yfinance, CoinGecko, Finviz, Finnhub calendar, RSS (CNBC, MarketWatch, Yahoo per-ticker, CoinDesk, The Block, Cointelegraph, Decrypt), crypto Fear & Greed |
| TradingView data | **Open** — isolated behind a data-provider interface |

## 2. Architecture (Approach C: split by determinism)

```
              ┌──────────── LLM (judgment) ────────────┐   ┌──── Deterministic Python ────┐
 schedule ──► │ research-analyst subagent              │──►│ fetch_news / calendar / ohlcv │
 /research    │   reads workflows/daily_research.md    │   │ market_overview, sources      │
              │                                        │   └──────────────┬───────────────┘
 /strategy ─► │ strategy-researcher subagent           │──►│ run_backtest / walk_forward   │
              │   hypothesis + kill criteria → tests   │   │ stress_tests (kill tests)     │
              │ strategy-critic subagent (independent) │──►│ → backtests/<id>/report.json  │
              │   tries to break it, writes gaps.md    │   └──────────────┬───────────────┘
              └───────────────────┬────────────────────┘                  │
                                  │ (only if it survives; human approves) │
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
    strategy-researcher.md    # strategy discovery, hypothesis + kill criteria, runs tests
    strategy-critic.md        # independent red team: finds gaps, argues for rejection
    entry-scanner.md          # runs scan, explains matches, never trades
  commands/
    research.md               # /research  → manual daily brief
    strategy.md               # /strategy <idea> → research + backtest
    backtest.md               # /backtest <strategy_id>
    scan.md                   # /scan → run entry scanner now
config/                       # PERSISTENT, git-tracked
  watchlist.txt               # TradingView export (EXCHANGE:SYMBOL)
  watchlist_mapping.yaml      # TV prefix → data provider
  sources.yaml                # research sources (see file for exclusions)
  schedule.yaml               # SGT schedules
  risk.yaml                   # per-trade risk %, max open signals, etc. (for alert sizing)
  rules/<strategy_id>.yaml    # promoted entry rules (only via promote workflow)
backtests/<strategy_id>/       # hypothesis.md (pre-registered), variants.log, <date>/report.json, gaps.md (critic)
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
  backtest/    run_backtest.py, walk_forward.py, stress_tests.py (kill tests), baselines.py, report.py
  signals/     evaluate_rules.py, scan.py
  delivery/    telegram_send.py, sheets_append.py
tests/         unit tests for indicators, rule evaluation, backtest determinism
docs/plans/    design docs
.tmp/          disposable
```

## 4. Agents

### research-analyst (scheduled 20:30 SGT weekdays + 10:00 SGT weekend crypto digest; or `/research`)
1. `market_overview.py` — SPY/QQQ/IWM, sector ETFs, VIX, DXY, BTC/ETH, dominance; key levels.
2. `fetch_calendar.py` — macro events (CPI, FOMC, NFP), earnings for watchlist names (next 10 days).
3. `fetch_news.py` — headlines per watchlist ticker + market-wide.
4. `fetch_sources.py` — RSS items from `config/sources.yaml` (last 24h, deduped).
5. `watchlist_state.py` — trend, distance to rule triggers ("near setup").
6. LLM synthesizes: **≤ 300-word Telegram brief** + full brief row in Sheets `Research` tab.
Rule: every claim cites its source; no price predictions stated as fact.

### strategy-researcher (`/strategy`, `/backtest`)
1. Write `backtests/<id>/hypothesis.md` **before any test**: the claimed edge, *why* it should exist (who is on the other side of the trade), and **kill criteria**, meaning the specific results that would falsify it.
2. Translate it to a parametrized rule spec (same YAML schema as `config/rules/`). Log every variant tried to `variants.log`; that count is reported and never hidden.
3. Run `run_backtest.py` → `walk_forward.py` → `stress_tests.py` (all kill tests in §5).
4. The researcher **may not** adjust parameters after seeing out-of-sample results. Any change creates a new variant, which goes back through step 2 and is counted.

### strategy-critic (independent red team, runs after every backtest)
- A separate subagent with a fresh context. It receives only the rule spec, the raw results and the kill-test outputs, **never the researcher's reasoning**, so it can't inherit the researcher's bias.
- Its mandate is to argue for rejection. It writes `backtests/<id>/gaps.md`: the failure modes found, untested conditions, suspicious results (too good, too smooth, too few trades) and data problems.
- It must list at least 3 concrete weaknesses or explicitly justify why it couldn't find them.
- The report shows **gaps first, metrics second**. It's logged to the Sheets `Backtests` tab.
- If the strategy survives, the researcher **proposes** promotion, the user approves, and `promote_rules.md` writes `config/rules/<id>.yaml` with `gaps.md` linked as known risks.

### entry-scanner (per `config/schedule.yaml`: after US close ~04:15/05:15 SGT, crypto on 4H/1D UTC closes; or `/scan`)
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
  gaps: backtests/ema_pullback_daily/gaps.md     # known weaknesses from the critic
  variants_tried: 7
  oos_profit_factor: 1.42
  oos_trades: 138
  worst_regime: "2022 bear: PF 0.84"
  mc_dd_p95_pct: 22.1
```

**Kill tests (mandatory; failing any one is a rejection unless the user explicitly overrides with a written reason):**

| # | Test | Question it answers | Fails if (defaults, tune later) |
|---|---|---|---|
| 1 | Walk-forward OOS | Does it work on data it wasn't tuned on? | OOS profit factor < 1.3, or < 100 OOS trades |
| 2 | Baselines | Does it beat doing nothing clever? | Doesn't beat buy-and-hold risk-adjusted, **or** doesn't beat random entries with the same exits and holding time (≥ 95th percentile of 1,000 random runs) |
| 3 | Regime split | Where does it break? | Loses badly in any regime: 2020 crash, 2022 bear, 2021 melt-up, sideways chop, crypto winter. Report every regime; never just the aggregate |
| 4 | Parameter sensitivity | Is the edge real or a lucky number? | Neighboring params (±20%) drop PF below 1.1 (a cliff-edge optimum) |
| 5 | Cost stress | Does the edge survive real friction? | Unprofitable at 2× fees and slippage (base: equities 0.05%/side, crypto 0.1%/side + spread) |
| 6 | Outlier dependence | Is it a few lucky trades? | Unprofitable after removing the top 5% of trades; > 30% of profit from one symbol |
| 7 | Monte Carlo | How bad can it realistically get? | 95th-percentile drawdown from trade-order reshuffles > 35% |
| 8 | Data integrity | Is the test itself lying? | Any lookahead (signal at bar *t* close, entry at bar *t+1* open), survivorship bias, or repainting indicator |
| 9 | Multiple testing | Did we just try enough variants to get lucky? | Deflated Sharpe ratio not significant given the count in `variants.log` |

**Survivorship warning:** the TradingView watchlist contains today's survivors. Backtests on it overstate results. Equities tests must also run on a broader universe (e.g. the S&P 500 or sector ETFs), and the gap between the two is reported as a finding.

**After promotion:** live alerts in the Sheets `Signals` tab are compared against the backtest's expected win rate and R-multiple. If live results drift outside the Monte Carlo band, the rule is flagged for review or retirement. A promoted rule is never assumed to keep working.

## 6. Delivery formats

**Telegram signal**
```
🟢 ENTRY SETUP — AAPL (1D)  rule: ema_pullback_daily
Close 228.40 | Entry ≈ next open | Stop 221.10 (−3.2%) | Target 239.35 (+4.8%)
Size @1% risk on $X: N shares   | Backtest OOS PF 1.42, 138 trades
⚠ Known weakness: fails in bear regimes (SPY < 200DMA now? no)
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
| 2 Backtesting | backtest, walk-forward and kill-test tools, `strategy-researcher` + `strategy-critic`, `/strategy`, `/backtest` | a known-bad strategy (e.g. an overfit MA cross) is **rejected** by the kill tests, and one sample strategy is reported with gaps.md |
| 3 Scanner | rule evaluator, `scan.py`, `entry-scanner`, cron/launchd | known historical setup reproduces an alert |
| 4 TradingView | per §7 decision | — |

## 10. Inputs needed from the user

- [x] Timezone: Asia/Singapore
- [x] Research sources: decided 2026-10-18 (see `config/sources.yaml` for the list and exclusions)
- [ ] TradingView watchlist export → `config/watchlist.txt`
- [x] Telegram bot token + chat id (@odot_cc_bot, verified 2026-10-18)
- [~] Google Sheet: ID set; access via service account in Phase 0
- [x] Finnhub API key: earnings + news OK; economic calendar is premium, so ForexFactory is used instead
- [ ] Account size for position-size hints (optional, `config/risk.yaml`)
