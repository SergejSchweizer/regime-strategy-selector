# Operations

This document defines the Production V1 runtime, security, monitoring, incident, promotion, and rollback requirements.

## 1. Operating principles

```text
one deployment = one target symbol = one selected instrument
one decision timestamp = one logical decision
one approval = at most one active execution plan
unknown state = no exposure increase
reconciliation failure = no exposure increase
artifact mismatch = halt
manual promotion only
atomic rollback only
```

The analytical system and execution system must remain independently restartable. Restarting either system must not create a duplicate decision or duplicate order plan.

## 2. Process topology

A production deployment contains:

```text
market-data adapter
feature service
regime service
deterministic expert service
deterministic allocator
risk service
decision store
external execution service
portfolio reconciler
monitoring and alerting
```

The services may run in one process for an initial deployment, but their contracts and persisted state must remain separate.

## 3. Startup sequence

Startup proceeds in this exact order:

1. load `DeploymentConfig.v1`;
2. load current `CapitalAllocation.v1`;
3. load `CompatibleArtifactSet.v1` atomically;
4. verify target symbol, instrument, exchange, horizons, hashes, code commit, and dependency lock;
5. verify operations and risk configurations;
6. connect market data in read-only mode;
7. connect exchange in read-only mode;
8. reconcile cash, position, open orders, and protective orders;
9. verify system clock;
10. acquire the deployment leadership lock;
11. enable analytical decisions;
12. enable exposure-changing execution only after every previous check passes.

Any failure before step 12 leaves the deployment in `SAFE_READ_ONLY`.

## 4. Runtime state machine

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

Allowed transitions:

```text
STARTING → SAFE_READ_ONLY
SAFE_READ_ONLY → READY
READY → DECIDING
DECIDING → READY
DECIDING → EXECUTING
EXECUTING → RECONCILING
RECONCILING → READY
any state → DEGRADED
any state → HALTED
DEGRADED → SAFE_READ_ONLY
HALTED → SAFE_READ_ONLY only after manual acknowledgement
```

There is no direct `HALTED → READY` transition.

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

Transitions are append-only and persisted. A state cannot move backwards.

## 5. Exactly-once decision semantics

### 5.1 Deterministic decision ID

```text
decision_id = hash(
    deployment_id,
    target_symbol,
    instrument_id,
    as_of,
    compatible_artifact_set_id
)
```

The same logical decision always receives the same ID after restart or retry.

### 5.2 Decision lock

Before creating a decision, the service acquires a distributed lock on:

```text
deployment_id + as_of
```

Only one owner may hold the lock. Lock loss before persistence aborts the decision. Lock loss after approval prevents new execution until reconciliation.

### 5.3 Execution idempotency

```text
execution_idempotency_key = hash(approval_id, target_notional)
```

The execution service must reject a second active plan with the same key. Exchange client-order IDs must derive from the execution plan and child-order sequence.

## 6. Decision schedule

Production V1 runs hourly.

At every scheduled hour:

1. wait until the final source M1 bucket is closed;
2. verify source watermark and system clock;
3. build and persist `MarketFeatureFrame.v1`;
4. run Module 1;
5. run all three experts;
6. run Module 2;
7. read current reconciled portfolio state;
8. run Module 3;
9. persist the complete `DecisionAuditRecord.v1` without execution report;
10. send an unexpired approval to execution;
11. reconcile and append execution and portfolio results.

A late decision does not shift the schedule. It expires and the next scheduled hour starts a new decision.

## 7. Service-level objectives and automatic actions

All thresholds are versioned in `OperationsConfig.v1`.

