# Contracts

This document is normative for Production V1. Undefined fields, implicit defaults, cross-asset payloads, alternative trading instruments and silent fallbacks are prohibited.

Related documents:

- [`ARCHITECTURE.md`](ARCHITECTURE.md)
- [`METHODOLOGY.md`](METHODOLOGY.md)
- [`OPERATIONS.md`](OPERATIONS.md)

## 1. Global constants and invariants

```text
target_symbol = BTC
traded_instrument_type = LINEAR_PERPETUAL
margin_mode = ISOLATED
position_mode = ONE_WAY
all timestamps = UTC
all percentages = decimal fractions unless field name ends in _bps
one basis point = 0.0001
methodology_version = 2.0.0
```

Global invariants:

```text
one deployment trades one configured linear BTC perpetual
all decision-chain payloads share deployment_id and trading_instrument_id
all source rows satisfy symbol == BTC
BTC spot fields are reference-only and never become order targets
ETH, SOL, inverse contracts, dated futures, options and spot execution are prohibited
future targets are prohibited from inference payloads
all feature inputs use closed source buckets only
wrong symbol, wrong contract type or wrong instrument fails closed
```

## 2. Units

### 2.1 Position fraction

```text
position_fraction = signed BTC-perpetual notional / allocated_equity
```

```text
-1.00 <= position_fraction <= +1.00
```

### 2.2 Direction

```text
SHORT = -1
FLAT  =  0
LONG  = +1
```

### 2.3 Notional and quantity

`notional` is settlement-currency exposure. `quantity` is exchange contract quantity. Analytical contracts produce notional and position fraction. Execution owns quantity conversion.

### 2.4 Absolute loss fields

Fields ending in `_abs` are positive decimal magnitudes in settlement currency or positive decimal fractions as defined by the field description. Drawdown fields ending in `_fraction` are positive fractions.

## 3. Capital and deployment contracts

### 3.1 CapitalAllocation.v1

```yaml
contract: CapitalAllocation.v1
fields:
  deployment_id: string
  target_symbol: BTC
  settlement_currency: string
  allocated_equity: decimal
  max_loss_budget: decimal
  max_margin_budget: decimal
  risk_per_trade_fraction: float
  valid_from: datetime_utc
  valid_until: datetime_utc
  allocation_version: string
```

Invariants:

```text
allocated_equity > 0
0 < max_loss_budget <= allocated_equity
0 < max_margin_budget <= allocated_equity
0 < risk_per_trade_fraction <= 0.02
allocation is valid at decision as_of
```

The recommended canary default is `risk_per_trade_fraction = 0.005`.

### 3.2 DeploymentConfig.v1

```yaml
contract: DeploymentConfig.v1
fields:
  deployment_id: string
  target_symbol: BTC
  trading_instrument_id: string
  reference_spot_instrument_id: string
  exchange: string
  settlement_currency: string
  margin_mode: ISOLATED
  position_mode: ONE_WAY
  decision_interval_minutes: 60
  primary_horizon_minutes: 240
  stress_horizon_minutes: 1440
  source_dataset_id: gold.market.history_full.m1
  compatible_artifact_set_id: string
  capital_allocation_version: string
  methodology_version: 2.0.0
  operations_config_version: string
```

Invariants:

```text
target_symbol, trading instrument and reference spot instrument are immutable for process lifetime
all loaded artifacts declare BTC and the same trading_instrument_id
startup fails on any symbol, instrument, contract-type, margin-mode, position-mode, version or hash mismatch
```

### 3.3 OperationsConfig.v1

```yaml
contract: OperationsConfig.v1
fields:
  config_version: string
  market_data_warning_delay_seconds: 120
  market_data_reduce_only_delay_seconds: 600
  feature_timeout_seconds: 30
  maximum_decision_age_seconds: 60
  maximum_source_gap_minutes: 180
  reconciliation_halt_seconds: 300
  pending_execution_plan_timeout_seconds: 120
  exchange_order_ttl_seconds: integer
  maximum_clock_offset_milliseconds: 500
  slippage_breach_multiplier: 2.0
  slippage_breach_consecutive_plans: 3
  funding_data_max_age_seconds: integer
  mark_index_divergence_warning_fraction: float
  mark_index_divergence_halt_fraction: float
  minimum_liquidation_buffer_warning_fraction: float
  manual_promotion_required: true
```

