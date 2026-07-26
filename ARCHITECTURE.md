# Architecture

## 1. Purpose

`regime-strategy-selector` produces one risk-controlled target position for exactly one configured crypto asset:

```text
target_symbol ∈ {BTC, ETH, SOL}
```

A deployment is bound to exactly one traded instrument:

```text
selected_instrument_type ∈ {SPOT, PERPETUAL}
```

Same-asset spot and perpetual data may both be used as information, but only the selected instrument may be traded.

The system does not allocate account capital across BTC, ETH, and SOL. An external capital service assigns each deployment an immutable `allocated_equity`, `max_loss_budget`, and `max_margin_budget`.

Exact schemas are in [`CONTRACTS.md`](CONTRACTS.md), formulas in [`METHODOLOGY.md`](METHODOLOGY.md), and runtime rules in [`OPERATIONS.md`](OPERATIONS.md).

## 2. Production V1 scope

| Concern | Production V1 rule |
|---|---|
| Asset | exactly one of BTC, ETH, SOL |
| Decision interval | 1 hour |
| Primary horizon | 4 hours |
| Stress horizon | 1 day |
| Regime model | Gaussian HMM, diagonal covariance, 3 states |
| Regime features | fixed five-feature vector |
| Strategy experts | deterministic trend, momentum, mean reversion |
| Allocator | deterministic probability-weighted mapping |
| Position | one signed net position |
| Exit | one stop, one take profit, one time stop |
| Instruments | eligible spot and perpetual candidates |
| Leverage | absolute position fraction no greater than 1.0 |
| Promotion | manual and atomic |
| Bandits/RL | research only |

Production V1 has one learned runtime component: Module 1. Module 2 and Module 3 are deterministic.

## 3. System boundary

```text
gold.market.history_full.m1
            │ filter symbol == target_symbol
            ▼
 point-in-time feature service
            │
            ├── training targets, offline only
            ├── trend expert
            ├── momentum expert
            └── mean-reversion expert
            ▼
 Module 1: Regime Estimator
            │ RegimePrediction.v1
            ▼
 Module 2: Deterministic Allocator
            │ AllocationProposal.v1
            ▼
 Module 3: Deterministic Risk Engine
            │ ApprovedTargetPosition.v1
            ▼
 external execution system
            ▼
 orders, fills, cancels, reconciliation
```

The analytical repository stops at `ApprovedTargetPosition.v1`. Order type, price, quantity, slicing, maker/taker behaviour, retries, and cancel/replace belong only to execution.

## 4. Units

### 4.1 Target position fraction

```text
target_position_fraction = signed target notional / allocated_equity
```

```text
SPOT:       0.00 to +1.00
PERPETUAL: -1.00 to +1.00
```

Spot borrowing, spot shorting, options execution, and leverage above 1.0 are excluded.

### 4.2 Strategy contribution weight

A contribution weight is a non-negative attribution and allocation fraction. It is not a position or quantity.

```text
trend_weight + momentum_weight + mean_reversion_weight + cash_weight = 1
```

### 4.3 Position and order ownership

Module 2 proposes a position fraction. Module 3 approves a position fraction and notional. Execution converts notional to exchange quantity.

## 5. Instrument selection

### 5.1 Candidate universe

Each asset has a versioned candidate universe, normally one spot and one perpetual instrument. Every candidate must have historical simulation, live execution, and reconciliation support.

### 5.2 Eligibility

A candidate is rejected when:

- decision-grid coverage is below 99.5%;
- a source gap exceeds 180 minutes;
- fees, spread, slippage, or funding cannot be modelled;
- instrument multiplier, minimum quantity, step, tick, margin mode, or position semantics are unknown;
- required execution and reconciliation behaviour is unsupported;
- median daily quote volume is below the configured threshold;
- historical replay and live execution cannot use equivalent rules.

### 5.3 Fair comparison

Eligible spot and perpetual candidates use identical:

- target asset;
- feature definitions;
- HMM configuration;
- expert definitions;
- allocator formulas;
- decision timestamps;
- allocated equity;
- absolute exposure cap;
- outer folds;
- risk limits.

Costs and instrument constraints remain instrument-specific. Spot is long-or-flat; perpetual is long, flat, or short.

### 5.4 Ranking

Candidates must first pass every hard gate. They are then ranked by:

1. higher median outer-fold net Calmar;
2. lower median absolute 95% CVaR loss;
3. higher median annualised net return;
4. lower median annualised turnover;
5. lower operational complexity.