| Condition | Default threshold | Automatic action |
|---|---:|---|
| Market-data bucket delay | > 120 seconds | reject exposure increase for current decision |
| Market-data bucket delay | > 600 seconds | enter `DEGRADED`; reduce-only execution |
| Feature computation duration | > 30 seconds | expire current decision |
| Decision age at execution | > 60 seconds | reject exposure increase |
| Source gap | any gap > 180 minutes | `HALTED` |
| Feature hash mismatch | any occurrence | `HALTED` |
| Artifact compatibility mismatch | any occurrence | startup failure or `HALTED` |
| Wrong symbol or instrument | any occurrence | `HALTED` |
| Portfolio reconciliation | `BROKEN` | cancel non-reduce-only orders; reduce-only mode |
| Reconciliation broken duration | > 300 seconds | `HALTED` |
| Pending execution plan age | > 120 seconds | stop new plans; reconcile |
| Oldest exchange order age | > configured order TTL | cancel and reconcile |
| Normalised regime entropy | > risk limit | abstain; no exposure increase |
| Maximum regime probability | < risk limit | abstain; no exposure increase |
| Daily loss | >= configured limit | cancel exposure-increasing orders; flatten or reduce per risk config; `HALTED` |
| Maximum drawdown | >= configured limit | reduce-only; `HALTED` |
| Kill switch | active | cancel open orders; apply configured emergency flatten; `HALTED` |
| Clock offset | > 500 milliseconds | exposure increase disabled |
| Realised slippage | > 2 × expected for 3 consecutive plans | enter `DEGRADED`; reduce max target change |
| Cost-model error | realised minus expected > configured tolerance | block challenger promotion; alert |

The emergency flatten policy is configured per instrument. It must not be inferred by a model.

## 8. Safe degradation

### 8.1 Preserve or reduce only

The following conditions allow only preservation or reduction of absolute exposure:

- data quality failure;
- model inference failure;
- allocator abstention;
- risk-engine rejection;
- high entropy;
- low maximum regime probability;
- stale capital allocation;
- stale cost model;
- broken reconciliation;
- execution connectivity loss;
- decision expiry.

### 8.2 Cash is not always immediately reachable

For a disconnected exchange or unresolved position, the system records a target of zero but must not claim that the position is flat until reconciliation confirms it.

### 8.3 No hidden fallback model

Production V1 has no secondary model loaded for automatic fallback. Model failure leads to abstention and risk-controlled exposure reduction.

## 9. Security

### 9.1 Exchange API key

Production keys must:

- have trading permission only;
- have no withdrawal permission;
- be restricted to the required exchange account or sub-account;
- use an IP allow-list when supported;
- use the minimum required instrument permissions;
- be rotated on a documented schedule and immediately after a suspected exposure.

### 9.2 Secret storage

Secrets must be loaded from an approved secret manager. They must not be stored in:

- source control;
- model artifacts;
- Docker images;
- plaintext configuration files;
- notebooks;
- logs.

### 9.3 Environment separation

Use separate credentials and, where possible, separate exchange accounts or sub-accounts for:

```text
paper
canary
production
```

A paper or canary process must not possess production credentials.

### 9.4 Access control

Manual promotion, risk-limit changes, capital-allocation changes, and kill-switch release require authenticated, auditable operator actions.

## 10. Logging and audit

Every service emits structured logs containing:

```text
timestamp
deployment_id
decision_id or execution_plan_id
target_symbol
instrument_id
compatible_artifact_set_id
service_version
state transition
result code
incident_id when present
```

Logs must not contain credentials or secret values.

`DecisionAuditRecord.v1` is immutable. Corrections are appended as new records referencing the original record hash.

## 11. Monitoring dashboards

### 11.1 Data and feature dashboard

- source watermark;
- source gaps and duplicates;
- observation age;
- core-feature validity;
- feature build latency;
- historical/live parity checks;
- hash mismatch count.

### 11.2 Model dashboard

- three current probabilities;
- 4-hour forward probabilities;
- normalised entropy;
- maximum probability;
- state occupancy;
- state duration;
- transition matrix drift;
- state-signature distance;
- abstention rate.

### 11.3 Strategy and allocator dashboard

