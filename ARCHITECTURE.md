# Architecture

## 1. Purpose

`regime-strategy-selector` produces one risk-controlled target position for one fixed Production V1 market:

```text
target_symbol = BTC
traded_instrument_type = LINEAR_PERPETUAL
margin_mode = ISOLATED
position_mode = ONE_WAY
```

One exchange-specific linear BTC perpetual is the only tradable instrument. BTC spot is an information and benchmark market only. Production V1 does not emit spot, ETH, SOL, options, inverse-perpetual or dated-futures orders.

An external capital service assigns the deployment:

```text
allocated_equity
max_loss_budget
max_margin_budget
```

Exact schemas are defined in [`CONTRACTS.md`](CONTRACTS.md), formulas in [`METHODOLOGY.md`](METHODOLOGY.md), and runtime rules in [`OPERATIONS.md`](OPERATIONS.md).

## 2. Normative Production V1 scope

| Concern | Production V1 rule |
|---|---|
| Asset | BTC only |
| Trading instrument | one configured linear BTC perpetual |
| Reference market | configured BTC spot market, information only |
| Decision interval | 1 hour |
| Primary horizon | 4 hours |
| Stress horizon | 1 day |
| Regime model | Gaussian HMM, diagonal covariance, 3 states |
| Regime features | fixed five-feature vector |
| Strategy experts | deterministic trend, momentum and mean reversion |
| Allocator | deterministic probability-weighted mapping |
| Position | one signed net BTC-perpetual position |
| Exit | one stop, one take profit and one time stop |
| Margin mode | isolated |
| Position mode | one-way |
| Maximum effective leverage | 1× |
| Promotion | manual and atomic |
| Bandits and RL | research only |

Production V1 has one learned runtime component: Module 1. Module 2 and Module 3 are deterministic.

## 3. System boundary

```text
gold.market.history_full.m1
            │ filter symbol == BTC
            │ validate BTC spot and BTC perpetual source rows
            ▼
 point-in-time feature service
            │
            ├── offline training targets
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
 external BTC-perpetual execution system
            ▼
 orders, fills, protective orders and reconciliation
```

The analytical repository stops at `ApprovedTargetPosition.v1`. Order side, quantity, order type, child-order schedule, maker/taker behaviour, retries and cancel/replace belong only to execution.

## 4. Market roles

### 4.1 Trading market

The deployment trades exactly one instrument:

```text
trading_instrument_id = exchange-specific linear BTC perpetual
```

Required properties:

- linear settlement;
- BTC underlying;
- perpetual maturity;
- long and short support;
- isolated margin support;
- one-way position mode support;
- reduce-only support;
- observable mark price, index price and liquidation price;
- known contract multiplier, quantity step, minimum quantity and price tick;
- reproducible fees and funding;
- live position and order reconciliation.

Inverse contracts are excluded because position notional, PnL and risk units differ materially from the linear contract conventions used by Production V1.

### 4.2 Reference spot market

The configured BTC spot market may supply:

- spot OHLCV;
- spot/perpetual basis;
- market-quality diagnostics;
- benchmark returns.

It is never an execution target. Loss of the required spot reference feed causes feature failure when a required feature depends on it; the system does not silently switch to another spot venue.

### 4.3 No runtime instrument selection

Production V1 does not choose between spot and perpetual at runtime or retraining time. The BTC perpetual is fixed by architecture. Changing exchange or perpetual contract creates a new deployment candidate and requires full replay, shadow, paper and canary validation.

## 5. Capital and units

### 5.1 Allocated equity

`allocated_equity` is the settlement-currency capital assigned to this deployment. It is not inferred from exchange account equity and may be smaller than total account equity.

### 5.2 Position fraction

```text
target_position_fraction = signed BTC-perpetual notional / allocated_equity
```

Examples:

```text
+0.40 = long BTC-perpetual notional equal to 40% of allocated equity
-0.40 = short BTC-perpetual notional equal to 40% of allocated equity
 0.00 = flat
```

