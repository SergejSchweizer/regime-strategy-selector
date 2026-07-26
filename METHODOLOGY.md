# Methodology

This document defines the exact Production V1 calculations and the research methodology used to establish statistical and economic relevance.

```text
methodology_version = 2.0.0
research_design_version = 1.0.0
```

Implementations must reproduce these formulas, timing conventions and experimental controls.

## 1. Numerical conventions

```text
all logarithms are natural logarithms
all volatility values are decimal, not percent
all position fractions are relative to allocated equity
crypto annualisation uses 365 days and 8,760 hours
risk-free rate = 0 in research metrics
feature_epsilon = 0.000000000001
clamp(x, a, b) = min(max(x, a), b)
sign(x) = -1 when x < 0, 0 when x = 0, +1 when x > 0
```

All calculations use closed hourly BTC bars aggregated from closed M1 buckets. The analytical trading price is the configured linear BTC-perpetual close or reconciled mark price, depending on the calculation. BTC spot is reference information only.

## 2. Hourly aggregation

For every UTC hour:

```text
hourly_open = first M1 open
hourly_high = maximum M1 high
hourly_low = minimum M1 low
hourly_close = last M1 close
hourly_volume = sum M1 volume
hourly_buy_volume = sum M1 buy volume
```

An hour is incomplete when any required M1 interval is missing. Incomplete hours are not silently filled.

## 3. Regime features

### 3.1 BTC-perpetual return over 24 hours

```text
return_24h = ln(perpetual_close_t / perpetual_close_(t-24h))
```

### 3.2 Annualised realised volatility over 24 hours

Let `r_j` be the 24 hourly BTC-perpetual log returns ending at `t`:

```text
realized_volatility_24h = sqrt(365 * sum(r_j^2))
```

### 3.3 Funding z-score over 30 days

Use observed funding events, not hourly repetitions of a forward-filled value. Let `f_t` be the most recent valid funding observation and `F_30d` the valid observations in the preceding 30 days:

```text
funding_mean_30d = mean(F_30d)
funding_std_30d = sample_std(F_30d)
funding_zscore_30d =
    (f_t - funding_mean_30d)
    / max(funding_std_30d, feature_epsilon)
```

The feature is unavailable when the latest observation is too old or the minimum observation count is not met.

### 3.4 Open-interest change over 24 hours

```text
open_interest_change_24h =
    ln(open_interest_t / open_interest_(t-24h))
```

Both values must be positive, present and sufficiently fresh.

### 3.5 Perpetual buy-volume share over 4 hours

```text
buy_volume_share_4h =
    sum(perpetual_buy_volume over last 4 complete hours)
    / max(sum(perpetual_total_volume over last 4 complete hours), feature_epsilon)
```

A value outside `[0,1]` before clipping is a data-quality failure.

### 3.6 ATR over 24 hours

```text
true_range_t = max(
    high_t - low_t,
    abs(high_t - close_(t-1)),
    abs(low_t - close_(t-1))
)

atr_24h = mean(last 24 true_range values)
```

### 3.7 Spot/perpetual basis

```text
spot_perpetual_basis_fraction =
    perpetual_close_t / spot_close_t - 1
```

Basis is diagnostic and is not an HMM emission feature in Production V1.

### 3.8 Mark/index divergence

```text
mark_index_divergence_fraction =
    abs(mark_price_t / index_price_t - 1)
```

## 4. Robust scaling

For each HMM feature:

```text
scaled_value =
    (value - training_median)
    / max(training_IQR, feature_epsilon)
```

Median and IQR are fitted on the training fold only and frozen in the model artifact.

## 5. Exponential moving average

For span `n`:

```text
alpha = 2 / (n + 1)
EMA_t = alpha * price_t + (1 - alpha) * EMA_(t-1)
```

The first EMA is seeded with the simple mean of the first `n` complete observations.

## 6. Trend expert

Inputs are hourly BTC-perpetual closes, 24-hour and 72-hour EMAs, and a 72-hour ordinary least-squares regression of log price on an integer time index.

```text
minimum_distance_fraction = 0.0025
strength_scale_fraction = 0.0200

trend_distance = (EMA_24h - EMA_72h) / current_perpetual_price

if abs(trend_distance) < minimum_distance_fraction:
    direction = 0
else:
    direction = sign(trend_distance)

strength = clamp(
    (abs(trend_distance) - minimum_distance_fraction)
    / (strength_scale_fraction - minimum_distance_fraction),
    0,
    1
)

log_price_j = intercept + slope * j + residual_j
confidence = clamp(regression_R_squared, 0, 1)
expected_holding_minutes = 4320
```

