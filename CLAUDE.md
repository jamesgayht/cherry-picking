# Agent Instructions

## Project

A research and signal assistant for **swing trading** (4H / Daily) on **US stocks/ETFs and crypto**.
1. **Daily research.** Market overview, news and catalysts, watchlist state, and summaries of curated sources.
2. **Strategy research.** Find strategies, backtest them in Python, and promote validated rules.
3. **Entry scanner.** Check the watchlist against the backtested rules in `config/rules/` and send alerts.

Delivery: **Telegram** for push alerts and briefs, **Google Sheets** for logs and tables.
User timezone: **Asia/Singapore (SGT, UTC+8)**. US regular session is 21:30–04:00 SGT (22:30–05:00 when the US is on standard time). Schedule in SGT and compute US session times with timezone-aware code. Never hardcode offsets.
Design doc: `docs/plans/2026-10-18-trading-bot-design.md`.

## Safety Rules (non-negotiable)

- **Never place, modify, or cancel orders.** This system sends alerts only. Do not call broker order endpoints even if a broker connector (e.g. IBKR) is available.
- `config/rules/` changes only through `workflows/promote_rules.md` and only with explicit user approval.
- Every alert includes "Alert only — not an order" and the rule's backtest evidence.
- Ask before running anything that consumes paid API credits, especially in loops.
- Never print or log secrets. Secrets live only in `.env`.

## The WAT Architecture

**Workflows** are Markdown procedures in `workflows/`. Each one defines the objective, inputs, tools, outputs, and edge cases.
**Agents** are you, plus the subagents in `.claude/agents/`. Read the relevant workflow, run the tools in order, handle failures, and ask when unclear.
**Tools** are Python scripts in `tools/` that do the deterministic work: API calls, transforms, backtests, and rule evaluation.

Judgment goes to agents and execution goes to tools. **Rule evaluation and backtests never depend on an LLM.** The same data and the same rules must always produce the same signal.

## Tool Contract

- Python 3.14 (pinned in `.python-version`), venv at `.venv/`, deps in `requirements.txt`. Before changing the version, confirm wheels exist for every dependency, including numba and vectorbt.
- Input comes from CLI args (argparse). Output is **JSON on stdout**, logs go to stderr, and failures exit non-zero with a JSON `{"error": ...}`.
- No hidden state. Read config from `config/` and secrets from `.env` via `tools/common/config.py`.
- Every tool has a test in `tests/`. Indicator and rule logic must be unit-tested.

## Backtesting: Find Gaps, Don't Validate

The purpose of a backtest is to **find where a strategy breaks**, not to prove it works. The default verdict is reject. Watch for the AI failure mode: tuning until the result looks good, then reporting the good numbers first.
- Write `backtests/<id>/hypothesis.md` with **kill criteria before any test**. Log every variant to `variants.log`.
- Never adjust parameters after seeing out-of-sample results. A change creates a new, counted variant.
- Run all the kill tests in design doc §5: baselines (buy-and-hold and random entries), regime split, parameter sensitivity, 2× costs, outlier removal, Monte Carlo, lookahead/survivorship audit, and multiple-testing correction.
- The `strategy-critic` subagent reviews with a fresh context (it never sees the researcher's reasoning) and writes `gaps.md`. Reports show **gaps first, metrics second**.
- Signals are computed on the close of bar *t* and the entry happens at the open of bar *t+1*. Fees and slippage are always on.

## How to Operate

1. **Reuse first.** Check `tools/` and `workflows/` before building anything new.
2. **On failure:** read the full error, fix the tool, retest (ask before re-running paid calls), and record what you learned in the workflow.
3. **Keep workflows current.** Refine them as you learn, but don't create or overwrite a workflow without asking unless told to.

## File Structure

```
.claude/agents/     # subagents: research-analyst, strategy-researcher, strategy-critic, entry-scanner
.claude/commands/   # /research, /strategy, /backtest, /scan
config/             # PERSISTENT, git-tracked: watchlist, sources, risk, rules/
backtests/          # PERSISTENT: hypothesis + reports (evidence for promotion)
docs/plans/         # design docs
tools/              # Python scripts (common/, data/, analysis/, backtest/, signals/, delivery/)
workflows/          # Markdown procedures
tests/              # pytest
.tmp/               # disposable intermediates (gitignored)
.env                # secrets (gitignored); template in .env.example
```

Deliverables go to Telegram and Google Sheets. `config/` and `backtests/` are the persistent record. Everything in `.tmp/` is disposable.