## 4. Instrument contracts

### 4.1 BTCLinearPerpetualSpec.v1

```yaml
contract: BTCLinearPerpetualSpec.v1
fields:
  exchange: string
  trading_instrument_id: string
  underlying_symbol: BTC
  instrument_type: LINEAR_PERPETUAL
  quote_currency: string
  settlement_currency: string
  contract_multiplier: decimal
  min_quantity: decimal
  quantity_step: decimal
  price_tick: decimal
  reduce_only_supported: true
  isolated_margin_supported: true
  one_way_position_mode_supported: true
  short_supported: true
  mark_price_available: true
  index_price_available: true
  liquidation_price_available: true
  funding_rate_available: true
  funding_interval_minutes: integer
  exchange_max_leverage: decimal
  production_max_effective_leverage: 1.0
  fee_schedule_version: string
  execution_adapter_version: string
  simulator_version: string
  spec_version: string
```

Invariants:

```text
instrument is linear, perpetual and BTC-underlying
production_max_effective_leverage <= 1
reduce-only, isolated margin and one-way mode are mandatory
inverse or quanto settlement is prohibited
```

### 4.2 BTCSpotReferenceSpec.v1

```yaml
contract: BTCSpotReferenceSpec.v1
fields:
  exchange: string
  reference_spot_instrument_id: string
  underlying_symbol: BTC
  quote_currency: string
  market_data_adapter_version: string
  spec_version: string
```

The reference spot contract has no execution permissions in this repository.

### 4.3 SmallAccountCapability.v1

```yaml
contract: SmallAccountCapability.v1
fields:
  deployment_id: string
  trading_instrument_id: string
  allocated_equity: decimal
  reference_price: decimal
  minimum_order_notional: decimal
  quantity_step_notional: decimal
  minimum_order_fraction: float
  quantity_step_fraction: float
  maximum_allowed_fraction: 0.01
  status: PASS|FAIL
  evaluated_at: datetime_utc
```

Definitions:

```text
minimum_order_fraction = minimum_order_notional / allocated_equity
quantity_step_fraction = quantity_step_notional / allocated_equity
```

`PASS` requires both fractions to be no greater than `0.01`.

## 5. Timing and data contracts

### 5.1 DecisionTiming.v1

```yaml
contract: DecisionTiming.v1
fields:
  as_of: datetime_utc
  latest_source_bucket_close: datetime_utc
  feature_completed_at: datetime_utc
  decision_persisted_at: datetime_utc
  approval_persisted_at: datetime_utc|null
  earliest_execution_at: datetime_utc|null
  valid_until: datetime_utc
  timing_policy_version: string
```

Invariants:

```text
latest_source_bucket_close <= as_of
feature_completed_at > as_of
decision_persisted_at >= feature_completed_at
approval_persisted_at >= decision_persisted_at when approval exists
earliest_execution_at > approval_persisted_at when execution is allowed
```

### 5.2 MarketFeatureFrame.v1

```yaml
contract: MarketFeatureFrame.v1
keys:
  deployment_id: string
  as_of: datetime_utc
  target_symbol: BTC
fields:
  trading_instrument_id: string
  reference_spot_instrument_id: string
  return_24h: float|null
  realized_volatility_24h: float|null
  funding_zscore_30d: float|null
  open_interest_change_24h: float|null
  buy_volume_share_4h: float|null
  atr_24h: float|null
  spot_perpetual_basis_fraction: float|null
  mark_index_divergence_fraction: float|null
  funding_observation_age_seconds: float|null
  open_interest_observation_age_seconds: float|null
  contiguous_history_minutes: integer
  data_quality_status: PASS|FAIL
  failure_reasons: list[string]
metadata:
  source_dataset_id: gold.market.history_full.m1
  source_dataset_version: string
  feature_contract_version: string
  feature_set_hash: string
  source_data_hash: string
  build_git_commit: string
  decision_interval_minutes: 60
```

