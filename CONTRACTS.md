# Contracts

This document is normative for Production V1. Every field has one unit and one owner. Undefined fields, implicit defaults, cross-symbol payloads, and silent fallbacks are prohibited.

The architecture is defined in [`ARCHITECTURE.md`](ARCHITECTURE.md). Runtime requirements are defined in [`OPERATIONS.md`](OPERATIONS.md).

## 1. Global rules

```text
target_symbol ∈ {BTC, ETH, SOL}
selected_instrument_type ∈ {SPOT, PERPETUAL}
all timestamps use UTC
all monetary values use the exchange settlement currency
all percentages are decimal fractions unless the field name ends in _bps
one basis point = 0.0001
```

Global invariants:

```text
one deployment uses one target_symbol
one deployment trades one selected instrument
all payloads in a decision chain share deployment_id, target_symbol, and instrument_id
source rows satisfy symbol == target_symbol
cross-asset features are prohibited
future targets are prohibited from inference payloads
feature inputs use closed source buckets only
wrong-symbol or wrong-instrument input fails closed
```

## 2. Common types and units

### 2.1 Position fraction

```text
position_fraction = signed instrument notional / allocated_equity
```

Bounds:

```text
SPOT:       [0.00, 1.00]
PERPETUAL: [-1.00, 1.00]
```

### 2.2 Direction

```text
SHORT = -1
FLAT  =  0
LONG  = +1
```

### 2.3 Notional

`notional` is absolute or signed settlement-currency exposure. It is never a base-asset quantity.

### 2.4 Quantity

`quantity` is base-asset or contract quantity and is owned by the execution system. Analytical contracts do not produce exchange quantity.

### 2.5 Price

Prices are settlement currency per base asset unless the exchange instrument explicitly defines a contract multiplier. Contract multiplier conversion is owned by execution.

## 3. Deployment and capital contracts

### 3.1 CapitalAllocation.v1

Produced by an external account-level capital service.

```yaml
contract: CapitalAllocation.v1
fields:
  deployment_id: string
  target_symbol: BTC|ETH|SOL
  settlement_currency: string
  allocated_equity: decimal
  max_loss_budget: decimal
  max_margin_budget: decimal
  valid_from: datetime_utc
  valid_until: datetime_utc
  allocation_version: string
```

Invariants:

```text
allocated_equity > 0
0 < max_loss_budget <= allocated_equity
0 < max_margin_budget <= allocated_equity
allocation is valid at decision as_of
```

### 3.2 DeploymentConfig.v1

```yaml
contract: DeploymentConfig.v1
fields:
  deployment_id: string
  target_symbol: BTC|ETH|SOL
  selected_instrument_id: string
  selected_instrument_type: SPOT|PERPETUAL
  exchange: string
  settlement_currency: string
  decision_interval_minutes: 60
  primary_horizon_minutes: 240
  stress_horizon_minutes: 1440
  source_dataset_id: gold.market.history_full.m1
  compatible_artifact_set_id: string
  capital_allocation_version: string
  operations_config_version: string
```

Invariants:

```text
target_symbol and selected instrument are immutable for process lifetime
all artifacts declare the same symbol, instrument, decision interval, and horizons
startup fails on unresolved version, hash, symbol, instrument, or expiry mismatch
PERPETUAL absolute max position fraction <= 1.0
```

## 4. Instrument contracts

### 4.1 InstrumentCandidate.v1

```yaml
contract: InstrumentCandidate.v1
fields:
  target_symbol: BTC|ETH|SOL
  exchange: string
  instrument_id: string
  instrument_type: SPOT|PERPETUAL
  settlement_currency: string
  contract_multiplier: decimal
  min_quantity: decimal
  quantity_step: decimal
  price_tick: decimal
  reduce_only_supported: bool
  short_supported: bool
  max_supported_leverage: decimal
  margin_mode: NONE|ISOLATED
  fee_schedule_version: string
  execution_adapter_version: string
  simulator_version: string
```

Production V1 invariants:

```text
SPOT short_supported = false
SPOT max_supported_leverage = 1
SPOT margin_mode = NONE
PERPETUAL reduce_only_supported = true
PERPETUAL short_supported = true
PERPETUAL max deployed leverage <= 1
```

### 4.2 InstrumentUniverse.v1

```yaml
contract: InstrumentUniverse.v1
fields:
  universe_id: string
  target_symbol: BTC|ETH|SOL
  candidates: InstrumentCandidate.v1[]
  minimum_decision_grid_coverage: 0.995
  maximum_gap_minutes: 180
  minimum_median_daily_quote_volume: decimal
  minimum_calmar_improvement: 0.10
  selection_config_version: string
```

### 4.3 InstrumentEligibilityResult.v1

```yaml
contract: InstrumentEligibilityResult.v1
fields:
  target_symbol: BTC|ETH|SOL
  instrument_id: string
  eligible: bool
  decision_grid_coverage: float
  maximum_gap_minutes: integer
  median_daily_quote_volume: decimal
  cost_model_complete: bool
  simulator_live_parity: bool
  execution_supported: bool
  reconciliation_supported: bool
  failed_gates: list[string]
```

### 4.4 InstrumentFoldMetrics.v1

All returns are net of fees, spread, slippage, and funding.

```yaml
contract: InstrumentFoldMetrics.v1
fields:
  outer_fold_id: string
  target_symbol: BTC|ETH|SOL
  instrument_id: string
  annualised_net_return: float
  maximum_drawdown_abs: float
  net_calmar: float|null
  cvar_95_loss_abs: float
  annualised_turnover: float
  net_sharpe: float|null
  profitable: bool
  positive_pnl: decimal
```

`net_calmar` is null when maximum drawdown is zero. A candidate with non-positive annualised net return is non-promotable regardless of numerical ratio.

### 4.5 InstrumentSelectionReport.v1

```yaml
contract: InstrumentSelectionReport.v1
fields:
  report_id: string
  target_symbol: BTC|ETH|SOL
  universe_id: string
  completed_outer_fold_ids: list[string]
  eligibility_results: InstrumentEligibilityResult.v1[]
  fold_metrics: InstrumentFoldMetrics.v1[]
  selected_instrument_id: string
  selected_instrument_type: SPOT|PERPETUAL
  median_net_calmar_by_instrument: map[string, float|null]
  median_cvar_95_loss_by_instrument: map[string, float]
  median_annualised_net_return_by_instrument: map[string, float]
  median_annualised_turnover_by_instrument: map[string, float]
  paired_calmar_difference_ci_95: [float, float]|null
  median_calmar_improvement: float|null
  selection_reason: string
  selection_config_version: string
  code_commit: string
```

Perpetual selection invariant:

```text
selected PERPETUAL requires:
- all eligibility gates pass
- lower paired Calmar CI bound > 0
- median Calmar improvement >= minimum_calmar_improvement
- all risk and cost-stress gates pass
```

Otherwise an eligible spot candidate is preferred.

## 5. Upstream and timing contracts

### 5.1 Upstream dataset

```text
dataset_id: gold.market.history_full.m1
grain: timestamp_m1, exchange, symbol
```

Production V1 consumes same-asset:

- spot OHLCV;
- perpetual OHLCV;
- funding and freshness;
- open interest and freshness;
- perpetual trade-flow aggregates.

Options trade flow is not a Production V1 dependency.

### 5.2 DecisionTiming.v1

```yaml
contract: DecisionTiming.v1
fields:
  as_of: datetime_utc
  latest_included_bucket_close: datetime_utc
  feature_completed_at: datetime_utc
  decision_persisted_at: datetime_utc
  earliest_execution_at: datetime_utc
  maximum_decision_age_seconds: integer
  timing_config_version: string
```

Invariants:

```text
latest_included_bucket_close = as_of
feature_completed_at > as_of
decision_persisted_at >= feature_completed_at
earliest_execution_at > decision_persisted_at
current time - as_of <= maximum_decision_age_seconds before exposure increase
```