## 7. Momentum expert

Inputs are the 12-hour BTC-perpetual log return, the last 12 hourly log returns and four-hour perpetual buy-volume share.

```text
minimum_vol_scaled_return = 0.50
strength_scale = 2.00
flow_strength_scale = 0.25

return_12h = ln(price_t / price_(t-12h))
realized_scale_12h = sqrt(sum(last 12 hourly log returns^2))
vol_scaled_return = return_12h / max(realized_scale_12h, feature_epsilon)

if abs(vol_scaled_return) < minimum_vol_scaled_return:
    direction = 0
else:
    direction = sign(vol_scaled_return)

strength = clamp(
    (abs(vol_scaled_return) - minimum_vol_scaled_return)
    / (strength_scale - minimum_vol_scaled_return),
    0,
    1
)

flow_bias = 2 * buy_volume_share_4h - 1
directional_flow_confirmation = direction * flow_bias

if direction = 0:
    confidence = 0
else:
    confidence = clamp(
        directional_flow_confirmation / flow_strength_scale,
        0,
        1
    )

expected_holding_minutes = 1440
```

## 8. Mean-reversion expert

Inputs are the last 24 hourly BTC-perpetual closes.

```text
entry_zscore = 1.00
strength_scale_zscore = 3.00

price_mean_24h = mean(last 24 hourly closes)
price_std_24h = sample_std(last 24 hourly closes)
price_zscore_24h =
    (current_price - price_mean_24h)
    / max(price_std_24h, feature_epsilon)

if abs(price_zscore_24h) < entry_zscore:
    direction = 0
else:
    direction = -sign(price_zscore_24h)

strength = clamp(
    (abs(price_zscore_24h) - entry_zscore)
    / (strength_scale_zscore - entry_zscore),
    0,
    1
)

confidence = strength
expected_holding_minutes = 240
```

An expert returns `FAIL` when an input is missing, stale, non-finite or lacks its complete lookback:

```text
FAIL -> direction = 0, strength = 0, confidence = 0
```

## 9. Regime affinity matrix

For persistent state `r` and strategy `s`, using inner-training observations only:

```text
weighted_mean_return_(r,s) =
    sum(state_probability_(t,r) * strategy_net_return_(t,s))
    / max(sum(state_probability_(t,r)), affinity_epsilon)

weighted_downside_(r,s) =
    sqrt(
        sum(state_probability_(t,r) * min(strategy_net_return_(t,s), 0)^2)
        / max(sum(state_probability_(t,r)), affinity_epsilon)
    )

raw_affinity_(r,s) = max(
    0,
    weighted_mean_return_(r,s)
    / max(weighted_downside_(r,s), affinity_epsilon)
)
```

Each row is clipped and scaled so:

```text
0 <= affinity_(r,s) <= 1
sum_s affinity_(r,s) <= 1 - minimum_cash_fraction
```

## 10. Deterministic allocator

### 10.1 Expert scores

```text
regime_affinity_s = sum_r(current_probability_r * affinity_(r,s))
expert_score_s = regime_affinity_s * strength_s * confidence_s
signed_score_s = expert_score_s * direction_s
```

### 10.2 Direction evidence

```text
positive_evidence = sum(max(signed_score_s, 0))
negative_evidence = sum(abs(min(signed_score_s, 0)))
```

```text
if max(positive_evidence, negative_evidence) < minimum_consensus_evidence:
    consensus_direction = FLAT
else if min(positive_evidence, negative_evidence) > 0
        and max(positive_evidence, negative_evidence)
            / min(positive_evidence, negative_evidence)
            < minimum_direction_dominance:
    consensus_direction = FLAT
else if positive_evidence > negative_evidence:
    consensus_direction = LONG
else:
    consensus_direction = SHORT
```

### 10.3 Contributions and cash

```text
if strategy direction agrees with consensus direction:
    active_score_s = expert_score_s
else:
    active_score_s = 0

strategy_contribution_weight_s = active_score_s
cash_weight = 1 - sum(active_score_s)
```

There is no upward renormalisation. `FLAT` implies zero strategy contributions and cash equal to one.

### 10.4 Regime certainty and volatility scaling

