# MLflow Experiment and Model Governance

## 1. Purpose

This document defines how `regime-strategy-selector` stores experiments, metrics, metadata, datasets, model artifacts, deployment bundles, promotion state and rollback information in MLflow.

MLflow is the experiment and model control plane. It does not replace:

- point-in-time feature generation;
- nested walk-forward splitting;
- state-signature construction;
- persistent state mapping;
- financial backtesting;
- bootstrap significance testing;
- the deterministic Risk Engine;
- the runtime decision and position state store.

## 2. Recommended deployment architecture

```text
GitHub
    └── source code, contracts, configs, tests

MLflow Tracking Server
    ├── experiments and runs
    ├── parameters and metrics
    ├── dataset lineage
    └── Model Registry metadata

PostgreSQL
    └── MLflow backend store

MinIO / S3-compatible object storage
    └── run artifacts and model artifacts

Runtime PostgreSQL
    └── filtered probability state, decisions, positions and audit

Parquet / analytical database
    └── historical market datasets and feature frames
```

The MLflow backend database and runtime decision database must be logically separated.

## 3. Experiment taxonomy

Use separate experiments for separate causal questions.

```text
btc-regime/00-data-and-feature-validation
btc-regime/10-standalone-exit-optimisation
btc-regime/20-regime-model-selection
btc-regime/30-regime-incremental-value
btc-regime/40-regime-dependent-exits
btc-regime/50-l2-microstructure-overlay
btc-regime/60-learned-allocator
btc-regime/90-shadow-paper-canary
```

Do not store all research in one undifferentiated experiment.

## 4. Run hierarchy

### 4.1 Parent run

A parent run represents one complete reproducible experiment definition:

```text
experiment design
candidate family
dataset snapshot
outer fold
search space
cost assumptions
code commit
```

### 4.2 Child runs

Child runs represent:

- deterministic seeds;
- inner folds;
- hyperparameter combinations;
- exit-profile combinations;
- cost-stress scenarios;
- placebo variants;
- bootstrap repetitions or bootstrap summaries.

Recommended structure:

```text
parent: candidate × outer_fold
    ├── child: seed
    ├── child: inner_fold × parameter_combination
    ├── child: BASE cost scenario
    ├── child: ELEVATED cost scenario
    └── child: SEVERE cost scenario
```

Outer-test results are logged only after all inner selection is complete and frozen.

## 5. Required tags

Tags identify the semantic role and governance status of a run.

```text
project = regime-strategy-selector
target_symbol = BTC
traded_instrument_type = LINEAR_PERPETUAL
run_role = INNER_TRAIN|INNER_VALIDATION|OUTER_TEST|PLACEBO|SHADOW|PAPER|CANARY
candidate_role = BASELINE|CHAMPION|CHALLENGER
model_family = string
strategy_id = TREND|MOMENTUM|MEAN_REVERSION|ALLOCATOR|NONE
state_schema_version = string
feature_contract_version = string
output_contract_version = string
experiment_design_version = string
validation_status = PASS|FAIL
alignment_status = PASS|FAIL|NOT_APPLICABLE
promotion_eligible = true|false
```

Tags must not be used as a substitute for numerical metrics.

## 6. Required parameters

### 6.1 Common parameters

```text
outer_fold_id
inner_fold_id
training_start
training_end
validation_start
validation_end
test_start
test_end
embargo_hours
purge_hours
decision_interval_minutes
primary_horizon_hours
stress_horizon_hours
random_seed
code_commit
dependency_lock_hash
dataset_name
dataset_version
dataset_digest
feature_set_hash
risk_config_version
cost_model_version
```

### 6.2 Regime-model parameters

```text
model_family
model_implementation_version
n_states
covariance_type
n_initialisations
convergence_tolerance
maximum_iterations
minimum_state_occupancy
maximum_state_alignment_distance
scaler_type
scaler_version
```

### 6.3 Exit-optimisation parameters

```text
strategy_id
exit_search_space_version
stop_atr_multiple
take_profit_atr_multiple
time_stop_hours
trailing_stop_enabled
selection_rule_version
```

### 6.4 Allocator parameters

```text
affinity_method_version
minimum_cash_fraction
minimum_consensus_evidence
minimum_direction_dominance
target_volatility_annual
volatility_floor
```

## 7. Metrics

Metrics must be prefixed according to their scope.

```text
train/*
inner_validation/*
outer_test/*
bootstrap/*
cost_base/*
cost_elevated/*
cost_severe/*
shadow/*
paper/*
canary/*
```

