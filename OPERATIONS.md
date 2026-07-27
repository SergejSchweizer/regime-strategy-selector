# Operations and Model Governance

This document defines Production V1 runtime behaviour, security, monitoring, incident handling, use of the existing NAS MLflow service, Model Registry governance, promotion, rollback and implementation work packages for one fixed linear BTC-perpetual deployment.

```text
operations_version = 2.2.0
mlflow_governance_version = 1.2.0
implementation_workflow_version = 1.1.0
```

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
MLflow is an external shared service
runtime decisions do not require live MLflow access
```

The analytical and execution systems remain independently restartable. Restarting either system must not create duplicate decisions, plans or protective orders.

## 2. Existing MLflow service baseline

The project adopts the following already deployed service:

```text
tracking_uri = http://10.10.1.3:5000
host = 10.10.1.3
port = 5000
transport = HTTP
backend_store = PostgreSQL
service_location = NAS
service_ownership = external shared platform
```

These facts are accepted as the current baseline because they are provided by the operator. They are not inferred from repository code.

The following properties remain `UNVERIFIED` until an integration work package records machine-readable evidence:

```text
MLflow server version
API compatibility with the selected client version
Model Registry availability
model alias support
artifact repository type
artifact upload/download behaviour
artifact durability across restart
PostgreSQL persistence across restart
PostgreSQL backup and restore process
authentication and authorisation
TLS or reverse-proxy protection
network exposure outside the trusted LAN
```

An unverified property is not a usable production capability.

### 2.1 Current security posture

The current endpoint uses plain HTTP. Until authentication and TLS are verified:

```text
use only from a trusted private LAN or VPN
never expose 10.10.1.3:5000 directly to the public internet
never log exchange credentials, passwords, access tokens or private keys
never place secrets in parameters, tags, artifact names or artifacts
assume traffic can be observed by any host with access to the LAN path
```

The project may use the endpoint for research metadata and non-secret artifacts after the basic capability probe passes. Promotion to paper, canary or production additionally requires the external-platform readiness evidence defined in this document.

## 3. Responsibility boundary

### This repository owns

```text
MLflow client configuration
endpoint health and compatibility checks
project experiment taxonomy
run roles, tags, parameters and metric namespaces
dataset references and digests
project artifacts and model packages
registered-model naming
candidate-versus-champion evidence
promotion and rollback policy
runtime audit references to immutable model versions
```

### The external NAS platform owns

```text
MLflow server process
PostgreSQL process and persistence
artifact-store implementation and persistence
network exposure
server authentication and authorisation
TLS and reverse proxy when introduced
server backup and restore
server upgrades and database migrations
```

This repository must not create a second local MLflow, PostgreSQL or object-store stack. It verifies the external service and fails clearly when required capabilities are unavailable.

## 4. Process topology

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

external dependency:
http://10.10.1.3:5000
    MLflow Tracking Server and Model Registry
    PostgreSQL-backed metadata
    artifact capability to be verified
```

Components may initially share a process, but contracts and persisted state remain separate.

## 5. MLflow capability states

The client exposes one platform status:

```text
UNVERIFIED
AVAILABLE
DEGRADED
UNAVAILABLE
INCOMPATIBLE
```

Definitions:

| State | Meaning | Allowed behaviour |
|---|---|---|
| `UNVERIFIED` | capability probe has not completed | unit tests and local deterministic work only |
| `AVAILABLE` | required API, registry and artifact checks pass | research logging, registration and approved promotion operations |
| `DEGRADED` | tracking works but one non-critical capability fails | existing runs may continue; no registration or promotion |
| `UNAVAILABLE` | endpoint cannot be reached | no remote logging, registration or promotion |
| `INCOMPATIBLE` | server/client or schema capability is unsupported | fail integration work until compatibility is resolved |

The status is evaluated per operation. A tracking-only research task may require fewer capabilities than model registration.

## 6. Deployment preparation and runtime separation

### 6.1 Deployment preparation

Deployment preparation may access MLflow and performs:

1. resolve the approved immutable registered-model version;
2. resolve the source run and artifact references;
3. download or copy the complete compatible deployment bundle;
4. verify artifact hashes, signatures, contracts and dependency metadata;
5. store the bundle in the deployment artifact directory;
6. persist a deployment manifest containing the exact MLflow identity;
7. execute golden prediction tests;
8. mark the bundle as locally materialised and deployment-eligible.

### 6.2 Runtime startup

Runtime startup does **not** resolve `@champion` on every restart. It loads the locally materialised immutable bundle named by `DeploymentConfig.v1`.

Startup proceeds in this order:

1. load `DeploymentConfig.v1`;
2. verify `target_symbol = BTC`;
3. load current `CapitalAllocation.v1`;
4. load the exact local compatible bundle and deployment manifest;
5. verify recorded MLflow model name, immutable version and source run;
6. verify code, dependency, feature, methodology, risk, operations and artifact hashes;
7. verify BTC perpetual and spot-reference specifications;
8. connect market data and exchange in read-only mode;
9. verify the configured linear BTC perpetual;
10. verify isolated margin, one-way mode and maximum production leverage of 1x;
11. verify reduce-only support;
12. reconcile cash, margin, position, orders and protective orders;
13. verify mark, index, liquidation and funding data;
14. verify the system clock;
15. validate `SmallAccountCapability.v1`;
16. acquire the deployment leadership lock;
17. execute golden prediction tests for the local bundle;
18. enable analytical decisions;
19. enable exposure-changing execution only after every prior check passes.

If MLflow is unavailable during runtime startup but the local bundle is valid, runtime may start under the normal safety rules. If the local bundle is absent, incomplete or hash-invalid, startup fails even when MLflow is reachable.

## 7. Runtime state machines

### 7.1 Deployment states

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

### 7.2 Decision states

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

## 8. Exactly-once semantics

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

## 9. Hourly decision schedule

At every scheduled UTC hour:

1. wait for the final source M1 bucket to close;
2. verify BTC spot and perpetual watermarks and clock;
3. build and persist `MarketFeatureFrame.v1`;
4. run the locally loaded regime estimator and enabled experts;
5. run the allocator;
6. read reconciled position, margin and liquidation state;
7. run the Risk Engine;
8. persist `DecisionAuditRecord.v1`;
9. send an unexpired approval to execution;
10. create at most one execution plan;
11. reconcile fills and position;
12. activate or replace reduce-only protective orders;
13. append execution and portfolio results to the audit chain;
14. enqueue non-blocking operational metric publication when enabled.

A late decision expires; it does not shift the schedule. MLflow connectivity is never in the critical hourly decision path.

## 10. Safe degradation

Feature failure, inference failure, allocator abstention, risk rejection, high entropy, stale capital or cost state, mark/index divergence, insufficient liquidation buffer, broken reconciliation, execution connectivity loss and decision expiry allow only preservation or reduction of absolute exposure.

MLflow failures have these effects:

| Failure | Runtime effect |
|---|---|
| tracking unavailable during research run start | fail the integration run before expensive computation unless offline mode is explicitly allowed |
| tracking unavailable after a research run starts | retain local recovery manifest; mark the run incomplete; do not claim evidence was logged |
| Registry unavailable | block model registration and deployment preparation |
| alias operation unavailable | block promotion and rollback-alias changes |
| artifact download unavailable | block new deployment preparation |
| MLflow unavailable during hourly runtime | continue using the verified local bundle; alert; block promotion only |
| local bundle invalid | halt regardless of MLflow availability |

There is no automatic fallback model.

## 11. Security

Production exchange API keys must have trading permission only, no withdrawal permission, sub-account restriction, IP allow-listing when available and no unnecessary instrument permissions.

Secrets come from an approved secret manager and are prohibited in Git, model artifacts, MLflow parameters, MLflow tags, artifact names, images, plaintext configuration, notebooks and logs.

Paper, canary and production use separate credentials and preferably separate accounts or sub-accounts. Promotion, capital changes, risk changes and kill-switch release require authenticated, auditable operator actions.