### 5.3 HistoricalFillPolicy.v1

```yaml
contract: HistoricalFillPolicy.v1
fields:
  entry_rule: NEXT_M1_OPEN_STRICTLY_AFTER_AS_OF
  same_bar_exit_priority: STOP_FIRST
  gap_stop_rule: FIRST_TRADABLE_PRICE_PLUS_ADVERSE_SLIPPAGE
  spread_model_version: string
  slippage_model_version: string
  fee_model_version: string
  funding_model_version: string
  policy_version: string
```

## 6. Feature contracts

### 6.1 Feature freshness defaults

```yaml
funding_max_age_minutes: 480
open_interest_max_age_minutes: 120
perpetual_trade_flow_max_age_minutes: 60
price_max_age_minutes: 2
```

These defaults are versioned. A value older than its limit is unavailable.

### 6.2 Core feature definitions

All lookbacks end at `as_of` and use closed buckets only.

#### return_24h

```text
return_24h = ln(perp_close_as_of / perp_close_24h_before)
```

Both prices must be available and positive.

#### realized_volatility_24h

Let `hourly_return_j` be the 24 consecutive hourly log returns ending at `as_of`.

```text
realized_volatility_24h = sqrt(365 * sum(hourly_return_j^2))
```

The output is annualised decimal volatility. All 24 returns are required.

#### funding_zscore_30d

Use only distinct observed funding events, not repeated forward-filled M1 rows.

```text
funding_zscore_30d =
    (latest_funding_rate - mean(observed_funding_rates_30d))
    / max(sample_std(observed_funding_rates_30d), feature_epsilon)
```

At least 30 observed funding events and a fresh latest observation are required.

#### open_interest_change_24h

```text
open_interest_change_24h = ln(open_interest_as_of / open_interest_24h_before)
```

Both observations must be positive and pass freshness limits.

#### buy_volume_share_4h

```text
buy_volume_share_4h =
    sum(perps_trades_buy_volume over 4h)
    / sum(perps_trades_volume over 4h)
```

The denominator must be positive. Trade rows are never imputed.

#### atr_24h

Aggregate M1 prices into 24 closed hourly bars. For each hour:

```text
true_range = max(
    high - low,
    abs(high - previous_close),
    abs(low - previous_close)
)

atr_24h = mean(last 24 true_range values)
```

### 6.3 RobustScalerState.v1

```yaml
contract: RobustScalerState.v1
fields:
  ordered_features:
    - return_24h
    - realized_volatility_24h
    - funding_zscore_30d
    - open_interest_change_24h
    - buy_volume_share_4h
  median_by_feature: map[string, float]
  iqr_by_feature: map[string, float]
  scaler_epsilon: float
  fitted_from: datetime_utc
  fitted_to: datetime_utc
  scaler_hash: string
```

Scaling formula:

```text
scaled = (value - median) / max(IQR, scaler_epsilon)
```

### 6.4 MarketFeatureFrame.v1

```yaml
contract: MarketFeatureFrame.v1
keys:
  deployment_id: string
  as_of: datetime_utc
  target_symbol: BTC|ETH|SOL
fields:
  return_24h: float|null
  realized_volatility_24h: float|null
  funding_zscore_30d: float|null
  open_interest_change_24h: float|null
  buy_volume_share_4h: float|null
  atr_24h: float|null
  source_availability: map[string, bool]
  observation_age_minutes: map[string, float|null]
  data_quality_status: PASS|FAIL
  failure_reasons: list[string]
metadata:
  source_dataset_version: string
  source_data_hash: string
  feature_contract_version: string
  feature_set_hash: string
  feature_build_commit: string
  timing: DecisionTiming.v1
```

Production V1 does not emit `DEGRADED`. All five core features and `atr_24h` must be valid. Otherwise status is `FAIL`.

### 6.5 TrainingTargetFrame.v1

Training and evaluation only.