### 7.1 Statistical regime metrics

```text
oos_predictive_log_likelihood
one_state_log_likelihood_difference
converged_seed_count
stable_seed_count
minimum_state_occupancy
maximum_state_occupancy
minimum_median_state_duration_hours
maximum_median_state_duration_hours
maximum_seed_alignment_distance
maximum_fold_alignment_distance
mean_normalised_entropy
entropy_p95
mean_maximum_probability
transition_matrix_stability
state_signature_stability
invalid_probability_count
```

### 7.2 Standalone strategy metrics

```text
net_return
annualised_net_return
net_calmar
net_sharpe
net_sortino
maximum_drawdown
cvar_95_loss
turnover
trade_count
win_rate
profit_factor
average_trade_net_return
median_trade_net_return
maximum_positive_pnl_fold_contribution
profitable_fold_fraction
```

### 7.3 Exit robustness metrics

```text
neighbourhood_score_mean
neighbourhood_score_std
neighbourhood_worst_score
parameter_sensitivity_rank
score_relative_to_inner_best
```

### 7.4 Candidate-versus-baseline metrics

```text
calmar_difference
net_return_difference
maximum_drawdown_difference
cvar_95_loss_difference
turnover_difference
outer_fold_win_fraction
paired_bootstrap_calmar_ci_lower
paired_bootstrap_calmar_ci_upper
paired_bootstrap_net_return_ci_lower
paired_bootstrap_net_return_ci_upper
```

### 7.5 Execution and L2 metrics

```text
expected_slippage_bps
realised_slippage_bps
spread_cost_bps
entry_adverse_selection_bps
entry_delay_minutes
no_new_entry_fraction
liquidity_rejection_fraction
stop_out_within_1h_fraction
```

## 8. Dataset lineage

MLflow stores references and hashes, not the complete historical lake.

Each run must log:

```text
dataset_name
dataset_version
dataset_uri
dataset_digest
dataset_schema_hash
source_data_hash
feature_set_hash
feature_build_commit
coverage_start
coverage_end
row_count
symbol
exchange
```

Recommended datasets:

```text
gold.market.history_full.m1
gold.live.microstructure_features.m1
gold.hybrid.full_l2.m1
```

A model is not reproducible when only a mutable path such as `latest.parquet` is logged.

## 9. Required run artifacts

### 9.1 Data and split artifacts

```text
dataset_manifest.json
feature_schema.json
feature_order.json
walk_forward_splits.json
point_in_time_validation_report.json
missingness_report.json
```

### 9.2 Regime-model artifacts

```text
raw_model.bin
scaler.json
transition_matrix.json
initial_state_probabilities.json
state_signatures.json
state_mapping.json
alignment_report.json
model_signature.json
probability_contract.json
```

### 9.3 Strategy and exit artifacts

```text
strategy_config.json
exit_search_space.json
selected_exit_profile.json
exit_surface.parquet
exit_robustness_report.json
standalone_strategy_report.json
```

### 9.4 Economic evaluation artifacts

```text
fold_metrics.parquet
equity_curve.parquet
trade_ledger.parquet
cost_breakdown.parquet
bootstrap_report.json
placebo_report.json
cost_stress_report.json
benchmark_comparison.json
```

### 9.5 Deployment artifacts

```text
deployment_manifest.json
golden_prediction_inputs.parquet
golden_prediction_outputs.parquet
runtime_config.json
risk_config.json
affinity_matrix.json
exit_profile_set.json
dependency_lock.txt
```

## 10. Custom MLflow model wrapper

Every promotable regime model must be packaged behind one common inference interface, preferably an MLflow PyFunc model.

The wrapper owns:

```text
feature validation
feature ordering
scaling
raw model inference
filtered probability calculation
4h forward probability calculation
persistent state mapping
canonical probability ordering
output validation
```

The public output is always:

```text
RegimePrediction.v1
```

Required invariants:

```text
all probabilities are finite
0 <= every probability <= 1
sum(current_probabilities) = 1
sum(forward_probabilities_4h) = 1
state order equals the registered canonical state schema
only filtered point-in-time probabilities are returned
feature and artifact hashes match
```

## 11. Registered models

### 11.1 Regime estimator

```text
Registered Model:
btc-regime-estimator
```

This model may contain versions produced by different compatible model families:

```text
diagonal Gaussian HMM
full-covariance Gaussian HMM
HSMM
Student-t HMM
Markov-switching autoregression
```

### 11.2 Deployment bundle

```text
Registered Model:
btc-regime-deployment-bundle
```

