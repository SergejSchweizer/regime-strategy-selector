# Architecture and Contracts

This document is the normative system-design and interface specification for Production V1. Undefined fields, implicit defaults, alternative trading instruments, cross-asset payloads and silent fallbacks are prohibited.

Exact calculations and validation methodology are defined in [`METHODOLOGY.md`](METHODOLOGY.md). Runtime, MLflow, promotion and rollback rules are defined in [`OPERATIONS.md`](OPERATIONS.md).

## 1. Production scope

```text
target_symbol = BTC
traded_instrument_type = LINEAR_PERPETUAL
margin_mode = ISOLATED
position_mode = ONE_WAY
all timestamps = UTC
methodology_version = 2.0.0
```

One exchange-specific linear BTC perpetual is the only tradable instrument. BTC spot is reference information and a benchmark only. Production V1 excludes ETH, SOL, spot execution, inverse or quanto contracts, dated futures, options, cross margin, hedge mode and effective leverage above 1x.

| Concern | Production V1 rule |
|---|---|
| Decision interval | 1 hour |
| Primary horizon | 4 hours |
| Stress horizon | 1 day |
| Regime model | diagonal Gaussian HMM, 3 persistent states |
| Strategy experts | deterministic trend, momentum and mean reversion |
| Allocator | deterministic probability-weighted mapping |
| Position | one signed net BTC-perpetual position |
| Exit | one stop, one take profit and one time stop |
| Promotion | manual and atomic |
| Bandits and RL | research only |

Production V1 has one learned runtime component: the regime estimator. Strategy experts, allocation and risk enforcement are deterministic.

## 2. System boundary

```text
gold.market.history_full.m1
        | filter symbol == BTC
        | validate spot and perpetual source rows
        v
point-in-time feature service
        |-- offline-only training targets
        |-- trend expert inputs
        |-- momentum expert inputs
        `-- mean-reversion expert inputs
        v
Module 1: Regime Estimator
        | RegimePrediction.v1
        v
Module 2: Deterministic Allocator
        | AllocationProposal.v1
        v
Module 3: Deterministic Risk Engine
        | ApprovedTargetPosition.v1
        v
external BTC-perpetual execution system
        v