- three expert directions, strengths, and confidence values;
- strategy contribution weights;
- consensus direction;
- cash fraction;
- regime certainty;
- volatility multiplier;
- proposed target fraction;
- dominant strategy and exit profile;
- expert disagreement frequency.

### 11.4 Risk and execution dashboard

- current and approved target fraction;
- clipping, rejection, and halt counts;
- daily loss and drawdown;
- turnover;
- margin use and liquidation buffer for perpetuals;
- pending plans and orders;
- fill latency;
- realised fees, funding, and slippage;
- expected versus realised cost;
- reconciliation status.

## 12. Alerts and runbooks

Every alert definition contains:

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

Critical alerts include:

- wrong symbol or instrument;
- incompatible artifact set;
- broken reconciliation beyond threshold;
- daily-loss or drawdown limit;
- kill switch;
- duplicate execution attempt;
- unrecognised exchange position;
- secret or authentication failure;
- inability to cancel exposure-increasing orders.

## 13. Deployment environments

### 13.1 Historical replay

Uses the production decision code and historical adapters. It must reproduce stored outer-fold decisions from immutable artifacts.

### 13.2 Live feature shadow

Runs the live market adapter and feature service but no model decision is sent to execution. Feature parity with an independently rebuilt historical snapshot is measured.

### 13.3 Full decision shadow

Runs all three modules and persists decisions. Execution receives nothing.

### 13.4 Paper execution

Runs the production execution state machine against a paper environment or deterministic simulator.

### 13.5 Small-capital canary

Uses a dedicated capital allocation and strict limits. Canary capital, loss limits, order size, and maximum target change must be materially below the intended production values.

### 13.6 Restricted production

Uses the production account but retains conservative leverage, target-change, and turnover limits. Production V1 never exceeds absolute position fraction 1.0.

## 14. Promotion

Promotion is manual and atomic.

A challenger package contains:

- `InstrumentSelectionReport.v1`;
- `RegimeModelArtifact.v1`;
- `AllocatorConfigArtifact.v1`;
- risk and operations configurations;
- compatible feature, cost, and execution versions;
- historical, shadow, paper, and canary reports;
- signed approval record.

Promotion requires:

- all hard research gates;
- no unresolved critical incidents;
- historical/live feature parity;
- acceptable realised cost error;
- successful paper reconciliation;
- canary operation within loss and incident limits;
- tested rollback package;
- operator approval.

A performance score alone cannot promote a challenger.

## 15. Rollback

Rollback replaces the entire `CompatibleArtifactSet.v1` and its linked risk and operations configurations.

Partial rollback is prohibited. The selected instrument, model, scaler, affinity matrix, strategy configuration, cost model, and risk config remain a compatible unit.

Rollback sequence:

1. disable exposure increases;
2. reconcile current exchange state;
3. cancel invalid or stale open orders;
4. activate the previous signed compatible set;
5. verify hashes and target instrument;
6. run a dry decision without execution;
7. resume in `SAFE_READ_ONLY`;
8. require manual transition to `READY`.

If the previous compatible set is unavailable or invalid, remain halted.

## 16. Backup and recovery

Persist and back up:

- deployment and capital configurations;
- compatible artifact sets;
- model and allocator artifacts;
- decision store;
- execution plans and exchange acknowledgements;
- portfolio reconciliation snapshots;
- immutable audit records;
- incident records.

Recovery testing must demonstrate that a clean process can reconstruct current analytical state and reconcile current exchange state without generating a duplicate execution plan.

## 17. Operations readiness checklist

Production activation requires all of the following:

- no-withdrawal production API key;
- secret-manager integration;
- deterministic decision and idempotency keys;
- distributed decision lock;
- persisted decision and execution state machines;
- exchange reconciliation and unknown-position handling;
- tested kill switch;
- tested emergency reduce/flatten policy;
- concrete alerts and runbooks;
- dashboards for data, model, allocation, risk, and execution;
- tested backup and recovery;
- tested atomic rollback;
- completed paper and canary stages;
- named operational owner.