The deployment bundle references or contains the exact compatible set:

```text
regime model version
scaler
feature contract
state schema
state mapping
affinity matrix
strategy configuration
exit profile set
risk configuration
cost model
timing policy
code commit
dependency lock
```

Production must load the deployment bundle, not independently select the latest version of every component.

## 12. Model-version tags

Every registered model version must include:

```text
source_run_id
model_family
model_implementation_version
feature_contract_version
output_contract_version
state_schema_version
state_mapping_version
strategy_config_version
exit_profile_set_version
affinity_matrix_version
risk_config_version
cost_model_version
dataset_digest
code_commit
dependency_lock_hash
statistical_validation_status
economic_validation_status
shadow_status
paper_status
canary_status
```

## 13. Aliases

Use mutable aliases pointing to immutable versions:

```text
@champion
@challenger
@shadow
@rollback
```

Example runtime reference:

```text
models:/btc-regime-deployment-bundle@champion
```

Promotion sequence:

```text
new version
→ @challenger
→ @shadow
→ paper validation
→ canary validation
→ previous @champion becomes @rollback
→ new version becomes @champion
```

Alias movement must be recorded in an audit event containing actor, timestamp, reason, source version, target version and evidence report.

## 14. Promotion policy

MLflow stores the evidence but does not decide promotion automatically.

The project promotion service evaluates the configured policy. At minimum:

```text
statistical_validation_status = PASS
economic_validation_status = PASS
alignment_status = PASS
outer_test results exist
paired bootstrap lower bound > configured threshold
cost stress passed
shadow passed
paper passed
canary passed
manual approval present
```

A higher point estimate alone is insufficient.

## 15. Strategy-exit evidence in MLflow

The strategy-exit roadmap requires three distinct run classes.

### 15.1 Standalone exit optimisation

```text
experiment = btc-regime/10-standalone-exit-optimisation
run_role = INNER_VALIDATION or OUTER_TEST
strategy_id = TREND|MOMENTUM|MEAN_REVERSION
```

Each parameter combination is a child run. The selected robust plateau configuration is stored as `selected_exit_profile.json`.

### 15.2 Regime incremental value

```text
experiment = btc-regime/30-regime-incremental-value
```

Paired runs must use identical:

```text
strategy config
exit profile set
risk config
cost model
walk-forward splits
```

The only intended difference is the regime information path.

### 15.3 Regime-dependent exits

```text
experiment = btc-regime/40-regime-dependent-exits
```

This experiment compares fixed strategy-specific profiles against a small discrete `State × Strategy → Exit Profile` mapping.

## 16. Runtime state is not a model artifact

The following online state must not be written into the Model Registry:

```text
last_processed_as_of
current_filtered_probabilities
current_position
open orders
protective orders
current drawdown
daily loss
```

It belongs in the runtime state and audit database. MLflow stores the immutable model and deployment bundle that produced the decision.

Every runtime decision records:

```text
mlflow_registered_model_name
mlflow_model_version
mlflow_model_alias_at_decision_time
source_run_id
artifact_sha256
output_contract_version
state_schema_version
```

## 17. Reproducibility tests

Before registration:

- model save/load must preserve output;
- same feature snapshot and same artifact must reproduce the same probabilities;
- golden prediction vectors must match within configured numerical tolerance;
- wrong feature order must fail;
- wrong feature hash must fail;
- unknown state mapping must fail;
- invalid probability sums must fail;
- dependency environment must be reconstructable.

## 18. Retention and immutability

- Registered model versions are immutable.
- Outer-test reports are immutable.
- Dataset digests and code commits are immutable references.
- Failed research runs may be retained with lifecycle tags for audit and multiple-testing control.
- Deletion of promoted or previously promoted artifacts is prohibited while any deployment or audit record references them.

## 19. Security

- The Tracking Server requires authentication and network restriction.
- PostgreSQL and MinIO credentials must be stored outside Git.
- Artifact access follows least privilege.
- Promotion aliases require elevated write permission.
- Research workers may create runs but must not move `@champion`.
- Every alias change and model registration is auditable.

## 20. Minimum implementation sequence

```text
1. self-host MLflow with PostgreSQL and MinIO
2. implement common run metadata helpers
3. log dataset lineage and walk-forward splits
4. log standalone strategy and exit experiments
5. package the HMM as a common PyFunc contract
6. create btc-regime-estimator
7. create btc-regime-deployment-bundle
8. implement candidate-versus-champion comparison
9. implement aliases and manual promotion
10. connect runtime decisions to exact MLflow model versions
```