The MLflow endpoint configuration is non-secret. Future username/password values are secret and must be supplied only through the approved environment or secret mechanism.

## 12. Logging and audit

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

Every deployment and runtime decision records:

```text
mlflow_tracking_uri = http://10.10.1.3:5000
mlflow_registered_model_name
mlflow_model_version
mlflow_model_alias_at_deployment_time
source_run_id
artifact_sha256
bundle_materialised_at
output_contract_version
state_schema_version
feature_set_hash
dataset_digest
code_commit
dependency_lock_hash
```

The immutable model version is mandatory. The alias alone is insufficient.

## 13. Monitoring

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

### Risk and execution

- approved fraction and notional;
- isolated margin use;
- mark/index divergence and liquidation buffer;
- funding and realised funding;
- clipping, rejection and halt counts;
- daily loss, drawdown and turnover;
- order age, fill latency, fees and slippage;
- reconciliation status.

### MLflow integration

- endpoint reachability;
- server version and client compatibility;
- request latency;
- failed run creations;
- failed metric and artifact writes;
- artifact round-trip status;
- Registry and alias capability status;
- incomplete-run recovery manifests;
- age of last successful platform validation;
- age of external PostgreSQL and artifact backup evidence when supplied by the platform operator.

## 14. Deployment environments

```text
historical replay
-> live feature shadow
-> full decision shadow
-> paper execution
-> small-capital canary
-> restricted production
```

Historical replay uses production decision code with historical adapters. Feature shadow has no execution. Decision shadow persists full decisions but sends no approvals. Paper uses a paper venue or deterministic simulator. Canary uses a dedicated small allocation, strict loss limits and reduced target changes.

# MLflow usage

## 15. Client configuration

The current default configuration is:

```text
MLFLOW_TRACKING_URI=http://10.10.1.3:5000
```

Configuration rules:

```text
the URI is loaded from typed configuration
the documented default may be overridden explicitly
the resolved URI is logged in integration evidence
unit tests use an in-memory fake or local test double, never the NAS endpoint
integration tests use a dedicated project-prefixed experiment
timeouts and retry counts are finite and versioned
no automatic fallback to local ./mlruns
```

Authentication variables are optional only while the server is verified as unauthenticated:

```text
MLFLOW_TRACKING_USERNAME
MLFLOW_TRACKING_PASSWORD
```

When authentication is enabled externally, client work introduces credentials through secrets without changing experiment or model identity.

## 16. Adoption verification order

The first MLflow stack verifies the existing service in this order:

1. TCP and HTTP reachability of `10.10.1.3:5000`;
2. health endpoint or API-level health request;
3. server version and client compatibility;
4. create, read and terminate a project-prefixed test run;
5. log and retrieve parameters, tags and metrics;
6. upload and download a deterministic checksum artifact;
7. restart-persistence evidence supplied or executed by the platform owner;
8. create or verify the project experiment namespace;
9. register a disposable test model version;
10. verify model version retrieval;
11. verify alias creation, movement and removal;
12. clean up disposable resources when supported;
13. persist `mlflow_capability_report.json`.

The capability report distinguishes `PASS`, `FAIL`, `UNVERIFIED` and `NOT_SUPPORTED` for every feature.

## 17. MLflow responsibility boundary

MLflow owns:

```text
experiment organisation
run metadata
parameters
scalar metrics
dataset references and digests
run artifacts
model packages
input and output signatures
registered model versions
aliases
candidate and champion lineage
promotion evidence references
system metrics for training and inference runs
```

MLflow does not own:

```text
raw historical data
live market-data ingestion
feature computation
walk-forward split logic
financial backtesting logic
bootstrap implementation
current filtered probabilities
current positions
open orders
current drawdown
risk-engine state
execution and reconciliation state
```

## 18. MLflow modules and use

### Tracking

Use Tracking for reproducible training, validation, backtest, comparison, shadow, paper and canary runs. Inner-validation and untouched outer-test results use distinct run roles.

### Dataset tracking

