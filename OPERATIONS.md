# Operations and Model Governance

This document defines Production V1 runtime behaviour, security, monitoring, incident handling, shared MLflow usage, Model Registry governance, promotion, rollback and implementation work packages for one fixed linear BTC-perpetual deployment.

```text
operations_version = 2.2.0
mlflow_governance_version = 1.2.0
implementation_workflow_version = 1.1.0
```

Exact calculations and research validation remain in [`METHODOLOGY.md`](METHODOLOGY.md). Public contracts and system boundaries remain in [`ARCHITECTURE.md`](ARCHITECTURE.md).

# Runtime operations

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
runtime monitoring and alerting
shared MLflow Tracking Server and Model Registry
```

Components may initially share a process, but their contracts and persisted states remain separate.

The shared MLflow platform is an external control-plane dependency maintained in `SergejSchweizer/mlflow`. It is not the runtime state store.

## 3. Startup sequence

Startup proceeds in this order:

1. load `DeploymentConfig.v1`;
2. verify `target_symbol = BTC`;
3. load current `CapitalAllocation.v1`;
4. connect to the shared MLflow platform using the runtime read-only identity;
5. resolve `regime-strategy-selector--deployment-bundle@champion`;
6. resolve and record the immutable model version behind the alias;
7. load `CompatibleArtifactSet.v1` atomically;
8. verify BTC perpetual and spot-reference specifications;
9. verify code, dependency, feature, methodology, risk, operations and artifact hashes;
10. connect market data and exchange in read-only mode;
11. verify the configured linear BTC perpetual;
12. verify isolated margin, one-way mode and maximum production leverage of 1x;
13. verify reduce-only support;
14. reconcile cash, margin, position, open orders and protective orders;
15. verify mark, index, liquidation and funding data;
16. verify the system clock;
17. validate `SmallAccountCapability.v1`;
18. acquire the deployment leadership lock;
19. execute golden prediction tests for the loaded bundle;
20. enable analytical decisions;
21. enable exposure-changing execution only after every prior check passes.

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
4. run the regime estimator and enabled experts;
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

Production exchange API keys must have trading permission only, no withdrawal permission, sub-account restriction, IP allow-listing when available and no unnecessary instrument permissions.

Secrets come from an approved secret mechanism and are prohibited in Git, MLflow artifacts, images, plaintext configuration, notebooks and logs.

Paper, canary and production use separate credentials and preferably separate accounts or sub-accounts. Promotion, capital changes, risk changes and kill-switch release require authenticated and auditable operator actions.

MLflow identities are separate from exchange identities.

## 11. Logging and audit

Every runtime service emits:

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

Every runtime decision records the exact MLflow identity:

```text
mlflow_registered_model_name
mlflow_model_version
mlflow_model_alias_at_decision_time
source_run_id
artifact_sha256
output_contract_version
state_schema_version
feature_set_hash
dataset_digest
code_commit
dependency_lock_hash
```

The resolved immutable model version, not only the alias, is mandatory for audit.

## 12. Runtime monitoring

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
- abstention rate;
- inference latency;
- invalid probability count.

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

Runtime monitoring is not replaced by MLflow run metrics.

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

Historical replay uses production decision code with historical adapters. Feature shadow has no execution. Decision shadow persists full decisions but sends no approvals. Paper uses a paper venue or deterministic simulator. Canary uses dedicated small capital, strict loss limits and reduced target changes. Restricted production retains conservative limits and never exceeds absolute fraction 1.0.

# Shared MLflow usage

## 15. Responsibility boundary

MLflow is the experiment and model control plane.

### MLflow owns

```text
experiment organisation
run metadata
parameters and scalar or time-series metrics
dataset references and digests
run artifacts
model packages
input and output signatures
registered model versions and aliases
candidate and champion lineage
promotion evidence references
system metrics emitted by client workers
```

### MLflow does not own

```text
raw historical data
live market-data ingestion
feature computation
walk-forward split logic
financial backtesting logic
current filtered probabilities
current positions and open orders
current drawdown and risk-engine state
execution and reconciliation state
```

## 16. Shared platform integration

The project connects to the shared platform maintained in `SergejSchweizer/mlflow`.

```text
GitHub
    source code, contracts, configs and tests

shared MLflow platform
    Tracking Server, Model Registry, backend PostgreSQL,
    RustFS artifacts, Caddy ingress and authentication

runtime PostgreSQL
    filtered probabilities, decisions, positions and audit

