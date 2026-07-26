# Regime Strategy Selector

A probabilistic, regime-aware trading system for BTC and ETH that separates market-state estimation, strategy allocation, and hard risk control.

The project consumes canonical Gold datasets produced by [`crypto-history-loader`](https://github.com/SergejSchweizer/crypto-history-loader). The source dataset contract is defined in its `DATASETS.md`. This repository does not redefine those source schemas. It defines the model-facing contracts derived from them.

The system contains three strictly separated modules:

1. **Regime Estimator** — learned model that estimates probabilities for three latent market regimes.
2. **Strategy Allocator** — learned model that combines regime probabilities with trend, momentum, and mean-reversion experts and proposes weights, position sizes, and TP/SL profiles.
3. **Deterministic Risk Engine** — non-learned control layer that validates, clips, or rejects the proposal before any order can be created.

```text
crypto-history-loader Gold datasets
                │
                ▼
        Point-in-time adapter
                │
                ▼
┌─────────────────────────────────────┐
│ Module 1: Regime Estimator          │
│ current and forward probabilities   │
└──────────────────┬──────────────────┘
                   │ RegimePrediction
                   ▼
        Trend / Momentum / Reversion
              strategy experts
                   │ ExpertSignal[]
                   ▼
┌─────────────────────────────────────┐
│ Module 2: Strategy Allocator        │
│ weights, sizing, TP/SL proposal     │
└──────────────────┬──────────────────┘
                   │ AllocationProposal
                   ▼
┌─────────────────────────────────────┐
│ Module 3: Deterministic Risk Engine │
│ limits, quality gates, kill switch  │
└──────────────────┬──────────────────┘
                   │ RiskDecision
                   ▼
             Approved order intents
```

---

# 1. Upstream dataset contracts

## 1.1 Canonical historical core

The initial system uses:

```text
gold.market.history_full.m1
```

Grain:

```text
one row per timestamp_m1, exchange, symbol
```

Primary keys:

| Variable | Type | Meaning |
|---|---|---|
| `timestamp_m1` | UTC timestamp | Closed one-minute bucket |
| `exchange` | string | Normalized exchange identifier |
| `symbol` | string | Normalized base asset, initially `BTC` or `ETH` |

Historical source variables available directly from `gold.market.history_full.m1`:

### Spot OHLCV

```text
spot_ohlcv_open_price
spot_ohlcv_high_price
spot_ohlcv_low_price
spot_ohlcv_close_price
spot_ohlcv_volume
spot_ohlcv_quote_volume
spot_ohlcv_trade_count
```

### Perpetual OHLCV

```text
perp_open_price
perp_high_price
perp_low_price
perp_close_price
perp_volume
perp_quote_volume
perp_trade_count
```

### Funding state

```text
funding_rate_last_known
funding_observed_at
minutes_since_funding
is_funding_observation_minute
funding_data_available
```

### Open-interest state

```text
open_interest_open_interest
open_interest_is_observed
open_interest_is_ffill
minutes_since_open_interest_observation
open_interest_observation_lag_sec
open_interest_source_timestamp
```

### Perpetual trade-flow aggregates

```text
perps_trades_open_price
perps_trades_high_price
perps_trades_low_price
perps_trades_close_price
perps_trades_volume
perps_trades_quote_volume
perps_trades_trade_count
perps_trades_buy_volume
perps_trades_sell_volume
perps_trades_buy_trade_count
perps_trades_sell_trade_count
perps_trades_buy_volume_share
```

### Option trade-flow aggregates

```text
options_trades_open_price
options_trades_high_price
options_trades_low_price
options_trades_close_price
options_trades_volume
options_trades_quote_volume
options_trades_trade_count
options_trades_buy_volume
options_trades_sell_volume
options_trades_buy_trade_count
options_trades_sell_trade_count
options_trades_buy_volume_share
```

`gold.market.history_full.m1` intentionally excludes IV/RV, L2, strategy features, targets, and labels. Missing source values remain null. Event-driven trade fields must never be forward-filled.

## 1.2 Derived trailing feature contract

The project converts the raw M1 history into a versioned point-in-time feature frame:

```text
MarketFeatureFrame.v1
```

The first implementation derives trailing features locally from `gold.market.history_full.m1`. Once `gold.market.regime_features.m1` is physically materialized and validated, the adapter may consume its equivalent canonical fields instead.

Candidate derived families include:

| Family | Examples derived from historical variables |
|---|---|
| Returns | log returns over 5m, 15m, 1h, 4h, 1d |
| Trend | EMA levels/slopes, breakout distance, persistence, regression slope |
| Momentum | raw and volatility-scaled returns, acceleration |
| Reversion | price z-score, VWAP distance, Bollinger distance, spread z-score, half-life |
| Volatility | rolling realized volatility, range volatility, volatility-of-volatility, jump proxy |
| Carry | funding level, change, z-score, freshness |
| Leverage | open-interest change, price × OI interaction, OI freshness |
| Trade flow | buy-volume share, signed volume, trade-count imbalance |
| Basis | perpetual/spot spread and its changes |
| Activity/liquidity proxies | turnover, volume z-score, trade-size proxy, Amihud-like proxy |
| Cross-asset | BTC/ETH relative return, rolling beta, correlation, correlation break |

All derived variables must use only observations with timestamps less than or equal to the row timestamp.

## 1.3 Optional enrichment contracts

These datasets are optional feature blocks and must not be required by the historical-core model until sufficient history and live parity exist.

### IV/RV block

From `gold.market.iv_rv.m1` or the corresponding fields in `gold.market.regime_features.m1`:

```text
canonical_rv_source
canonical_rv_source_available
rv_5m
rv_15m
rv_1h
rv_4h
rv_1d
rv_30d
rv_5m_annualized_pct
rv_15m_annualized_pct
rv_1h_annualized_pct
rv_4h_annualized_pct
rv_1d_annualized_pct
rv_30d_annualized_pct
parkinson_rv_1h
jump_proxy
iv_rv_spread_30d_pct
iv_rv_ratio_30d
iv_rv_zscore_1d
iv_rv_percentile_30d
minutes_since_iv_observation
minutes_since_rv_observation
iv_available
rv_available
```

Deprecated mixed-unit IV/RV compatibility fields must not be selected for new models.

### Perpetual L2 block

```text
perps_l2_best_bid_price
perps_l2_best_ask_price
perps_l2_mid_price
perps_l2_spread
perps_l2_top_bid_size
perps_l2_top_ask_size
perps_l2_top_of_book_imbalance
perps_l2_bid_depth_10bps
perps_l2_ask_depth_10bps
perps_l2_bid_depth_50bps
perps_l2_ask_depth_50bps
perps_l2_quote_age_seconds
perps_l2_quote_available
perps_l2_stale_quote
perps_l2_minutes_since_observation
perps_l2_as_of
perps_l2_live_snapshot_derived
```

### Option L2 and option-surface blocks

```text
options_l2_contract_count
options_l2_quote_coverage_ratio
options_l2_stale_quote_ratio
options_l2_median_spread
options_l2_top_bid_depth
options_l2_top_ask_depth
options_l2_bid_depth_10bps
options_l2_ask_depth_10bps
options_l2_bid_depth_50bps
options_l2_ask_depth_50bps
options_l2_max_quote_age_seconds
options_l2_as_of
options_l2_live_snapshot_derived

options_surface_atm_iv
options_surface_short_dated_iv
options_surface_skew
options_surface_term_structure
options_surface_put_call_iv_spread
options_surface_contract_count
options_surface_fresh_quote_count
options_surface_stale_quote_count
options_surface_max_quote_age_seconds
options_surface_quote_coverage_ratio
```

During live inference, compatible fields can come from `gold.live.full.m1`. An optional block may enter a production model only after historical and live calculations pass parity tests.

## 1.4 Training-only target contract

Forward-looking variables are consumed only during training and evaluation:

```text
gold.market.prediction_targets.m1
```

Permitted target variables:

```text
target_forward_return_1h
target_forward_return_4h
target_forward_return_1d

target_forward_drawdown_1h
target_forward_drawdown_4h
target_forward_drawdown_1d

target_cost_adjusted_return_1h
target_cost_adjusted_return_4h
target_cost_adjusted_return_1d

target_future_rv_1h
target_future_rv_4h
target_future_rv_1d

target_future_iv_spread_change_1h
target_future_iv_spread_change_4h
target_future_iv_spread_change_1d

label_regime_shift_1h
label_regime_shift_4h
label_regime_shift_1d
```

These fields are prohibited from every live feature frame and from every historical feature row supplied to either learned model.

---

# 2. Shared contracts

## 2.1 MarketFeatureFrame.v1

One point-in-time row supplied to model code.

```yaml
contract: MarketFeatureFrame.v1
keys:
  timestamp_m1: datetime_utc
  exchange: string
  symbol: string
fields:
  source_features: map[string, float|int|bool|null]
  derived_features: map[string, float|int|bool|null]
  availability_flags: map[string, bool]
  observation_ages: map[string, float|null]
metadata:
  dataset_id: string
  dataset_version: string
  feature_set_hash: string
  source_data_hash: string
  build_git_commit: string
```

Rules:

- Sorted by `timestamp_m1`.
- Unique on `timestamp_m1`, `exchange`, `symbol`.
- No forward target or label columns.
- No silent imputation of executions, volume, or trade counts.
- Stale or forward-filled state must retain its observation-age flags.
- The feature-set hash must match the model artifact.

## 2.2 PortfolioState.v1

This contract is produced by the portfolio/execution subsystem, not by `crypto-history-loader`.

```yaml
contract: PortfolioState.v1
fields:
  timestamp: datetime_utc
  equity: float
  cash: float
  gross_exposure: float
  net_exposure: float
  current_drawdown: float
  daily_pnl: float
  rolling_pnl: float
  positions_by_symbol: map
  positions_by_strategy: map
  unrealized_pnl_by_strategy: map
  time_in_position_by_strategy: map
  realised_turnover: float
```

## 2.3 CostModelSnapshot.v1

Historical values are estimated from market data and configured exchange costs. Live values are supplied by the execution layer.

```yaml
contract: CostModelSnapshot.v1
fields:
  timestamp: datetime_utc
  maker_fee_bps: float
  taker_fee_bps: float
  expected_spread_bps: float
  expected_slippage_bps: float
  funding_rate: float|null
  liquidity_capacity: float|null
  cost_model_version: string
```

---

# 3. Module 1 — Regime Estimator

## 3.1 Responsibility

The Regime Estimator has exactly one responsibility:

> Convert a compact point-in-time market feature subset into probabilities for three latent market regimes.

It does not select strategies, set position sizes, set stops, or approve orders.

## 3.2 Inputs

### Training input

```yaml
contract: RegimeTrainingInput.v1
fields:
  features: MarketFeatureFrame.v1[]
  training_window_start: datetime_utc
  training_window_end: datetime_utc
  symbols: [BTC, ETH]
  n_regimes: 3
  candidate_feature_registry: FeatureRegistry.v1
  inner_walk_forward_splits: WalkForwardSplit.v1[]
```

Allowed variables:

- source variables from `gold.market.history_full.m1`;
- trailing variables derived from those source variables;
- optional IV/RV and L2 blocks only when explicitly enabled and parity-tested.

Training targets from `gold.market.prediction_targets.m1` may be used only to evaluate economic usefulness or forward transition quality. They are not emission features.

### Inference input

```yaml
contract: RegimeInferenceInput.v1
fields:
  as_of: datetime_utc
  feature_row: MarketFeatureFrame.v1
  model_id: string
```

## 3.3 Candidate models

Initial model search space:

```text
Gaussian HMM with diagonal covariance
Gaussian HMM with full covariance
robust/heavy-tailed HMM
Hidden Semi-Markov Model
Markov-switching autoregressive model
Gaussian Mixture Model baseline
change-point detector as complementary baseline
```

The number of latent regimes is fixed at three in version 1.

## 3.4 Output contract

```yaml
contract: RegimePrediction.v1
fields:
  as_of: datetime_utc
  exchange: string
  symbol: string
  model_id: string
  model_family: string
  model_version: string
  feature_set_hash: string
  current_probabilities:
    regime_0: float
    regime_1: float
    regime_2: float
  forward_probabilities:
    horizon_1h: [float, float, float]
    horizon_4h: [float, float, float]
    horizon_1d: [float, float, float]
  most_likely_regime: integer
  transition_risk: float
  probability_entropy: float
  model_confidence: float
  data_quality_status: PASS|DEGRADED|FAIL
  state_signature_ids: [string, string, string]
```

Contract invariants:

```text
0 <= every probability <= 1
sum(current_probabilities) = 1 within tolerance
sum(each forward probability vector) = 1 within tolerance
most_likely_regime = argmax(current_probabilities)
FAIL data quality forbids downstream trading
```

Only filtered, live-safe probabilities may be emitted:

```text
P(S_t | X_1, ..., X_t)
```

Smoothed states using observations after `t` are prohibited for trading and allocator training.

## 3.5 State alignment contract

State IDs have no permanent economic meaning. Every fitted model emits a state signature built from training-only statistics:

```yaml
contract: RegimeStateSignature.v1
fields:
  mean_return: float
  realised_volatility: float
  trend_strength: float
  drawdown_state: float
  funding_state: float|null
  open_interest_change: float|null
  flow_imbalance: float|null
  median_duration: float
```

States are aligned between folds and retraining dates by minimum-distance matching of normalized signatures. Strategy mappings must reference aligned signature IDs, never raw HMM state numbers.

## 3.6 Regime-model evaluation

Every Optuna trial is evaluated on time-ordered inner validation folds.

### Hard rejection gates

A trial is pruned if any of the following occurs:

- model does not converge;
- covariance or transition parameters are numerically degenerate;
- any regime has validation occupancy below the configured minimum, initially 5%;
- median regime duration is below the configured trading horizon;
- excessive switching exceeds the configured maximum;
- probabilities contain NaN, infinity, or fail to sum to one;
- the selected feature set is not live reproducible;
- any feature or preprocessing step uses future data;
- states cannot be aligned consistently across folds.

### Evaluation dimensions

| Dimension | Metric | Direction |
|---|---|---|
| Predictive fit | validation log likelihood per observation | maximize |
| Forward probability quality | log loss/Brier score against aligned next-state realization | minimize |
| Occupancy | distance from acceptable occupancy range | minimize |
| Persistence | useful regime duration and switch rate | optimize within bounds |
| Separation | pairwise state-distribution distance | maximize |
| Stability | state-signature similarity across folds | maximize |
| Transition stability | variation of aligned transition matrices | minimize |
| Economic usefulness | separation of forward return, drawdown, RV, and fixed-expert results | maximize |
| Downstream uplift | fixed regime-aware mapping versus fixed non-regime baseline | maximize |
| Parsimony | selected feature count and model complexity | minimize |

The evaluation target is not a human-assigned regime label. The model is judged by whether it produces statistically coherent, stable, point-in-time states that improve downstream decisions.

## 3.7 Regime-model selection

Optuna performs multi-objective optimization over:

```text
model family
feature families
compact feature subset
lookback horizons
transformations
scaler
covariance structure
regularization
transition parameters
initialization
```

Recommended feature constraint:

```text
minimum selected features: 3
maximum selected features: 8
```

Candidate selection occurs in four steps:

1. **Reject invalid trials** using the hard gates.
2. **Build a Pareto front** over predictive fit, stability, economic usefulness, and parsimony.
3. **Apply a frozen tie-break score** whose weights are fixed before the outer test.
4. **Select the simplest candidate within one standard error of the best validation score.**

Initial tie-break score after fold-wise normalization:

```text
RegimeSelectionScore =
    0.25 × predictive_fit
  + 0.20 × state_stability
  + 0.20 × economic_separation
  + 0.20 × downstream_uplift
  + 0.10 × persistence_quality
  + 0.05 × parsimony
```

The score weights are configuration, must be versioned, and must not be adjusted after inspecting an outer test period.

The selected candidate is refitted on the complete three-year outer training window and evaluated exactly once on the untouched outer test interval.

---

# 4. Strategy expert contracts

The strategy experts are deterministic or separately fitted signal generators. They are not part of the Regime Estimator and are not allowed to reinterpret regime state IDs.

## 4.1 Common input

```yaml
contract: StrategyExpertInput.v1
fields:
  feature_row: MarketFeatureFrame.v1
  regime_prediction: RegimePrediction.v1
  portfolio_state: PortfolioState.v1
  cost_snapshot: CostModelSnapshot.v1
```

## 4.2 Historical source-to-expert mapping

### Trend expert

Primary historical variables and derivatives:

```text
perp_close_price
perp_high_price
perp_low_price
perp_volume
spot_ohlcv_close_price
strategy_trend_ema_3m
strategy_trend_ema_slope_3m
strategy_trend_ema_10m
strategy_trend_ema_slope_10m
strategy_trend_breakout_distance_5m
strategy_trend_breakout_distance_15m
strategy_trend_persistence_5m
strategy_trend_persistence_15m
```

The `strategy_*` variables are consumed from `gold.market.regime_features.m1` when materialized or derived identically from `gold.market.history_full.m1`.

### Momentum expert

```text
perp_close_price
perp_volume
perps_trades_buy_volume_share
strategy_momentum_log_return_1m
strategy_momentum_log_return_5m
strategy_momentum_log_return_15m
strategy_momentum_vol_scaled_return_5m
strategy_momentum_vol_scaled_return_15m
```

### Mean-reversion expert

```text
perp_close_price
spot_ohlcv_close_price
perp_volume
strategy_reversion_price_zscore_5m
strategy_reversion_price_zscore_15m
strategy_reversion_vwap_distance_5m
strategy_reversion_vwap_distance_15m
strategy_reversion_bollinger_distance_5m
strategy_reversion_bollinger_distance_15m
strategy_reversion_spot_perp_spread_zscore_5m
strategy_reversion_spot_perp_spread_zscore_15m
strategy_reversion_half_life_5m
```

### Shared cost and capacity variables

```text
funding_rate_last_known
funding_data_available
minutes_since_funding
strategy_cost_turnover_notional_1m
strategy_cost_turnover_notional_5m
strategy_cost_turnover_notional_15m
strategy_cost_spot_perp_spread
```

These strategy-cost variables are consumed from `gold.market.regime_features.m1` when available or derived from `history_full`.

## 4.3 Common output

```yaml
contract: StrategyExpertSignal.v1
fields:
  as_of: datetime_utc
  symbol: string
  strategy_id: trend|momentum|mean_reversion
  strategy_version: string
  signal_direction: float       # [-1, 1]
  signal_strength: float        # [0, 1]
  signal_confidence: float      # [0, 1]
  expected_return: float|null
  expected_volatility: float|null
  expected_holding_minutes: integer
  estimated_cost_bps: float
  capacity_limit: float|null
  current_position: float
  requested_entry: float
```

---

# 5. Module 2 — Strategy Allocator

## 5.1 Responsibility

The Strategy Allocator has exactly one responsibility:

> Convert regime probabilities, expert signals, portfolio state, and cost state into a proposed allocation and risk profile.

It does not approve orders and cannot override risk limits.

## 5.2 Training input

Historical allocator training must use out-of-fold regime predictions generated by earlier-only Regime Estimator fits.

```yaml
contract: AllocatorTrainingInput.v1
fields:
  oof_regime_predictions: RegimePrediction.v1[]
  expert_signals: StrategyExpertSignal.v1[]
  portfolio_state_path: PortfolioState.v1[]
  cost_snapshots: CostModelSnapshot.v1[]
  training_targets:
    forward_returns: gold.market.prediction_targets.m1
    forward_drawdowns: gold.market.prediction_targets.m1
    cost_adjusted_returns: gold.market.prediction_targets.m1
  inner_walk_forward_splits: WalkForwardSplit.v1[]
```

Incorrect:

```text
fit Regime Estimator on all three years
→ infer retrospective states on the same three years
→ train allocator on those states
```

Correct:

```text
fit Regime Estimator on earlier data
→ emit filtered probabilities for the next historical interval
→ repeat through time
→ concatenate out-of-fold probabilities
→ train allocator
```

## 5.3 Inference input

```yaml
contract: AllocatorInferenceInput.v1
fields:
  as_of: datetime_utc
  regime_prediction: RegimePrediction.v1
  expert_signals:
    trend: StrategyExpertSignal.v1
    momentum: StrategyExpertSignal.v1
    mean_reversion: StrategyExpertSignal.v1
  portfolio_state: PortfolioState.v1
  cost_snapshot: CostModelSnapshot.v1
```

The allocator state may include:

```text
three current regime probabilities
three forward probability vectors
transition risk and probability entropy
three expert directions, strengths, confidences, expected risks, and costs
realized volatility and optional IV/RV state
funding and open-interest state
current strategy weights and positions
unrealized PnL and current drawdown
time in position
recent expert performance
estimated spread, slippage, fees, and funding
```

## 5.4 Candidate models

Candidates are evaluated in increasing complexity:

```text
hard rule-based regime mapping
probability-weighted mapping
Bayesian-optimized static allocator
regularized supervised allocator
contextual bandit
constrained reinforcement-learning policy
```

A complex model is eligible only if it beats simpler baselines under identical data, execution assumptions, and walk-forward periods.

## 5.5 Action space

Version 1 uses a constrained action space:

```text
trend_weight
momentum_weight
mean_reversion_weight
cash_weight
global_risk_multiplier
TP/SL profile per strategy
```

Weight invariant:

```text
trend_weight + momentum_weight + mean_reversion_weight + cash_weight = 1
```

Initial TP/SL profiles:

| Profile | Stop loss | Take profit |
|---|---:|---:|
| Conservative | 1.0 × ATR | 1.5 × ATR |
| Balanced | 1.5 × ATR | 2.5 × ATR |
| Trend | 2.0 × ATR | 4.0 × ATR |
| Wide | 3.0 × ATR | 6.0 × ATR |

Continuous unrestricted TP/SL optimization is excluded from the first production candidate.

## 5.6 Output contract

```yaml
contract: AllocationProposal.v1
fields:
  as_of: datetime_utc
  symbol: string
  allocator_model_id: string
  allocator_model_family: string
  allocator_version: string
  regime_model_id: string
  strategy_weights:
    trend: float
    momentum: float
    mean_reversion: float
    cash: float
  target_position_by_strategy:
    trend: float
    momentum: float
    mean_reversion: float
  global_risk_multiplier: float
  stop_loss_profile_by_strategy: map[string, string]
  take_profit_profile_by_strategy: map[string, string]
  expected_holding_minutes_by_strategy: map[string, integer]
  policy_confidence: float
  expected_net_utility: float|null
  estimated_turnover: float
  estimated_cost_bps: float
```

The proposal is advisory. Module 3 may clip or reject every field.

## 5.7 Allocator evaluation

Every candidate is evaluated on time-ordered validation episodes with identical expert signals, costs, and market data.

### Hard rejection gates

Reject a candidate if:

- any action violates the action-space invariants;
- evaluation contains look-ahead data;
- net performance is calculated without fees, spread, slippage, and funding;
- turnover or strategy switching exceeds configured limits;
- maximum drawdown breaches the research limit;
- the candidate collapses to an invalid or unstable action;
- performance is driven by one fold while most folds are negative;
- it does not outperform the required simple baseline.

### Evaluation dimensions

| Dimension | Metric | Direction |
|---|---|---|
| Net performance | cost-adjusted return | maximize |
| Risk-adjusted performance | Sharpe and Sortino | maximize |
| Drawdown | maximum drawdown and Calmar | minimize/maximize |
| Tail risk | CVaR and worst-period loss | minimize |
| Stability | median result and dispersion across folds | maximize/minimize |
| Consistency | fraction of profitable folds | maximize |
| Regret | loss versus best ex-post expert | minimize |
| Turnover | notional turnover | minimize |
| Switching | strategy-weight change frequency | minimize |
| Baseline uplift | improvement over static and non-regime allocators | maximize |
| Complexity | parameters, training variance, inference cost | minimize |

For RL candidates, the reward must be net economic utility:

```text
Reward =
    realized net PnL
  - transaction costs
  - funding costs
  - slippage
  - drawdown penalty
  - tail-risk penalty
  - turnover penalty
  - strategy-switching penalty
```

## 5.8 Allocator-model selection

The model-development comparison uses untouched outer walk-forward folds. Within each outer training window, Optuna sees only inner folds.

Selection procedure:

1. Reject candidates that fail hard gates.
2. Rank remaining candidates by their Pareto position across net utility, drawdown, tail risk, stability, turnover, and complexity.
3. Apply a frozen tie-break score.
4. Prefer the simplest model within one standard error of the best score.
5. Require improvement over both:
   - best static strategy mix;
   - probability-weighted regime baseline.
6. Promote RL only when it also beats the contextual-bandit and regularized allocator baselines.

Initial fold-normalized tie-break score:

```text
AllocatorSelectionScore =
    0.30 × net_risk_adjusted_return
  + 0.20 × drawdown_quality
  + 0.15 × tail_risk_quality
  + 0.15 × fold_stability
  + 0.10 × low_regret
  + 0.10 × turnover_efficiency
```

Initial promotion gates:

```text
positive net uplift in at least 60% of outer folds
positive median net uplift across outer folds
no breach of the maximum-drawdown limit
no material deterioration in CVaR
performance survives configured cost-stress scenarios
```

Thresholds and score weights are versioned configuration. They must be fixed before outer-test inspection.

---

# 6. Module 3 — Deterministic Risk Engine

## 6.1 Responsibility

The Risk Engine has exactly one responsibility:

> Convert an advisory allocation proposal into an approved, clipped, or rejected set of order intents under hard portfolio, market-data, liquidity, and operational constraints.

It is not optimized by Optuna and is not selected through ML metrics.

## 6.2 Inputs

```yaml
contract: RiskEngineInput.v1
fields:
  proposal: AllocationProposal.v1
  regime_prediction: RegimePrediction.v1
  expert_signals: StrategyExpertSignal.v1[]
  feature_row: MarketFeatureFrame.v1
  portfolio_state: PortfolioState.v1
  cost_snapshot: CostModelSnapshot.v1
  risk_limits: RiskLimits.v1
  exchange_constraints: ExchangeConstraints.v1
```

Dataset-derived risk variables include:

```text
funding_rate_last_known
funding_data_available
minutes_since_funding
open_interest_open_interest
open_interest_is_observed
open_interest_is_ffill
minutes_since_open_interest_observation
perp_close_price
perp_volume
perp_quote_volume
perps_trades_buy_volume_share
derived realized volatility
derived basis and turnover
optional perps_l2_spread and depth
optional quote-age and stale-quote flags
optional IV/RV and option-surface state
```

Externally supplied variables include:

```text
account equity and cash
open positions
current drawdown and loss limits
exchange minimum order sizes
margin and leverage rules
order and exposure limits
operational kill-switch state
```

## 6.3 Output contract

```yaml
contract: RiskDecision.v1
fields:
  as_of: datetime_utc
  proposal_id: string
  status: APPROVED|CLIPPED|REJECTED|HALTED
  approved_strategy_weights: map[string, float]
  approved_position_by_strategy: map[string, float]
  approved_stop_levels: map[string, float]
  approved_take_profit_levels: map[string, float]
  approved_order_intents: list
  rejected_actions: list
  triggered_rules: list[string]
  risk_override_reason: string|null
  gross_exposure_after: float
  net_exposure_after: float
  risk_config_version: string
```

## 6.4 Deterministic controls

The engine enforces:

- maximum gross and net exposure;
- maximum leverage;
- maximum position by asset and strategy;
- portfolio concentration and strategy-correlation limits;
- daily, rolling, and maximum-drawdown limits;
- volatility scaling;
- liquidity and capacity limits;
- stale-data and missing-data rejection;
- maximum turnover and order size;
- funding and cost limits;
- exchange and instrument constraints;
- circuit breakers and kill switches.

## 6.5 Risk-engine evaluation

The Risk Engine is verified, not statistically selected.

Required verification:

```text
unit tests for every limit and boundary
property tests for invariants
scenario tests for crashes, gaps, stale data, missing data, and exchange outages
replay tests on historical stress intervals
integration tests against allocator outputs
fail-closed behavior tests
configuration-version audit tests
```

Success means the engine always enforces its declared rules, including when both learned models are wrong.

---

# 7. End-to-end training and selection

## 7.1 Outer walk-forward

For each outer evaluation date:

```text
1. Use the previous three years as outer training data.
2. Create time-ordered inner train/validation folds.
3. Optimize Module 1 only on inner folds.
4. Select and refit the Regime Estimator on the full outer training window.
5. Generate out-of-fold RegimePrediction records for allocator training.
6. Generate all expert signals and cost snapshots point in time.
7. Optimize Module 2 only on inner allocator folds.
8. Freeze both learned models.
9. Evaluate the complete pipeline once on the untouched outer test period.
10. Move the outer window forward and repeat.
```

No outer-test result may be used to retune a candidate within the same research run.

## 7.2 Best-model artifacts

### RegimeModelArtifact.v1

```yaml
selected_model_family: string
selected_features: list[string]
preprocessing_pipeline: object
model_parameters: object
state_signatures: list
state_alignment_metadata: object
feature_set_hash: string
training_window: [datetime, datetime]
inner_validation_metrics: object
outer_evaluation_metrics: object
selection_score_version: string
```

### AllocatorModelArtifact.v1

```yaml
selected_model_family: string
policy_parameters: object
expert_contract_versions: object
regime_model_contract_version: string
action_space_version: string
cost_model_version: string
training_window: [datetime, datetime]
inner_validation_metrics: object
outer_evaluation_metrics: object
selection_score_version: string
```

### RiskConfigArtifact.v1

```yaml
risk_limits: object
exchange_constraints: object
data_quality_rules: object
kill_switch_rules: object
config_version: string
```

## 7.3 Champion/challenger promotion

The current production models are the champions. A retrained pair becomes challenger models.

Promotion requires:

- all schema and feature-hash checks pass;
- challenger passes the same hard gates;
- challenger improves the frozen selection objective;
- no material deterioration in drawdown, CVaR, turnover, or data-quality behavior;
- shadow-live behavior is consistent with backtest assumptions;
- both model artifacts and the risk configuration are reproducible from their manifests.

The Regime Estimator and Strategy Allocator are versioned separately, but production deployment records the exact compatible pair.

---

# 8. Repository structure

```text
regime-strategy-selector/
├── configs/
│   ├── datasets/
│   ├── features/
│   ├── models/
│   ├── selection/
│   ├── strategies/
│   └── risk/
├── contracts/
│   ├── market_feature_frame.schema.json
│   ├── regime_prediction.schema.json
│   ├── strategy_expert_signal.schema.json
│   ├── allocation_proposal.schema.json
│   └── risk_decision.schema.json
├── src/regime_strategy_selector/
│   ├── data/
│   │   ├── adapters/
│   │   ├── validation/
│   │   └── feature_store/
│   ├── features/
│   ├── regimes/
│   │   ├── models/
│   │   ├── selection/
│   │   ├── alignment/
│   │   └── inference/
│   ├── strategies/
│   │   ├── trend/
│   │   ├── momentum/
│   │   └── mean_reversion/
│   ├── allocation/
│   │   ├── rules/
│   │   ├── supervised/
│   │   ├── bandits/
│   │   └── reinforcement_learning/
│   ├── risk/
│   ├── backtesting/
│   ├── optimization/
│   ├── evaluation/
│   └── monitoring/
├── tests/
├── notebooks/
├── scripts/
└── README.md
```

---

# 9. Success criteria

The architecture is successful only when:

- Module 1 emits stable, calibrated, live-safe regime probabilities from a compact feature subset;
- Module 2 improves net out-of-sample allocation results over simpler non-regime and probability-weighted baselines;
- Module 3 enforces all limits deterministically and fails closed;
- all evaluations include fees, spread, slippage, and funding;
- historical and live feature contracts remain equivalent;
- results remain stable across multiple outer walk-forward periods;
- optional L2 and IV/RV blocks demonstrate incremental outer-test value before promotion;
- shadow-live performance does not materially diverge from the frozen backtest assumptions.
