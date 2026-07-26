# Methodology

This document defines the exact Production V1 calculations.

```text
methodology_version = 2.0.0
```

Implementations must reproduce these formulas and conventions.

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

All calculations use closed hourly BTC bars aggregated from closed M1 buckets.

The Production V1 analytical price is the configured linear BTC-perpetual close or reconciled mark price, depending on the calculation. BTC spot is reference information only.

## 2. Hourly aggregation

For every UTC hour, aggregate complete M1 bars only:

```text
hourly_open = first M1 open
hourly_high = maximum M1 high
hourly_low = minimum M1 low
hourly_close = last M1 close
hourly_volume = sum M1 volume
hourly_buy_volume = sum M1 buy volume
```

An hour is incomplete when any required M1 interval is missing. Incomplete hours are not silently filled.

## 3. Production V1 feature formulas

### 3.1 BTC-perpetual return over 24 hours

```text
return_24h = ln(perpetual_close_t / perpetual_close_(t-24h))
```

### 3.2 Annualised realized volatility over 24 hours

Let `r_j` be the 24 hourly BTC-perpetual log returns ending at `t`:

```text
realized_volatility_24h = sqrt(365 × sum(r_j^2))
```

This is an annualised decimal volatility.

### 3.3 Funding z-score over 30 days

Use actual observed funding events, not hourly repetitions of a forward-filled funding value.

Let `f_t` be the most recent observed funding rate and let `F_30d` be all valid funding observations in the preceding 30 days:

```text
funding_mean_30d = mean(F_30d)
funding_std_30d = sample_std(F_30d)
funding_zscore_30d =
    (f_t - funding_mean_30d)
    / max(funding_std_30d, feature_epsilon)
```

The feature is unavailable when the latest funding observation is stale beyond the configured limit or fewer than the configured minimum observations exist.

### 3.4 Open-interest change over 24 hours

```text
open_interest_change_24h =
    ln(open_interest_t / open_interest_(t-24h))
```

The feature is unavailable when either value is non-positive, missing or stale beyond contract limits.

### 3.5 Perpetual buy-volume share over 4 hours

```text
buy_volume_share_4h =
    sum(perpetual_buy_volume over last 4 complete hours)
    / max(sum(perpetual_total_volume over last 4 complete hours), feature_epsilon)
```

The result is clipped to `[0,1]` only after source validation. A value outside `[0,1]` before clipping is a data-quality failure.

### 3.6 ATR over 24 hours

For each hourly bar:

```text
true_range_t = max(
    high_t - low_t,
    abs(high_t - close_(t-1)),
    abs(low_t - close_(t-1))
)
```

Production V1 uses the simple 24-hour mean:

```text
atr_24h = mean(last 24 true_range values)
```

### 3.7 BTC spot/perpetual basis

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

This is an operational and risk diagnostic.

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
EMA_t = alpha × price_t + (1 - alpha) × EMA_(t-1)
```

The first EMA value is seeded with the simple mean of the first `n` complete observations.

## 6. Trend expert

### 6.1 Inputs

```text
hourly BTC-perpetual closes
EMA span = 24 hours
EMA span = 72 hours
72-hour linear regression of log price on integer time index
```

Defaults:

```text
minimum_distance_fraction = 0.0025
strength_scale_fraction = 0.0200
```

### 6.2 Direction

```text
trend_distance = (EMA_24h - EMA_72h) / current_perpetual_price

if abs(trend_distance) < minimum_distance_fraction:
    direction = 0
else:
    direction = sign(trend_distance)
```

### 6.3 Strength

```text
strength = clamp(
    (abs(trend_distance) - minimum_distance_fraction)
    / (strength_scale_fraction - minimum_distance_fraction),
    0,
    1
)
```

### 6.4 Confidence

Fit ordinary least squares to the last 72 hourly log prices:

```text
log_price_j = intercept + slope × j + residual_j
confidence = clamp(regression_R_squared, 0, 1)
```

### 6.5 Holding time

```text
expected_holding_minutes = 4320
```

## 7. Momentum expert

### 7.1 Inputs

```text
12-hour BTC-perpetual log return
12 hourly BTC-perpetual log returns
4-hour perpetual buy-volume share
```

Defaults:

```text
minimum_vol_scaled_return = 0.50
strength_scale = 2.00
flow_strength_scale = 0.25
```

### 7.2 Volatility-scaled return

```text
return_12h = ln(price_t / price_(t-12h))
realized_scale_12h = sqrt(sum(last 12 hourly log returns^2))
vol_scaled_return = return_12h / max(realized_scale_12h, feature_epsilon)
```

### 7.3 Direction

```text
if abs(vol_scaled_return) < minimum_vol_scaled_return:
    direction = 0
else:
    direction = sign(vol_scaled_return)
```

### 7.4 Strength

```text
strength = clamp(
    (abs(vol_scaled_return) - minimum_vol_scaled_return)
    / (strength_scale - minimum_vol_scaled_return),
    0,
    1
)
```

### 7.5 Confidence

```text
flow_bias = 2 × buy_volume_share_4h - 1
directional_flow_confirmation = direction × flow_bias