Parquet or analytical database
    historical market data and feature frames
```

The shared MLflow backend and project runtime database are logically and operationally separate. The client never receives direct RustFS credentials when artifact access is proxied.

Required client configuration:

```text
MLFLOW_TRACKING_URI
MLFLOW_TRACKING_USERNAME
MLFLOW_TRACKING_PASSWORD
MLFLOW_PROJECT_ID = regime-strategy-selector
MLFLOW_EXPERIMENT_PREFIX = regime-strategy-selector/
MLFLOW_REGISTERED_MODEL_PREFIX = regime-strategy-selector--
```

Credentials are injected outside Git.

## 17. MLflow identities

```text
regime-strategy-selector-research
regime-strategy-selector-promotion
regime-strategy-selector-runtime
```

### Research identity

May create and update project experiments and runs, log dataset inputs, metrics and artifacts, and read project registry resources. It cannot move protected aliases or mutate the deployment-bundle registered model unless the shared platform permission model requires registration to be delegated to the promotion service.

### Promotion identity

May validate evidence, register approved immutable versions and move authorised project aliases. It cannot administer the shared platform.

### Runtime identity

May resolve and load the approved deployment bundle and estimator versions. It is read-only and cannot create research runs or move aliases.

Permission behaviour is validated against the pinned shared-platform MLflow version. Documentation must not assume permission APIs from a different version.

## 18. MLflow modules and exact use

### 18.1 Tracking

Use MLflow Tracking for every reproducible training, validation, backtest, comparison, shadow, paper and canary run.

A run has one semantic role. Inner-validation and untouched outer-test evidence are never written to the same run role.

### 18.2 Dataset tracking

Use MLflow dataset inputs for:

```text
inner training frame
inner validation frame
outer test frame
shadow evaluation frame
paper evaluation frame
canary evaluation frame
```

MLflow stores source URI, digest, schema and profile reference. It does not duplicate the historical lake.

Contexts:

```text
training
validation
testing
shadow
paper
canary
```

### 18.3 Artifact logging

Use run artifacts for structured outputs that do not fit scalar metadata:

```text
dataset and walk-forward manifests
feature schemas and order
model parameters and scalers
state signatures and mappings
equity curves and trade ledgers
cost, bootstrap and placebo reports
golden prediction fixtures
deployment manifests and dependency locks
```

### 18.4 Custom model packaging

Every promotable regime estimator uses one MLflow PyFunc-compatible interface. Models From Code may be used only when the pinned shared-platform version qualifies it; a versioned standard PyFunc packaging path remains available.

The wrapper owns:

```text
feature validation and ordering
scaling
raw inference
filtered probability calculation
four-hour probability projection
persistent-state mapping
canonical probability ordering
entropy and maximum-probability calculation
output validation
```

The public output is always `RegimePrediction.v1`.

### 18.5 Model signatures and examples

Every logged model includes:

```text
input signature
output signature
representative input example
serving input example
dependency environment
```

Domain invariants require finite probabilities in `[0,1]`, vectors summing to one, canonical state order, filtered point-in-time outputs and matching feature and artifact hashes.

### 18.6 System metrics

Enable MLflow system metrics for computationally significant runs:

```text
multi-seed HMM training
alternative model training
large walk-forward evaluation
bootstrap evaluation
shadow inference
paper inference
canary inference
```

Collector dependencies such as `psutil`, sampling settings and node identity belong to this client repository and its dependency lock. The shared platform only guarantees ingestion, persistence and search.

### 18.7 Search and reporting

Use the MLflow search API and UI to construct:

```text
candidate-versus-champion tables
seed stability tables
outer-fold comparisons
exit robustness tables
failed-run inventories
promotion evidence summaries
shadow, paper and canary summaries
```

Queries filter by run role, experiment-design version, dataset digest and code commit before metrics are compared.

## 19. Experiment taxonomy

```text
regime-strategy-selector/00-data-and-feature-validation
regime-strategy-selector/10-standalone-exit-optimisation
regime-strategy-selector/20-regime-model-selection
regime-strategy-selector/30-regime-incremental-value
regime-strategy-selector/40-regime-dependent-exits
regime-strategy-selector/50-learned-allocator
regime-strategy-selector/90-shadow-paper-canary
```

Separate causal questions remain in separate experiments.

## 20. Run hierarchy and granularity

A parent run represents one reproducible experiment definition:

```text
candidate family
dataset snapshot
outer fold
experiment-design version
search-space version
cost assumptions
risk configuration
code commit
dependency lock
```

Child runs represent:

```text
deterministic seed
inner fold
hyperparameter combination
exit-profile combination
cost scenario
placebo variant
bootstrap summary
```

```text
parent: candidate x outer_fold
    |-- child: seed
    |-- child: inner_fold x parameter combination
    |-- child: BASE cost
    |-- child: ELEVATED cost
    `-- child: SEVERE cost
```