Invariants:

```text
all core HMM features are finite when status = PASS
all source buckets are closed at as_of
no target or future label is present
no non-BTC field is present
trading instrument and reference spot IDs match deployment
FAIL forbids exposure increase
```

### 5.3 TrainingTargetFrame.v1

```yaml
contract: TrainingTargetFrame.v1
keys:
  as_of: datetime_utc
  target_symbol: BTC
fields:
  forward_log_return_4h: float|null
  forward_drawdown_4h_fraction: float|null
  forward_realized_volatility_4h: float|null
  forward_log_return_1d: float|null
  forward_drawdown_1d_fraction: float|null
  cost_adjusted_return_4h: float|null
metadata:
  target_contract_version: string
  target_build_commit: string
  cost_model_version: string
  methodology_version: 2.0.0
```

Targets are offline only and never appear in inference payloads.

## 6. Runtime state contracts

### 6.1 CostModelSnapshot.v1

```yaml
contract: CostModelSnapshot.v1
fields:
  as_of: datetime_utc
  deployment_id: string
  target_symbol: BTC
  trading_instrument_id: string
  maker_fee_bps: float
  taker_fee_bps: float
  expected_half_spread_bps: float
  expected_entry_slippage_bps: float
  expected_exit_slippage_bps: float
  current_funding_rate: float
  expected_funding_bps_4h: float
  next_funding_at: datetime_utc|null
  funding_observation_age_seconds: float
  estimated_capacity_notional: decimal
  scenario: BASE|ELEVATED|SEVERE|LIVE
  cost_model_version: string
```

### 6.2 PortfolioState.v1

```yaml
contract: PortfolioState.v1
fields:
  as_of: datetime_utc
  deployment_id: string
  target_symbol: BTC
  trading_instrument_id: string
  allocated_equity: decimal
  cash_available: decimal
  current_position_fraction: float
  current_position_notional: decimal
  current_contract_quantity: decimal
  current_average_entry_price: decimal|null
  current_mark_price: decimal
  current_index_price: decimal
  current_liquidation_price: decimal|null
  current_liquidation_buffer_fraction: float|null
  current_margin_used: decimal
  current_unrealised_pnl: decimal
  current_realised_pnl_day: decimal
  current_drawdown_fraction: float
  rolling_loss_abs: decimal
  current_stop_price: decimal|null
  current_take_profit_price: decimal|null
  position_opened_at: datetime_utc|null
  reconciliation_status: RECONCILED|PENDING|BROKEN
  pending_execution_plan_id: string|null
```

Invariants:

```text
abs(current_position_fraction) <= 1
BROKEN reconciliation forbids exposure increase
position and margin fields refer to the configured BTC perpetual only
```

### 6.3 OperationalState.v1

```yaml
contract: OperationalState.v1
fields:
  as_of: datetime_utc
  deployment_id: string
  market_data_connected: bool
  execution_connected: bool
  model_service_healthy: bool
  feature_service_healthy: bool
  portfolio_reconciled: bool
  isolated_margin_verified: bool
  one_way_position_mode_verified: bool
  production_leverage_verified: bool
  decision_lock_available: bool
  kill_switch_active: bool
  active_incident_id: string|null
```

## 7. Module 1 contracts

### 7.1 RegimeTrainingConfig.v1

```yaml
contract: RegimeTrainingConfig.v1
fields:
  target_symbol: BTC
  n_states: 3
  model_family: GAUSSIAN_HMM
  covariance_type: DIAGONAL
  n_initialisations: 20
  minimum_converged_initialisations: 16
  minimum_state_occupancy: 0.05
  minimum_median_duration_steps: 2
  maximum_normalised_entropy: float
  minimum_maximum_probability: float
  maximum_seed_signature_distance: float
  maximum_state_alignment_distance: float
  feature_set_hash: string
  methodology_version: 2.0.0
  config_version: string
```

