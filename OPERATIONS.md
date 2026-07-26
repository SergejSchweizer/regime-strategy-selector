# Operations and Model Governance

This document defines Production V1 runtime behaviour, security, monitoring, incident handling, MLflow experiment tracking, Model Registry governance, promotion and rollback for one fixed linear BTC-perpetual deployment.

## 1. Operating principles

```text
one deployment = BTC = one linear BTC perpetual
BTC spot = reference data only
one decision timestamp = one logical decision
one approval = at most one active execution plan
isolated margin only
one-way position mode only
absolute effective leverage <= 1x
unknown state = no exposure increase
reconciliation failure = no exposure increase
artifact mismatch = halt
manual promotion only
atomic rollback only
```

The analytical and execution systems remain independently restartable. Restarting either system must not create duplicate decisions, plans or protective orders.

## 2. Process topology

```text
BTC market-data adapter
point-in-time feature service
regime service
deterministic expert service
deterministic allocator
risk service
decision and audit store
BTC-perpetual execution service
portfolio and margin reconciler
monitoring and alerting
MLflow Tracking Server and Model Registry
```

Components may initially share a process, but contracts and persisted state remain separate.

## 3. Startup sequence

Startup proceeds in this order:

1. load `DeploymentConfig.v1`;
2. verify `target_symbol = BTC`;
3. load current `CapitalAllocation.v1`;
4. resolve the approved MLflow champion deployment bundle;
5. load `CompatibleArtifactSet.v1` atomically;
6. verify BTC perpetual and spot-reference specifications;
7. verify code, dependency, feature, methodology, risk, operations and artifact hashes;
8. connect market data and exchange in read-only mode;
9. verify the exact configured linear BTC perpetual;
10. verify isolated margin, one-way mode and maximum production leverage of 1x;
11. verify reduce-only support;
12. reconcile cash, margin, position, open orders and protective orders;
13. verify mark, index, liquidation and funding data;
14. verify the system clock;
15. validate `SmallAccountCapability.v1`;
16. acquire the deployment leadership lock;
17. enable analytical decisions;
18. enable exposure-changing execution only after every prior check passes.

Any failure leaves the deployment in `SAFE_READ_ONLY` or `HALTED`.

## 4. Runtime state machines

### 4.1 Deployment states

```text
STARTING
SAFE_READ_ONLY
READY
DECIDING
EXECUTING
RECONCILING
DEGRADED
HALTED
```

```text
STARTING -> SAFE_READ_ONLY
SAFE_READ_ONLY -> READY
READY -> DECIDING
DECIDING -> READY|EXECUTING
EXECUTING -> RECONCILING
RECONCILING -> READY
any state -> DEGRADED|HALTED
DEGRADED -> SAFE_READ_ONLY
HALTED -> SAFE_READ_ONLY only after manual acknowledgement
```

There is no direct `HALTED -> READY` transition.

### 4.2 Decision states

```text
CREATED
FEATURED
INFERRED
ALLOCATED
APPROVED
REJECTED
EXECUTION_CREATED
EXECUTING
RECONCILED
FAILED
EXPIRED
```

Transitions are append-only and never move backwards.

## 5. Exactly-once semantics

```text
decision_id = hash(
    deployment_id,
    BTC,
    trading_instrument_id,
    as_of,
    compatible_artifact_set_id
)
```

A distributed lock is acquired on `deployment_id + as_of`. Lock loss before persistence aborts the decision; lock loss after approval blocks new execution until reconciliation.

```text
execution_idempotency_key = hash(
    approval_id,
    trading_instrument_id,
    approved_target_notional
)
```

The execution service rejects a second active plan with the same key.

```text
protective_order_set_id = hash(
    execution_plan_id,
    reconciled_entry_fill_id,
    exit_profile_id
)
```

At most one active protective-order set exists for the reconciled net position.

## 6. Hourly decision schedule

At every scheduled UTC hour:

1. wait for the final source M1 bucket to close;
2. verify BTC spot and perpetual watermarks and clock;
3. build and persist `MarketFeatureFrame.v1`;
4. run the regime estimator and all enabled experts;
5. run the allocator;
6. read reconciled position, margin and liquidation state;
7. run the Risk Engine;
8. persist `DecisionAuditRecord.v1`;
9. send an unexpired approval to execution;
10. create at most one execution plan;
11. reconcile fills and position;
12. activate or replace reduce-only protective orders;
13. append execution and portfolio results to the audit chain.

A late decision expires; it does not shift the schedule.

## 7. Service objectives and automatic actions