```text
regime_certainty =
    clamp((maximum_probability - 1/3) / (2/3), 0, 1)

volatility_multiplier =
    clamp(
        target_volatility_annual
        / max(realized_volatility_24h, volatility_floor),
        0,
        1
    )

global_risk_multiplier = regime_certainty * volatility_multiplier

preliminary_target_position_fraction =
    direction_sign
    * (1 - cash_weight)
    * global_risk_multiplier
```

Clamp the result to `[-1,1]`.

## 11. Exit profiles and risk-based sizing

Production defaults are starting configurations, not evidence of optimality:

| Dominant expert | Stop | Take profit | Maximum holding time |
|---|---:|---:|---:|
| Mean reversion | 1.0 x ATR_24h | 1.5 x ATR_24h | 4 hours |
| Momentum | 1.5 x ATR_24h | 2.5 x ATR_24h | 24 hours |
| Trend | 2.0 x ATR_24h | 4.0 x ATR_24h | 72 hours |

```text
stop_distance_price = stop_atr_multiple * atr_24h
stop_fraction = stop_distance_price / entry_reference_price

risk_position_cap =
    risk_per_trade_fraction
    / max(stop_fraction, feature_epsilon)

absolute_sizing_cap = min(
    abs(preliminary_target_position_fraction),
    risk_position_cap,
    max_abs_position_fraction,
    max_margin_fraction
)

risk_sized_target_fraction =
    sign(preliminary_target_position_fraction)
    * absolute_sizing_cap
```

The Risk Engine may reduce the target further but may not increase it.

## 12. Linear BTC-perpetual PnL and costs

```text
target_notional = target_position_fraction * allocated_equity
contract_quantity = target_notional / (reference_price * contract_multiplier)
```

Execution rounds quantity towards zero.

For signed quantity `q`, multiplier `m`, entry price `P_0` and exit or mark price `P_t`:

```text
pnl = q * m * (P_t - P_0)
```

For executed notional `N`:

```text
fee_cost = abs(N) * fee_rate
spread_cost = abs(N) * half_spread_fraction
slippage_cost = abs(N) * slippage_fraction
```

Entry and exit costs are charged separately.

At each funding event:

```text
funding_cashflow = -signed_position_notional * funding_rate
```

A positive funding rate charges longs and credits shorts.

Liquidation buffer:

```text
long:  (mark_price - liquidation_price) / mark_price
short: (liquidation_price - mark_price) / mark_price
```

A non-positive or unavailable buffer while a position is open is a critical risk failure. Liquidation is not a normal exit mechanism.

## 13. Historical execution conventions

- A decision at `as_of` first executes at the open of the first complete M1 bucket with `open_time > as_of`, including adverse spread, slippage and fees.
- If stop and take profit are both touched in one M1 bar and their order is unknown, the stop is assumed first.
- A gap through a stop fills at the first simulated tradable price plus adverse slippage.
- A time stop exits at the first eligible M1 open after expiry, including exit costs.

## 14. Standalone expert simulation

Each expert is evaluated independently:

```text
standalone_target_fraction =
    clamp(direction * strength * confidence, -1, 1)
```

The same sizing, costs, funding and exit conventions apply as in the combined system.

## 15. Equity and performance metrics

```text
equity_t = allocated_equity + cumulative_realized_pnl_t + unrealized_pnl_t
hourly_net_return_t = equity_t / equity_(t-1) - 1

total_net_return = ending_equity / starting_equity - 1

annualized_net_return =
    (ending_equity / starting_equity)^(8760 / n_hours) - 1

running_peak_t = max(equity_0, ..., equity_t)
drawdown_t = equity_t / running_peak_t - 1
maximum_drawdown_fraction = abs(min(drawdown_t))

net_calmar = annualized_net_return / maximum_drawdown_fraction

net_sharpe =
    mean(hourly_net_returns)
    / sample_std(hourly_net_returns)
    * sqrt(8760)

downside_returns_t = min(hourly_net_return_t, 0)
downside_deviation = sqrt(mean(downside_returns_t^2))
net_sortino =
    mean(hourly_net_returns)
    / downside_deviation
    * sqrt(8760)
```

Let `q_05` be the empirical fifth percentile:

```text
cvar_95_loss_abs =
    abs(mean(hourly_net_return_t where hourly_net_return_t <= q_05))
```