```yaml
contract: TrainingTargetFrame.v1
keys:
  as_of: datetime_utc
  target_symbol: BTC|ETH|SOL
  instrument_id: string
fields:
  forward_net_return_4h: float|null
  forward_drawdown_4h_abs: float|null
  forward_realized_volatility_4h: float|null
  forward_drawdown_1d_abs: float|null
metadata:
  fill_policy_version: string
  cost_model_version: string
  target_contract_version: string
```

The full future interval and simulated execution costs are required. Targets never enter live inference.

## 7. Cost and state contracts

### 7.1 CostModelSnapshot.v1

```yaml
contract: CostModelSnapshot.v1
fields:
  as_of: datetime_utc
  target_symbol: BTC|ETH|SOL
  instrument_id: string
  instrument_type: SPOT|PERPETUAL
  maker_fee_bps: float
  taker_fee_bps: float
  expected_half_spread_bps: float
  expected_entry_slippage_bps: float
  expected_exit_slippage_bps: float
  expected_funding_bps_4h: float
  estimated_capacity_notional: decimal
  scenario: BASE|ELEVATED|SEVERE|LIVE
  cost_model_version: string
```

For spot, `expected_funding_bps_4h = 0`.

### 7.2 PortfolioState.v1

```yaml
contract: PortfolioState.v1
fields:
  as_of: datetime_utc
  deployment_id: string
  target_symbol: BTC|ETH|SOL
  instrument_id: string
  allocated_equity: decimal
  cash_available: decimal
  current_position_fraction: float
  current_position_notional: decimal
  current_average_entry_price: decimal|null
  current_unrealised_pnl: decimal
  current_realised_pnl_day: decimal
  current_drawdown_abs: float
  rolling_loss_abs: float
  current_stop_price: decimal|null
  current_take_profit_price: decimal|null
  position_opened_at: datetime_utc|null
  reconciliation_status: RECONCILED|PENDING|BROKEN
  pending_execution_plan_id: string|null
```

No virtual opposing positions exist in Production V1.

### 7.3 OperationalState.v1

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
  decision_lock_available: bool
  kill_switch_active: bool
  active_incident_id: string|null
```

## 8. Module 1 contracts

### 8.1 RegimeTrainingConfig.v1

```yaml
contract: RegimeTrainingConfig.v1
fields:
  target_symbol: BTC|ETH|SOL
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
  config_version: string
```

### 8.2 RegimePrediction.v1

```yaml
contract: RegimePrediction.v1
fields:
  deployment_id: string
  as_of: datetime_utc
  target_symbol: BTC|ETH|SOL
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
each probability is finite and in [0,1]
each vector sums to 1 within tolerance
normalised_entropy is in [0,1]
maximum_probability = max(current_probabilities)
most_likely_state = argmax(current_probabilities)
FAIL or INVALID forces abstain_recommended = true
```

### 8.3 RegimeStateSignature.v1

```yaml
contract: RegimeStateSignature.v1
fields:
  signature_id: string
  target_symbol: BTC|ETH|SOL
  mean_return_4h: float
  realized_volatility_4h: float
  downside_volatility_4h: float
  trend_strength: float
  mean_drawdown_4h_abs: float
  mean_funding_zscore: float
  mean_open_interest_change: float
  mean_buy_volume_share: float
  median_duration_steps: float
  occupancy: float
```

## 9. Strategy expert contracts

### 9.1 StrategyConfig.v1

```yaml
contract: StrategyConfig.v1
fields:
  trend:
    fast_ema_hours: 24
    slow_ema_hours: 72
    minimum_distance_fraction: float
    strength_scale_fraction: float
  momentum:
    return_window_hours: 12
    minimum_vol_scaled_return: float
    strength_scale: float
  mean_reversion:
    zscore_window_hours: 24
    entry_zscore: float
    strength_scale_zscore: float
  config_version: string
