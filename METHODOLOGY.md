# Methodology

This document defines the exact Production V1 strategy-signal and performance calculations. Implementations must reproduce these formulas and conventions.

## 1. Numerical conventions

```text
all log returns use natural logarithms
all volatility values are decimal, not percent
crypto annualisation uses 365 days and 8,760 hours
risk-free rate = 0 in Production V1 research metrics
feature_epsilon = configured positive constant
clamp(x, a, b) = min(max(x, a), b)
sign(x) = -1 when x < 0, 0 when x = 0, +1 when x > 0
```

All calculations use closed hourly bars derived from closed M1 buckets.

The same-asset perpetual close is the Production V1 analytical reference price, even when spot is the selected execution instrument. If this reference series is unavailable, the Production V1 feature and expert pipeline fails closed. There is no silent switch to another reference series.

## 2. Exponential moving average

For span `n`:

```text
alpha = 2 / (n + 1)
EMA_t = alpha * price_t + (1 - alpha) * EMA_(t-1)
```

The first EMA value is seeded with the simple mean of the first `n` observations. A signal is unavailable until the seed and complete required history exist.

## 3. Trend expert

### 3.1 Inputs

```text
hourly perpetual closes
EMA span 24 hours
EMA span 72 hours
72-hour linear regression of log price on integer time index
```

Default configuration:

```text
minimum_distance_fraction = 0.0025
strength_scale_fraction = 0.0200
```

### 3.2 Direction

```text
trend_distance = (EMA_24h - EMA_72h) / current_price

if abs(trend_distance) < minimum_distance_fraction:
    direction = 0
else:
    direction = sign(trend_distance)
```

### 3.3 Strength

```text
strength = clamp(
    (abs(trend_distance) - minimum_distance_fraction)
    / (strength_scale_fraction - minimum_distance_fraction),
    0,
    1
)
```

`strength_scale_fraction` must be greater than `minimum_distance_fraction`.

### 3.4 Confidence

Fit ordinary least squares to the last 72 hourly log prices:

```text
log_price_j = intercept + slope * j + residual_j
```

```text
confidence = clamp(regression_R_squared, 0, 1)
```

### 3.5 Holding time

```text
expected_holding_minutes = 4320
```

## 4. Momentum expert

### 4.1 Inputs

```text
12-hour log return
12 hourly log returns
4-hour perpetual buy-volume share
```

Default configuration:

```text
minimum_vol_scaled_return = 0.50
strength_scale = 2.00
flow_strength_scale = 0.25
```

### 4.2 Volatility-scaled return

```text
return_12h = ln(price_as_of / price_12h_before)
realized_scale_12h = sqrt(sum(last_12_hourly_log_returns^2))
vol_scaled_return = return_12h / max(realized_scale_12h, feature_epsilon)
```

### 4.3 Direction

```text
if abs(vol_scaled_return) < minimum_vol_scaled_return:
    direction = 0
else:
    direction = sign(vol_scaled_return)
```

### 4.4 Strength

```text
strength = clamp(
    (abs(vol_scaled_return) - minimum_vol_scaled_return)
    / (strength_scale - minimum_vol_scaled_return),
    0,
    1
)
```

`strength_scale` must be greater than `minimum_vol_scaled_return`.

### 4.5 Confidence

```text
flow_bias = 2 * buy_volume_share_4h - 1
directional_flow_confirmation = direction * flow_bias

if direction = 0:
    confidence = 0
else:
    confidence = clamp(directional_flow_confirmation / flow_strength_scale, 0, 1)
```

Momentum confidence is therefore zero when trade flow materially opposes the momentum direction.

### 4.6 Holding time

```text
expected_holding_minutes = 1440
```

## 5. Mean-reversion expert

### 5.1 Inputs

```text
last 24 hourly perpetual closes
```

Default configuration:

```text
entry_zscore = 1.00
strength_scale_zscore = 3.00
```

### 5.2 Price z-score

```text
price_mean_24h = mean(last_24_hourly_closes)
price_std_24h = sample_std(last_24_hourly_closes)
price_zscore_24h =
    (current_price - price_mean_24h)
    / max(price_std_24h, feature_epsilon)
```

### 5.3 Direction

```text
if abs(price_zscore_24h) < entry_zscore:
    direction = 0
else:
    direction = -sign(price_zscore_24h)
```

### 5.4 Strength and confidence

```text
strength = clamp(
    (abs(price_zscore_24h) - entry_zscore)
    / (strength_scale_zscore - entry_zscore),
    0,
    1
)

confidence = strength
```

`strength_scale_zscore` must be greater than `entry_zscore`.

### 5.5 Holding time

```text
expected_holding_minutes = 240
```

## 6. Expert data quality

An expert returns `FAIL` when any required input is missing, stale, non-finite, or lacks its complete lookback.

```text
FAIL → direction = 0, strength = 0, confidence = 0
```