Outer-test results are logged only after inner selection is complete and frozen.

Bounded deployment runs:

```text
one shadow run = one evaluation window
one paper run = one deployment bundle and paper episode
one canary run = one deployment bundle and canary observation window
```

One MLflow run per hourly decision is prohibited. Hourly decisions remain in the runtime audit store.

## 21. Required MLflow tags

```text
project = regime-strategy-selector
repository = SergejSchweizer/regime-strategy-selector
work_package_id = string
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
code_commit = full SHA
dataset_digest = immutable digest
owner = string
```

Tags identify semantics; they do not replace metrics.

## 22. Required MLflow parameters

### Common

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

### Regime model

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

### Exit and allocator

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

## 23. Metric namespace

Every metric uses one scope prefix:

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
system/
```

Required families include:

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
inference_latency_ms
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
expected_slippage_bps
realised_slippage_bps
spread_cost_bps
```

### Robustness and comparison metrics

```text
neighbourhood_score_mean
neighbourhood_score_std
neighbourhood_worst_score
parameter_sensitivity_rank
score_relative_to_inner_best
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

Path-dependent financial evaluation remains project code; MLflow stores its outputs.

## 24. Dataset lineage

Every run logs:

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

Mutable paths such as `latest.parquet` are insufficient. A child-run digest must match its parent experiment definition.

## 25. Required artifacts

### Data and splits

```text
dataset_manifest.json
feature_schema.json
feature_order.json
walk_forward_splits.json
point_in_time_validation_report.json
missingness_report.json
historical_live_parity_report.json
```

### Regime model

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
seed_stability_report.json
```

### Strategy and exits

```text
strategy_config.json
exit_search_space.json
selected_exit_profile.json
exit_surface.parquet
exit_robustness_report.json
standalone_strategy_report.json
```

### Economic evaluation

```text
fold_metrics.parquet
equity_curve.parquet
trade_ledger.parquet
cost_breakdown.parquet
bootstrap_report.json
placebo_report.json
cost_stress_report.json
benchmark_comparison.json
candidate_evidence_report.json
```

### Deployment

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

Artifact sizes must remain within the shared-platform qualified limits. Oversized evaluation surfaces are partitioned or compressed according to the project artifact policy.

## 26. Model Registry and bundle contract

Registered models:

```text
regime-strategy-selector--regime-estimator
regime-strategy-selector--deployment-bundle
```

The estimator model stores statistically and economically evaluated estimator versions.

The deployment-bundle model stores or references one complete compatible set:

```text
regime estimator version
scaler
feature contract
state schema and mapping
affinity matrix
strategy configuration
exit profile set
risk configuration
cost model
timing policy
code commit
dependency lock
```

Production loads the deployment bundle and never independently selects latest component versions.

Aliases:

```text
@champion
@challenger
@shadow
@rollback
```

Runtime reference:

```text
models:/regime-strategy-selector--deployment-bundle@champion
```

Every alias movement records actor, timestamp, reason, previous version, target version and evidence report.

## 27. Registration gates

Before registration:

```text
save/load preserves output
identical input and artifact reproduce probabilities
golden prediction vectors match tolerance
wrong feature order fails
wrong feature hash fails
unknown state mapping fails
invalid probability sums fail
dependency environment is reconstructable
statistical outer-test evidence exists
economic outer-test evidence exists when required
shared-platform round trip passes
```

A research run may be retained without registration.

## 28. Promotion policy

MLflow stores evidence but does not decide promotion. The project promotion service performs the decision using the dedicated promotion identity.

Required sequence:

```text
search promotion-eligible candidates
resolve current champion
verify identical comparison folds and dataset digests
verify contract and bundle compatibility
evaluate statistical and economic gates
verify paired bootstrap
verify BASE, ELEVATED and SEVERE cost scenarios
register immutable candidate
assign @challenger
run shadow
assign @shadow when eligible
run paper
run canary
require manual approval
move previous @champion to @rollback
move candidate to @champion
```

A higher point estimate alone is insufficient.