Production V1 bounds:

```text
-1.00 <= target_position_fraction <= +1.00
```

The exchange may permit higher leverage, but the Risk Engine must never approve absolute notional greater than allocated equity.

### 5.3 Small-account capability

The selected perpetual must support complete risk implementation for a small account. At deployment validation time:

```text
minimum_order_notional / allocated_equity <= 0.01
quantity_step_notional / allocated_equity <= 0.01
```

For capital equivalent to €1,000, both values must therefore be no greater than the settlement-currency equivalent of €10. If either ratio exceeds 1%, the instrument is ineligible for that allocation.

### 5.4 Loss-budget sizing

For the selected exit profile:

```text
stop_fraction = stop_distance / entry_reference_price
risk_position_cap = risk_per_trade_fraction / max(stop_fraction, epsilon)
```

The approved absolute position fraction cannot exceed `risk_position_cap`, the allocator target, the configured exposure cap or the margin cap.

## 6. Data and timing

### 6.1 Production data

Production V1 uses only same-asset BTC data from:

```text
gold.market.history_full.m1
```

Core source families:

- BTC spot OHLCV;
- BTC perpetual OHLCV;
- BTC perpetual funding and freshness;
- BTC perpetual open interest and freshness;
- BTC perpetual trade flow.

Option trade flow is not a Production V1 dependency.

Trade executions, volume and trade counts are never forward-filled. Last-known state values may be used only with explicit observation age and availability fields.

### 6.2 Decision timing

`as_of` is the close time of the latest M1 bucket included in a feature snapshot.

```text
latest included source close <= as_of
feature completion > as_of
decision persistence >= feature completion
earliest execution submission > decision persistence
```

Historical entries use the first complete M1 bucket whose open time is strictly after `as_of`. If stop and take profit are both touched in one M1 bucket and the intrabar path is unknown, the adverse stop event is assumed first.

### 6.3 Horizons

```text
decision_interval = 1 hour
primary_evaluation_horizon = 4 hours
stress_horizon = 1 day
```

The 4-hour horizon drives model and allocator evaluation. The 1-day horizon drives stress diagnostics and the validation embargo.

## 7. Point-in-time feature service

### 7.1 Fixed HMM feature vector

Production V1 uses exactly:

```text
return_24h
realized_volatility_24h
funding_zscore_30d
open_interest_change_24h
buy_volume_share_4h
```

`atr_24h` and spot/perpetual basis diagnostics are computed for exits and monitoring but are not HMM emission features.

A missing, stale, non-finite or incomplete required feature sets `data_quality_status = FAIL`. There is no degraded feature vector and no silent imputation.

### 7.2 Scaling

```text
scaled_value =
    (value - training_median)
    / max(training_IQR, scaler_epsilon)
```

Feature order, formulas, medians, interquartile ranges and epsilon are frozen in the model artifact. Live inference never refits the scaler.

### 7.3 Feature evolution

Production V1 does not perform binary feature search over more than 100 variables. A new feature enters only through controlled ablation against the frozen five-feature baseline and requires a new feature-contract version and complete outer-fold reruns.

## 8. Module 1 — Regime Estimator

### 8.1 Model

```text
model_family = Gaussian HMM
covariance_type = diagonal
n_states = 3
n_initialisations = 20
minimum_stable_converged_fits = 16
```

Full-covariance and duration-aware HMMs are challengers. Other model families are research diagnostics.

### 8.2 Fit stability

For every training fold:

1. fit exactly 20 recorded deterministic seeds;
2. reject non-converged and degenerate fits;
3. align successful states by normalized state signatures;
4. reject the model when seed-level signature distance exceeds the configured threshold;
5. select the highest-likelihood member of the stable seed cluster.

### 8.3 Runtime output

Only filtered probabilities are valid:

```text
P(state at as_of | observations available through as_of)
```

