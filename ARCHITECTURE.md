# Architecture

## 1. Purpose

`regime-strategy-selector` produces one risk-controlled target position for exactly one configured crypto asset:

```text
target_symbol ∈ {BTC, ETH, SOL}
```

A deployment is also bound to exactly one traded instrument selected from an explicit asset-specific universe:

```text
selected_instrument_type ∈ {SPOT, PERPETUAL}
```

The same-asset spot and perpetual markets may both supply features, but only the selected instrument may receive orders.

The system does not allocate capital across BTC, ETH, and SOL. If separate deployments share an exchange account, an external account-level capital service must assign each deployment an immutable `allocated_equity` and `max_loss_budget`.

## 2. Normative Production V1

Production V1 intentionally restricts model and execution freedom.

| Concern | Production V1 rule |
|---|---|
| Asset scope | exactly one of BTC, ETH, SOL |
| Decision interval | 1 hour |
| Primary evaluation horizon | 4 hours |
| Stress horizon | 1 day |
| Regime count | 3 |
| Regime model | Gaussian HMM, diagonal covariance |
| Core regime features | fixed five-feature set |
| Allocator | deterministic probability-weighted mapping |
| Position structure | one net direction and one net position |
| Exit structure | one net stop, one net take-profit, one time stop |
| Instrument universe | eligible spot and perpetual candidates |
| Perpetual leverage | absolute target position fraction no greater than 1.0 |
| Promotion | manual only |
| RL and bandits | research only |

Production V1 has only one learned runtime component: the Regime Estimator. The allocator and risk engine are deterministic and versioned.

## 3. System boundary

```text
gold.market.history_full.m1
            │
            ├── filter symbol == target_symbol
            ├── validate source freshness and coverage
            ▼
 point-in-time feature service
            │
            ├────────────► training targets (offline only)
            ├────────────► trend expert
            ├────────────► momentum expert
            └────────────► mean-reversion expert
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
            │
            ▼
 exchange orders, fills, cancels, reconciliation
```

The analytical repository stops at `ApprovedTargetPosition.v1`. It does not choose order type, limit price, child-order schedule, maker/taker behaviour, retry policy, or cancel/replace behaviour.

## 4. Unambiguous units

### 4.1 Allocated equity

`allocated_equity` is the capital assigned to this deployment by an external account-level service.

### 4.2 Target position fraction

```text
target_position_fraction = signed target notional / allocated_equity
```

Examples:

```text
+0.40 = long notional equal to 40% of allocated equity
-0.40 = short notional equal to 40% of allocated equity
 0.00 = flat
```

Production V1 bounds are:

```text
SPOT:       0.00 <= target_position_fraction <= 1.00
PERPETUAL: -1.00 <= target_position_fraction <= 1.00
```

Spot shorting, borrowing, options execution, and leverage above 1.0 are excluded from Production V1.

### 4.3 Risk budget

A strategy contribution weight is a non-negative attribution weight. It is not a position and not a quantity. Trend, momentum, mean-reversion, and cash weights sum to one.

### 4.4 Price and quantity

The analytical system uses decimal prices and base-asset quantities only for observation and approved target calculation. The execution system converts approved notional into exchange-valid quantity using instrument multiplier, quantity step, price tick, and current reference price.

## 5. Instrument selection

### 5.1 Candidate universe

Every asset has an explicit, versioned `InstrumentUniverse.v1`. A normal universe contains:

```text
one spot instrument
one perpetual instrument
```

The universe may contain only instruments supported by the execution system and the historical simulator.

### 5.2 Eligibility gates

An instrument is ineligible when any of the following is true:

- historical decision-grid coverage is below 99.5% in an outer training window;
- a contiguous market-data gap exceeds three decision intervals;
- the cost model cannot represent fees, spread, slippage, and, for perpetuals, funding;
- exchange minimum size, tick, quantity step, margin mode, or position semantics are unknown;
- live reconciliation is not implemented;
- required order types or reduce-only behaviour are unsupported;
- the instrument breaches configured liquidity or notional-capacity limits;
- the instrument cannot be reproduced identically in historical replay and live execution.

Coverage thresholds are defaults and must be versioned. They cannot be relaxed after inspecting an outer test result.

### 5.3 Fair comparison

Spot and perpetual candidates are evaluated with:

- the same target asset;
- the same feature service;
- the same regime model family and parameters;
- the same expert definitions;
- the same allocator formula;
- the same decision timestamps;
- the same allocated equity;
- the same absolute exposure cap of 1.0;
- instrument-specific but complete costs and execution constraints;
- the same outer walk-forward periods.

Spot is long-or-flat. Perpetual is long, flat, or short. This constraint is part of the comparison and must not be normalised away.

### 5.4 Ranking rule

