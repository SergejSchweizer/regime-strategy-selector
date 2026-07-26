# Contracts

This document defines the versioned data and service interfaces for `regime-strategy-selector`.

The architecture is described in [`ARCHITECTURE.md`](ARCHITECTURE.md).

## 1. Global contract rules

Every training run, model artifact, inference request, portfolio state, allocation proposal, risk decision, and order intent is bound to exactly one configured asset:

```text
target_symbol ∈ {BTC, ETH, SOL}
```

Global invariants:

```text
all payloads in one request chain use the same target_symbol
payload target_symbol equals deployment target_symbol
model artifact target_symbol equals deployment target_symbol
source rows satisfy symbol == target_symbol
cross-asset fields are prohibited
forward targets are prohibited from inference payloads
all timestamps are UTC
all decision inputs use closed source buckets only
```

Any symbol mismatch must fail closed before model inference or order creation.

---

# 2. Upstream dataset contract

## 2.1 Dataset

```text
dataset_id: gold.market.history_full.m1
grain: one row per timestamp_m1, exchange, symbol
keys: timestamp_m1, exchange, symbol
```

Only rows matching the configured `target_symbol` are eligible.

## 2.2 Key columns

| Variable | Type | Meaning |
|---|---|---|
| `timestamp_m1` | datetime UTC | Closed one-minute bucket |
| `exchange` | string | Normalised exchange identifier |
| `symbol` | string | Normalised base asset; allowed project values are `BTC`, `ETH`, `SOL` |

## 2.3 Spot OHLCV

```text
spot_ohlcv_open_price
spot_ohlcv_high_price
spot_ohlcv_low_price
spot_ohlcv_close_price
spot_ohlcv_volume
spot_ohlcv_quote_volume
spot_ohlcv_trade_count
```

## 2.4 Perpetual OHLCV

```text
perp_open_price
perp_high_price
perp_low_price
perp_close_price
perp_volume
perp_quote_volume
perp_trade_count
```

## 2.5 Funding state

```text
funding_rate_last_known
funding_observed_at
minutes_since_funding
is_funding_observation_minute
funding_data_available
```

## 2.6 Open-interest state

```text
open_interest_open_interest
open_interest_is_observed
open_interest_is_ffill
minutes_since_open_interest_observation
open_interest_observation_lag_sec
open_interest_source_timestamp
```

## 2.7 Perpetual trade-flow aggregates

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

## 2.8 Option trade-flow aggregates

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

## 2.9 Upstream invariants

```text
rows are unique on timestamp_m1, exchange, symbol
rows are sorted by timestamp_m1
trade executions, volume, and counts are never forward-filled
last-known funding and open-interest values retain age and availability metadata
missing source values remain null unless the upstream dataset explicitly supplies a state value and freshness metadata
```

---

# 3. Configuration contracts

## 3.1 DeploymentConfig.v1

```yaml
contract: DeploymentConfig.v1
fields:
  deployment_id: string
  target_symbol: BTC|ETH|SOL
  exchange: string
  decision_interval: string
  source_dataset_id: gold.market.history_full.m1
  regime_model_id: string
  allocator_model_id: string
  risk_config_version: string
  feature_contract_version: string
  strategy_config_versions: map[string, string]
  cost_model_version: string
  execution_config_version: string
```

Invariants:

```text
target_symbol is immutable for the lifetime of the deployment process
all loaded artifacts declare the same target_symbol
all contract versions are resolvable before startup
startup fails on any hash, symbol, or version mismatch
```

## 3.2 FeatureRegistryEntry.v1

```yaml
contract: FeatureRegistryEntry.v1
fields:
  feature_name: string
  feature_family: string
  source_columns: list[string]
  lookback_minutes: integer
  decision_interval: string
  availability_rule: string
  missing_value_policy: string
  scaler_candidates: list[string]
  live_reproducible: bool
  computation_version: string
  expected_directional_role: string|null
```

A feature is ineligible if:

- it references another asset;
- it uses a future observation;
- timestamp semantics are ambiguous;
- it cannot be reproduced by the live feature service;
- it silently imputes event data;
- it has no versioned implementation;
- required lookback is unavailable.

## 3.3 WalkForwardSplit.v1

```yaml
contract: WalkForwardSplit.v1
fields:
  split_id: string
  target_symbol: BTC|ETH|SOL
  train_start: datetime_utc
  train_end: datetime_utc
  validation_start: datetime_utc
  validation_end: datetime_utc
  purge_minutes: integer
  embargo_minutes: integer
  decision_interval: string
```

---

# 4. Feature and target contracts

## 4.1 MarketFeatureFrame.v1