orders, fills, protective orders and reconciliation
```

The analytical repository stops at `ApprovedTargetPosition.v1`. Order side, exchange quantity, order type, price, maker/taker behaviour, child-order scheduling, retries and cancel/replace belong only to execution.

## 3. Global invariants and units

```text
one deployment trades one configured linear BTC perpetual
all decision-chain payloads share deployment_id and trading_instrument_id
all source rows satisfy symbol == BTC
BTC spot fields are reference-only and never become order targets
future targets are prohibited from inference payloads
all feature inputs use closed source buckets only
wrong symbol, contract type, instrument, margin mode or position mode fails closed
all percentages are decimal fractions unless a field ends in _bps
one basis point = 0.0001
```

### 3.1 Position fraction

```text
position_fraction = signed BTC-perpetual notional / allocated_equity
-1.00 <= position_fraction <= +1.00
```

`notional` is settlement-currency exposure. `quantity` is exchange contract quantity. Analytical contracts produce notional and position fractions; execution owns quantity conversion and rounding.

### 3.2 Direction

```text
SHORT = -1
FLAT  =  0
LONG  = +1
```

## 4. Market, capital and timing

### 4.1 Trading instrument

The configured perpetual must provide:

- linear settlement and BTC underlying;
- perpetual maturity and long/short support;
- isolated margin and one-way position mode;
- reduce-only orders;
- mark, index and liquidation prices;
- funding rate and funding schedule;
- known multiplier, quantity step, minimum quantity and price tick;
- reproducible fees and live position/order reconciliation.

Changing exchange or contract creates a new deployment candidate and requires complete replay, shadow, paper and canary validation.

### 4.2 Reference spot market

BTC spot may supply OHLCV, basis, market-quality diagnostics and benchmark returns. It is never an execution target and there is no silent venue substitution.

### 4.3 Capital allocation

An external capital service provides:

```text
allocated_equity
max_loss_budget
max_margin_budget
risk_per_trade_fraction
```

The Risk Engine never approves absolute notional greater than allocated equity, even when the exchange supports higher leverage.

### 4.4 Small-account capability

```text
minimum_order_notional / allocated_equity <= 0.01
quantity_step_notional / allocated_equity <= 0.01
```

Both conditions must pass. At EUR 1,000 equivalent allocation, each value must be no greater than EUR 10 equivalent in settlement currency.

### 4.5 Decision timing

`as_of` is the close of the latest M1 bucket included in a feature snapshot.

```text
latest_source_bucket_close <= as_of
feature_completed_at > as_of
decision_persisted_at >= feature_completed_at
approval_persisted_at >= decision_persisted_at
earliest_execution_at > approval_persisted_at
```

Historical execution begins at the first complete M1 bucket whose open is strictly after `as_of`. If stop and take profit are touched in the same M1 bucket and the path is unknown, the adverse stop is assumed first.

## 5. Data and feature architecture

Production V1 uses same-asset BTC data from `gold.market.history_full.m1`:

- BTC spot OHLCV;
- BTC perpetual OHLCV;
- perpetual funding and freshness;
- perpetual open interest and freshness;
- perpetual trade flow.

Trade executions, volume and trade counts are never forward-filled. Last-known state values are usable only with explicit observation age and availability metadata.

The fixed regime feature vector is:

```text
return_24h
realized_volatility_24h
funding_zscore_30d
open_interest_change_24h
buy_volume_share_4h
```

`atr_24h`, spot/perpetual basis and mark/index divergence are exit or risk diagnostics, not HMM emission features. Missing, stale, non-finite or incomplete required features produce `data_quality_status = FAIL`; no reduced feature vector or silent imputation is allowed.

Feature order, formulas, medians, interquartile ranges and epsilon are frozen in the model artifact. New features require controlled ablation against the fixed baseline, a new feature-contract version and complete outer-fold reruns.

## 6. Module architecture

### 6.1 Module 1: persistent regime estimator

```text
model_family = Gaussian HMM
covariance_type = diagonal
n_states = 3
n_initialisations = 20
minimum_stable_converged_fits = 16
```

Each training fold fits deterministic seeds, rejects non-converged or degenerate fits, aligns successful states by normalised state signatures and selects the highest-likelihood member of the stable seed cluster.

Only filtered point-in-time probabilities are valid:

```text
P(state at as_of | observations available through as_of)
```

The public output includes current probabilities, four-hour forward probabilities, entropy, maximum probability, persistent state-signature identities and abstention status. Retrospectively smoothed states are prohibited in trading backtests and runtime decisions.

A new internal state receives an existing persistent identity only when its normalised signature distance is no greater than `maximum_state_alignment_distance`. Otherwise the candidate is `ALIGNMENT_INVALID` and cannot be promoted.

Every alternative model family must expose the same `RegimePrediction.v1` contract with the same canonical persistent-state order.

### 6.2 Deterministic strategy experts

Experts consume BTC market data but not regime probabilities.

| Expert | Horizon | Economic role |
|---|---:|---|
| Mean reversion | 1-4 hours | short-horizon reversal |
| Momentum | 4-24 hours | medium-horizon continuation |
| Trend | 1-7 days | persistent direction |

Each emits direction, strength, confidence, expected holding time, estimated round-trip cost and data-quality status. A strategy that fails standalone economic gates is disabled rather than rescued by regime weighting.

### 6.3 Module 2: deterministic allocator

A versioned `affinity[state][strategy]` matrix combines the complete regime-probability vector with independent expert signals.

```text
regime_affinity_s = sum(probability_r * affinity[r][s])
expert_score_s = regime_affinity_s * strength_s * confidence_s
signed_score_s = expert_score_s * direction_s
```

Positive and negative evidence determine one consensus direction. Weak or materially conflicting evidence produces `FLAT`. Only experts agreeing with the consensus retain their score; unused allocation remains cash and active scores are not renormalised upward.

The dominant expert selects one provisional net exit profile. There are no sleeve-level exchange positions or opposing sleeve stops.

### 6.4 Module 3: deterministic risk engine

The Risk Engine returns `APPROVED`, `CLIPPED`, `REJECTED` or `HALTED`. It enforces:

- exact BTC instrument equality and linear contract semantics;
- isolated margin and one-way mode;
- absolute position fraction no greater than 1.0;
- stop-distance-based risk-per-trade sizing;
- capital, loss and margin budgets;
- minimum liquidation buffer;
- funding, fee, spread, slippage and cost limits;
- daily loss, rolling loss and drawdown limits;
- target-change and turnover limits;
- data freshness, entropy and abstention;
- reconciliation, pending-plan and kill-switch state.

Abstention or uncertainty may preserve or reduce exposure but may never increase absolute exposure.

### 6.5 External execution

Execution owns target-delta calculation, contract quantity, rounding, order construction, maker/taker decisions, slicing, partial fills, cancel/replace, reduce-only protective orders and reconciliation. Every approval creates at most one logical execution plan through deterministic idempotency.

## 7. Public contract catalogue

The schemas below are normative. Implementations may use generated classes, JSON Schema, Pydantic or another typed representation, but field names, units and invariants must remain compatible.

### 7.1 Deployment and capital

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

Invariants: `allocated_equity > 0`; loss and margin budgets are positive and no greater than equity; `0 < risk_per_trade_fraction <= 0.02`; allocation is valid at decision `as_of`. Recommended canary default: `0.005`.

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

Instrument identity and symbol are immutable for process lifetime. Startup fails on version, hash, instrument, symbol, margin-mode or position-mode mismatch.

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

### 7.2 Instrument specifications

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

Inverse or quanto settlement is prohibited.

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

This contract has no execution permissions.

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

`PASS` requires both fractions to be no greater than `0.01`.

### 7.3 Timing and data

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

`PASS` requires finite core features, closed buckets, matching instruments and no future target or non-BTC field. `FAIL` forbids exposure increase.

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

Targets are offline only.

### 7.4 Runtime state

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

Absolute position fraction cannot exceed 1. `BROKEN` reconciliation forbids exposure increase.

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

### 7.5 Regime estimator

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

Both probability vectors must be finite, bounded in `[0,1]` and sum to 1. `FAIL` or `INVALID` forces abstention.

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

### 7.6 Strategy and allocation

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

`FAIL` sets direction, strength and confidence to zero.

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

Affinities are in `[0,1]`; each state row sums to no more than `1 - minimum_cash_fraction`.

```yaml
contract: ExitProfile.v1
fields:
  profile_id: MEAN_REVERSION|MOMENTUM|TREND
  stop_atr_multiple: float
  take_profit_atr_multiple: float
  maximum_holding_minutes: integer
  profile_version: string
