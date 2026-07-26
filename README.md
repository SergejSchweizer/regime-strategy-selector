# Regime Strategy Selector

A production-oriented, probabilistic trading architecture for BTC and ETH built from the historical core data produced by [`crypto-history-loader`](https://github.com/SergejSchweizer/crypto-history-loader).

The system contains three strictly separated modules:

1. **Regime Estimator** — estimates probabilities for three latent market regimes.
2. **Strategy Allocator** — combines regime probabilities with independent trend, momentum, and mean-reversion experts and proposes portfolio risk budgets, signed target exposures, and exit profiles.
3. **Deterministic Risk Engine** — validates, clips, nets, or rejects the proposal before any order intent can be emitted.

The source-of-truth dataset for version 1 is:

```text
gold.market.history_full.m1
```

All model features, training targets, strategy signals, cost estimates, and risk inputs must be derived from that historical core or supplied by explicit portfolio, exchange, and execution contracts.

---

## 1. Architecture

```text
gold.market.history_full.m1
              │
              ▼
   Point-in-time feature builder
              │
              ├──────────────► TrainingTargetFrame.v1
              │                  training/evaluation only
              ▼
      MarketFeatureFrame.v1
              │
              ├──────────────► Trend Expert
              ├──────────────► Momentum Expert
              └──────────────► Mean-Reversion Expert
              │                  StrategyExpertSignal.v1[]
              ▼
┌──────────────────────────────────────┐
│ Module 1: Regime Estimator           │
│ three current and forward            │
│ regime-probability vectors           │
└───────────────────┬──────────────────┘
                    │ RegimePrediction.v1
                    ▼
┌──────────────────────────────────────┐
│ Module 2: Strategy Allocator         │
│ risk budgets, signed target          │
│ exposures, cash reserve, exit profile│
└───────────────────┬──────────────────┘
                    │ AllocationProposal.v1
                    ▼
┌──────────────────────────────────────┐
│ Module 3: Deterministic Risk Engine  │
│ data gates, limits, netting,         │
│ clipping, circuit breakers           │
└───────────────────┬──────────────────┘
                    │ RiskDecision.v1
                    ▼
          Approved order intents
                    │
                    ▼
       External execution subsystem
```

The execution subsystem is deliberately outside the three analytical modules. It owns order placement, acknowledgements, fills, cancellations, retries, reconciliation, and exchange-specific state.

---

## 2. Core design decisions

### 2.1 One joint market regime

Version 1 estimates one joint BTC/ETH market regime rather than unrelated regime labels per asset.

The Regime Estimator consumes synchronized BTC and ETH features and emits:

```text
scope = BTC_ETH_MARKET
three current regime probabilities
three forward regime probabilities for each configured horizon
```

The three strategy experts still emit signals per asset. The Strategy Allocator therefore allocates across six strategy sleeves:

```text
BTC × trend
BTC × momentum
BTC × mean_reversion
ETH × trend
ETH × momentum
ETH × mean_reversion
```

plus cash.

### 2.2 Fixed decision clock

Raw data remains M1, but every research run and production model must declare one decision interval. The recommended first production candidate is hourly.

```yaml
decision_interval: 1h
feature_source_grain: 1m
decision_timestamp_rule: closed_bucket_only
```

All features must be computed from fully closed source buckets. A model trained on one decision interval cannot be deployed on another interval without a new artifact and validation run.

### 2.3 Probability context, not hard routing

The Regime Estimator does not decide which strategy trades. It provides probabilistic context.

The Strategy Allocator receives the complete probability vector and may allocate to several experts simultaneously. Cash is always a valid action.

### 2.4 Independent strategy experts

Trend, momentum, and mean-reversion experts do not receive regime probabilities. They must remain testable without the Regime Estimator.

This separation makes it possible to determine whether the regime layer adds genuine value over the same underlying expert signals.

### 2.5 Risk budgets are not signed positions

Allocator outputs distinguish:

- **risk budget**: non-negative share of deployable risk assigned to a sleeve;
- **signed target exposure**: positive for long, negative for short;
- **cash reserve**: non-negative unallocated capital/risk.

Risk budgets may sum to one. Signed exposures do not.

---

# 3. Upstream dataset contract

## 3.1 Grain and keys

`gold.market.history_full.m1` has one row per:

```text
timestamp_m1, exchange, symbol
```

Primary keys:

| Variable | Type | Meaning |
|---|---|---|
| `timestamp_m1` | UTC timestamp | Closed one-minute bucket |
| `exchange` | string | Normalized exchange identifier |
| `symbol` | string | Normalized base asset, initially `BTC` or `ETH` |

## 3.2 Direct source variables

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

Missing source values remain null. Event-driven trade fields must never be forward-filled. Last-known state variables may be used only together with their availability and observation-age metadata.

---

# 4. Point-in-time feature contract

## 4.1 MarketFeatureFrame.v1

The feature builder converts M1 source data into a decision-time frame.

```yaml
contract: MarketFeatureFrame.v1
keys:
  as_of: datetime_utc
  exchange: string
  scope: BTC_ETH_MARKET
fields:
  btc_features: map[string, float|int|bool|null]
  eth_features: map[string, float|int|bool|null]
  cross_asset_features: map[string, float|int|bool|null]
  availability_flags: map[string, bool]
  observation_ages: map[string, float|null]
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
all source buckets are closed at as_of
no target or future column is present
keys are unique
rows are time ordered
feature_set_hash matches the model artifact
state freshness is explicit
trade executions and volumes are never imputed
```

## 4.2 Derived feature families

All derived variables must use observations at or before `as_of`.

| Family | Candidate variables |
|---|---|
| Returns | log returns over 5m, 15m, 1h, 4h, 1d |
| Trend | EMA distance, EMA slope, breakout distance, directional persistence, rolling regression slope and fit |
| Momentum | raw returns, volatility-scaled returns, acceleration, volume-confirmed momentum |
| Mean reversion | price z-score, VWAP distance, Bollinger distance, spot-perpetual spread z-score, half-life proxy |
| Volatility | realized volatility derived from returns, high-low range estimators, downside volatility, volatility-of-volatility, jump proxy |
| Carry | funding level, change, z-score, direction, freshness |
| Leverage | open-interest change, price/open-interest interaction, open-interest freshness |
| Trade flow | buy-volume share, signed volume, buy/sell trade-count imbalance, average trade-size proxy |
| Basis | perpetual/spot spread, spread change, spread z-score |
| Activity and capacity | turnover, volume z-score, trade-count z-score, Amihud-like proxy |
| Cross-asset | BTC/ETH relative return, rolling correlation, rolling beta, correlation break, lead-lag features |
| Data quality | missingness, source age, stale-state counts, contiguous-history length |

## 4.3 Feature registry

Every candidate feature must be registered before Optuna can select it.

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

A feature is ineligible when:

- it uses a future observation;
- its timestamp semantics are ambiguous;
- it cannot be reproduced by the live feature service;
- it silently imputes event data;
- it lacks a versioned definition;
- its required lookback is unavailable.

---

# 5. Training-only target contract

Training targets are derived locally from `gold.market.history_full.m1`. They are never included in model inference inputs.

```yaml
contract: TrainingTargetFrame.v1
keys:
  as_of: datetime_utc
  scope: BTC_ETH_MARKET
fields:
  btc_forward_log_return_1h: float|null
  btc_forward_log_return_4h: float|null
  btc_forward_log_return_1d: float|null
  eth_forward_log_return_1h: float|null
  eth_forward_log_return_4h: float|null
  eth_forward_log_return_1d: float|null

  btc_forward_drawdown_1h: float|null
  btc_forward_drawdown_4h: float|null
  btc_forward_drawdown_1d: float|null
  eth_forward_drawdown_1h: float|null
  eth_forward_drawdown_4h: float|null
  eth_forward_drawdown_1d: float|null

  btc_forward_realized_volatility_1h: float|null
  btc_forward_realized_volatility_4h: float|null
  btc_forward_realized_volatility_1d: float|null
  eth_forward_realized_volatility_1h: float|null
  eth_forward_realized_volatility_4h: float|null
  eth_forward_realized_volatility_1d: float|null

  btc_cost_adjusted_return_1h: float|null
  btc_cost_adjusted_return_4h: float|null
  btc_cost_adjusted_return_1d: float|null
  eth_cost_adjusted_return_1h: float|null
  eth_cost_adjusted_return_4h: float|null
  eth_cost_adjusted_return_1d: float|null
metadata:
  target_contract_version: string
  cost_model_version: string
```

A target is null unless the full future horizon exists. The embargo used during validation must be at least as long as the longest target horizon.

---

# 6. Shared runtime contracts

## 6.1 PortfolioState.v1

Produced by the portfolio and execution subsystem.

```yaml
contract: PortfolioState.v1
fields:
  as_of: datetime_utc
  equity: float
  cash: float
  gross_exposure: float
  net_exposure: float
  current_drawdown: float
  daily_pnl: float
  rolling_pnl: float
  positions_by_symbol: map[string, float]
  virtual_sleeve_positions: map[string, float]
  unrealized_pnl_by_sleeve: map[string, float]
  realized_pnl_by_sleeve: map[string, float]
  time_in_position_by_sleeve: map[string, integer]
  realized_turnover: float
  pending_orders: list
  reconciliation_status: PASS|DEGRADED|FAIL
```

Virtual sleeves preserve strategy attribution even when opposing strategy positions are netted into one exchange position.

## 6.2 CostModelSnapshot.v1

Historical values are estimated from historical market variables and configured exchange costs. Live values are supplied by the execution subsystem.

```yaml
contract: CostModelSnapshot.v1
fields:
  as_of: datetime_utc
  symbol: BTC|ETH
  maker_fee_bps: float
  taker_fee_bps: float
  expected_spread_bps: float
  expected_slippage_bps: float
  funding_rate: float|null
  estimated_capacity_notional: float|null
  stress_multiplier: float
  cost_model_version: string
```

The backtest must evaluate at least:

```text
base cost scenario
elevated cost scenario
severe cost scenario
```

---

# 7. Module 1 — Regime Estimator

## 7.1 Responsibility

The Regime Estimator has exactly one responsibility:

> Convert a compact joint BTC/ETH point-in-time feature subset into probabilities for three latent market regimes.

It does not:

- generate strategy signals;
- allocate capital;
- size positions;
- choose stops or take profits;
- approve orders.

## 7.2 Training input

```yaml
contract: RegimeTrainingInput.v1
fields:
  features: MarketFeatureFrame.v1[]
  targets_for_diagnostics: TrainingTargetFrame.v1[]
  training_window_start: datetime_utc
  training_window_end: datetime_utc
  n_regimes: 3
  feature_registry: FeatureRegistryEntry.v1[]
  inner_walk_forward_splits: WalkForwardSplit.v1[]
  selection_config_version: string
```

Targets are used only for economic diagnostics and downstream benchmark evaluation. They are not emission variables.

## 7.3 Inference input

```yaml
contract: RegimeInferenceInput.v1
fields:
  as_of: datetime_utc
  feature_row: MarketFeatureFrame.v1
  model_id: string
```

## 7.4 Candidate models

Initial search space:

```text
Gaussian HMM with diagonal covariance
Gaussian HMM with tied covariance
Gaussian HMM with regularized full covariance
robust heavy-tailed HMM
Hidden Semi-Markov Model
Markov-switching autoregressive model
Gaussian Mixture Model baseline
change-point detector as complementary diagnostic
```

The number of latent regimes is fixed at three in version 1.

## 7.5 Output contract

```yaml
contract: RegimePrediction.v1
fields:
  as_of: datetime_utc
  scope: BTC_ETH_MARKET
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
  data_quality_status: PASS|DEGRADED|FAIL
  state_signature_ids: [string, string, string]
```

Invariants:

```text
every probability is between zero and one
each probability vector sums to one within tolerance
most_likely_regime is the largest current probability
FAIL data quality forces abstention
model/feature hashes match the deployed artifact
```

Only filtered, live-safe probabilities may be emitted:

```text
P(state at t | observations available through t)
```

Retrospectively smoothed states are prohibited for allocator training, backtesting, and live inference.

## 7.6 State alignment

Raw state numbers have no permanent economic meaning.

```yaml
contract: RegimeStateSignature.v1
fields:
  signature_id: string
  mean_market_return: float
  btc_return: float
  eth_return: float
  market_realized_volatility: float
  downside_volatility: float
  trend_strength: float
  drawdown_state: float
  funding_state: float|null
  open_interest_change: float|null
  flow_imbalance: float|null
  median_duration: float
  occupancy: float
```

States are aligned between folds and retraining dates through minimum-distance matching of normalized signatures. Downstream code must reference signature IDs, never raw state numbers.

## 7.7 Evaluation

Every trial is evaluated on purged, time-ordered inner validation folds.

### Hard rejection gates

Reject a trial when:

- the model does not converge;
- covariance or transition parameters are degenerate;
- a regime has validation occupancy below the configured minimum;
- median regime duration is shorter than the minimum useful holding horizon;
- switching exceeds the configured maximum;
- probabilities are invalid;
- features are not live reproducible;
- any preprocessing step uses future data;
- state signatures cannot be aligned consistently;
- performance depends on unavailable source history;
- feature count exceeds the configured maximum.

### Evaluation dimensions

| Dimension | Metric | Direction |
|---|---|---|
| Predictive density | out-of-sample observation log likelihood per row | maximize |
| Probability sharpness | entropy subject to calibration and stability | controlled |
| Occupancy | distance from configured occupancy band | minimize |
| Persistence | episode duration and switch rate | within configured range |
| State separation | pairwise distribution distance | maximize |
| Signature stability | aligned signature similarity across folds | maximize |
| Transition stability | variation of aligned transition matrices | minimize |
| Economic separation | differences in future return, drawdown, volatility, and fixed-expert results | maximize |
| Benchmark uplift | frozen regime-aware mapping versus frozen non-regime mapping | maximize |
| Parsimony | feature count and model complexity | minimize |
| Retraining stability | feature and parameter drift across adjacent windows | minimize |

There is no external ground-truth regime label. Accuracy against states produced by the same model family is therefore diagnostic only and must not be a primary selection objective.

## 7.8 Feature and model selection

Optuna searches:

```text
model family
feature families
compact feature subset
lookback horizons
transformations
scaler
covariance structure
regularization
transition constraints
initialization
```

Initial feature constraint:

```text
minimum selected features: 3
maximum selected features: 8
```

Feature search is hierarchical:

```text
remove invalid features
cluster highly redundant features on training data
select feature families
select a limited number of representatives per family
fit and evaluate the candidate
```

Selection procedure:

1. Reject invalid trials.
2. Build a Pareto front over predictive density, stability, economic usefulness, and parsimony.
3. Retain a shortlist of the top `K` materially different regime candidates.
4. Apply a frozen tie-break score for ranking only.
5. Use the one-standard-error rule to prefer simpler candidates.
6. Generate out-of-fold probabilities for every shortlisted candidate.
7. Defer final regime-model promotion until compatible allocator candidates have been evaluated.

This shortlist avoids prematurely selecting a statistically attractive regime model that is weak for allocation.

Initial normalized ranking score:

```text
RegimeSelectionScore =
    0.25 × predictive_density
  + 0.20 × signature_stability
  + 0.20 × economic_separation
  + 0.15 × frozen_mapping_uplift
  + 0.10 × persistence_quality
  + 0.10 × parsimony_and_retraining_stability
```

Weights are versioned and fixed before any outer-test inspection.

---

# 8. Strategy expert contracts

The strategy experts are independent signal generators. They do not consume regime probabilities and do not decide portfolio weights.

## 8.1 Common input

```yaml
contract: StrategyExpertInput.v1
fields:
  as_of: datetime_utc
  feature_row: MarketFeatureFrame.v1
  cost_snapshots:
    BTC: CostModelSnapshot.v1
    ETH: CostModelSnapshot.v1
  strategy_config_version: string
```

## 8.2 Source-to-expert mapping

### Trend expert

Primary variables and derivatives:

```text
perp_close_price
perp_high_price
perp_low_price
perp_volume
spot_ohlcv_close_price
EMA distance and slope
rolling regression slope and fit
breakout distance
directional persistence
realized volatility derived from returns
```

### Momentum expert

```text
perp_close_price
perp_volume
perps_trades_buy_volume_share
log return over configured horizons
volatility-scaled return
return acceleration
volume confirmation
BTC/ETH relative momentum
```

### Mean-reversion expert

```text
perp_close_price
spot_ohlcv_close_price
perp_volume
price z-score
VWAP distance
Bollinger distance
spot-perpetual spread z-score
half-life proxy
short-horizon reversal
```

### Shared cost and capacity variables

```text
funding_rate_last_known
funding_data_available
minutes_since_funding
perp_quote_volume
perps_trades_quote_volume
derived turnover
derived spot-perpetual spread
estimated fees
estimated spread
estimated slippage
```

## 8.3 Common output

One signal per strategy and symbol:

```yaml
contract: StrategyExpertSignal.v1
fields:
  as_of: datetime_utc
  symbol: BTC|ETH
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
signal_direction is between minus one and one
signal_strength and confidence are between zero and one
FAIL status forces raw_target_exposure to zero
```

---

# 9. Module 2 — Strategy Allocator

## 9.1 Responsibility

The Strategy Allocator has exactly one responsibility:

> Convert regime probabilities, independent expert signals, portfolio state, and cost state into a proposed portfolio allocation.

It does not approve orders and cannot override risk limits.

## 9.2 Training input

Allocator training must use regime predictions generated out of fold by earlier-only Regime Estimator fits.

```yaml
contract: AllocatorTrainingInput.v1
fields:
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

Incorrect:

```text
fit the regime model on the complete training window
infer retrospective states on that same window
train the allocator on those states
```

Correct:

```text
fit on earlier data
emit filtered probabilities for the next interval
repeat through time
concatenate out-of-fold probabilities
train the allocator
```

## 9.3 Inference input

```yaml
contract: AllocatorInferenceInput.v1
fields:
  as_of: datetime_utc
  regime_prediction: RegimePrediction.v1
  expert_signals: StrategyExpertSignal.v1[]
  portfolio_state: PortfolioState.v1
  cost_snapshots: CostModelSnapshot.v1[]
  allocator_model_id: string
```

## 9.4 Candidate models

Evaluate in increasing complexity:

```text
cash-only baseline
equal-risk expert mix
best static expert mix
hard regime-to-expert mapping
probability-weighted mapping
regularized supervised allocator
contextual bandit
constrained reinforcement-learning policy
```

A more complex model is eligible only when it beats every required simpler baseline under identical data, costs, and walk-forward periods.

The recommended first production candidate is a regularized supervised allocator or contextual bandit. Reinforcement learning remains a challenger until sequential value is demonstrated beyond turnover, position-state, and switching effects already represented by simpler methods.

## 9.5 Action space

Version 1 uses constrained actions.

```yaml
risk_budgets:
  btc_trend: float
  btc_momentum: float
  btc_mean_reversion: float
  eth_trend: float
  eth_momentum: float
  eth_mean_reversion: float
  cash: float

signed_target_exposures:
  btc_trend: float
  btc_momentum: float
  btc_mean_reversion: float
  eth_trend: float
  eth_momentum: float
  eth_mean_reversion: float

global_risk_multiplier: float
exit_profile_by_sleeve: map[string, string]
```

Invariants:

```text
all risk budgets are non-negative
risk budgets plus cash sum to one
global risk multiplier is bounded
signed target exposures are bounded by their risk budgets and expert directions
```

Initial exit profiles are versioned, deterministic templates based on trailing ATR or realized-volatility units:

| Profile | Stop distance | Take-profit distance |
|---|---:|---:|
| Conservative | 1.0 risk unit | 1.5 risk units |
| Balanced | 1.5 risk units | 2.5 risk units |
| Trend | 2.0 risk units | 4.0 risk units |
| Wide | 3.0 risk units | 6.0 risk units |

The allocator chooses a profile ID. Module 3 resolves and validates the absolute levels from the current entry reference and risk variables.

Unrestricted continuous stop and take-profit optimization is excluded from the first production candidate.

## 9.6 Output contract

```yaml
contract: AllocationProposal.v1
fields:
  proposal_id: string
  as_of: datetime_utc
  allocator_model_id: string
  allocator_model_family: string
  allocator_version: string
  regime_model_id: string

  risk_budget_by_sleeve: map[string, float]
  cash_budget: float
  signed_target_exposure_by_sleeve: map[string, float]
  gross_target_by_symbol: map[string, float]
  net_target_by_symbol: map[string, float]

  global_risk_multiplier: float
  exit_profile_by_sleeve: map[string, string]
  expected_holding_minutes_by_sleeve: map[string, integer]

  policy_confidence: float
  abstain_recommended: bool
  expected_net_utility: float|null
  estimated_turnover: float
  estimated_cost_bps: float
```

The proposal is advisory. Module 3 may clip or reject every field.

## 9.7 Evaluation

All candidates use identical out-of-fold regime predictions, expert signals, portfolio simulation, and cost scenarios.

### Hard rejection gates

Reject a candidate when:

- action invariants are violated;
- evaluation contains look-ahead information;
- costs omit fees, spread, slippage, or funding;
- turnover or switching exceeds configured limits;
- drawdown breaches the research limit;
- actions become numerically unstable;
- most folds lose money while one fold dominates;
- results fail severe cost stress;
- required simple baselines are not beaten;
- the policy frequently acts when Module 1 recommends abstention;
- training and inference state definitions differ.

### Evaluation dimensions

| Dimension | Metric | Direction |
|---|---|---|
| Net performance | net return after all modeled costs | maximize |
| Risk-adjusted performance | Sharpe, Sortino, Calmar | maximize |
| Drawdown | maximum and average drawdown | minimize |
| Tail risk | CVaR and worst-period loss | minimize |
| Stability | median result and dispersion across folds | maximize/minimize |
| Consistency | fraction of profitable folds | maximize |
| Regret | loss versus best ex-post expert | minimize |
| Turnover | notional turnover | minimize |
| Switching | sleeve-weight change frequency | minimize |
| Baseline uplift | improvement over static and non-regime baselines | maximize |
| Capacity | performance under notional scaling | maximize |
| Complexity | parameters, training variance, inference cost | minimize |
| Abstention quality | loss avoided versus opportunity forgone | optimize |

For reinforcement-learning candidates, reward is net economic utility:

```text
realized net PnL
minus transaction costs
minus funding costs
minus slippage
minus drawdown penalty
minus tail-risk penalty
minus turnover penalty
minus strategy-switching penalty
```

## 9.8 Allocator and model-pair selection

The two learned modules are selected as a compatible pair, not as isolated winners.

Procedure:

1. Keep the top `K` materially different Regime Estimator candidates.
2. Generate separate out-of-fold probabilities for each candidate.
3. Train the full allocator candidate ladder against each regime candidate.
4. Reject invalid allocator/regime pairs.
5. Build a pair-level Pareto front.
6. Prefer the simplest pair within one standard error of the best pair.
7. Evaluate the frozen pair exactly once on the untouched outer test interval.
8. Aggregate results across all outer folds before declaring a champion.

Initial pair-level normalized ranking score:

```text
PairSelectionScore =
    0.25 × net_risk_adjusted_return
  + 0.15 × drawdown_quality
  + 0.15 × tail_risk_quality
  + 0.15 × outer_fold_stability
  + 0.10 × low_regret
  + 0.10 × turnover_efficiency
  + 0.05 × regime_stability
  + 0.05 × parsimony
```

Promotion gates:

```text
positive net uplift in at least 60 percent of outer folds
positive median net uplift across outer folds
no breach of the maximum-drawdown limit
no material deterioration in CVaR
survival under elevated and severe cost scenarios
no single fold contributes a dominant share of total PnL
```

Score weights and thresholds are versioned and frozen before outer-test inspection.

---

# 10. Module 3 — Deterministic Risk Engine

## 10.1 Responsibility

The Risk Engine has exactly one responsibility:

> Convert an advisory allocation proposal into an approved, clipped, netted, rejected, or halted set of order intents under hard portfolio, data, cost, exchange, and operational constraints.

It is not optimized by Optuna and is not selected through trading metrics.

## 10.2 Inputs

```yaml
contract: RiskEngineInput.v1
fields:
  proposal: AllocationProposal.v1
  regime_prediction: RegimePrediction.v1
  expert_signals: StrategyExpertSignal.v1[]
  feature_row: MarketFeatureFrame.v1
  portfolio_state: PortfolioState.v1
  cost_snapshots: CostModelSnapshot.v1[]
  risk_limits: RiskLimits.v1
  exchange_constraints: ExchangeConstraints.v1
  operational_state: OperationalState.v1
```

Dataset-derived controls include:

```text
funding state and freshness
open-interest state and freshness
perpetual price and volume
quote volume
trade-flow imbalance
derived realized volatility
derived basis
derived turnover and capacity
data missingness
contiguous-history length
source observation ages
```

Externally supplied controls include:

```text
account equity and cash
positions and pending orders
current drawdown and loss limits
minimum order sizes
margin and leverage rules
order and exposure limits
exchange connectivity
reconciliation state
kill-switch state
```

## 10.3 Output contract

```yaml
contract: RiskDecision.v1
fields:
  as_of: datetime_utc
  proposal_id: string
  status: APPROVED|CLIPPED|NETTED|REJECTED|HALTED

  approved_risk_budget_by_sleeve: map[string, float]
  approved_signed_exposure_by_sleeve: map[string, float]
  approved_net_target_by_symbol: map[string, float]

  approved_stop_level_by_sleeve: map[string, float]
  approved_take_profit_level_by_sleeve: map[string, float]
  approved_order_intents: list

  rejected_actions: list
  triggered_rules: list[string]
  risk_override_reason: string|null

  gross_exposure_after: float
  net_exposure_after: float
  estimated_margin_after: float
  risk_config_version: string
```

## 10.4 Deterministic controls

The engine enforces:

- maximum gross and net exposure;
- maximum leverage and estimated margin;
- maximum position by symbol and sleeve;
- concentration and strategy-correlation limits;
- daily, rolling, and maximum-drawdown limits;
- volatility-based scaling;
- historical capacity and turnover limits;
- stale-data and missing-data rejection;
- model-confidence and entropy gates;
- maximum order size and order frequency;
- funding and total-cost limits;
- exchange and instrument constraints;
- pending-order and reconciliation constraints;
- circuit breakers and kill switches.

When the Regime Estimator or Allocator recommends abstention, the engine may only reduce exposure or preserve a configured safe state.

## 10.5 Verification

The Risk Engine is verified, not statistically selected.

Required tests:

```text
unit tests for every limit and boundary
property tests for contract invariants
scenario tests for crashes, gaps, stale data, missing data, and exchange outages
historical replay tests on stress intervals
integration tests against every allocator action type
netting and virtual-sleeve attribution tests
pending-order and reconciliation tests
idempotency tests
fail-closed behavior tests
configuration-version audit tests
```

Success means all declared rules remain enforced even when both learned models are wrong.

---

# 11. End-to-end training and validation

## 11.1 Nested purged walk-forward

For each outer evaluation date:

```text
1. Select the previous three years as the outer training window.
2. Build point-in-time features using training-window data only.
3. Create time-ordered inner folds.
4. Purge overlapping label intervals.
5. Apply an embargo at least as long as the maximum target horizon.
6. Run Optuna for Module 1 only on inner folds.
7. Retain the top K materially different regime candidates.
8. Generate out-of-fold filtered probabilities for every retained candidate.
9. Generate expert signals, portfolio paths, costs, and targets point in time.
10. Train the Module 2 candidate ladder for every retained regime candidate.
11. Select a candidate pair using inner data only.
12. Refit the selected pair on the complete outer training window.
13. Freeze features, artifacts, costs, action space, and risk configuration.
14. Evaluate the complete system once on the untouched outer test interval.
15. Advance the outer window and repeat.
```

No outer-test result may be used to retune a candidate in the same research run.

## 11.2 Statistical safeguards

Because Optuna evaluates many models and feature subsets, raw best-trial performance is upward biased.

Required safeguards:

- block-bootstrap confidence intervals;
- performance distribution across outer folds;
- one-standard-error selection;
- explicit count of attempted trials and model families;
- multiple-testing-aware reporting;
- deflated risk-adjusted performance diagnostics;
- parameter and feature-selection stability;
- sensitivity to small changes in costs and hyperparameters;
- exclusion of results dominated by one market episode.

These safeguards are decision diagnostics, not replacements for outer walk-forward testing.

## 11.3 Model artifacts

### RegimeModelArtifact.v1

```yaml
selected_model_family: string
selected_features: list[string]
preprocessing_pipeline: object
model_parameters: object
state_signatures: list
state_alignment_metadata: object
feature_set_hash: string
source_data_hash: string
training_window: [datetime, datetime]
decision_interval: string
inner_validation_metrics: object
outer_evaluation_metrics: object
selection_score_version: string
code_commit: string
dependency_lock_hash: string
```

### AllocatorModelArtifact.v1

```yaml
selected_model_family: string
policy_parameters: object
expert_contract_versions: object
regime_model_id: string
action_space_version: string
cost_model_version: string
training_window: [datetime, datetime]
inner_validation_metrics: object
outer_evaluation_metrics: object
selection_score_version: string
code_commit: string
dependency_lock_hash: string
```

### RiskConfigArtifact.v1

```yaml
risk_limits: object
exchange_constraints: object
data_quality_rules: object
confidence_and_entropy_rules: object
kill_switch_rules: object
config_version: string
code_commit: string
```

The exact compatible artifact triplet is recorded for every production decision.

---

# 12. Production deployment

## 12.1 Champion and challenger

The current deployed pair is the champion. Retrained candidates are challengers.

Promotion requires:

- all schema, hash, and lineage checks pass;
- all hard validation gates pass;
- the challenger improves the frozen pair-level objective;
- drawdown, CVaR, turnover, and abstention behavior do not materially deteriorate;
- cost-stress results remain acceptable;
- shadow behavior is consistent with backtest assumptions;
- model decisions are reproducible from immutable artifacts;
- rollback to the previous champion is tested.

A challenger is never promoted from a single favorable outer fold.

## 12.2 Shadow and canary stages

Deployment stages:

```text
offline research
historical replay
live feature shadow
full decision shadow
paper execution
small-capital canary
restricted production
full approved production
```

Each stage has explicit minimum observation counts, incident criteria, and rollback rules.

## 12.3 Monitoring

### Data monitoring

```text
source freshness
missingness by field
unexpected null transitions
timestamp gaps and duplicates
observation-age distribution
feature drift
BTC/ETH synchronization
feature-set hash mismatch
```

### Regime monitoring

```text
probability distribution
entropy
state occupancy
episode duration
switch rate
state-signature drift
transition-matrix drift
abstention frequency
```

### Allocator monitoring

```text
risk-budget distribution
signed exposure distribution
cash allocation
turnover and switching
policy confidence
expert disagreement
expected versus realized costs
expected versus realized utility
```

### Risk and execution monitoring

```text
clipping and rejection rate
triggered rules
gross and net exposure
margin utilization
pending-order age
fill and cancellation rates
reconciliation breaks
realized slippage
kill-switch state
```

## 12.4 Safe degradation

The system must define deterministic behavior for:

- missing source rows;
- stale funding or open interest;
- model inference failure;
- feature-hash mismatch;
- unavailable artifact;
- high regime entropy;
- expert disagreement;
- portfolio reconciliation failure;
- exchange disconnection.

The default safe behavior is reduced exposure or cash, never inference from incomplete hidden state.

## 12.5 Reproducibility and audit

Every decision must be traceable to:

```text
source data version and hash
feature contract and hash
model artifacts
strategy versions
cost model version
risk configuration
code commit
dependency lock
input payload
output payload
risk overrides
execution acknowledgements and fills
```

---

# 13. Recommended repository structure

```text
regime-strategy-selector/
├── configs/
│   ├── datasets/
│   ├── features/
│   ├── models/
│   ├── selection/
│   ├── strategies/
│   ├── costs/
│   └── risk/
├── contracts/
│   ├── market_feature_frame.schema.json
│   ├── training_target_frame.schema.json
│   ├── regime_prediction.schema.json
│   ├── strategy_expert_signal.schema.json
│   ├── allocation_proposal.schema.json
│   ├── risk_decision.schema.json
│   └── model_artifact.schema.json
├── src/regime_strategy_selector/
│   ├── data/
│   │   ├── adapters/
│   │   ├── validation/
│   │   └── feature_store/
│   ├── features/
│   │   ├── registry/
│   │   ├── transformations/
│   │   └── parity/
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
│   │   ├── baselines/
│   │   ├── supervised/
│   │   ├── bandits/
│   │   └── reinforcement_learning/
│   ├── portfolio/
│   │   ├── sleeves/
│   │   ├── netting/
│   │   └── attribution/
│   ├── costs/
│   ├── risk/
│   ├── backtesting/
│   ├── optimization/
│   ├── evaluation/
│   ├── artifacts/
│   └── monitoring/
├── tests/
│   ├── contracts/
│   ├── features/
│   ├── models/
│   ├── backtesting/
│   ├── risk/
│   └── integration/
├── notebooks/
├── scripts/
└── README.md
```

---

# 14. Implementation roadmap

## Phase 1 — Deterministic research foundation

- Implement source validation and `MarketFeatureFrame.v1`.
- Implement the feature registry and point-in-time feature builder.
- Implement `TrainingTargetFrame.v1`.
- Fix the hourly decision clock for the first experiments.
- Implement cost scenarios and a portfolio simulator.
- Implement cash-only, equal-risk, static-mix, and single-expert baselines.
- Implement virtual sleeves, netting, and attribution.

## Phase 2 — Regime Estimator

- Implement Gaussian HMM baselines.
- Add robust and duration-aware challengers.
- Add hierarchical Optuna feature selection.
- Add purged inner walk-forward and embargo.
- Generate filtered out-of-fold probabilities.
- Implement state signatures and alignment.
- Produce a top-K regime shortlist.

## Phase 3 — Strategy experts and allocator

- Implement independently testable strategy experts.
- Implement hard and probability-weighted mappings.
- Implement a regularized supervised allocator.
- Evaluate a contextual bandit.
- Add constrained reinforcement learning only as a challenger.
- Select compatible regime/allocator pairs.

## Phase 4 — Deterministic risk and execution contracts

- Implement all risk limits and data-quality gates.
- Implement abstention and safe-degradation rules.
- Implement order-intent, reconciliation, and portfolio-state contracts.
- Add stress replays and fail-closed tests.

## Phase 5 — Production operations

- Build immutable model and configuration artifacts.
- Add feature, model, policy, risk, and execution monitoring.
- Run live feature and decision shadow stages.
- Run paper execution.
- Run a small-capital canary with strict limits.
- Establish incident response and rollback procedures.

---

# 15. Production-readiness criteria

The system is not production-ready until all of the following hold:

- point-in-time feature generation is deterministic and live reproducible;
- the three strategy experts have positive or defensible standalone behavior after costs;
- Module 1 produces stable, interpretable, live-safe probabilities from a compact feature subset;
- a regime/allocator pair beats the required simpler baselines across multiple outer folds;
- uplift survives elevated and severe cost scenarios;
- no single fold or market episode dominates the result;
- feature and parameter selection remain reasonably stable across retraining dates;
- abstention reduces loss in uncertain conditions without eliminating most opportunity;
- virtual-sleeve attribution reconciles with net exchange positions;
- Module 3 passes boundary, stress, replay, idempotency, and fail-closed tests;
- historical replay and live shadow decisions are consistent;
- paper execution confirms cost and order-state assumptions;
- canary deployment remains within predefined risk and incident limits;
- every decision is reproducible and auditable;
- rollback to the previous champion is operationally tested.

---

## Status

This repository currently defines the production architecture and research methodology. Implementation should proceed from deterministic baselines to more complex models. No complex allocator, including reinforcement learning, is eligible for production unless it provides stable, cost-adjusted, outer-walk-forward improvement over simpler alternatives under the same data and risk constraints.