All thresholds are versioned in `OperationsConfig.v1` or `RiskLimits.v1`.

| Condition | Default trigger | Automatic action |
|---|---:|---|
| Market-data bucket delay | >120 seconds | reject exposure increase |
| Market-data bucket delay | >600 seconds | `DEGRADED`, reduce-only |
| Required spot reference unavailable | any required snapshot | feature `FAIL` |
| Feature computation duration | >30 seconds | expire decision |
| Decision age at execution | >60 seconds | reject exposure increase |
| Source gap | >180 minutes | `HALTED` |
| Feature or artifact hash mismatch | any | `HALTED` |
| Wrong symbol, instrument or contract type | any | `HALTED` |
| Margin mode not isolated | any | cancel increasing orders, `HALTED` |
| Position mode not one-way | any | cancel increasing orders, `HALTED` |
| Effective leverage configuration >1x | any | startup failure or `HALTED` |
| Small-account capability | `FAIL` | startup failure |
| Funding data stale | beyond limit | no exposure increase |
| Absolute funding rate | above limit | reduce or reject |
| Mark/index divergence | warning threshold | no exposure increase |
| Mark/index divergence | halt threshold | reduce-only, `HALTED` |
| Liquidation buffer | warning threshold | clip, reduce-only |
| Liquidation buffer | hard limit | emergency reduction, `HALTED` |
| Reconciliation | `BROKEN` | cancel non-reduce-only orders |
| Reconciliation broken duration | >300 seconds | `HALTED` |
| Pending execution-plan age | >120 seconds | stop new plans, reconcile |
| Exchange-order age | above TTL | cancel and reconcile |
| Regime entropy | above limit | abstain |
| Maximum regime probability | below limit | abstain |
| Daily loss or drawdown | limit reached | reduce or flatten, `HALTED` |
| Kill switch | active | cancel, emergency reduce or flatten |
| Clock offset | >500 milliseconds | disable exposure increase |
| Realised slippage | >2x expected for 3 plans | `DEGRADED`, reduce target-change cap |
| Cost-model error | above tolerance | block promotion and alert |

Emergency reduction and flattening are deterministic and never inferred by a model.

## 8. Safe degradation

Feature failure, inference failure, allocator abstention, risk rejection, high entropy, stale capital or cost state, mark/index divergence, insufficient liquidation buffer, broken reconciliation, execution connectivity loss and decision expiry allow only preservation or reduction of absolute exposure.

A target of zero is not a confirmed flat position. The system may claim flat only after exchange reconciliation.

Production V1 has no fallback asset, fallback spot execution, fallback perpetual contract or automatic fallback model.

## 9. Execution requirements

Execution converts approved notional into exchange-valid quantity using reference price, contract multiplier and quantity step, rounding towards zero.

```text
delta_notional = approved_target_notional - reconciled_current_notional
```

Execution never infers a target from raw signals. Protective exits and degradation-driven reductions use reduce-only. A reduce-only rejection is a reconciliation event, not permission to send an unrestricted replacement.

The account holds one net position in one-way mode and uses isolated margin. Funding observations, held position, realised funding cash flow and cumulative funding are recorded for every funding event.

## 10. Security

Production API keys must have trading permission only, no withdrawal permission, sub-account restriction, IP allow-listing when available and no unnecessary instrument permissions.

Secrets come from an approved secret manager and are prohibited in Git, model artifacts, images, plaintext configuration, notebooks and logs.

Paper, canary and production use separate credentials and preferably separate accounts or sub-accounts. Promotion, capital changes, risk changes and kill-switch release require authenticated, auditable operator actions.

## 11. Logging and audit

Every service emits:

```text
timestamp
deployment_id
decision_id or execution_plan_id
target_symbol = BTC
trading_instrument_id
compatible_artifact_set_id
service_version
state transition
result code
incident_id when present
```

Logs contain no credentials. `DecisionAuditRecord.v1` is immutable; corrections append a new record referencing the original hash.

Every runtime decision also records the exact MLflow model and bundle identity:

```text
mlflow_registered_model_name
mlflow_model_version
mlflow_model_alias_at_decision_time
source_run_id
artifact_sha256
output_contract_version
state_schema_version
```

## 12. Monitoring

### Data and features

- spot and perpetual watermarks, gaps and duplicates;
- funding and open-interest ages;
- feature validity and latency;
- historical/live parity;
- feature-hash mismatch count.

### Regime model

- current and four-hour probabilities;
- normalised entropy and maximum probability;
- state occupancy and duration;
- transition-matrix drift;
- state-signature distance;
- abstention rate.

### Strategy and allocation