### 7.2 RegimePrediction.v1

```yaml
contract: RegimePrediction.v1
fields:
  deployment_id: string
  as_of: datetime_utc
  target_symbol: BTC
  model_id: string
  current_probabilities: [float, float, float]
  forward_probabilities_4h: [float, float, float]
  normalised_entropy: float
  maximum_probability: float
  most_likely_state: 0|1|2
  state_signature_ids: [string, string, string]
  state_alignment_status: VALID|INVALID
  abstain_recommended: bool
  abstain_reasons: list[string]
  data_quality_status: PASS|FAIL
  feature_set_hash: string
  model_artifact_hash: string
```

Invariants:

```text
probabilities are finite and in [0,1]
each probability vector sums to 1
normalised_entropy is in [0,1]
maximum_probability = max(current_probabilities)
most_likely_state = argmax(current_probabilities)
FAIL or INVALID forces abstention
```

### 7.3 RegimeStateSignature.v1

```yaml
contract: RegimeStateSignature.v1
fields:
  signature_id: string
  target_symbol: BTC
  mean_return_4h: float
  realized_volatility_4h: float
  downside_volatility_4h: float
  trend_strength: float
  mean_drawdown_4h_fraction: float
  mean_funding_zscore: float
  mean_open_interest_change: float
  mean_buy_volume_share: float
  median_duration_steps: float
  occupancy: float
```

## 8. Strategy expert contracts

### 8.1 StrategyConfig.v1

```yaml
contract: StrategyConfig.v1
fields:
  feature_epsilon: 0.000000000001
  trend:
    fast_ema_hours: 24
    slow_ema_hours: 72
    regression_window_hours: 72
    minimum_distance_fraction: 0.0025
    strength_scale_fraction: 0.0200
  momentum:
    return_window_hours: 12
    minimum_vol_scaled_return: 0.50
    strength_scale: 2.00
    flow_strength_scale: 0.25
  mean_reversion:
    zscore_window_hours: 24
    entry_zscore: 1.00
    strength_scale_zscore: 3.00
  methodology_version: 2.0.0
  config_version: string
```

### 8.2 StrategyExpertSignal.v1

```yaml
contract: StrategyExpertSignal.v1
fields:
  deployment_id: string
  as_of: datetime_utc
  target_symbol: BTC
  trading_instrument_id: string
  strategy_id: TREND|MOMENTUM|MEAN_REVERSION
  direction: -1|0|1
  strength: float
  confidence: float
  expected_holding_minutes: integer
  estimated_round_trip_cost_bps: float
  data_quality_status: PASS|FAIL
  strategy_version: string
```

`FAIL` forces direction, strength and confidence to zero.

## 9. Module 2 contracts

### 9.1 RegimeStrategyAffinityMatrix.v1

```yaml
contract: RegimeStrategyAffinityMatrix.v1
fields:
  target_symbol: BTC
  trading_instrument_id: string
  state_signature_ids: [string, string, string]
  strategy_order: [TREND, MOMENTUM, MEAN_REVERSION]
  affinity_matrix: [[float, float, float], [float, float, float], [float, float, float]]
  affinity_epsilon: float
  minimum_cash_fraction: float
  minimum_consensus_evidence: float
  minimum_direction_dominance: float
  target_volatility_annual: float
  volatility_floor: float
  methodology_version: 2.0.0
  config_version: string
```

All affinities are in `[0,1]`; each row sum is no greater than `1 - minimum_cash_fraction`.

### 9.2 ExitProfile.v1

```yaml
contract: ExitProfile.v1
fields:
  profile_id: MEAN_REVERSION|MOMENTUM|TREND
  stop_atr_multiple: float
  take_profit_atr_multiple: float
  maximum_holding_minutes: integer
  profile_version: string
```