if direction = 0:
    confidence = 0
else:
    confidence = clamp(
        directional_flow_confirmation / flow_strength_scale,
        0,
        1
    )
```

### 7.6 Holding time

```text
expected_holding_minutes = 1440
```

## 8. Mean-reversion expert

### 8.1 Inputs

```text
last 24 hourly BTC-perpetual closes
```

Defaults:

```text
entry_zscore = 1.00
strength_scale_zscore = 3.00
```

### 8.2 Price z-score

```text
price_mean_24h = mean(last 24 hourly closes)
price_std_24h = sample_std(last 24 hourly closes)
price_zscore_24h =
    (current_price - price_mean_24h)
    / max(price_std_24h, feature_epsilon)
```

### 8.3 Direction

```text
if abs(price_zscore_24h) < entry_zscore:
    direction = 0
else:
    direction = -sign(price_zscore_24h)
```

### 8.4 Strength and confidence

```text
strength = clamp(
    (abs(price_zscore_24h) - entry_zscore)
    / (strength_scale_zscore - entry_zscore),
    0,
    1
)

confidence = strength
```

### 8.5 Holding time

```text
expected_holding_minutes = 240
```

## 9. Expert data quality

An expert returns `FAIL` when any required input is missing, stale, non-finite or lacks its complete lookback.

```text
FAIL → direction = 0, strength = 0, confidence = 0
```

No expert imputes missing BTC price, trade-volume or return observations.

## 10. Regime affinity matrix

For state `r` and strategy `s`, using inner-training observations only:

```text
weighted_mean_return_(r,s) =
    sum(state_probability_(t,r) × strategy_net_return_(t,s))
    / max(sum(state_probability_(t,r)), affinity_epsilon)

