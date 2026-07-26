# Regime Strategy Selector

A production-oriented regime and strategy allocation system for one fixed Production V1 market:

```text
target_symbol = BTC
traded_instrument_type = LINEAR_PERPETUAL
margin_mode = ISOLATED
position_mode = ONE_WAY
```

Production V1 trades one configured BTC linear perpetual contract. BTC spot data may be consumed as a same-asset reference feed and benchmark, but the system never emits spot orders.

The deployed perpetual contract is exchange-specific and immutable for the lifetime of a deployment:

```text
trading_instrument_id = configured BTC perpetual contract
reference_spot_instrument_id = configured BTC spot market
```

ETH, SOL, spot execution, inverse contracts, cross margin, hedge mode, options and leverage above 1× are outside Production V1.

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — normative Production V1 design, module boundaries, training, validation and deployment lifecycle.
- [`CONTRACTS.md`](CONTRACTS.md) — implementable schemas, units, invariants, artifacts and audit records.
- [`METHODOLOGY.md`](METHODOLOGY.md) — exact feature, signal, allocation, sizing, cost and performance formulas.
- [`OPERATIONS.md`](OPERATIONS.md) — runtime state machines, SLOs, security, incident handling, promotion and rollback.
- [`ROADMAP.md`](ROADMAP.md) — fachliche Reihenfolge für Standalone-Strategien, Exit-Optimierung, Regime-Evidenz, L2 und spätere lernende Allokatoren.
- [`MLFLOW.md`](MLFLOW.md) — normative Regeln für Experimente, Runs, Metriken, Metadaten, Artefakte, Model Registry, Promotion und Rollback.
- [`crypto-history-loader/DATASETS.md`](https://github.com/SergejSchweizer/crypto-history-loader/blob/main/DATASETS.md) — upstream Gold dataset definitions.

## Production V1

```text
gold.market.history_full.m1
            │ filter symbol == BTC
            ▼
 point-in-time feature service
            │ BTC perpetual = trading/reference price
            │ BTC spot = reference information only
            ▼
 fixed five-feature regime vector
            ▼
 Gaussian HMM, diagonal covariance, three states
            ▼
 filtered regime probabilities
            ▼
 deterministic trend / momentum / mean-reversion experts
            ▼
 deterministic probability-weighted allocator
            ▼
 one signed BTC-perpetual target position
            ▼
 deterministic risk engine
            ▼
 approved BTC-perpetual target notional
            ▼
 external execution system
```

Production V1 has one learned runtime component: the Regime Estimator. Strategy experts, allocation and risk enforcement are deterministic and versioned.

## Fixed market scope

| Concern | Production V1 rule |
|---|---|
| Asset | BTC only |
| Traded instrument | one linear BTC perpetual |
| Reference market | BTC spot, information only |
| Position direction | long, flat or short |
| Margin mode | isolated |
| Position mode | one-way |
| Maximum exposure | absolute notional no greater than allocated equity |
| Effective leverage | no greater than 1× |
| Decision interval | 1 hour |
| Primary evaluation horizon | 4 hours |
| Stress horizon | 1 day |
| Promotion | manual and atomic |

The instrument must support sufficiently fine sizing for a small account. At the configured reference capital, both minimum tradable notional and one quantity-step notional must be no greater than 1% of allocated equity. For capital equivalent to €1,000, each must therefore be no greater than the settlement-currency equivalent of €10.

## Module 1 — Regime Estimator

Production V1 uses one three-state Gaussian HMM with diagonal covariance and a fixed feature vector:

```text
return_24h
realized_volatility_24h
funding_zscore_30d
open_interest_change_24h
buy_volume_share_4h
```

It emits:

```text
current_probabilities[3]
forward_probabilities_4h[3]
normalised_entropy
maximum_probability
most_likely_state
state_signature_ids[3]
data_quality_status
abstain_recommended
```

Only filtered point-in-time probabilities are valid. Retrospectively smoothed states are prohibited in training inputs, backtests and live decisions.

## Strategy experts

Trend, momentum and mean reversion are deterministic BTC signal generators. They do not consume regime probabilities.

| Expert | Primary horizon |
|---|---:|
| Mean reversion | 1–4 hours |
| Momentum | 4–24 hours |
| Trend | 1–7 days |

Each expert emits direction, strength, confidence, expected holding time, estimated round-trip cost and data-quality status. Exact formulas are defined in `METHODOLOGY.md`.

## Module 2 — Deterministic Allocator

A versioned regime-to-strategy affinity matrix combines the complete regime-probability vector with the three expert signals. The allocator produces:

```text
strategy contribution weights
one consensus direction: SHORT, FLAT or LONG
one proposed BTC-perpetual position fraction
one cash weight
one global risk multiplier
one net-position exit profile
abstention recommendation
```

Opposing virtual positions are prohibited. When directional evidence is weak or materially conflicted, the target is flat.

## Module 3 — Deterministic Risk Engine

The Risk Engine validates or reduces the proposed BTC-perpetual target. It outputs `ApprovedTargetPosition.v1`, not an exchange order.

It enforces:

- BTC symbol and configured perpetual identity;
- isolated margin and one-way position mode;
- allocated-equity, loss-budget and margin-budget limits;
- maximum 1× effective leverage;
- stop-distance-based loss sizing;
- liquidation-buffer, funding, fee, spread and slippage limits;
- drawdown, daily loss, turnover, freshness and operational gates;
- fail-closed behaviour and reduce-only degradation.

## External execution system

Only the execution system decides:

- order side, quantity and order type;
- maker/taker behaviour and order slicing;
- price and quantity rounding;
- partial-fill handling;
- cancel/replace and retry;
- reduce-only protective orders;
- exchange reconciliation.

## Timing

```text
decision_interval = 1h
primary_evaluation_horizon = 4h
stress_horizon = 1d
```

A decision uses only closed M1 buckets. Historical entry simulation starts at the first eligible M1 open strictly after `as_of`. Live execution starts only after the feature snapshot, analytical decision and risk approval have been persisted.

## Model ladder

```text
Production V1:
- diagonal Gaussian HMM
- deterministic probability-weighted allocator
- standalone-calibrated and frozen strategy-specific exit profiles

Challengers:
- full-covariance Gaussian HMM
- duration-aware HMM
- regularised supervised allocator
- small discrete regime-dependent exit-profile mapping

Research only:
- contextual bandit
- reinforcement learning
```

## Evidence and experiment order

Economic evidence is established in stages:

```text
standalone Strategy Experts with nested exit optimisation
→ frozen strategy-specific exit profiles
→ No-Regime baseline versus Regime Candidate
→ optional regime-dependent discrete exit profiles
→ optional L2 microstructure overlay
→ optional learned allocator
```

The core comparisons are:

```text
Regime Candidate - No-Regime Baseline
= value of regime weighting

Regime-dependent exits - fixed exits
= additional value of regime-conditioned exits

L2 overlay - no-L2 common-window baseline
= additional microstructure value
```

MLflow records the experiment design, dataset lineage, parameters, statistical and economic metrics, artifacts and immutable model versions. Promotion remains governed by project-specific statistical, economic, shadow, paper, canary and manual approval gates.

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

Promotion is always manual. The BTC-perpetual instrument specification, model, scaler, affinity matrix, strategy configuration, exit-profile set, risk configuration, timing policy, cost model, code and dependencies are promoted and rolled back as one compatible artifact set.