Defaults:

```text
MEAN_REVERSION: stop 1.0, take profit 1.5, time stop 240 minutes
MOMENTUM:       stop 1.5, take profit 2.5, time stop 1440 minutes
TREND:          stop 2.0, take profit 4.0, time stop 4320 minutes
```

### 9.3 AllocationProposal.v1

```yaml
contract: AllocationProposal.v1
fields:
  proposal_id: string
  deployment_id: string
  as_of: datetime_utc
  target_symbol: BTC
  trading_instrument_id: string
  strategy_contribution_weights:
    trend: float
    momentum: float
    mean_reversion: float
    cash: float
  consensus_direction: SHORT|FLAT|LONG
  regime_certainty: float
  volatility_multiplier: float
  global_risk_multiplier: float
  preliminary_target_position_fraction: float
  dominant_strategy: TREND|MOMENTUM|MEAN_REVERSION|null
  exit_profile_id: MEAN_REVERSION|MOMENTUM|TREND|null
  provisional_stop_distance_fraction: float|null
  provisional_take_profit_distance_fraction: float|null
  abstain_recommended: bool
  abstain_reasons: list[string]
  allocator_config_version: string
  methodology_version: 2.0.0
```

Invariants:

```text
weights are in [0,1] and sum to 1
FLAT implies preliminary target = 0
abs(preliminary target) <= 1
active strategy weights are not renormalized upward
cash = 1 - sum(active expert scores)
```

## 10. Module 3 contracts

### 10.1 RiskLimits.v1

```yaml
contract: RiskLimits.v1
fields:
  deployment_id: string
  target_symbol: BTC
  trading_instrument_id: string
  max_abs_position_fraction: 1.0
  max_abs_target_change_per_decision: float
  max_daily_turnover_fraction: float
  max_daily_loss_abs: decimal
  max_rolling_loss_abs: decimal
  max_drawdown_fraction: float
  max_margin_fraction: float
  minimum_liquidation_buffer_fraction: float
  max_expected_round_trip_cost_bps: float
  max_absolute_funding_rate: float
  maximum_normalised_entropy: float
  minimum_maximum_probability: float
  max_decision_age_seconds: integer
  config_version: string
```

### 10.2 ApprovedTargetPosition.v1

```yaml
contract: ApprovedTargetPosition.v1
fields:
  approval_id: string
  proposal_id: string
  deployment_id: string
  as_of: datetime_utc
  valid_until: datetime_utc
  target_symbol: BTC
  trading_instrument_id: string
  status: APPROVED|CLIPPED|REJECTED|HALTED
  current_position_fraction: float
  allocator_target_position_fraction: float
  risk_position_cap: float
  approved_target_position_fraction: float
  approved_target_notional: decimal
  approved_stop_atr_multiple: float|null
  approved_take_profit_atr_multiple: float|null
  approved_maximum_holding_minutes: integer|null
  reduce_only_required: bool
  projected_margin_fraction: float
  projected_liquidation_buffer_fraction: float|null
  triggered_rules: list[string]
  rejection_reason: string|null
  risk_config_version: string
```

Invariants:

```text
approved notional = approved target fraction × allocated equity
abs(approved target fraction) <= 1
approved absolute target <= abs(risk_position_cap)
REJECTED and HALTED cannot increase absolute exposure
abstention cannot increase absolute exposure
BROKEN reconciliation cannot increase absolute exposure
expired approval cannot be executed
```

The Risk Engine does not emit side, quantity, order type or price.

## 11. Execution boundary contracts

### 11.1 ExecutionPlan.v1

```yaml
contract: ExecutionPlan.v1
fields:
  execution_plan_id: string
  approval_id: string
  deployment_id: string
  target_symbol: BTC
  trading_instrument_id: string
  current_reconciled_notional: decimal
  target_notional: decimal
  delta_notional: decimal
  urgency: REDUCE_ONLY|NORMAL|EMERGENCY
  idempotency_key: string
  created_at: datetime_utc
  status: CREATED|SUBMITTING|PARTIALLY_FILLED|FILLED|CANCELLED|FAILED|RECONCILIATION_REQUIRED
```