One point-in-time feature row for one configured asset.

```yaml
contract: MarketFeatureFrame.v1
keys:
  as_of: datetime_utc
  exchange: string
  target_symbol: BTC|ETH|SOL
fields:
  source_features: map[string, float|int|bool|null]
  derived_features: map[string, float|int|bool|null]
  availability_flags: map[string, bool]
  observation_ages: map[string, float|null]
  data_quality_status: PASS|DEGRADED|FAIL
metadata:
  source_dataset_id: gold.market.history_full.m1
  source_dataset_version: string
  feature_contract_version: string
  feature_set_hash: string
  source_data_hash: string
  build_git_commit: string
  decision_interval: string
```

Invariants:

```text
target_symbol matches deployment target_symbol
all source buckets are closed at as_of
no future target or label is present
no cross-asset feature is present
feature_set_hash matches the model artifact
state freshness is explicit
trade executions and volumes are never imputed
FAIL status forbids learned-model trading decisions
```

## 4.2 Candidate derived feature families

### Returns

```text
log_return_5m
log_return_15m
log_return_1h
log_return_4h
log_return_1d
```

### Trend

```text
ema_distance_<window>
ema_slope_<window>
breakout_distance_<window>
directional_persistence_<window>
regression_slope_<window>
regression_r2_<window>
```

### Momentum

```text
vol_scaled_return_<window>
return_acceleration_<window>
volume_confirmed_momentum_<window>
```

### Mean reversion

```text
price_zscore_<window>
vwap_distance_<window>
bollinger_distance_<window>
spot_perp_spread_zscore_<window>
mean_reversion_half_life_<window>
short_horizon_reversal_<window>
```

### Volatility

```text
realized_volatility_<window>
downside_volatility_<window>
range_volatility_<window>
volatility_of_volatility_<window>
jump_proxy_<window>
atr_<window>
```

### Carry and leverage

```text
funding_level
funding_change_<window>
funding_zscore_<window>
funding_direction
funding_freshness
open_interest_change_<window>
price_oi_interaction_<window>
open_interest_freshness
```

### Trade flow and activity

```text
buy_volume_share_<window>
signed_volume_<window>
trade_count_imbalance_<window>
average_trade_size_proxy_<window>
turnover_<window>
volume_zscore_<window>
trade_count_zscore_<window>
amihud_proxy_<window>
```

### Basis

```text
spot_perp_spread
spot_perp_spread_change_<window>
spot_perp_spread_zscore_<window>
```

### Data quality

```text
missing_feature_count
stale_state_count
maximum_observation_age
contiguous_history_minutes
```

The exact closed feature list is owned by the feature registry and feature-set hash, not by this illustrative list.

## 4.3 TrainingTargetFrame.v1

Training and evaluation only. Never passed to inference.

```yaml
contract: TrainingTargetFrame.v1
keys:
  as_of: datetime_utc
  target_symbol: BTC|ETH|SOL
fields:
  forward_log_return_1h: float|null
  forward_log_return_4h: float|null
  forward_log_return_1d: float|null
  forward_drawdown_1h: float|null
  forward_drawdown_4h: float|null
  forward_drawdown_1d: float|null
  forward_realized_volatility_1h: float|null
  forward_realized_volatility_4h: float|null
  forward_realized_volatility_1d: float|null
  cost_adjusted_return_1h: float|null
  cost_adjusted_return_4h: float|null
  cost_adjusted_return_1d: float|null
metadata:
  target_contract_version: string
  target_build_commit: string
  cost_model_version: string
```

Invariants:

```text
target_symbol matches source row symbol
a target is null unless its complete future horizon exists
targets are excluded from MarketFeatureFrame.v1
targets are excluded from all live inference requests
validation embargo is at least the longest target horizon
```

---

# 5. Runtime state contracts

## 5.1 PortfolioState.v1

Produced by the portfolio and execution subsystem for one asset.

```yaml
contract: PortfolioState.v1
fields:
  as_of: datetime_utc
  target_symbol: BTC|ETH|SOL
  equity: float
  cash: float
  gross_exposure: float
  net_exposure: float
  current_drawdown: float
  daily_pnl: float
  rolling_pnl: float
  exchange_position: float
  virtual_sleeve_positions:
    trend: float
    momentum: float
    mean_reversion: float
  unrealized_pnl_by_sleeve: map[string, float]
  realized_pnl_by_sleeve: map[string, float]
  time_in_position_by_sleeve: map[string, integer]
  realized_turnover: float
  pending_orders: list
  reconciliation_status: RECONCILED|PENDING|BROKEN
```

Invariants:

```text
exchange_position reconciles to the net sleeve position within tolerance
BROKEN reconciliation status forbids exposure increases
all positions and pending orders reference target_symbol only
```

## 5.2 CostModelSnapshot.v1

```yaml
contract: CostModelSnapshot.v1
fields:
  as_of: datetime_utc
  target_symbol: BTC|ETH|SOL
  maker_fee_bps: float
  taker_fee_bps: float
  expected_spread_bps: float
  expected_slippage_bps: float
  funding_rate: float|null
  estimated_capacity_notional: float|null
  scenario: BASE|ELEVATED|SEVERE|LIVE
  cost_model_version: string
```

Historical values are estimated from the configured asset's market data and exchange fee configuration. Live values are supplied by the execution layer.

## 5.3 OperationalState.v1

```yaml
contract: OperationalState.v1
fields:
  as_of: datetime_utc
  target_symbol: BTC|ETH|SOL
  market_data_connected: bool
  exchange_connected: bool
  model_service_healthy: bool
  portfolio_reconciled: bool
  pending_order_count: integer
  oldest_pending_order_age_seconds: float|null
  kill_switch_active: bool
  incident_id: string|null
```

---

# 6. Module 1 contracts

## 6.1 RegimeTrainingInput.v1

```yaml
contract: RegimeTrainingInput.v1
fields:
  target_symbol: BTC|ETH|SOL
  features: MarketFeatureFrame.v1[]
  targets: TrainingTargetFrame.v1[]
  training_window_start: datetime_utc
  training_window_end: datetime_utc
  n_regimes: 3
  candidate_feature_registry: FeatureRegistryEntry.v1[]
  inner_walk_forward_splits: WalkForwardSplit.v1[]
  optimization_config_version: string
  selection_config_version: string
```

Targets may be used for economic evaluation of discovered regimes, but never as HMM emission features or inference inputs.

## 6.2 RegimeInferenceInput.v1

```yaml
contract: RegimeInferenceInput.v1
fields:
  as_of: datetime_utc
  target_symbol: BTC|ETH|SOL
  feature_row: MarketFeatureFrame.v1
  model_id: string
```

## 6.3 RegimePrediction.v1

```yaml
contract: RegimePrediction.v1
fields:
  as_of: datetime_utc
  target_symbol: BTC|ETH|SOL
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
  abstain_recommended: bool
  abstain_reasons: list[string]
  data_quality_status: PASS|DEGRADED|FAIL
  state_signature_ids: [string, string, string]
```

Invariants:

```text
each probability is between zero and one
each probability vector sums to one within tolerance
most_likely_regime equals argmax(current_probabilities)
probabilities are filtered using observations available through as_of only
FAIL data quality forces abstain_recommended = true
target_symbol and feature_set_hash match the loaded artifact
```

## 6.4 RegimeStateSignature.v1

```yaml
contract: RegimeStateSignature.v1
fields:
  target_symbol: BTC|ETH|SOL
  signature_id: string
  mean_return: float
  realized_volatility: float
  downside_volatility: float
  trend_strength: float
  drawdown_state: float
  funding_state: float|null
  open_interest_change: float|null
  flow_imbalance: float|null
  median_duration: float
  occupancy: float
```

State IDs are aligned across folds and retraining windows using these normalized signatures. Raw model state numbers must not be used as permanent business identifiers.

---

# 7. Strategy expert contracts

## 7.1 StrategyExpertInput.v1

```yaml
contract: StrategyExpertInput.v1
fields:
  as_of: datetime_utc
  target_symbol: BTC|ETH|SOL
  feature_row: MarketFeatureFrame.v1
  cost_snapshot: CostModelSnapshot.v1
  strategy_config_version: string
```

Regime probabilities are deliberately absent. Experts must remain independently testable.

## 7.2 StrategyExpertSignal.v1

One record per strategy expert.

```yaml
contract: StrategyExpertSignal.v1
fields:
  as_of: datetime_utc
  target_symbol: BTC|ETH|SOL
  strategy_id: trend|momentum|mean_reversion
  strategy_version: string
  signal_direction: float
  signal_strength: float
  signal_confidence: float
  expected_return: float|null
  expected_volatility: float|null
  expected_holding_minutes: integer
  estimated_cost_bps: float
  estimated_capacity_notional: float|null
  raw_target_exposure: float
  data_quality_status: PASS|DEGRADED|FAIL
```

Invariants:

```text
signal_direction is in [-1, 1]
signal_strength and signal_confidence are in [0, 1]
FAIL status forces raw_target_exposure = 0
all three experts emit at most one signal per as_of and target_symbol
```

---

# 8. Module 2 contracts