```

### 9.2 StrategyExpertSignal.v1

```yaml
contract: StrategyExpertSignal.v1
fields:
  deployment_id: string
  as_of: datetime_utc
  target_symbol: BTC|ETH|SOL
  strategy_id: TREND|MOMENTUM|MEAN_REVERSION
  direction: -1|0|1
  strength: float
  confidence: float
  expected_holding_minutes: integer
  estimated_round_trip_cost_bps: float
  data_quality_status: PASS|FAIL
  strategy_version: string
```

Invariants:

```text
strength and confidence are in [0,1]
FAIL forces direction = 0, strength = 0, confidence = 0
one signal per strategy and as_of
```

## 10. Module 2 contracts

### 10.1 RegimeStrategyAffinityMatrix.v1

```yaml
contract: RegimeStrategyAffinityMatrix.v1
fields:
  target_symbol: BTC|ETH|SOL
  instrument_id: string
  state_signature_ids: [string, string, string]
  strategy_order: [TREND, MOMENTUM, MEAN_REVERSION]
  affinity_matrix: [[float, float, float], [float, float, float], [float, float, float]]
  affinity_epsilon: float
  minimum_cash_fraction: float
  minimum_consensus_evidence: float
  minimum_direction_dominance: float
  target_volatility_annual: float
  volatility_floor: float
  config_version: string
```

All affinity values are in `[0,1]`. Each row sum is no greater than `1 - minimum_cash_fraction`.

### 10.2 ExitProfile.v1

```yaml
contract: ExitProfile.v1
fields:
  profile_id: MEAN_REVERSION|MOMENTUM|TREND
  stop_atr_multiple: float
  take_profit_atr_multiple: float
  maximum_holding_minutes: integer
  profile_version: string
```

Production defaults:

```text
MEAN_REVERSION: stop 1.0, take profit 1.5, max holding 240 minutes
MOMENTUM:       stop 1.5, take profit 2.5, max holding 1440 minutes
TREND:          stop 2.0, take profit 4.0, max holding 4320 minutes
```

### 10.3 AllocationProposal.v1

```yaml
contract: AllocationProposal.v1
fields:
  proposal_id: string
  deployment_id: string
  as_of: datetime_utc
  target_symbol: BTC|ETH|SOL
  instrument_id: string
  strategy_contribution_weights:
    trend: float
    momentum: float
    mean_reversion: float
    cash: float
  consensus_direction: SHORT|FLAT|LONG
  regime_certainty: float
  volatility_multiplier: float
  global_risk_multiplier: float
  proposed_target_position_fraction: float
  dominant_strategy: TREND|MOMENTUM|MEAN_REVERSION|null
  exit_profile_id: MEAN_REVERSION|MOMENTUM|TREND|null
  abstain_recommended: bool
  abstain_reasons: list[string]
  allocator_config_version: string
```

Invariants:

```text
all contribution weights are in [0,1]
contribution weights sum to 1
regime certainty, volatility multiplier, and risk multiplier are in [0,1]
FLAT implies proposed target position fraction = 0
SPOT implies proposed target position fraction >= 0
absolute proposed target position fraction <= 1
abstention cannot propose a larger absolute exposure than the current reconciled exposure
```

## 11. Module 3 contracts

### 11.1 RiskLimits.v1

```yaml
contract: RiskLimits.v1
fields:
  deployment_id: string
  target_symbol: BTC|ETH|SOL
  instrument_id: string
  max_abs_position_fraction: float
  max_abs_target_change_per_decision: float
  max_daily_turnover_fraction: float
  max_daily_loss_abs: float
  max_rolling_loss_abs: float
  max_drawdown_abs: float
  max_margin_fraction: float
  minimum_liquidation_buffer_fraction: float
  max_expected_round_trip_cost_bps: float
  maximum_normalised_entropy: float
  minimum_maximum_probability: float
  max_decision_age_seconds: integer
  config_version: string