### 11.2 ExecutionReport.v1

```yaml
contract: ExecutionReport.v1
fields:
  execution_plan_id: string
  approval_id: string
  completed_at: datetime_utc|null
  submitted_orders: list
  fills: list
  fees_paid: decimal
  funding_paid: decimal
  realised_slippage_bps: float|null
  final_reconciled_position_notional: decimal|null
  final_reconciled_position_fraction: float|null
  final_mark_price: decimal|null
  final_liquidation_price: decimal|null
  final_liquidation_buffer_fraction: float|null
  reconciliation_status: RECONCILED|PENDING|BROKEN
  failure_reason: string|null
```

## 12. Artifact contracts

### 12.1 RegimeModelArtifact.v1

```yaml
contract: RegimeModelArtifact.v1
fields:
  model_id: string
  target_symbol: BTC
  trading_instrument_id: string
  feature_set_hash: string
  scaler_state: object
  transition_matrix: object
  emission_parameters: object
  state_signatures: RegimeStateSignature.v1[]
  seed_list: list[integer]
  converged_seed_count: integer
  seed_stability_metrics: object
  training_window: [datetime_utc, datetime_utc]
  inner_metrics: object
  completed_outer_metrics: object
  methodology_version: 2.0.0
  code_commit: string
  dependency_lock_hash: string
  artifact_hash: string
```

### 12.2 AllocatorConfigArtifact.v1

```yaml
contract: AllocatorConfigArtifact.v1
fields:
  target_symbol: BTC
  trading_instrument_id: string
  affinity_matrix: RegimeStrategyAffinityMatrix.v1
  strategy_config: StrategyConfig.v1
  exit_profiles: ExitProfile.v1[]
  training_window: [datetime_utc, datetime_utc]
  validation_metrics: object
  methodology_version: 2.0.0
  code_commit: string
  artifact_hash: string
```

### 12.3 CompatibleArtifactSet.v1

```yaml
contract: CompatibleArtifactSet.v1
fields:
  artifact_set_id: string
  deployment_id: string
  target_symbol: BTC
  trading_instrument_spec: BTCLinearPerpetualSpec.v1
  reference_spot_spec: BTCSpotReferenceSpec.v1
  small_account_capability: SmallAccountCapability.v1
  regime_model_id: string
  allocator_artifact_hash: string
  risk_config_version: string
  operations_config_version: string
  feature_contract_version: string
  methodology_version: 2.0.0
  cost_model_version: string
  execution_adapter_version: string
  decision_timing_version: string
  code_commit: string
  dependency_lock_hash: string
  compatibility_hash: string
```

The complete set is loaded, promoted and rolled back atomically.

## 13. Audit contract

### 13.1 DecisionAuditRecord.v1

```yaml
contract: DecisionAuditRecord.v1
fields:
  decision_id: string
  deployment_id: string
  as_of: datetime_utc
  target_symbol: BTC
  trading_instrument_id: string
  compatible_artifact_set_id: string
  capital_allocation: CapitalAllocation.v1
  timing: DecisionTiming.v1
  feature_frame: MarketFeatureFrame.v1
  regime_prediction: RegimePrediction.v1
  expert_signals: StrategyExpertSignal.v1[]
  allocation_proposal: AllocationProposal.v1
  portfolio_state_before: PortfolioState.v1
  operational_state: OperationalState.v1
  approved_target: ApprovedTargetPosition.v1
  execution_report: ExecutionReport.v1|null
  portfolio_state_after: PortfolioState.v1|null
  methodology_version: 2.0.0
  record_hash: string
```

The record is immutable and sufficient to reproduce the analytical BTC-perpetual decision from pinned source data, code, dependencies, artifacts, methodology and configurations.