```text
forward_probabilities_4h = current_probabilities × transition_matrix^4
normalised_entropy = -sum(p_i × ln(p_i)) / ln(3)
maximum_probability = max(p_i)
```

Generic fields such as undocumented `model_confidence` or `transition_risk` are prohibited.

### 8.4 Abstention

Module 1 recommends abstention on:

- feature failure;
- inference error;
- invalid probability vector;
- entropy above the configured limit;
- maximum probability below the configured minimum;
- invalid state alignment;
- feature, scaler or artifact hash mismatch.

### 8.5 State identity

A new state receives an existing signature identity only when its normalized distance is no greater than `maximum_state_alignment_distance`. Otherwise the challenger is `ALIGNMENT_INVALID` and cannot be promoted.

## 9. Deterministic strategy experts

Experts operate only on BTC data and do not consume regime probabilities.

| Expert | Horizon | Economic role |
|---|---:|---|
| Mean reversion | 1–4 hours | short-horizon reversal |
| Momentum | 4–24 hours | medium-horizon continuation |
| Trend | 1–7 days | persistent direction |

Each expert emits:

```text
direction ∈ {-1, 0, +1}
strength ∈ [0, 1]
confidence ∈ [0, 1]
expected_holding_minutes
estimated_round_trip_cost_bps
data_quality_status
```

Every expert must show defensible standalone BTC-perpetual behaviour after costs. An expert that fails standalone gates is disabled rather than rescued by the allocator.

## 10. Module 2 — Deterministic Allocator

### 10.1 Affinity matrix

The versioned matrix `affinity[state][strategy]` is estimated on inner training data from probability-weighted BTC-perpetual strategy returns divided by probability-weighted downside deviation.

All affinities are non-negative. Each state row sums to no more than `1 - minimum_cash_fraction`.

### 10.2 Runtime scores

```text
regime_affinity_s = sum(probability_r × affinity[r][s])
expert_score_s = regime_affinity_s × strength_s × confidence_s
signed_score_s = expert_score_s × direction_s
```

Positive and negative evidence determine one consensus direction. If evidence is too weak or insufficiently dominant, the result is `FLAT`.

### 10.3 Contribution weights and cash

Only experts agreeing with the consensus retain their score:

```text
strategy_contribution_weight_s = active_expert_score_s
cash_weight = 1 - sum(active_expert_scores)
```

Active scores are not renormalized upward. Unused allocation remains cash.

### 10.4 Preliminary target

```text
regime_certainty = clamp((maximum_probability - 1/3) / (2/3), 0, 1)
volatility_multiplier = clamp(target_volatility / max(realized_volatility_24h, floor), 0, 1)
global_risk_multiplier = regime_certainty × volatility_multiplier
preliminary_target_fraction = direction_sign × (1 - cash_weight) × global_risk_multiplier
```

Module 2 does not apply exchange quantities, margin or liquidation logic.

### 10.5 One net exit profile

The expert with the largest contribution determines the provisional net exit profile:

| Dominant expert | Stop | Take profit | Time stop |
|---|---:|---:|---:|
| Mean reversion | 1.0 × ATR_24h | 1.5 × ATR_24h | 4 hours |
| Momentum | 1.5 × ATR_24h | 2.5 × ATR_24h | 24 hours |
| Trend | 2.0 × ATR_24h | 4.0 × ATR_24h | 72 hours |

There are no sleeve-level exchange positions or opposing sleeve stops.

## 11. Module 3 — Deterministic Risk Engine

Module 3 returns `APPROVED`, `CLIPPED`, `REJECTED` or `HALTED` and an `ApprovedTargetPosition.v1`.

It enforces:

- BTC symbol and exact perpetual instrument equality;
- linear contract semantics;
- isolated margin and one-way position mode;
- absolute position fraction no greater than 1.0;
- stop-distance-based risk-per-trade cap;
- allocated-equity, loss-budget and margin-budget limits;
- minimum liquidation buffer;
- funding, fee, spread, slippage and round-trip cost limits;
- daily loss, rolling loss and maximum drawdown limits;
- maximum target change and turnover;
- data freshness, entropy and abstention;
- reconciliation, pending-plan and kill-switch state.