An eligible instrument must first pass all risk and robustness gates. Remaining candidates are ranked lexicographically:

1. highest median outer-fold net Calmar ratio;
2. lower median absolute 95% CVaR loss;
3. higher median annualised net return;
4. lower median annualised turnover;
5. lower operational complexity.

`net` means after fees, spread, slippage, and funding.

A paired block-bootstrap comparison is computed for the difference in outer-fold Calmar results. The perpetual is selected only when:

```text
lower bound of the 95% confidence interval > 0
and
median Calmar improvement >= min_calmar_improvement
```

The default `min_calmar_improvement` is `0.10`. If these conditions are not met, spot is selected when it passes all gates. Therefore a clearly superior perpetual is traded, while statistically indistinguishable results resolve to the simpler spot instrument.

### 5.5 Selection lifecycle

Instrument selection is never performed at every trading decision. It is performed during model-development and challenger evaluation. The selected instrument is frozen in the compatible artifact set.

Changing from spot to perpetual or from perpetual to spot creates a new deployment challenger and requires:

```text
historical replay
→ live decision shadow
→ paper execution
→ small-capital canary
→ manual promotion
```

## 6. Data and timing

### 6.1 Source data

Production V1 uses only:

```text
gold.market.history_full.m1
```

Eligible same-asset source families are:

- spot OHLCV;
- perpetual OHLCV;
- funding state and age;
- open-interest state and age;
- perpetual trade-flow aggregates.

Option trade flow is excluded from the Production V1 core feature set. It may be evaluated later as an optional challenger block only when asset-specific coverage passes the same data gates.

Trade executions, volume, and trade counts are never forward-filled. Last-known funding and open-interest values may be used only with their age and availability fields.

### 6.2 Decision timestamp

`as_of` is the close time of the latest M1 bucket included in the feature snapshot.

Rules:

```text
all included source buckets have close_time <= as_of
feature computation starts after as_of
analytical decision is persisted before execution begins
earliest live order submission > as_of
```

### 6.3 Historical fill rule

A historical decision cannot fill in a bucket used to construct that decision.

```text
historical entry bucket = first complete M1 bucket with open_time > as_of
```

The simulated fill starts from that bucket's open price and applies the configured spread, slippage, fee, and funding model.

When both stop and take-profit are touched inside the same M1 bucket and the intra-bucket path is unknown, the adverse event is assumed to occur first. A gap through a stop fills at the first tradable simulated price plus adverse slippage.

### 6.4 Horizons

```text
decision_interval = 1h
primary_evaluation_horizon = 4h
stress_horizon = 1d
```

The 4-hour horizon drives model and allocator selection. The 1-day horizon is a risk diagnostic and embargo requirement. It is not a second optimisation objective of equal priority.

## 7. Point-in-time feature service

### 7.1 Fixed Production V1 feature vector

The Regime Estimator consumes exactly five features:

```text
return_24h
realized_volatility_24h
funding_zscore_30d
open_interest_change_24h
buy_volume_share_4h
```

Definitions are in `CONTRACTS.md` and executable feature code must match the feature-set hash.

No silent fallback is allowed. If a required core feature is unavailable or stale beyond its contract limit, `MarketFeatureFrame.v1.data_quality_status = FAIL` and the system may only preserve or reduce exposure.

### 7.2 Scaling

Production V1 uses a training-only robust scaler:

```text
scaled_value = (value - training_median) / max(training_IQR, scaler_epsilon)
```

The median, interquartile range, epsilon, column order, and feature definitions are stored in the model artifact. Live inference may not refit or update the scaler.

### 7.3 Feature evolution

New features are introduced by controlled ablation:

1. register one feature or one coherent feature block;
2. rerun all outer folds;
3. compare against the frozen five-feature baseline;
4. require stable incremental value after costs;
5. create a new feature-contract version.

Blind binary search across more than 100 features is excluded from Production V1.

## 8. Module 1 — Regime Estimator

### 8.1 Production model

```text
model_family = Gaussian HMM
covariance_type = diagonal
n_states = 3
n_initialisations = 20
```

Model challengers are full-covariance Gaussian HMM and a duration-aware HMM. GMM, generic change-point models, contextual bandits, and RL are research diagnostics, not Production V1 candidates.

### 8.2 Fitting requirements

For each fit:

- run exactly 20 deterministic seeds recorded in the artifact;
- require at least 16 converged, non-degenerate fits;
- align states across successful seeds using state signatures;
- reject the candidate when median aligned signature distance exceeds the configured seed-stability threshold;
- select the highest training likelihood only from the stable, non-degenerate seed cluster.

### 8.3 Runtime probabilities

Only filtered probabilities are valid:

```text
P(state at as_of | observations with timestamp <= as_of)
```

The 4-hour forward vector is computed as:

```text
forward_probabilities_4h = current_probabilities × transition_matrix^4
```

because the decision interval is one hour.

Normalised entropy is:

```text
normalised_entropy = -sum(p_i * ln(p_i)) / ln(3)
```

It is in `[0, 1]`. `maximum_probability = max(p_i)`.

The contract does not expose ambiguous fields named `model_confidence` or `transition_risk`.

### 8.4 Abstention

Module 1 recommends abstention when any of the following is true:

- feature data quality is `FAIL`;
- inference fails;
- probability values are invalid;
- normalised entropy exceeds `max_regime_entropy`;
- maximum probability is below `min_regime_probability`;
- the deployed state alignment is invalid;
- the feature or model artifact hash does not match.

### 8.5 State alignment

Each state signature contains return, volatility, downside volatility, trend strength, drawdown state, funding, open-interest change, flow imbalance, duration, and occupancy.

Minimum-distance matching may be used only when the matched distance is no greater than `max_state_alignment_distance`. A state above this threshold is not forcibly assigned an old business identity. The challenger is marked `ALIGNMENT_INVALID` and cannot be promoted.

## 9. Strategy experts

Experts are deterministic, independently testable signal generators. They do not receive regime probabilities.

| Expert | Required economic horizon | Output role |
|---|---:|---|
| Mean reversion | 1–4 hours | short-horizon reversal |
| Momentum | 4–24 hours | medium-horizon continuation |
| Trend | 1–7 days | persistent direction |

Each expert emits:

```text
direction in {-1, 0, +1}
strength in [0, 1]
confidence in [0, 1]
expected_holding_minutes
estimated_cost_bps
data_quality_status
```

Feature overlap is allowed only when the expert contract documents why the same observation has a different horizon-specific meaning.

Experts are evaluated standalone after costs. An expert that does not have defensible standalone behaviour cannot be rescued solely by the allocator.

## 10. Module 2 — Deterministic Allocator

### 10.1 Regime-strategy affinity matrix

The allocator contains a versioned matrix:

```text
affinity[state][strategy] in [0, 1]
```

Rows correspond to aligned regime signatures. Columns correspond to trend, momentum, and mean reversion.

The matrix is estimated on inner training data only. For each state and strategy:

```text
weighted_mean_return =
    sum(state_probability_t * strategy_net_return_t)
    / sum(state_probability_t)

weighted_downside =
    sqrt(
        sum(state_probability_t * min(strategy_net_return_t, 0)^2)
        / sum(state_probability_t)
    )

raw_affinity = max(
    0,
    weighted_mean_return / max(weighted_downside, affinity_epsilon)
)
```

Each row is clipped to `[0, 1]` and normalised so its three strategy affinities sum to no more than `1 - minimum_cash_fraction`. All constants are versioned.

### 10.2 Runtime strategy scores

For each strategy:

```text
regime_affinity_s = sum(current_probability_r * affinity[r][s])
expert_score_s = regime_affinity_s * strength_s * confidence_s
signed_score_s = expert_score_s * direction_s
```

Positive and negative evidence are:

```text
positive_evidence = sum(max(signed_score_s, 0))
negative_evidence = sum(abs(min(signed_score_s, 0)))
```

Direction selection:

```text
if max(positive_evidence, negative_evidence) < min_consensus_evidence:
    direction = FLAT
else if min(positive_evidence, negative_evidence) > 0
        and max(...) / min(...) < min_direction_dominance:
    direction = FLAT
else:
    direction = LONG when positive_evidence > negative_evidence
    direction = SHORT when negative_evidence > positive_evidence
```

For a spot instrument, `SHORT` is converted to `FLAT`.

Strategies opposing the consensus direction receive zero contribution. Remaining strategy scores are normalised into non-negative strategy contribution weights.

### 10.3 Cash and risk multiplier

The minimum cash fraction is configured and cannot be negative.

Regime certainty is:

```text
regime_certainty =
    clamp((maximum_probability - 1/3) / (2/3), 0, 1)
```

Volatility scaling is:

```text
volatility_multiplier =
    clamp(target_volatility_annual / max(realized_volatility_24h, volatility_floor), 0, 1)
```

The global risk multiplier is:

```text
global_risk_multiplier = regime_certainty * volatility_multiplier
```

The preliminary signed target is:

```text
proposed_target_position_fraction =
    direction_sign
    * (1 - cash_fraction)
    * global_risk_multiplier
```

where `direction_sign` is `-1`, `0`, or `+1`.

### 10.4 One net exit profile

Production V1 has one net position and one net exit profile. No sleeve-level exchange stops exist.

The dominant strategy is the strategy with the largest contribution weight. It selects a deterministic profile:

| Dominant strategy | Stop distance | Take-profit distance | Maximum holding time |
|---|---:|---:|---:|
| Mean reversion | 1.0 × ATR_24h | 1.5 × ATR_24h | 4 hours |
| Momentum | 1.5 × ATR_24h | 2.5 × ATR_24h | 24 hours |
| Trend | 2.0 × ATR_24h | 4.0 × ATR_24h | 72 hours |

For a long position:

```text
stop = entry_reference_price - stop_distance
take_profit = entry_reference_price + take_profit_distance
```

For a short position the signs are reversed.

The entry reference price is the first reconciled average fill price supplied by the execution system. Until that fill exists, exit levels are provisional and no close-order price is assumed by the analytical system.

### 10.5 Learned allocators

A regularised supervised allocator may be evaluated as a challenger after Production V1 is stable. Contextual bandits and reinforcement learning remain research-only until a supervised challenger has demonstrated stable incremental value.

## 11. Module 3 — Deterministic Risk Engine

Module 3 receives the proposal, capital allocation, current portfolio, instrument constraints, operational state, and risk configuration.

It may return only:

```text
APPROVED
CLIPPED
REJECTED
HALTED
```

It outputs an approved target, not orders.

The engine enforces:

- exact target-symbol and selected-instrument equality;
- allocated-equity and max-loss budget;
- spot or perpetual exposure bounds;
- perpetual leverage no greater than 1.0 in Production V1;
- margin and liquidation-buffer rules;
- current and projected drawdown;
- daily and rolling loss limits;
- maximum target change and turnover;
- maximum modeled cost;
- feature freshness and data-quality status;
- regime entropy and abstention;
- portfolio reconciliation;
- pending-decision and operational state;
- kill switch.

When any upstream component recommends abstention, the approved absolute exposure cannot exceed the current reconciled absolute exposure.

## 12. Execution boundary

The execution system converts an approved target into orders. It owns:

- target-to-order delta calculation;
- quantity and price rounding;
- order type;
- slicing and urgency;
- maker/taker choice;
- partial fills;
- cancel/replace;
- retry and rate-limit handling;
- exchange acknowledgements;
- position and cash reconciliation;
- activation and maintenance of stop/take-profit orders.

The execution system must use deterministic idempotency keys and must not create more than one logical execution plan for the same approved decision.

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

### 13.2 Selection order

For each instrument candidate and outer fold:

1. apply instrument eligibility gates;
2. build point-in-time features from outer training data only;
3. fit the robust scaler on each inner training fold only;
4. fit 20 HMM seeds;
5. reject unstable model fits;
6. emit filtered out-of-fold probabilities;
7. generate standalone expert returns after instrument-specific costs;
8. estimate the deterministic affinity matrix on inner training data;
9. evaluate the full deterministic pipeline on inner validation data;
10. freeze the selected configuration;
11. evaluate once on the outer test interval.

Completed outer folds are aggregated before instrument or model promotion.

### 13.3 Hard research gates

A candidate is rejected when:

- any leakage or timing violation exists;
- data eligibility fails;
- fewer than 16 of 20 HMM seeds converge stably;
- any state occupancy is below 5%;
- median episode duration is below 2 decision intervals;
- state alignment exceeds the configured threshold;
- net return is non-positive in more than 40% of outer folds;
- one fold contributes more than 50% of aggregate positive PnL;
- maximum drawdown exceeds the research limit;
- elevated or severe cost stress removes all positive median return;
- historical and live feature definitions differ;
- the candidate requires unsupported operational behaviour.

### 13.4 Primary model metric

The primary performance measure is net Calmar ratio:

```text
net_Calmar = annualised_net_return / absolute_maximum_drawdown
```

If annualised net return is not positive, net Calmar is treated as non-promotable regardless of its numerical value.

Secondary diagnostics are 95% CVaR, Sharpe, Sortino, turnover, profitable-fold fraction, parameter stability, state stability, and abstention quality.

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

Every promotion is manual. A challenger must carry immutable data, feature, instrument, model, allocator, risk, code, and dependency identifiers.

Rollback restores the previous complete compatible artifact set. Partial rollback of only the model or only the instrument is prohibited.

## 15. Production-readiness criteria

The system is not production-ready until:

- executable contracts validate every payload;
- historical and live decisions use the same decision function;
- the fixed five features reproduce exactly in shadow mode;
- instrument selection passes eligibility, cost, bootstrap, and robustness gates;
- the selected instrument remains stable across completed outer folds;
- the HMM passes multi-seed and state-alignment tests;
- experts have defensible standalone net behaviour;
- deterministic allocation beats cash and static baselines;
- risk controls pass boundary, property, stress, replay, idempotency, and fail-closed tests;
- paper fills validate the historical cost model;
- canary operation remains inside predefined incident and loss limits;
- every decision is reproducible;
- manual rollback is tested.