```

### 11.2 ApprovedTargetPosition.v1

```yaml
contract: ApprovedTargetPosition.v1
fields:
  approval_id: string
  proposal_id: string
  deployment_id: string
  as_of: datetime_utc
  valid_until: datetime_utc
  target_symbol: BTC|ETH|SOL
  instrument_id: string
  status: APPROVED|CLIPPED|REJECTED|HALTED
  current_position_fraction: float
  approved_target_position_fraction: float
  approved_target_notional: decimal
  approved_stop_atr_multiple: float|null
  approved_take_profit_atr_multiple: float|null
  approved_maximum_holding_minutes: integer|null
  reduce_only_required: bool
  triggered_rules: list[string]
  rejection_reason: string|null
  risk_config_version: string
```

Invariants:

```text
approved_target_notional = approved_target_position_fraction * allocated_equity
absolute approved target <= configured and instrument bounds
REJECTED and HALTED cannot increase absolute exposure
abstention cannot increase absolute exposure
BROKEN reconciliation cannot increase absolute exposure
expired approval cannot be executed
```

The Risk Engine does not emit side, quantity, order type, limit price, or child orders.

## 12. Execution boundary contracts

### 12.1 ExecutionPlan.v1

Produced by the external execution system from `ApprovedTargetPosition.v1`.

```yaml
contract: ExecutionPlan.v1
fields:
  execution_plan_id: string
  approval_id: string
  deployment_id: string
  target_symbol: BTC|ETH|SOL
  instrument_id: string
  current_reconciled_notional: decimal
  target_notional: decimal
  delta_notional: decimal
  urgency: REDUCE_ONLY|NORMAL|EMERGENCY
  idempotency_key: string
  created_at: datetime_utc
  status: CREATED|SUBMITTING|PARTIALLY_FILLED|FILLED|CANCELLED|FAILED|RECONCILIATION_REQUIRED
```

### 12.2 ExecutionReport.v1

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
  reconciliation_status: RECONCILED|PENDING|BROKEN
  failure_reason: string|null
```

## 13. Artifact contracts

### 13.1 RegimeModelArtifact.v1

```yaml
contract: RegimeModelArtifact.v1
fields:
  model_id: string
  target_symbol: BTC|ETH|SOL
  feature_set_hash: string
  scaler_state: RobustScalerState.v1
  transition_matrix: object
  emission_parameters: object
  state_signatures: RegimeStateSignature.v1[]
  seed_list: list[integer]
  converged_seed_count: integer
  seed_stability_metrics: object
  training_window: [datetime_utc, datetime_utc]
  inner_metrics: object
  completed_outer_metrics: object
  code_commit: string
  dependency_lock_hash: string
  artifact_hash: string
```

### 13.2 AllocatorConfigArtifact.v1

```yaml
contract: AllocatorConfigArtifact.v1
fields:
  target_symbol: BTC|ETH|SOL
  instrument_id: string
  affinity_matrix: RegimeStrategyAffinityMatrix.v1
  strategy_config: StrategyConfig.v1
  exit_profiles: ExitProfile.v1[]
  training_window: [datetime_utc, datetime_utc]
  validation_metrics: object
  code_commit: string
  artifact_hash: string
```

### 13.3 CompatibleArtifactSet.v1

```yaml
contract: CompatibleArtifactSet.v1
fields:
  artifact_set_id: string
  deployment_id: string
  target_symbol: BTC|ETH|SOL
  selected_instrument_id: string
  selected_instrument_type: SPOT|PERPETUAL
  instrument_selection_report_id: string
  regime_model_id: string
  allocator_artifact_hash: string
  risk_config_version: string
  feature_contract_version: string
  cost_model_version: string
  execution_adapter_version: string
  decision_timing_version: string
  code_commit: string
  dependency_lock_hash: string
  compatibility_hash: string
```

A production deployment loads the set atomically. Partial artifact substitution is prohibited.

## 14. Audit contract

### 14.1 DecisionAuditRecord.v1

```yaml
contract: DecisionAuditRecord.v1
fields:
  decision_id: string
  deployment_id: string
  as_of: datetime_utc
  target_symbol: BTC|ETH|SOL
  instrument_id: string
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
  record_hash: string
```

The record is immutable and sufficient to reproduce the analytical decision from pinned source data, code, dependencies, artifacts, and configurations.
