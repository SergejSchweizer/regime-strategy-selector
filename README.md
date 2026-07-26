# Regime Strategy Selector

A production-oriented trading system for exactly one configured crypto asset per deployment:

```text
target_symbol ∈ {BTC, ETH, SOL}
```

One deployment, training run, backtest, model artifact, risk decision, and execution process is bound to one immutable `target_symbol`.

The system may trade either the configured asset's spot instrument or its perpetual instrument. The traded instrument is selected offline from an explicit candidate universe using leakage-safe walk-forward evaluation. It is then frozen in the deployment artifact.

```text
selected_instrument_type ∈ {SPOT, PERPETUAL}
```

If the perpetual has materially better net return/risk performance after fees, spread, slippage, funding, liquidation constraints, and cost stress, the perpetual is selected. If spot and perpetual are statistically indistinguishable, spot is preferred because it has lower operational and liquidation complexity.

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — normative system design, model-selection procedure, instrument selection, module boundaries, training, deployment, and production roadmap.
- [`CONTRACTS.md`](CONTRACTS.md) — implementable input/output schemas, units, invariants, timing definitions, artifacts, and audit records.
- [`METHODOLOGY.md`](METHODOLOGY.md) — exact strategy-signal, performance-metric, cost-stress, and bootstrap formulas.
- [`OPERATIONS.md`](OPERATIONS.md) — runtime state machine, security, monitoring thresholds, incident handling, promotion, and rollback.
- [`crypto-history-loader/DATASETS.md`](https://github.com/SergejSchweizer/crypto-history-loader/blob/main/DATASETS.md) — upstream Gold dataset definitions.

## Production V1

Production V1 deliberately limits the number of learned components and free parameters.

```text
gold.market.history_full.m1
            │ filter symbol == target_symbol
            ▼
 point-in-time feature service
            ▼
 fixed five-feature regime vector
            ▼
 Gaussian HMM, diagonal covariance, three states
            ▼
 filtered regime probabilities
            ▼
 independent trend / momentum / mean-reversion scores
            ▼
 deterministic probability-weighted allocator
            ▼
 one signed net target position + one exit profile
            ▼
 deterministic risk engine
            ▼
 approved target position
            ▼
 external execution system
```

### Module 1 — Regime Estimator

Production V1 uses one Gaussian HMM with diagonal covariance and three latent states. It consumes a fixed, versioned core feature set:

```text
return_24h
realized_volatility_24h
funding_zscore_30d
open_interest_change_24h
buy_volume_share_4h
```

All features use only the configured asset. Spot and perpetual observations of that same asset may both be used as market information regardless of which instrument is traded.

The output is limited to:

```text
current regime probabilities[3]
forward regime probabilities at the 4h primary horizon
normalised probability entropy
maximum regime probability
most likely regime
state-signature IDs
data-quality status
abstention recommendation
```

Retrospectively smoothed states are prohibited.

### Strategy experts

Trend, momentum, and mean reversion are independent deterministic signal generators. They do not receive regime probabilities.

Production V1 uses fixed economic horizons:

| Expert | Primary horizon |
|---|---:|
| Mean reversion | 1–4 hours |
| Momentum | 4–24 hours |
| Trend | 1–7 days |

Each expert emits direction, strength, confidence, expected holding time, and estimated cost. Exact formulas are defined in `METHODOLOGY.md`.

### Module 2 — Deterministic Allocator

Production V1 does not use reinforcement learning, a contextual bandit, or a learned allocator.

A versioned regime-to-strategy affinity matrix combines the complete regime-probability vector with the three independent expert scores. The allocator produces:

```text
strategy contribution weights
one consensus direction: SHORT, FLAT, or LONG
one signed target position fraction
one cash fraction
one global risk multiplier
one net-position exit profile ID
abstention recommendation
```

Opposing sleeve positions are not allowed in Production V1. If expert disagreement is material and no direction dominates, the allocator moves to cash.

### Module 3 — Deterministic Risk Engine

The Risk Engine validates or reduces the proposed target. It outputs an `ApprovedTargetPosition.v1`, not an exchange order.

It enforces:

- target-symbol and selected-instrument equality;
- capital, exposure, leverage, margin, drawdown, turnover, cost, data-quality, and operational limits;
- one net position and one net exit profile;
- fail-closed behaviour;
- abstention and safe degradation.

### External execution system

The execution system alone decides:

- market versus limit order;
- order slicing;
- maker/taker behaviour;
- price and quantity rounding;
- cancel/replace and retry;
- partial-fill handling;
- reconciliation with the exchange.

## Timing

The initial decision clock is hourly while raw data remains M1.

```text
decision_interval = 1h
primary_evaluation_horizon = 4h
stress_horizon = 1d
```

A decision uses only fully closed M1 buckets. The earliest live order submission occurs after the feature snapshot and decision are persisted. Historical fills use the first eligible M1 bucket strictly after the decision timestamp.

## Instrument selection

For each `target_symbol`, the candidate universe is explicitly configured, normally:

```text
spot candidate
perpetual candidate
```

An instrument is eligible only when data coverage, cost modelling, liquidity, operational support, and exchange constraints pass hard gates.

Eligible instruments are compared with the same features, model family, expert definitions, allocator, risk limits, timing rules, and cost scenarios. The primary ranking metric is median outer-fold net Calmar ratio. Tie-breakers are, in order:

1. lower median 95% CVaR loss;
2. higher median annualised net return;
3. lower median turnover;
4. lower operational complexity.

A change of traded instrument creates a new challenger deployment and requires shadow, paper, and canary validation.

## Model ladder

```text
Production V1:
- Gaussian HMM, diagonal covariance
- deterministic probability-weighted allocator

Model challengers:
- Gaussian HMM with full covariance
- duration-aware HMM
- regularised supervised allocator

Research only:
- contextual bandit
- reinforcement learning
```

A more complex component is not eligible unless it improves untouched outer-fold results after costs and passes the same risk, stability, and operational gates.

## Deployment path

```text
offline research
→ historical replay
→ live feature shadow
→ full decision shadow
→ paper execution
→ small-capital canary
→ restricted production
```

Promotion is always manual. Every production decision must be reproducible from immutable data, feature, model, allocator, risk, instrument, code, dependency, methodology, and operations versions.