Abstention or uncertainty may preserve or reduce exposure but may never increase absolute exposure.

Module 3 never emits order side, quantity, order type, price or child-order instructions.

## 12. External execution

Execution converts the approved BTC-perpetual target notional into exchange-valid orders. It owns:

- current-position-to-target delta;
- contract quantity calculation;
- quantity and price rounding;
- order side, type and urgency;
- maker/taker choice and slicing;
- partial fills;
- cancel/replace and retry;
- reduce-only protective orders;
- mark, index and liquidation-price monitoring;
- position, margin, cash and open-order reconciliation.

Every approval creates at most one logical execution plan through deterministic idempotency.

## 13. Training and validation

### 13.1 Default schedule

```text
outer training window = previous 3 years
outer test interval = next 3 months
outer step = 3 months
inner validation block = 3 months
retraining frequency = quarterly
purge = longest overlapping target interval
embargo = 1 day
```

### 13.2 Fold procedure

For every outer fold:

1. validate BTC perpetual and BTC spot source coverage;
2. build point-in-time features from training data only;
3. fit the robust scaler on each inner training fold only;
4. fit and stability-check 20 HMM seeds;
5. generate filtered out-of-fold regime probabilities;
6. generate standalone BTC-perpetual expert returns after full costs;
7. estimate the affinity matrix on inner training data;
8. simulate the deterministic pipeline with margin, funding, stops and costs;
9. freeze the candidate;
10. evaluate it once on the untouched outer test interval.

### 13.3 Required benchmarks

The Production V1 pipeline is compared against:

- cash;
- BTC spot buy-and-hold as an information benchmark;
- unlevered BTC-perpetual long-only buy-and-hold;
- each standalone expert;
- an equal-weight deterministic expert mix without regime context;
- the same experts with static, non-regime weights.

Spot benchmark performance never makes spot tradable.

### 13.4 Hard gates

Reject a candidate on:

- leakage or timing violation;
- BTC perpetual instrument-contract failure;
- small-account capability failure;
- fewer than 16 stable converged HMM seeds;
- state occupancy below 5%;
- median state duration below 2 hours;
- invalid state alignment;
- non-positive net return in more than 40% of outer folds;
- one fold contributing more than 50% of aggregate positive PnL;
- research drawdown-limit breach;
- minimum liquidation-buffer breach;
- elevated or severe cost-stress failure;
- historical/live feature mismatch;
- unsupported execution or reconciliation behaviour.

Primary model-selection metric is net Calmar. CVaR, Sharpe, Sortino, turnover, fold consistency, state stability, funding sensitivity, liquidation distance and abstention are mandatory secondary diagnostics.

## 14. Production lifecycle

```text
offline research
→ historical replay
→ live feature shadow
→ full decision shadow
→ paper BTC-perpetual execution
→ small-capital BTC-perpetual canary
→ restricted production
```

Promotion is manual. The BTC perpetual specification, reference spot specification, model, scaler, affinity matrix, strategy configuration, risk configuration, operations configuration, timing policy, cost model, code and dependencies are promoted and rolled back as one compatible artifact set.

## 15. Production readiness

Production activation requires:

- executable contract validation;
- one shared historical/live decision function;
- exact historical/live feature parity;
- validated linear BTC-perpetual contract semantics;
- verified isolated margin and one-way position mode;
- verified 1% small-account sizing granularity;
- stable multi-seed HMM results;
- standalone expert evidence after costs;
- deterministic allocator improvement over required baselines;
- complete funding and cost stress;
- liquidation-buffer stress tests;
- risk-engine property, replay, idempotency and fail-closed tests;
- paper execution cost calibration;
- successful small-capital canary operation;
- immutable audit records;
- tested manual rollback.
