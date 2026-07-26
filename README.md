# Regime Strategy Selector

A production-oriented, probabilistic trading system for exactly one configured crypto asset per deployment:

```text
target_symbol ∈ {BTC, ETH, SOL}
```

The same codebase can be deployed separately for BTC, ETH, or SOL, but one model instance, backtest, artifact set, allocator, risk decision, and execution process must never combine several assets.

The version 1 market-data source is:

```text
gold.market.history_full.m1
```

Only rows matching the configured `target_symbol` are eligible.

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — system design, module boundaries, training, model selection, risk controls, deployment, monitoring, and roadmap.
- [`CONTRACTS.md`](CONTRACTS.md) — versioned input/output schemas, invariants, dataset fields, runtime payloads, model artifacts, and audit records.
- [`crypto-history-loader/DATASETS.md`](https://github.com/SergejSchweizer/crypto-history-loader/blob/main/DATASETS.md) — canonical upstream Gold dataset definitions.

## Three-module system

```text
gold.market.history_full.m1
            │ filter symbol == target_symbol
            ▼
 point-in-time feature builder
            │
            ├──────────────► Training targets
            ├──────────────► Trend expert
            ├──────────────► Momentum expert
            └──────────────► Mean-reversion expert
            ▼
┌───────────────────────────────────┐
│ 1. Regime Estimator               │
│ three probabilistic market states │
└────────────────┬──────────────────┘
                 ▼
┌───────────────────────────────────┐
│ 2. Strategy Allocator             │
│ risk budgets, exposure, exits     │
└────────────────┬──────────────────┘
                 ▼
┌───────────────────────────────────┐
│ 3. Deterministic Risk Engine      │
│ gates, limits, clipping, halt     │
└────────────────┬──────────────────┘
                 ▼
        Approved order intents
                 ▼
       External execution system
```

### Module 1 — Regime Estimator

Selects a compact feature subset from the configured asset's historical data and estimates current and forward probabilities for three latent regimes.

Candidate models include HMM, robust or duration-aware HMM variants, Markov-switching models, GMM, and change-point baselines. Only filtered, point-in-time probabilities are valid.

### Module 2 — Strategy Allocator

Combines the complete regime-probability vector with independent trend, momentum, and mean-reversion signals.

It proposes:

- non-negative risk budgets for the three strategy sleeves;
- signed target exposure per sleeve;
- cash allocation;
- a bounded global risk multiplier;
- deterministic TP/SL profile identifiers.

A regularised supervised allocator or contextual bandit is the preferred first production candidate. Reinforcement learning remains a challenger until it beats simpler models after costs in untouched outer walk-forward tests.

### Module 3 — Deterministic Risk Engine

Validates, clips, nets, rejects, or halts the allocation proposal. It is not an ML model and is not optimised by Optuna.

It enforces symbol consistency, exposure, leverage, margin, drawdown, capacity, data quality, confidence, cost, exchange, reconciliation, and kill-switch constraints.

## Key design rules

- One deployment targets one immutable asset: BTC, ETH, or SOL.
- Features use only observations available at the decision timestamp.
- Raw M1 data is converted to a declared decision interval; hourly is the initial recommendation.
- Strategy experts do not receive regime probabilities.
- Regime and allocator models are selected as a compatible pair.
- Allocator training uses out-of-fold regime probabilities from earlier-only fits.
- Purging and embargo protect overlapping forward targets.
- Risk budgets, signed positions, and cash are separate concepts.
- Three virtual strategy sleeves are attributed separately and netted to one exchange position.
- Cash and abstention are valid outcomes.
- The execution subsystem is outside the analytical modules.
- Every artifact and payload carries `target_symbol`, version, lineage, and hash metadata.
- Wrong-symbol inputs fail closed.

## Model selection

The Regime Estimator is evaluated on predictive density, occupancy, persistence, state separation, signature stability, transition stability, economic separation, benchmark uplift, parsimony, and retraining stability.

The Strategy Allocator is evaluated on net performance after fees, spread, slippage and funding; Sharpe, Sortino and Calmar; drawdown; CVaR; fold stability; regret; turnover; switching; capacity; baseline uplift; complexity; and abstention quality.

Selection uses:

```text
nested purged walk-forward
→ top-K regime shortlist
→ out-of-fold regime probabilities
→ allocator ladder per regime candidate
→ pair-level Pareto front
→ one-standard-error preference for simpler pairs
→ untouched outer tests
→ champion/challenger promotion
```

## Production path

```text
offline research
→ historical replay
→ live feature shadow
→ full decision shadow
→ paper execution
→ small-capital canary
→ restricted production
→ full approved production
```

Production requires deterministic live feature parity, robust cost-stressed outer-fold results, independent expert baselines, immutable artifacts, auditability, fail-closed risk controls, reconciliation, monitoring, incident handling, and tested rollback.

## Recommended repository structure

```text
regime-strategy-selector/
├── README.md
├── ARCHITECTURE.md
├── CONTRACTS.md
├── configs/
├── contracts/
├── src/regime_strategy_selector/
│   ├── data/
│   ├── features/
│   ├── regimes/
│   ├── strategies/
│   ├── allocation/
│   ├── portfolio/
│   ├── costs/
│   ├── risk/
│   ├── backtesting/
│   ├── optimization/
│   ├── evaluation/
│   ├── artifacts/
│   └── monitoring/
├── tests/
├── notebooks/
└── scripts/
```

## Status

The repository currently defines the target architecture and contracts. Implementation should progress from deterministic data, portfolio, cost, expert, and risk foundations toward more complex learned components. No complex allocator is eligible for production unless it demonstrates stable, cost-adjusted improvement over simpler baselines under identical single-asset data and risk constraints.