Log immutable references, digests, schema hashes and contexts for training, validation, testing, shadow, paper and canary frames. Do not upload the historical lake merely to duplicate storage.

### Artifact logging

Log structured evidence including dataset manifests, split manifests, feature schemas, state signatures, state mappings, equity curves, trade ledgers, cost reports, bootstrap reports, placebo reports, golden fixtures and deployment manifests.

### Custom model packaging

Every promotable regime estimator uses one common MLflow PyFunc-compatible interface. The wrapper owns feature validation, ordering, scaling, filtered inference, four-hour projection, persistent-state mapping, canonical probability order, entropy and output validation.

### Signatures and examples

Every logged model contains an input signature, output signature, representative input example, serving input example and reconstructable dependency environment.

### Model Registry

Use project-qualified registered model names:

```text
regime-strategy-selector--regime-estimator
regime-strategy-selector--deployment-bundle
```

The deployment bundle contains or references the exact estimator, scaler, feature contract, state schema, mapping, affinity matrix, strategy configuration, exits, risk configuration, cost model, timing policy, code commit and dependency lock.

### Aliases

```text
@champion
@challenger
@shadow
@rollback
```

Aliases may be used for operator selection. Deployment manifests always record the resolved immutable version.

### Model evaluation

MLflow model evaluation may be used for conventional supervised diagnostics. Path-dependent financial evaluation remains in project code and its results are logged to MLflow.

### System metrics

Enable system metrics for multi-seed model training, alternative model training, large walk-forward evaluation, bootstrap evaluation and deployment-stage inference diagnostics.

### Search and reporting

Search queries must filter by project, run role, experiment-design version, dataset digest and code commit before metrics are compared.

## 19. Experiment taxonomy

```text
regime-strategy-selector/00-platform-validation
regime-strategy-selector/10-data-and-feature-validation
regime-strategy-selector/20-standalone-exit-optimisation
regime-strategy-selector/30-regime-model-selection
regime-strategy-selector/40-regime-incremental-value
regime-strategy-selector/50-regime-dependent-exits
regime-strategy-selector/60-learned-allocator
regime-strategy-selector/90-shadow-paper-canary
```

The platform-validation experiment is reserved for deterministic integration checks. It must not contain financial research evidence.

## 20. Run hierarchy

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

Child runs represent deterministic seeds, inner folds, hyperparameter combinations, exit profiles, cost scenarios, placebo variants and bootstrap summaries.

Outer-test results are logged only after inner selection is complete and frozen.

## 21. Required tags

```text
project = regime-strategy-selector
repository = SergejSchweizer/regime-strategy-selector
work_package_id = string
tracking_uri = http://10.10.1.3:5000
target_symbol = BTC
traded_instrument_type = LINEAR_PERPETUAL
run_role = INTEGRATION_TEST|INNER_TRAIN|INNER_VALIDATION|OUTER_TEST|PLACEBO|SHADOW|PAPER|CANARY
candidate_role = BASELINE|CHAMPION|CHALLENGER|NOT_APPLICABLE
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

## 22. Required parameters and metrics

Common parameters include fold windows, purge and embargo, horizons, random seed, code commit, dependency lock hash, dataset identity and digest, feature-set hash, risk config version and cost model version.

Statistical metrics include predictive log likelihood, seed convergence and stability, state occupancy and duration, alignment distance, entropy, transition stability, signature stability, invalid probability count and inference latency.

Economic metrics include net return, annualised return, Calmar, Sharpe, Sortino, maximum drawdown, CVaR, turnover, trade count, profit factor, fold concentration, slippage and spread cost.

Candidate comparisons include paired differences, outer-fold win fraction and paired bootstrap confidence intervals.

Every metric uses a scope prefix:

```text
platform/
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

## 23. Required artifacts

### Platform adoption

```text
mlflow_capability_report.json
mlflow_server_version.json
mlflow_client_compatibility.json
tracking_roundtrip_report.json
artifact_roundtrip_report.json
registry_roundtrip_report.json
external_platform_evidence_manifest.json
```

### Data and model research