Perpetual is selected only when the paired block-bootstrap 95% interval for `perpetual Calmar - spot Calmar` has a positive lower bound and the median Calmar improvement is at least `0.10`. Otherwise eligible spot is preferred.

The selected instrument is frozen. An instrument change is a new challenger deployment requiring replay, shadow, paper, canary, and manual promotion.

## 6. Data and timing

### 6.1 Production data

Production V1 uses:

- spot OHLCV;
- perpetual OHLCV;
- funding and freshness;
- open interest and freshness;
- perpetual trade flow.

Option trade flow is not a core dependency.

No trade execution, volume, or count is forward-filled. Last-known state values require valid age metadata.

### 6.2 Decision timing

`as_of` is the close time of the latest included M1 bucket.

```text
latest included close <= as_of
feature completion > as_of
decision persistence >= feature completion
earliest execution > decision persistence
```

Historical fills use the first M1 open strictly after `as_of`. If stop and take profit are both touched in one M1 bar, stop is assumed first. Gap stops fill at the first tradable simulated price plus adverse slippage.

### 6.3 Horizons

```text
decision_interval = 1 hour
primary_evaluation_horizon = 4 hours
stress_horizon = 1 day
```

The 4-hour horizon controls selection. The 1-day horizon controls stress diagnostics and embargo length.

## 7. Feature service

### 7.1 Fixed regime vector

```text
return_24h
realized_volatility_24h
funding_zscore_30d
open_interest_change_24h
buy_volume_share_4h
```

`atr_24h` is additionally computed for exit levels but is not an HMM emission feature.

A missing, stale, non-finite, or incomplete required value sets data quality to `FAIL`. Production V1 has no degraded feature mode and no silent fallback.

### 7.2 Scaling

```text
scaled = (value - training_median) / max(training_IQR, scaler_epsilon)
```

Scaler values, feature order, and definitions are frozen in the model artifact. Live inference cannot refit them.

### 7.3 Feature evolution

Production V1 does not run binary Optuna selection over more than 100 features. A new feature enters only through a controlled ablation against the frozen five-feature baseline and creates a new contract version.

## 8. Module 1 — Regime Estimator

### 8.1 Model

```text
Gaussian HMM
diagonal covariance
3 states
20 deterministic initialisations
minimum 16 stable converged fits
```

Full-covariance and duration-aware HMMs are challengers. Other model families are diagnostics only.

### 8.2 Fit stability

States are aligned across successful seeds. A fit is rejected when seed-level aligned signatures exceed the configured stability threshold. The selected seed is the highest-likelihood member of the stable, non-degenerate seed cluster.

### 8.3 Runtime output

Only filtered probabilities are emitted:

```text
P(state at as_of | observations through as_of)
```

```text
forward_probabilities_4h = current_probabilities × transition_matrix^4
normalised_entropy = -sum(p_i * ln(p_i)) / ln(3)
maximum_probability = max(p_i)
```

Ambiguous fields such as generic model confidence or transition risk are excluded.

### 8.4 Abstention

Module 1 abstains on:

- failed feature quality;
- inference error;
- invalid probability vector;
- entropy above the configured limit;
- maximum probability below the configured minimum;
- invalid state alignment;
- hash or artifact mismatch.

### 8.5 State alignment

A new state may receive an existing signature identity only when distance is no greater than `maximum_state_alignment_distance`. Otherwise the challenger is `ALIGNMENT_INVALID` and cannot be promoted.

## 9. Strategy experts

Experts are deterministic and do not consume regime probabilities.

| Expert | Horizon | Role |
|---|---:|---|
| Mean reversion | 1–4 hours | short reversal |
| Momentum | 4–24 hours | continuation |
| Trend | 1–7 days | persistent direction |

Each emits direction, strength, confidence, holding time, estimated cost, and data-quality status. Exact formulas are normative in `METHODOLOGY.md`.

Every expert is evaluated standalone after instrument-specific costs. An expert with no defensible standalone behaviour is not enabled in the combined allocator.

## 10. Module 2 — Deterministic Allocator

### 10.1 Affinity matrix

The versioned matrix `affinity[state][strategy]` is estimated from inner training data using probability-weighted net return divided by probability-weighted downside deviation. Values are non-negative and each row sum is no greater than `1 - minimum_cash_fraction`.

### 10.2 Runtime scores

```text
regime_affinity_s = sum(probability_r * affinity[r][s])
expert_score_s = regime_affinity_s * strength_s * confidence_s
signed_score_s = expert_score_s * direction_s
```

Positive and negative evidence determine one consensus direction. If evidence is too weak or opposing evidence lacks configured dominance, the result is `FLAT`. Spot converts `SHORT` to `FLAT`.