weighted_downside_(r,s) =
    sqrt(
        sum(state_probability_(t,r) × min(strategy_net_return_(t,s), 0)^2)
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

## 11. Deterministic allocator

### 11.1 Regime affinity and expert score

```text
regime_affinity_s = sum_r(current_probability_r × affinity_(r,s))
expert_score_s = regime_affinity_s × strength_s × confidence_s
signed_score_s = expert_score_s × direction_s
```

### 11.2 Direction evidence

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

BTC perpetual supports long and short; no directional conversion is applied.

### 11.3 Contribution weights and cash

```text
if strategy direction agrees with consensus direction:
    active_score_s = expert_score_s
else:
    active_score_s = 0

strategy_contribution_weight_s = active_score_s
cash_weight = 1 - sum(active_score_s)
```

No post-hoc upward renormalization is allowed. If consensus is `FLAT`, all strategy contributions are zero and cash is one.

### 11.4 Regime certainty

```text
regime_certainty =
    clamp((maximum_probability - 1/3) / (2/3), 0, 1)
```

### 11.5 Volatility multiplier

```text
volatility_multiplier =
    clamp(
        target_volatility_annual
        / max(realized_volatility_24h, volatility_floor),
        0,
        1
    )
```

### 11.6 Preliminary target

```text
global_risk_multiplier = regime_certainty × volatility_multiplier

preliminary_target_position_fraction =
    direction_sign
    × (1 - cash_weight)
    × global_risk_multiplier
```

Clamp the result to `[-1, 1]`.

## 12. Exit profiles and risk-based sizing

### 12.1 Exit distances

| Dominant expert | Stop | Take profit | Maximum holding time |
|---|---:|---:|---:|
| Mean reversion | 1.0 × ATR_24h | 1.5 × ATR_24h | 4 hours |
| Momentum | 1.5 × ATR_24h | 2.5 × ATR_24h | 24 hours |
| Trend | 2.0 × ATR_24h | 4.0 × ATR_24h | 72 hours |

### 12.2 Stop fraction

```text
stop_distance_price = stop_atr_multiple × atr_24h
stop_fraction = stop_distance_price / entry_reference_price
```

### 12.3 Risk position cap

```text
risk_position_cap =
    risk_per_trade_fraction
    / max(stop_fraction, feature_epsilon)
```

### 12.4 Approved sizing envelope

Before other risk gates:

```text
absolute_sizing_cap = min(
    abs(preliminary_target_position_fraction),
    risk_position_cap,
    max_abs_position_fraction,
    max_margin_fraction
)

risk_sized_target_fraction =
    sign(preliminary_target_position_fraction)
    × absolute_sizing_cap
```

The Risk Engine may reduce this further but may not increase it.

## 13. Linear BTC-perpetual PnL and costs

### 13.1 Notional and quantity

```text
target_notional = target_position_fraction × allocated_equity
contract_quantity = target_notional / (reference_price × contract_multiplier)
```

Execution rounds quantity toward zero to the exchange quantity step.

### 13.2 Linear PnL

For signed contract quantity `q`, multiplier `m`, entry price `P_0` and exit or mark price `P_t`:

```text
pnl = q × m × (P_t - P_0)
```

Positive `q` is long; negative `q` is short.

### 13.3 Trading costs

For executed notional `N`:

```text
fee_cost = abs(N) × fee_rate
spread_cost = abs(N) × half_spread_fraction
slippage_cost = abs(N) × slippage_fraction
```

Entry and exit costs are charged separately.

### 13.4 Funding

At each funding event:

```text
funding_cashflow = -signed_position_notional × funding_rate
```

A positive funding rate therefore charges longs and credits shorts. Funding is applied only when the position is open at the exchange-defined funding timestamp.

### 13.5 Liquidation buffer

For a long position:

```text
liquidation_buffer_fraction =
    (mark_price - liquidation_price) / mark_price
```

For a short position:

```text
liquidation_buffer_fraction =
    (liquidation_price - mark_price) / mark_price
```

A non-positive or unavailable buffer while a position is open is a critical risk failure. Production V1 does not treat liquidation as a normal exit mechanism.

## 14. Historical execution conventions

### 14.1 Entry

A decision at `as_of` may first execute at the open of the first complete M1 bucket with `open_time > as_of`, plus adverse spread, slippage and fees.

### 14.2 Stop and take profit

If both stop and take profit are touched in one M1 bar and intrabar order is unknown, the stop is assumed first.

A gap through a stop fills at the first simulated tradable price plus adverse slippage.

### 14.3 Time stop

At maximum holding time, the position exits at the first eligible M1 open after expiry, including exit costs.

## 15. Standalone expert simulation

Each expert is evaluated as a standalone BTC-perpetual strategy:

```text
standalone_target_fraction =
    clamp(direction × strength × confidence, -1, 1)
```

The same risk sizing, costs, stop, take-profit, funding and time-stop conventions apply as in the combined pipeline.

## 16. Equity and return series

```text
equity_t = allocated_equity + cumulative_realized_pnl_t + unrealized_pnl_t
hourly_net_return_t = equity_t / equity_(t-1) - 1
```

Equity includes fees, spread, slippage, funding and exit effects.

## 17. Performance metrics

### 17.1 Total net return

```text
total_net_return = ending_equity / starting_equity - 1
```

### 17.2 Annualized net return

```text
annualized_net_return =
    (ending_equity / starting_equity)^(8760 / n_hours) - 1
```

Ending equity must be positive.

### 17.3 Drawdown

```text
running_peak_t = max(equity_0, ..., equity_t)
drawdown_t = equity_t / running_peak_t - 1
maximum_drawdown_fraction = abs(min(drawdown_t))
```

### 17.4 Net Calmar

```text
net_calmar = annualized_net_return / maximum_drawdown_fraction
```

Calmar is null when maximum drawdown is zero. Non-positive annualized return is non-promotable.

### 17.5 Net Sharpe

```text
net_sharpe =
    mean(hourly_net_returns)
    / sample_std(hourly_net_returns)
    × sqrt(8760)
```

### 17.6 Net Sortino

```text
downside_returns_t = min(hourly_net_return_t, 0)
downside_deviation = sqrt(mean(downside_returns_t^2))
net_sortino =
    mean(hourly_net_returns)
    / downside_deviation
    × sqrt(8760)
```

### 17.7 95% CVaR loss

Let `q_05` be the empirical 5th percentile of hourly net returns:

```text
cvar_95_loss_abs =
    abs(mean(hourly_net_return_t where hourly_net_return_t <= q_05))
```

### 17.8 Turnover

```text
turnover_fraction_t =
    abs(approved_target_fraction_t - current_position_fraction_t)

annualized_turnover =
    sum(turnover_fraction_t) × 8760 / n_hours
```

### 17.9 Profitable-fold fraction

```text
profitable_fold_fraction =
    number of outer folds with positive total net return
    / number of completed outer folds
```

### 17.10 PnL concentration

```text
fold_pnl_concentration =
    maximum positive fold PnL
    / sum(all positive fold PnL)
```

## 18. Cost and funding stress

### 18.1 Base

Use estimated or paper-calibrated fees, spread, slippage and observed funding.

### 18.2 Elevated

```text
spread = 1.5 × base spread
slippage = 1.5 × base slippage
fees = contractual schedule
funding = observed funding
```

### 18.3 Severe

```text
spread = 2.0 × base spread
slippage = 2.0 × base slippage
fees = taker fee for every fill
funding = adverse observed funding for the held direction
```

A candidate fails cost stress when median outer-fold net return is not positive in both elevated and severe scenarios.

## 19. Required benchmarks

Evaluate the Production V1 pipeline against:

```text
cash
BTC spot buy-and-hold information benchmark
unlevered BTC-perpetual long-only buy-and-hold
standalone trend expert
standalone momentum expert
standalone mean-reversion expert
equal-weight experts without regime context
static expert mix without regime context
```

BTC spot benchmark performance does not make spot tradable.

## 20. Parameter changes

Changing any formula, threshold, lookback, annualization convention, cost multiplier, funding convention, liquidation-buffer rule or metric definition requires:

- a new methodology or configuration version;
- complete outer-fold reruns;
- a new compatible artifact set;
- shadow, paper and canary validation before promotion.