```text
dataset_manifest.json
feature_schema.json
feature_order.json
walk_forward_splits.json
point_in_time_validation_report.json
raw_model.bin
scaler.json
transition_matrix.json
state_signatures.json
state_mapping.json
alignment_report.json
model_signature.json
seed_stability_report.json
fold_metrics.parquet
equity_curve.parquet
trade_ledger.parquet
bootstrap_report.json
placebo_report.json
cost_stress_report.json
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

## 24. Registration and promotion gates

Before registration:

```text
platform capability required for the operation is AVAILABLE
save/load preserves output
identical input and artifact reproduce probabilities
golden vectors match tolerance
wrong feature order or hash fails
unknown state mapping fails
invalid probability sums fail
dependency environment is reconstructable
statistical outer-test evidence exists
economic outer-test evidence exists when required
```

Promotion sequence:

```text
search eligible candidates
resolve current champion
verify identical folds and dataset digests
verify contracts and bundle compatibility
evaluate statistical and economic gates
verify paired bootstrap and cost stress
register immutable candidate
assign @challenger
run shadow
assign @shadow when eligible
run paper
run canary
require manual approval
move previous @champion to @rollback
move candidate to @champion
materialise and verify the selected immutable bundle
```

If Registry or alias capability is unavailable, promotion is blocked. A higher point estimate alone is insufficient.

## 25. External platform readiness evidence

Before paper, canary or production promotion, the platform operator must provide or execute evidence for:

```text
PostgreSQL data persists across controlled restart
artifacts persist across controlled restart
PostgreSQL backup exists and is restorable
artifact backup exists and is restorable
server version is pinned or recorded
network exposure is limited to approved hosts
public internet exposure is absent
authentication status is documented
TLS status is documented
operator and recovery contacts are documented
```

This repository stores references and checksums for that evidence. It does not implement the external infrastructure.

# Implementation workflow

## 26. Deterministic stacked PR protocol

A work package produces exactly one primary PR unless explicitly split.

```text
branch = agent/<lowercase-work-package-id>-<short-description>
title = [<WORK_PACKAGE_ID>] <imperative outcome>
```

Every PR declares exact parents, base commit, owned files, deterministic fixtures, acceptance commands, MLflow requirements, external-service assumptions, rollback and non-goals.

A PR must not combine unrelated refactoring, multiple model families, research selection and production promotion, external platform provisioning and trading logic, or cleanup unrelated to the work package.

## 27. S20: Adopt the existing NAS MLflow service

| ID | Objective | Depends on | Completion gate |
|---|---|---|---|
| S20-P01 | Add typed MLflow client configuration with default URI `http://10.10.1.3:5000` | S00-P02 | configuration and override tests pass |
| S20-P02 | Implement finite-timeout reachability, version and compatibility probe | S20-P01 | deterministic capability report |
| S20-P03 | Implement project experiment naming and common run metadata | S20-P02 | metadata contract tests pass |
| S20-P04 | Implement run, parameter, metric and tag round-trip in the validation experiment | S20-P03 | tracking round-trip passes |
| S20-P05 | Implement dataset-input and checksum-artifact round-trip | S20-P04, S10-P01 | lineage and artifact reports pass |
| S20-P06 | Verify Model Registry model-version operations | S20-P05 | disposable registration round-trip passes |
| S20-P07 | Verify alias operations and permission failure handling | S20-P06 | alias capability report passes or records `NOT_SUPPORTED` |
| S20-P08 | Implement parent/child runs and run-role validation | S20-P04 | invalid role mixing fails |
| S20-P09 | Implement metric namespace validation | S20-P08 | unscoped metrics fail |
| S20-P10 | Implement run search and evidence-summary utilities | S20-P09 | deterministic candidate tables |
| S20-P11 | Implement incomplete-run local recovery manifests | S20-P04 | interrupted logging recovery test passes |
| S20-P12 | Add external-platform readiness evidence schema and validation | S20-P02 | missing production prerequisites fail closed |

Removed from this repository plan:

```text
local PostgreSQL deployment
local MLflow server deployment
local object-store deployment
reverse-proxy deployment
server authentication provisioning
server backup implementation
```

These are owned by the external NAS platform.

## 28. Other foundation and platform work packages

### S00: Foundations

| ID | Objective | Depends on | Completion gate |
|---|---|---|---|
| S00-P01 | Establish package layout, formatting, typing and test commands | none | clean deterministic toolchain |
| S00-P02 | Implement canonical configuration loading and version validation | S00-P01 | invalid config fails closed |
| S00-P03 | Implement shared IDs, hashing, clocks and deterministic fixtures | S00-P02 | stable IDs and fixture suite |
| S00-P04 | Generate typed public contracts from architecture schemas | S00-P02 | schema compatibility tests pass |

### S60: Deterministic risk engine

| ID | Objective | Depends on | Completion gate |
|---|---|---|---|
| S60-P01 | Implement stop-distance and capital-based sizing caps | S50-P02 | sizing property tests pass |
| S60-P02 | Implement funding, cost, turnover and target-change limits | S60-P01 | boundary tests pass |
| S60-P03 | Implement drawdown, daily-loss and liquidation gates | S60-P02 | fail-closed tests pass |
| S60-P04 | Implement abstention and reduce-only degradation | S60-P03 | exposure never increases on failure |
| S60-P05 | Implement `ApprovedTargetPosition.v1` audit reasons | S60-P04 | replayable approval decisions |

### S70: Integrated replay and audit

| ID | Objective | Depends on | Completion gate |
|---|---|---|---|
| S70-P01 | Compose feature, model, experts, allocator and risk decision function | S30-P07, S40-P07, S50-P06, S60-P05 | deterministic decision replay |
| S70-P02 | Implement historical execution simulator | S70-P01 | timing and adverse-fill tests |
| S70-P03 | Implement immutable decision audit chain | S70-P01 | hash-chain replay test |
| S70-P04 | Implement complete cost and funding accounting | S70-P02 | ledger reconciliation passes |
| S70-P05 | Build compatible deployment bundle | S70-P03, S70-P04, S20-P05 | bundle compatibility test |
| S70-P06 | Register candidate bundle and golden predictions | S70-P05, S30-P07, S20-P06 | registration gates pass |

### S80: Deployment and promotion

| ID | Objective | Depends on | Completion gate |
|---|---|---|---|
| S80-P01 | Implement immutable bundle materialisation and startup checks | S70-P06 | runtime starts without live MLflow when local bundle is valid |
| S80-P02 | Implement runtime decision and execution state machines | S80-P01 | restart and idempotency tests |
| S80-P03 | Implement feature and decision shadow modes | S80-P02 | shadow parity report |
| S80-P04 | Implement paper execution and reconciliation | S80-P03, S20-P12 | paper readiness gates |
| S80-P05 | Implement canary controls and monitoring | S80-P04 | canary readiness gates |
| S80-P06 | Implement Registry alias promotion service | S80-P05, S20-P07 | audited alias movement |
| S80-P07 | Implement atomic local-bundle rollback and recovery drill | S80-P06 | rollback replay passes without live MLflow dependency |
| S80-P08 | Implement production readiness report | S80-P07, S20-P12 | all required evidence linked |

## 29. Production readiness

Production activation requires:

```text
verified access to http://10.10.1.3:5000
compatible MLflow client/server versions
verified tracking, artifact and Registry capabilities
external PostgreSQL and artifact persistence evidence
external backup and restore evidence
approved LAN/VPN exposure and documented HTTP security posture
complete lineage from dataset to immutable deployment bundle
locally materialised and hash-verified champion bundle
no-withdrawal exchange credentials
secret management
verified contract semantics
isolated margin and one-way enforcement
1x leverage cap
idempotency and locking
persisted runtime state machines
reconciliation
liquidation and funding monitoring
tested kill switch
alerts and runbooks
atomic rollback
completed paper and canary stages
named operational owner
```

The current existence of the NAS endpoint alone is not production-readiness evidence. It is the starting dependency for the adoption stack.