## 29. Rollback

Rollback:

1. disables exposure increases;
2. reconciles positions and orders;
3. resolves the previous complete bundle from `@rollback` to an immutable version;
4. verifies hashes, contract identity, margin mode and position mode;
5. executes a dry decision;
6. resumes in `SAFE_READ_ONLY`;
7. requires manual transition to `READY`.

Partial rollback is prohibited.

## 30. Runtime state is not a model artifact

The Model Registry must not store:

```text
last_processed_as_of
current probabilities
current position
open orders
protective orders
current drawdown
daily loss
```

These belong in the runtime state and audit database.

## 31. Reproducibility, retention and access

Registered model versions, outer-test reports, dataset digests and code commits are immutable. Failed runs are retained according to the project `research-audit` retention class for audit and multiple-testing control. Promoted or previously promoted artifacts are not deleted while referenced.

The shared platform performs destructive garbage collection only after a dry run, backup gate and protected-reference check.

## 32. Backup and recovery boundary

The shared platform backs up the MLflow backend database and RustFS artifact store.

This project additionally backs up:

```text
deployment and capital configurations
compatible deployment bundle references
instrument specifications
decision state
execution plans
exchange acknowledgements
reconciliation snapshots
audit and incident records
```

Recovery testing must reconstruct analytical state, reload the immutable approved bundle and reconcile the live position without duplicate execution.

# Implementation workflow

## 33. Deterministic stacked PR protocol

A work package produces exactly one primary PR unless its table explicitly defines separable outputs.

### Branch and title

```text
branch = agent/<lowercase-work-package-id>-<short-description>
title = [<WORK_PACKAGE_ID>] <imperative outcome>
```

### Parent relation

```yaml
work_package_id: S20-P02
depends_on:
  - S20-P01
base_commit: exact parent SHA
stack_parent_branch: agent/s20-p01-mlflow-client
```

A dependent PR initially targets its stack parent. After squash merge, it rebases onto the resulting mainline commit and is revalidated before retargeting.

### Atomicity

One PR changes one contract, implementation slice, deterministic test layer or integration boundary. It must not combine unrelated refactoring, multiple model families, research selection and production promotion, infrastructure provisioning and trading logic, or unrelated cleanup.

### Determinism

Every PR defines:

```text
fixed random seeds
fixed fixture timestamps
fixed dataset digest or synthetic fixture version
stable ordering
explicit numerical tolerance
exact acceptance commands
expected artifact names
```

Tests may not depend on wall-clock time, mutable `latest` paths, unordered iteration, unrecorded randomness or unbounded network responses.

## 34. Required PR body

```yaml
work_package_id: string
objective: one observable outcome
depends_on: [work package IDs]
base_commit: SHA
contracts_added: [contract versions]
contracts_changed: [contract versions]
files_owned: [paths]
implementation_summary: [ordered steps]
acceptance_commands: [exact commands]
deterministic_fixtures: [fixture IDs]
mlflow_experiment: exact canonical name or NOT_APPLICABLE
mlflow_run_role: exact role or NOT_APPLICABLE
mlflow_parameters: [required keys]
mlflow_metrics: [required keys]
mlflow_artifacts: [required paths]
rollback_or_disable_path: description
non_goals: [explicit exclusions]
```

A PR is incomplete when a required field is omitted.

## 35. Foundation and integration work packages

### S00 — Foundations

| ID | Objective | Depends on | Completion gate |
|---|---|---|---|
| S00-P01 | Establish package layout, formatting, typing and test commands | none | deterministic toolchain passes |
| S00-P02 | Implement canonical configuration loading and version validation | S00-P01 | invalid config fails closed |
| S00-P03 | Implement shared IDs, hashing, clocks and deterministic fixtures | S00-P02 | stable IDs and fixtures pass |
| S00-P04 | Generate typed public contracts from architecture schemas | S00-P02 | compatibility tests pass |

### S20 — Shared MLflow integration