## 8.1 AllocatorTrainingInput.v1

```yaml
contract: AllocatorTrainingInput.v1
fields:
  target_symbol: BTC|ETH|SOL
  regime_candidate_id: string
  oof_regime_predictions: RegimePrediction.v1[]
  expert_signals: StrategyExpertSignal.v1[]
  portfolio_state_path: PortfolioState.v1[]
  cost_snapshots: CostModelSnapshot.v1[]
  targets: TrainingTargetFrame.v1[]
  inner_walk_forward_splits: WalkForwardSplit.v1[]
  action_space_version: string
  selection_config_version: string
```

Only out-of-fold regime predictions produced by earlier-only fits are allowed.

## 8.2 AllocatorInferenceInput.v1

```yaml
contract: AllocatorInferenceInput.v1
fields:
  as_of: datetime_utc
  target_symbol: BTC|ETH|SOL
  regime_prediction: RegimePrediction.v1
  expert_signals:
    trend: StrategyExpertSignal.v1
    momentum: StrategyExpertSignal.v1
    mean_reversion: StrategyExpertSignal.v1
  portfolio_state: PortfolioState.v1
  cost_snapshot: CostModelSnapshot.v1
  allocator_model_id: string
```

## 8.3 AllocationProposal.v1

```yaml
contract: AllocationProposal.v1
fields:
  proposal_id: string
  as_of: datetime_utc
  target_symbol: BTC|ETH|SOL
  allocator_model_id: string
  allocator_model_family: string
  allocator_version: string
  regime_model_id: string
  risk_budget_by_sleeve:
    trend: float
    momentum: float
    mean_reversion: float
  cash_budget: float
  signed_target_exposure_by_sleeve:
    trend: float
    momentum: float
    mean_reversion: float
  gross_target_exposure: float
  net_target_exposure: float
  global_risk_multiplier: float
  exit_profile_by_sleeve: map[string, string]
  expected_holding_minutes_by_sleeve: map[string, integer]
  policy_confidence: float
  abstain_recommended: bool
  abstain_reasons: list[string]
  expected_net_utility: float|null
  estimated_turnover: float
  estimated_cost_bps: float
```

Invariants:

```text
all risk budgets and cash_budget are non-negative
sum(risk budgets) + cash_budget = 1 within tolerance
global_risk_multiplier is within configured bounds
signed sleeve exposures follow the corresponding expert direction unless explicitly neutral
net_target_exposure equals the sum of signed sleeve exposures after policy scaling
gross_target_exposure equals the sum of absolute signed sleeve exposures
target_symbol matches all inputs and artifacts
```

The proposal is advisory. Module 3 may reduce or reject every field.

---

# 9. Module 3 contracts

## 9.1 RiskLimits.v1

```yaml
contract: RiskLimits.v1
fields:
  target_symbol: BTC|ETH|SOL
  max_gross_exposure: float
  max_net_exposure: float
  max_leverage: float
  max_margin_fraction: float
  max_sleeve_exposure: map[string, float]
  max_daily_loss: float
  max_rolling_loss: float
  max_drawdown: float
  max_order_notional: float
  max_turnover_per_day: float
  max_order_frequency: integer
  max_expected_cost_bps: float
  max_funding_rate: float|null
  min_model_confidence: float
  max_regime_entropy: float
  stale_data_limits: map[string, float]
  config_version: string
```

## 9.2 ExchangeConstraints.v1

```yaml
contract: ExchangeConstraints.v1
fields:
  target_symbol: BTC|ETH|SOL
  instrument_id: string
  min_order_size: float
  order_size_step: float
  price_tick: float
  max_leverage: float
  margin_mode: string
  allowed_order_types: list[string]
  reduce_only_supported: bool
  constraints_version: string
```

## 9.3 RiskEngineInput.v1

```yaml
contract: RiskEngineInput.v1
fields:
  as_of: datetime_utc
  target_symbol: BTC|ETH|SOL
  proposal: AllocationProposal.v1
  regime_prediction: RegimePrediction.v1
  expert_signals: StrategyExpertSignal.v1[]
  feature_row: MarketFeatureFrame.v1
  portfolio_state: PortfolioState.v1
  cost_snapshot: CostModelSnapshot.v1
  risk_limits: RiskLimits.v1
  exchange_constraints: ExchangeConstraints.v1
  operational_state: OperationalState.v1
```

## 9.4 OrderIntent.v1