No expert imputes missing trade volume, price, or return observations.

## 7. Standalone expert simulation

Each expert is evaluated as a standalone strategy before allocator evaluation.

The standalone target position fraction is:

```text
standalone_target_fraction = direction * strength * confidence
```

Instrument constraints apply:

```text
SPOT and standalone_target_fraction < 0 → target = 0
PERPETUAL → clamp target to [-1, 1]
SPOT → clamp target to [0, 1]
```

Entries, exits, costs, stops, take profit, and time stops use the same policies as the combined Production V1 pipeline.

## 8. Equity and return series

### 8.1 Equity

```text
equity_t = allocated_equity + cumulative_realized_pnl_t + unrealized_pnl_t
```

### 8.2 Hourly net return

```text
hourly_net_return_t = equity_t / equity_(t-1) - 1
```

The equity series includes fees, spread, slippage, funding, and realised stop/take-profit effects.

## 9. Performance metrics

### 9.1 Total net return

```text
total_net_return = ending_equity / starting_equity - 1
```

### 9.2 Annualised net return

For `n_hours > 0`:

```text
annualised_net_return =
    (ending_equity / starting_equity)^(8760 / n_hours) - 1
```

If ending equity is not positive, the candidate is rejected and annualised return is undefined.

### 9.3 Drawdown

```text
running_peak_t = max(equity_0, ..., equity_t)
drawdown_t = equity_t / running_peak_t - 1
maximum_drawdown_abs = abs(min(drawdown_t))
```

### 9.4 Net Calmar ratio

```text
net_calmar = annualised_net_return / maximum_drawdown_abs
```

If maximum drawdown is zero, Calmar is null. A non-positive annualised net return is non-promotable even if a ratio could be numerically produced.

### 9.5 Net Sharpe ratio

```text
net_sharpe =
    mean(hourly_net_returns)
    / sample_std(hourly_net_returns)
    * sqrt(8760)
```

Sharpe is null when hourly return standard deviation is zero.

### 9.6 Net Sortino ratio

```text
downside_returns_t = min(hourly_net_return_t, 0)
downside_deviation = sqrt(mean(downside_returns_t^2))

net_sortino =
    mean(hourly_net_returns)
    / downside_deviation
    * sqrt(8760)
```

Sortino is null when downside deviation is zero.

### 9.7 95% CVaR loss

Sort hourly net returns ascending. Let `q_05` be the empirical 5th percentile.

```text
cvar_95_loss_abs = abs(mean(hourly_net_return_t where hourly_net_return_t <= q_05))
```

If the tail set is empty, CVaR is null and the candidate is rejected.

### 9.8 Turnover

For every approved target transition:

```text
turnover_fraction_t =
    abs(approved_target_fraction_t - current_position_fraction_t)

annualised_turnover =
    sum(turnover_fraction_t) * 8760 / n_hours
```

### 9.9 Profitable-fold fraction

```text
profitable_fold_fraction =
    number_of_outer_folds_with_total_net_return_greater_than_zero
    / number_of_completed_outer_folds
```

### 9.10 PnL concentration

```text
fold_pnl_concentration =
    maximum_positive_fold_pnl
    / sum(all_positive_fold_pnl)
```

If there is no positive fold PnL, the candidate is rejected.

## 10. Cost scenarios

### 10.1 Base

Uses estimated historical or live-calibrated fees, spread, slippage, and funding.

### 10.2 Elevated

```text
spread = 1.5 × base spread
slippage = 1.5 × base slippage
fees = contractual fee schedule
funding = observed funding
```

### 10.3 Severe

```text
spread = 2.0 × base spread
slippage = 2.0 × base slippage
fees = taker fee for all fills
funding cost = adverse observed funding for held direction
```

A candidate fails cost stress when median outer-fold net return is not positive in both elevated and severe scenarios.

## 11. Paired block bootstrap

Instrument comparison uses paired hourly return differences on timestamps available for both candidates.

Default parameters:

```text
block_length_hours = 24
resamples = 10000
confidence_level = 95%
random_seed = versioned integer
```

Each resample draws 24-hour contiguous blocks with replacement until it reaches the original sample length. The same block indices are used for spot and perpetual, preserving pairing.

For every resample, compute the complete Calmar metric for each instrument and the difference:

```text
calmar_difference = perpetual_net_calmar - spot_net_calmar
```

The 2.5th and 97.5th empirical percentiles form the 95% interval.

Perpetual is materially superior only when:

```text
lower_interval_bound > 0
and
median_completed_outer_fold_calmar_difference >= 0.10
```

## 12. Parameter changes

All default thresholds in this document belong to a versioned strategy or selection configuration.

Changing any threshold, lookback, annualisation convention, metric definition, cost multiplier, or bootstrap setting requires:

- a new configuration version;
- complete outer-fold reruns;
- a new challenger artifact set;
- shadow, paper, and canary validation before promotion.