| ID | Objective | Depends on | Completion gate |
|---|---|---|---|
| S20-P01 | Add shared Tracking Server client configuration, authentication and health checks | S00-P02 | configured client and explicit failure tests |
| S20-P02 | Implement common run tags and parameters | S20-P01 | metadata contract tests pass |
| S20-P03 | Implement dataset-input and artifact logging helpers | S20-P02, S10-P01 | lineage integration tests pass |
| S20-P04 | Implement canonical experiment naming, parent/child runs and run-role validation | S20-P02 | invalid naming and role mixing fail |
| S20-P05 | Implement metric namespace validation | S20-P04 | unscoped metrics fail |
| S20-P06 | Implement run search and evidence-summary utilities | S20-P05 | deterministic candidate tables |
| S20-P07 | Integrate with the shared NAS MLflow platform and validate client compatibility | S20-P01 | client connects without deploying MLflow infrastructure |
| S20-P08 | Add project onboarding and research, promotion and runtime identity contracts | S20-P07 | permission integration tests or version-specific runbook pass |
| S20-P09 | Qualify representative estimator and deployment-bundle round trips | S20-P03, S20-P04, S20-P08 | immutable version, alias, hashes and golden prediction pass |

`S20-P07` explicitly excludes local MLflow PostgreSQL, RustFS, Caddy and authentication deployment. Those are owned by `SergejSchweizer/mlflow`.

`S20-P08` owns client identity requirements and tests; it does not administer the shared platform.

`S20-P09` uses the real project package contract against deterministic fixtures and a non-production alias. It must not move `@champion`.

### S60 — Deterministic risk engine

| ID | Objective | Depends on | Completion gate |
|---|---|---|---|
| S60-P01 | Implement stop-distance and capital-based sizing caps | S50-P02 | sizing property tests pass |
| S60-P02 | Implement funding, cost, turnover and target-change limits | S60-P01 | boundary tests pass |
| S60-P03 | Implement drawdown, daily-loss and liquidation gates | S60-P02 | fail-closed tests pass |
| S60-P04 | Implement abstention and reduce-only degradation | S60-P03 | exposure never increases on failure |
| S60-P05 | Implement `ApprovedTargetPosition.v1` audit reasons | S60-P04 | approval decisions replay |

### S70 — Integrated replay and audit

| ID | Objective | Depends on | Completion gate |
|---|---|---|---|
| S70-P01 | Compose feature, model, experts, allocator and risk decision function | S30-P07, S40-P07, S50-P06, S60-P05 | deterministic decision replay |
| S70-P02 | Implement historical execution simulator | S70-P01 | timing and adverse-fill tests pass |
| S70-P03 | Implement immutable decision audit chain | S70-P01 | hash-chain replay passes |
| S70-P04 | Implement complete cost and funding accounting | S70-P02 | ledger reconciliation passes |
| S70-P05 | Build compatible deployment bundle | S70-P03, S70-P04, S20-P03 | bundle compatibility passes |
| S70-P06 | Register candidate bundle and golden predictions | S70-P05, S30-P07, S20-P09 | registration gates pass |

### S80 — Deployment and promotion

| ID | Objective | Depends on | Completion gate |
|---|---|---|---|
| S80-P01 | Implement startup compatibility and golden-prediction checks | S70-P06 | unsafe bundle cannot start |
| S80-P02 | Implement runtime decision and execution state machines | S80-P01 | restart and idempotency tests pass |
| S80-P03 | Implement feature and decision shadow modes | S80-P02 | shadow parity report passes |
| S80-P04 | Implement paper execution and reconciliation | S80-P03 | paper readiness gates pass |
| S80-P05 | Implement canary controls and monitoring | S80-P04 | canary readiness gates pass |
| S80-P06 | Implement registry alias promotion service | S80-P05, S20-P08, S20-P09 | audited alias movement passes |
| S80-P07 | Implement atomic rollback and recovery drill | S80-P06 | rollback replay passes |
| S80-P08 | Implement production readiness report | S80-P07 | all required evidence is linked |

## 36. Work-package ownership

```text
ARCHITECTURE.md
    contracts, boundaries and invariants

METHODOLOGY.md
    algorithms, experiments, metrics and research work packages

OPERATIONS.md
    runtime, shared MLflow integration, promotion and platform-client work packages
```

A backlog generator may not merge rows from different stacks or reintroduce client-owned MLflow infrastructure.

## 37. Production readiness

Production activation requires:

```text
no-withdrawal exchange credentials
secret management
verified contract semantics
isolated margin and one-way enforcement
1x leverage cap
small-account capability
idempotency and locking
persisted state machines
reconciliation
mark, index, liquidation and funding monitoring
tested kill switch
alerts and runbooks
runtime dashboards
runtime backup and recovery
shared MLflow client qualification
complete dataset-to-bundle lineage
separate research, promotion and runtime identities
protected alias permission tests
atomic rollback
completed paper and canary stages
named operational owner
```