```yaml
contract: OrderIntent.v1
fields:
  intent_id: string
  as_of: datetime_utc
  target_symbol: BTC|ETH|SOL
  instrument_id: string
  side: BUY|SELL
  quantity: float
  order_type: MARKET|LIMIT|STOP|TAKE_PROFIT
  limit_price: float|null
  stop_price: float|null
  reduce_only: bool
  sleeve_attribution: map[string, float]
  idempotency_key: string
  risk_decision_id: string
```

## 9.5 RiskDecision.v1

```yaml
contract: RiskDecision.v1
fields:
  risk_decision_id: string
  as_of: datetime_utc
  target_symbol: BTC|ETH|SOL
  proposal_id: string
  status: APPROVED|CLIPPED|NETTED|REJECTED|HALTED
  approved_risk_budget_by_sleeve: map[string, float]
  approved_signed_exposure_by_sleeve: map[string, float]
  approved_net_target_exposure: float
  approved_stop_level_by_sleeve: map[string, float]
  approved_take_profit_level_by_sleeve: map[string, float]
  approved_order_intents: OrderIntent.v1[]
  rejected_actions: list
  triggered_rules: list[string]
  risk_override_reason: string|null
  gross_exposure_after: float
  net_exposure_after: float
  estimated_margin_after: float
  risk_config_version: string
```

Invariants:

```text
all inputs and outputs reference the configured target_symbol only
HALTED and REJECTED emit no exposure-increasing order intent
abstention may preserve or reduce exposure but cannot increase it
approved exposure respects all risk and exchange constraints
order intents are idempotent
wrong-symbol input forces HALTED or REJECTED
```

---

# 10. Model artifact contracts

## 10.1 RegimeModelArtifact.v1

```yaml
contract: RegimeModelArtifact.v1
fields:
  model_id: string
  target_symbol: BTC|ETH|SOL
  selected_model_family: string
  selected_features: list[string]
  preprocessing_pipeline: object
  model_parameters: object
  state_signatures: RegimeStateSignature.v1[]
  state_alignment_metadata: object
  feature_contract_version: string
  feature_set_hash: string
  source_data_hash: string
  training_window: [datetime_utc, datetime_utc]
  decision_interval: string
  inner_validation_metrics: object
  outer_evaluation_metrics: object
  selection_score_version: string
  code_commit: string
  dependency_lock_hash: string
  artifact_hash: string
```

## 10.2 AllocatorModelArtifact.v1

```yaml
contract: AllocatorModelArtifact.v1
fields:
  model_id: string
  target_symbol: BTC|ETH|SOL
  selected_model_family: string
  policy_parameters: object
  expert_contract_versions: map[string, string]
  regime_model_id: string
  action_space_version: string
  cost_model_version: string
  training_window: [datetime_utc, datetime_utc]
  decision_interval: string
  inner_validation_metrics: object
  outer_evaluation_metrics: object
  selection_score_version: string
  code_commit: string
  dependency_lock_hash: string
  artifact_hash: string
```

## 10.3 RiskConfigArtifact.v1

```yaml
contract: RiskConfigArtifact.v1
fields:
  target_symbol: BTC|ETH|SOL
  risk_limits: RiskLimits.v1
  exchange_constraints: ExchangeConstraints.v1
  data_quality_rules: object
  confidence_and_entropy_rules: object
  kill_switch_rules: object
  config_version: string
  code_commit: string
  artifact_hash: string
```

## 10.4 CompatibleArtifactSet.v1

```yaml
contract: CompatibleArtifactSet.v1
fields:
  deployment_id: string
  target_symbol: BTC|ETH|SOL
  regime_model_id: string
  allocator_model_id: string
  risk_config_version: string
  feature_contract_version: string
  strategy_config_versions: map[string, string]
  cost_model_version: string
  decision_interval: string
  compatibility_hash: string
```

A production decision must record the exact `CompatibleArtifactSet.v1` used.

---

# 11. Audit contract

## 11.1 DecisionAuditRecord.v1

```yaml
contract: DecisionAuditRecord.v1
fields:
  decision_id: string
  as_of: datetime_utc
  target_symbol: BTC|ETH|SOL
  deployment_id: string
  source_dataset_version: string
  source_data_hash: string
  feature_contract_version: string
  feature_set_hash: string
  compatible_artifact_set: CompatibleArtifactSet.v1
  feature_input_hash: string
  regime_prediction: RegimePrediction.v1
  expert_signals: StrategyExpertSignal.v1[]
  allocation_proposal: AllocationProposal.v1
  risk_decision: RiskDecision.v1
  execution_acknowledgements: list
  fills: list
  portfolio_state_before: PortfolioState.v1
  portfolio_state_after: PortfolioState.v1|null
```

The record must be immutable and sufficient to reproduce the analytical decision from pinned data, code, dependencies, model artifacts, and configuration.