### 10.3 Contributions and cash

Only strategies agreeing with the consensus retain their expert score:

```text
strategy_contribution_weight_s = active expert score_s
cash_weight = 1 - sum(active expert scores)
```

Active scores are not renormalised upward. Unused allocation remains cash. When direction is `FLAT`, all strategy contributions are zero and cash is one.

### 10.4 Target fraction

```text
regime_certainty = clamp((maximum_probability - 1/3) / (2/3), 0, 1)
volatility_multiplier = clamp(target_volatility / max(realized_volatility_24h, floor), 0, 1)
global_risk_multiplier = regime_certainty * volatility_multiplier
proposed_target_fraction = direction_sign * (1 - cash_weight) * global_risk_multiplier
```

Instrument bounds are then applied.

### 10.5 One net exit profile

The strategy with the largest contribution is dominant:

| Dominant strategy | Stop | Take profit | Time stop |
|---|---:|---:|---:|
| Mean reversion | 1.0 × ATR_24h | 1.5 × ATR_24h | 4 hours |
| Momentum | 1.5 × ATR_24h | 2.5 × ATR_24h | 24 hours |
| Trend | 2.0 × ATR_24h | 4.0 × ATR_24h | 72 hours |

There are no sleeve-level exchange positions or opposing sleeve stops.

A supervised allocator is a later challenger. Bandits and RL remain research-only.

## 11. Module 3 — Deterministic Risk Engine

Module 3 outputs `APPROVED`, `CLIPPED`, `REJECTED`, or `HALTED` and an `ApprovedTargetPosition.v1`.

It enforces:

- symbol, instrument, deployment, and artifact equality;
- capital and loss budgets;
- spot/perpetual exposure bounds;
- leverage no greater than 1.0;
- margin and liquidation buffer;
- daily, rolling, and drawdown limits;
- maximum target change and turnover;
- expected cost limits;
- freshness, entropy, and abstention;
- reconciliation and operational state;
- kill switch.

Abstention cannot increase absolute exposure. Module 3 never emits order type, quantity, side, or limit price.

## 12. External execution

Execution owns:

- target-to-order delta;
- exchange quantity and price rounding;
- order type and urgency;
- slicing;
- maker/taker choice;
- partial fills;
- cancel/replace and retry;
- stop/take-profit activation after reconciled entry fill;
- exchange position and cash reconciliation.

Every approval creates at most one logical execution plan through deterministic idempotency.

## 13. Training and validation

### 13.1 Default schedule

```text
outer training = previous 3 years
outer test = next 3 months
outer step = 3 months
inner validation = 3 months
retraining = quarterly
embargo = 1 day
```

### 13.2 Fold procedure

For each eligible instrument and outer fold:

1. build training-only point-in-time features;
2. fit the training-only scaler;
3. fit 20 HMM seeds;
4. reject unstable fits;
5. generate filtered out-of-fold probabilities;
6. generate expert returns after instrument-specific costs;
7. estimate the affinity matrix on inner training data;
8. validate the deterministic pipeline;
9. freeze the candidate;
10. evaluate once on the outer test.

### 13.3 Hard gates

Reject a candidate on:

- leakage or timing violation;
- instrument ineligibility;
- fewer than 16 stable converged seeds;
- state occupancy below 5%;
- median duration below 2 hours;
- invalid state alignment;
- non-positive net return in more than 40% of outer folds;
- one fold above 50% of aggregate positive PnL;
- drawdown limit breach;
- failed elevated or severe cost stress;
- historical/live feature mismatch;
- unsupported operational behaviour.

Primary selection metric is net Calmar. CVaR, Sharpe, Sortino, turnover, fold consistency, state stability, and abstention are secondary diagnostics. Exact definitions are in `METHODOLOGY.md`.

## 14. Production lifecycle

```text
offline research
→ historical replay
→ live feature shadow
→ full decision shadow
→ paper execution
→ small-capital canary
→ restricted production
```

Promotion is manual. The instrument, model, scaler, affinity matrix, strategy configuration, risk configuration, timing policy, cost model, code, and dependencies are promoted and rolled back as one compatible set.

## 15. Production readiness

Production requires:

- executable contract validation;
- one shared historical/live decision function;
- exact feature parity;
- robust instrument selection;
- stable multi-seed HMM results;
- standalone expert evidence;
- deterministic allocator improvement over cash and static baselines;
- complete cost stress;
- risk-engine property, stress, replay, idempotency, and fail-closed tests;
- paper cost calibration;
- successful canary operation;
- immutable audit records;
- tested manual rollback.