- expert direction, strength and confidence;
- contribution weights and disagreement;
- consensus direction and cash weight;
- regime certainty and volatility multiplier;
- preliminary target and selected exit profile.

### Risk and execution

- current and approved fraction and notional;
- isolated margin use;
- mark/index divergence and liquidation buffer;
- funding and realised funding;
- clipping, rejection and halt counts;
- daily loss, drawdown and turnover;
- order age, fill latency, fees and slippage;
- reconciliation status.

## 13. Alerts and runbooks

Each alert defines:

```yaml
alert_id: string
severity: INFO|WARNING|CRITICAL
detection_rule: string
automatic_action: string
operator_action: string
runbook_url: string
owner: string
acknowledgement_deadline_seconds: integer
```

Critical alerts include wrong instrument, changed contract semantics, margin or position-mode drift, leverage above 1x, artifact incompatibility, prolonged broken reconciliation, missing liquidation price, liquidation-buffer breach, loss-limit breach, kill switch, duplicate execution, unrecognised position, inability to cancel increasing orders and secret failure.

## 14. Deployment environments

```text
historical replay
-> live feature shadow
-> full decision shadow
-> paper execution
-> small-capital canary
-> restricted production
```

Historical replay uses production decision code with historical adapters. Feature shadow has no execution. Decision shadow persists full decisions but sends no approvals. Paper runs the production execution state machine against a paper venue or deterministic simulator. Canary uses a dedicated small allocation, strict loss limits and reduced target changes. Restricted production retains conservative limits and never exceeds absolute fraction 1.0.

## 15. MLflow role and infrastructure

MLflow is the experiment and model control plane. It does not replace point-in-time feature generation, nested walk-forward splitting, persistent state mapping, financial backtesting, bootstrap tests, the Risk Engine or runtime state storage.

Recommended architecture:

```text
GitHub
    source code, contracts, configs and tests

MLflow Tracking Server
    experiments, runs, parameters, metrics, lineage and registry metadata

PostgreSQL
    MLflow backend store

MinIO or S3-compatible storage
    run and model artifacts

Runtime PostgreSQL
    filtered probabilities, decisions, positions and audit

Parquet or analytical database
    historical market data and feature frames
```

The MLflow backend and runtime database are logically separated.

## 16. MLflow experiment taxonomy

Use separate experiments for separate causal questions:

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

Do not place all research in one experiment.

## 17. MLflow run hierarchy

A parent run represents one reproducible experiment definition: candidate family, dataset snapshot, outer fold, search space, costs and code commit.

Child runs represent deterministic seeds, inner folds, parameter combinations, exit profiles, cost scenarios, placebos and bootstrap summaries.

```text
parent: candidate x outer_fold
    |-- child: seed
    |-- child: inner_fold x parameter combination
    |-- child: BASE cost
    |-- child: ELEVATED cost
    `-- child: SEVERE cost
```

Outer-test results are logged only after inner selection is complete and frozen.

## 18. Required MLflow metadata

### Tags

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

### Common parameters

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

### Model parameters

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

### Exit and allocator parameters

```text
strategy_id
exit_search_space_version
stop_atr_multiple
take_profit_atr_multiple
time_stop_hours
trailing_stop_enabled
selection_rule_version
affinity_method_version
minimum_cash_fraction
minimum_consensus_evidence
minimum_direction_dominance
target_volatility_annual
volatility_floor
```

Tags identify semantics; they do not replace metrics.

## 19. MLflow metrics

Prefix metrics by scope:

```text
train/
inner_validation/
outer_test/
bootstrap/
cost_base/
cost_elevated/
cost_severe/
shadow/
paper/
canary/
```

### Statistical regime metrics

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

### Economic metrics

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

### Exit robustness

```text
neighbourhood_score_mean
neighbourhood_score_std
neighbourhood_worst_score
parameter_sensitivity_rank
score_relative_to_inner_best
```

### Candidate versus baseline

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

### Execution and L2

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

## 20. Dataset lineage and artifacts

MLflow stores immutable references and hashes, not the full historical lake.

Every run logs dataset name, version, URI, digest, schema hash, source-data hash, feature-set hash, build commit, coverage interval, row count, symbol and exchange. A mutable path such as `latest.parquet` is insufficient.

Required artifacts:

```text
data and splits
- dataset_manifest.json
- feature_schema.json
- feature_order.json
- walk_forward_splits.json
- point_in_time_validation_report.json
- missingness_report.json