```

Production defaults are mean reversion `1.0/1.5/240`, momentum `1.5/2.5/1440`, and trend `2.0/4.0/4320` for stop ATR multiple, take-profit ATR multiple and minutes.

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

Weights sum to 1, `FLAT` implies a zero target, absolute target is no greater than 1 and active weights are not renormalised upward.

### 7.7 Risk and execution boundary

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

Approved notional equals approved fraction times allocated equity. Rejected, halted, abstaining, expired or unreconciled decisions cannot increase exposure. The Risk Engine emits no order side, quantity, type or price.

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

### 7.8 Immutable artifacts and audit

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

The audit record is immutable and sufficient to reproduce the analytical decision from pinned data, code, dependencies, models and configurations.

## 8. Compatibility and evolution

Any change to field names, units, persistent state order, feature order, model output semantics, instrument identity, exit-profile semantics, timing or risk interpretation requires a new contract or configuration version.

The following components form one compatibility boundary:

```text
BTC perpetual specification
BTC spot reference specification
feature contract and scaler
regime model and persistent state mapping
affinity matrix
strategy configuration
exit profile set
risk and operations configuration
cost model and timing policy
execution adapter
code commit and dependency lock
```

Production must never independently load the latest version of each component.

## 9. Production readiness

Activation requires executable contract validation, exact historical/live feature parity, stable multi-seed regime fits, valid persistent-state alignment, standalone strategy evidence after costs, deterministic allocator improvement over required baselines, complete funding and cost stress, liquidation-buffer tests, risk-engine property and replay tests, paper cost calibration, successful small-capital canary operation, immutable audit records and tested atomic rollback.