```text
turnover_fraction_t =
    abs(approved_target_fraction_t - current_position_fraction_t)

annualized_turnover =
    sum(turnover_fraction_t) * 8760 / n_hours

profitable_fold_fraction =
    outer folds with positive net return
    / completed outer folds

fold_pnl_concentration =
    maximum positive fold PnL
    / sum(all positive fold PnL)
```

Calmar is null when maximum drawdown is zero. Non-positive annualised return is non-promotable.

## 16. Cost stress

### BASE

Use estimated or paper-calibrated fees, spread, slippage and observed funding.

### ELEVATED

```text
spread = 1.5 * base spread
slippage = 1.5 * base slippage
fees = contractual schedule
funding = observed funding
```

### SEVERE

```text
spread = 2.0 * base spread
slippage = 2.0 * base slippage
fees = taker fee for every fill
funding = adverse observed funding for the held direction
```

A candidate fails cost stress when median outer-fold net return is not positive in both ELEVATED and SEVERE scenarios.

## 17. Required benchmarks

```text
cash
BTC spot buy-and-hold information benchmark
unlevered BTC-perpetual long-only buy-and-hold
standalone trend
standalone momentum
standalone mean reversion
equal-weight experts without regime context
static expert mix without regime context
```

Spot benchmark performance never makes spot tradable.

## 18. Experimental identification principle

A performance improvement may be attributed only to the component that differs between candidate and baseline. A regime model must not appear superior merely because its strategy experts use different stop-loss, take-profit or time-stop rules.

The project tests five distinct hypotheses:

1. each standalone expert has economic value after complete costs;
2. regime probabilities add value with unchanged experts and exits;
3. discrete regime-dependent exits add value beyond fixed strategy exits;
4. L2 improves entry, liquidity and execution decisions;
5. a learned allocator adds value beyond the deterministic allocator.

Each hypothesis requires its own baseline, experiment and promotion gates.

## 19. Nested walk-forward design

Each outer fold contains an inner chronological selection process:

```text
Outer Training Window
    |-- inner train/validation folds
    |-- model and hyperparameter selection
    |-- persistent state mapping
    |-- exit-profile selection
    `-- freeze every selected artifact

Outer Test Window
    `-- one unchanged evaluation
```

The outer test is never used for feature selection, model family, number of states, state mapping, exit optimisation, affinity estimation, risk settings, cost calibration, hyperparameter tuning or promotion thresholds.

Default schedule:

```text
outer training window = previous 3 years
outer test interval = next 3 months
outer step = 3 months
inner validation block = 3 months
retraining frequency = quarterly
purge = longest overlapping target interval
embargo = 1 day
```

Only point-in-time data and filtered probabilities are valid.

## 20. Phase 0: reproducible baseline

Deliverables:

- fixed BTC-perpetual and spot-reference specifications;
- fixed feature and output contracts;
- deterministic expert formulas and Risk Engine;
- reproducible cost model and purged/embargoed splits;
- MLflow Tracking Server, backend and artifact store;
- golden prediction tests;
- initial registered champion bundle.

Baseline systems include cash, spot benchmark, perpetual long-only, each standalone expert, equal expert mix and a no-regime deterministic allocator.

## 21. Phase 1: standalone exit optimisation

Each strategy must establish independent economic evidence before regime weighting is considered. A failing expert is disabled.

For strategy `s`:

```text
exit_parameters_s = (
    stop_atr_multiple,
    take_profit_atr_multiple,
    time_stop_hours
)
```

Starting search spaces:

```text
Trend
stop   in {1.5, 2.0, 2.5, 3.0}
target in {2.5, 3.0, 4.0, 5.0}
time    in {24, 48, 72, 120} hours

Momentum
stop   in {1.0, 1.5, 2.0}
target in {1.5, 2.0, 2.5, 3.0}
time    in {4, 8, 12, 24} hours

Mean reversion
stop   in {0.5, 0.75, 1.0, 1.25}
target in {0.5, 1.0, 1.5, 2.0}
time    in {1, 2, 4, 8} hours
```

Search spaces are versioned. Extensions such as trailing stops or break-even rules require a new exit-contract and experiment-design version.

The selection objective is not maximum gross return. Maximise median inner-validation net Calmar subject to hard gates for drawdown, CVaR, profitable-fold fraction, minimum trade count, PnL concentration, cost stress and parameter stability.

Select a robust plateau rather than a point optimum. Prefer a simple configuration with:

```text
score >= 95% of the best inner-validation score
```

and stable neighbouring configurations. Record:

```text
neighbourhood_score_mean
neighbourhood_score_std
neighbourhood_worst_score
parameter_sensitivity_rank
```

The resulting strategy-specific exit profiles are frozen before outer testing.

## 22. Phase 2: pure regime incremental value

Compare systems using identical experts, exit profiles, risk configuration, costs and walk-forward splits:

```text
System B: No-Regime Baseline
- static strategy weights or time-invariant average affinity

System C: Regime Candidate
- dynamic weighting through the regime probability vector
```

```text
regime_incremental_value =
    Performance(System C) - Performance(System B)
```

Required controls include a one-state model, uniform probabilities, static average affinity, time-shifted probabilities, block-permuted probabilities and a Markov placebo with similar state duration.

Statistical gates include superior out-of-sample predictive log likelihood, at least 16 stable converged seeds, non-degenerate covariance, minimum state occupancy, plausible duration, valid alignment, stable signatures and valid probability/entropy behaviour.

Starting economic gates:

```text
candidate_median_outer_fold_net_calmar
>= champion_median_outer_fold_net_calmar + 0.10

paired_bootstrap_calmar_difference_ci_lower > 0
candidate_outer_fold_win_fraction >= 0.60
candidate_cvar_95_loss <= champion_cvar_95_loss * 1.05
candidate_max_drawdown <= champion_max_drawdown + 0.02
maximum_positive_pnl_fold_contribution <= 0.50
```

ELEVATED and SEVERE cost stress must pass. A regime model is economically relevant only when System C robustly exceeds System B.

## 23. Phase 3: alternative regime models

Candidate ladder:

```text
Champion baseline
- diagonal Gaussian HMM

Challengers
- full-covariance Gaussian HMM
- duration-aware HMM or HSMM
- Student-t HMM
- Markov-switching autoregression
```

Every model exposes `RegimePrediction.v1` with identical persistent-state order, field names and probability invariants. The promotion unit is the complete compatible bundle, not the raw model alone.

## 24. Phase 4: discrete regime-dependent exits

Only after the pure regime test passes may the project compare:

```text
System C: regime weighting + fixed strategy-specific exits
System D: regime weighting + discrete regime-dependent exits

regime_exit_incremental_value =
    Performance(System D) - Performance(System C)
```

Free continuous stop and target values per `state x strategy` are prohibited initially. Select from a small versioned library:

```text
MR_TIGHT
MR_NORMAL
MOMENTUM_NORMAL
TREND_DEFENSIVE
TREND_NORMAL
NO_TRADE
```

This limits degrees of freedom and improves reproducibility, governance and auditability.

## 25. Phase 5: L2 microstructure overlay

L2 is initially a separate short-horizon overlay rather than an emission input of the persistent core regime model.

```text
MicrostructureSignal.v1
- order_book_pressure
- liquidity_stress
- transition_risk
- expected_slippage_bps
- spread_stress
- depth_fragility
- data_quality_status
```

The first production-adjacent version may reduce exposure, delay entry, increase expected execution cost, trigger `NO_NEW_ENTRY` and identify liquidity stress. It may not independently increase exposure.

Evaluate:

```text
A = long history without L2
B = common window without L2
C = same common window with L2
```

The isolated L2 value is first `C - B`; only then test whether C also robustly exceeds A.

## 26. Phase 6: learned allocator

Research order:

```text
1. deterministic allocator
2. regularised supervised allocator
3. contextual bandit
4. reinforcement learning
```

A learned policy initially chooses only strategy mix, exposure bucket, discrete exit profile and cash/no-trade. The deterministic Risk Engine remains outside the learned policy and has final authority.

## 27. Experiment matrix

| System | Regime | Exit rules | Purpose |
|---|---|---|---|
| A | no | standalone optimised | strategy evidence |
| B | no | frozen | no-regime baseline |
| C | yes | identical to B | pure regime value |
| D | yes | regime-dependent discrete | additional exit value |
| E | yes | D plus L2 overlay | microstructure value |
| F | yes | E plus learned allocator | policy value |

```text
C - B = value of regime weighting
D - C = value of regime-dependent exits
E - D = value of L2 overlay
F - E = value of learned allocation
```

## 28. Change control

Changing a formula, threshold, lookback, search space, annualisation convention, cost multiplier, funding treatment, liquidation rule, metric definition or experimental comparison requires:

- a new methodology, configuration or experiment-design version;
- complete outer-fold reruns;
- a new compatible deployment bundle;
- shadow, paper and canary validation before promotion.