regime model
- raw_model.bin
- scaler.json
- transition_matrix.json
- initial_state_probabilities.json
- state_signatures.json
- state_mapping.json
- alignment_report.json
- model_signature.json
- probability_contract.json

strategy and exits
- strategy_config.json
- exit_search_space.json
- selected_exit_profile.json
- exit_surface.parquet
- exit_robustness_report.json
- standalone_strategy_report.json

economic evaluation
- fold_metrics.parquet
- equity_curve.parquet
- trade_ledger.parquet
- cost_breakdown.parquet
- bootstrap_report.json
- placebo_report.json
- cost_stress_report.json
- benchmark_comparison.json

deployment
- deployment_manifest.json
- golden_prediction_inputs.parquet
- golden_prediction_outputs.parquet
- runtime_config.json
- risk_config.json
- affinity_matrix.json
- exit_profile_set.json
- dependency_lock.txt
```

## 21. Common MLflow model wrapper

Every promotable regime model is packaged behind one common MLflow PyFunc-compatible interface. The wrapper owns feature validation and ordering, scaling, raw inference, filtered probabilities, four-hour projection, persistent-state mapping, canonical ordering and output validation.

The public output is always `RegimePrediction.v1`.

Required invariants:

```text
all probabilities are finite and in [0,1]
current and forward vectors each sum to 1
state order equals the registered persistent-state schema
only filtered point-in-time probabilities are returned
feature and artifact hashes match
```

## 22. Model Registry

Registered models:

```text
btc-regime-estimator
btc-regime-deployment-bundle
```

`btc-regime-estimator` may contain compatible versions from diagonal or full Gaussian HMMs, HSMMs, Student-t HMMs or Markov-switching autoregressions.

The deployment bundle contains or references the exact model version, scaler, feature contract, state schema and mapping, affinity matrix, strategy configuration, exit profiles, risk configuration, cost model, timing policy, code commit and dependency lock.

Production loads the deployment bundle and never independently selects the latest component versions.

Every registered version is tagged with source run, model family and implementation version, feature/output/state/mapping versions, strategy and exit versions, affinity/risk/cost versions, dataset digest, code commit, dependency hash and statistical, economic, shadow, paper and canary status.

## 23. Aliases, promotion and rollback

Aliases point to immutable versions:

```text
@champion
@challenger
@shadow
@rollback
```

Runtime reference:

```text
models:/btc-regime-deployment-bundle@champion
```

Promotion sequence:

```text
new immutable version
-> @challenger
-> @shadow
-> paper validation
-> canary validation
-> previous @champion becomes @rollback
-> new version becomes @champion
```

Every alias change records actor, timestamp, reason, source version, target version and evidence report.

MLflow stores evidence but does not decide promotion. The project promotion service requires statistical, economic and alignment passes, outer-test reports, paired bootstrap evidence, cost-stress pass, shadow, paper and canary pass, and manual approval. A higher point estimate alone is insufficient.

Rollback disables exposure increases, reconciles the position and orders, activates the previous complete signed bundle, verifies hashes and instrument state, runs a dry decision, resumes in `SAFE_READ_ONLY` and requires manual transition to `READY`. Partial rollback is prohibited.

## 24. Runtime state is not a model artifact

The Model Registry must not store `last_processed_as_of`, current probabilities, positions, orders, drawdown or daily loss. These belong in the runtime state and audit database.

## 25. Reproducibility, retention and access

Before registration:

- save/load preserves output;
- identical input and artifact reproduce probabilities;
- golden prediction vectors match tolerance;
- wrong feature order or hash fails;
- unknown state mapping fails;
- invalid probability sums fail;
- the dependency environment is reconstructable.

Registered model versions, outer-test reports, dataset digests and code commits are immutable. Failed runs are retained for audit and multiple-testing control. Promoted or previously promoted artifacts are not deleted while referenced.

The Tracking Server requires authentication and network restriction. Research workers may create runs but cannot move `@champion`; alias movement requires elevated permission and is auditable.

## 26. Backup, recovery and readiness

Back up deployment and capital configurations, compatible bundles, model and allocator artifacts, instrument specifications, decision state, execution plans, exchange acknowledgements, reconciliation snapshots, audit and incident records.

Recovery testing must reconstruct analytical state and reconcile the live position without duplicate execution.

Production activation requires no-withdrawal credentials, secret management, verified contract semantics, isolated margin and one-way enforcement, 1x leverage cap, small-account capability, idempotency and locking, persisted state machines, reconciliation, mark/index/liquidation/funding monitoring, tested kill switch, alerts and runbooks, dashboards, backup and recovery, atomic rollback, completed paper and canary stages, and a named operational owner.