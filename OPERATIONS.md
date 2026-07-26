# Operations

This document defines the Production V1 runtime, security, monitoring, incident, promotion and rollback requirements for one fixed linear BTC-perpetual deployment.

## 1. Operating principles

```text
one deployment = BTC = one linear BTC perpetual
BTC spot = reference data only
one decision timestamp = one logical decision
one approval = at most one active execution plan
isolated margin only
one-way position mode only
absolute effective leverage <= 1×
unknown state = no exposure increase
reconciliation failure = no exposure increase
artifact mismatch = halt
manual promotion only
atomic rollback only
```

The analytical and execution systems must remain independently restartable. Restarting either system must not create a duplicate decision, duplicate execution plan or duplicate protective order set.

## 2. Process topology

A Production V1 deployment contains:

```text
BTC market-data adapter
point-in-time feature service
regime service
deterministic expert service
deterministic allocator
risk service
decision store
BTC-perpetual execution service
portfolio and margin reconciler
monitoring and alerting
```

These components may run in one process initially, but their contracts and persisted states must remain separate.

## 3. Startup sequence

Startup proceeds in this exact order:

1. load `DeploymentConfig.v1`;
2. verify `target_symbol = BTC`;
3. load current `CapitalAllocation.v1`;
4. load `CompatibleArtifactSet.v1` atomically;
5. verify the BTC linear-perpetual and BTC spot-reference specifications;
6. verify code, dependency, feature, methodology, risk and operations hashes;
7. connect market data in read-only mode;
8. connect the exchange in read-only mode;
9. verify the exchange instrument is the configured BTC linear perpetual;
10. verify isolated margin mode;
11. verify one-way position mode;
12. set or verify maximum production leverage of 1×;
13. verify reduce-only support;
14. reconcile cash, margin, position, open orders and protective orders;
15. verify mark price, index price, liquidation price and funding availability;
16. verify system clock;
17. validate `SmallAccountCapability.v1` for the current capital allocation;
18. acquire the deployment leadership lock;
19. enable analytical decisions;
20. enable exposure-changing execution only after every previous check passes.

Any failure before step 20 leaves the deployment in `SAFE_READ_ONLY` or `HALTED`, according to severity.

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

## 5. Exactly-once semantics

### 5.1 Deterministic decision ID

```text
decision_id = hash(
    deployment_id,
    BTC,
    trading_instrument_id,
    as_of,
    compatible_artifact_set_id
)
```

The same logical decision receives the same ID after restart or retry.

### 5.2 Decision lock

Before creating a decision, acquire a distributed lock on:

```text
deployment_id + as_of
```

Lock loss before decision persistence aborts the decision. Lock loss after approval blocks new execution until reconciliation.

### 5.3 Execution idempotency

```text
execution_idempotency_key = hash(
    approval_id,
    trading_instrument_id,
    approved_target_notional
)
```

The execution service rejects a second active plan with the same key. Exchange client-order IDs derive from the execution plan and child-order sequence.

### 5.4 Protective-order idempotency

The stop and take-profit set uses:

```text
protective_order_set_id = hash(
    execution_plan_id,
    reconciled_entry_fill_id,
    exit_profile_id
)
```

At most one active protective-order set may exist for the reconciled net position.

## 6. Hourly decision schedule

At every scheduled UTC hour:

1. wait until the final source M1 bucket is closed;
2. verify BTC spot and BTC perpetual source watermarks;
3. verify system clock;
4. build and persist `MarketFeatureFrame.v1`;
5. run Module 1;
6. run all enabled experts;
7. run Module 2;
8. read current reconciled position, margin and liquidation state;
9. run Module 3;
10. persist `DecisionAuditRecord.v1` without execution report;
11. send an unexpired approval to execution;
12. create at most one execution plan;
13. reconcile fills and position;
14. activate or replace reduce-only protective orders;
15. append execution and portfolio results to the audit chain.

A late decision does not shift the schedule. It expires and the next scheduled hour creates a new decision.

## 7. Service-level objectives and automatic actions

All thresholds are versioned in `OperationsConfig.v1` or `RiskLimits.v1`.

| Condition | Default trigger | Automatic action |
|---|---:|---|
| BTC market-data bucket delay | > 120 seconds | reject exposure increase for current decision |
| BTC market-data bucket delay | > 600 seconds | enter `DEGRADED`; reduce-only execution |
| Required BTC spot reference unavailable | any required snapshot | feature `FAIL`; no exposure increase |
| Feature computation duration | > 30 seconds | expire current decision |
| Decision age at execution | > 60 seconds | reject exposure increase |
| Source gap | any gap > 180 minutes | `HALTED` |
| Feature hash mismatch | any occurrence | `HALTED` |
| Artifact compatibility mismatch | any occurrence | startup failure or `HALTED` |
| Non-BTC symbol or wrong instrument | any occurrence | `HALTED` |
| Contract is not linear perpetual | any occurrence | `HALTED` |
| Margin mode not isolated | any occurrence | cancel exposure-increasing orders; `HALTED` |
| Position mode not one-way | any occurrence | cancel exposure-increasing orders; `HALTED` |
| Effective leverage configuration > 1× | any occurrence | startup failure or `HALTED` |
| Small-account capability | `FAIL` | startup failure for that capital allocation |
| Funding data stale | beyond configured maximum | no exposure increase |
| Absolute funding rate | above risk limit | reduce or reject target |
| Mark/index divergence | above warning threshold | no exposure increase |
| Mark/index divergence | above halt threshold | reduce-only; `HALTED` |
| Liquidation buffer | below warning threshold | reduce-only; clip target |
| Liquidation buffer | below hard limit | emergency reduction; `HALTED` |
| Portfolio reconciliation | `BROKEN` | cancel non-reduce-only orders; reduce-only mode |
| Reconciliation broken duration | > 300 seconds | `HALTED` |
| Pending execution-plan age | > 120 seconds | stop new plans; reconcile |
| Oldest exchange-order age | > configured TTL | cancel and reconcile |
| Regime entropy | above risk limit | abstain; no exposure increase |
| Maximum regime probability | below risk limit | abstain; no exposure increase |
| Daily loss | limit reached | cancel exposure-increasing orders; reduce or flatten; `HALTED` |
| Maximum drawdown | limit reached | reduce-only; `HALTED` |
| Kill switch | active | cancel open orders; emergency reduction or flatten; `HALTED` |
| Clock offset | > 500 milliseconds | exposure increase disabled |
| Realised slippage | > 2× expected for 3 plans | enter `DEGRADED`; reduce maximum target change |
| Realised cost-model error | above tolerance | block promotion; alert |

Emergency reduction and flatten policies are deterministic and instrument-specific. They are never inferred by a model.

## 8. Safe degradation

### 8.1 Preserve or reduce only

The following conditions allow only preservation or reduction of absolute exposure:

- feature failure;
- model inference failure;
- allocator abstention;
- risk rejection;
- high entropy;
- low maximum regime probability;
- stale capital allocation;
- stale cost or funding state;
- mark/index divergence;
- insufficient liquidation buffer;
- broken reconciliation;
- execution connectivity loss;
- decision expiry.

### 8.2 Flat target is not confirmed flat position

When the exchange is disconnected or the position is unresolved, the system may record a target of zero but must not claim the position is flat until reconciliation confirms it.

### 8.3 No hidden fallback market or model

Production V1 has:

```text
no fallback asset
no fallback spot execution
no fallback perpetual contract
no automatic fallback model
```

Failure leads to abstention and deterministic risk reduction.

## 9. BTC-perpetual execution requirements

### 9.1 Quantity conversion

Execution converts approved notional to contract quantity using the current validated reference price, contract multiplier and quantity step. Quantity is rounded toward zero.

### 9.2 Target delta

```text
delta_notional = approved_target_notional - reconciled_current_notional
```

Execution must not infer a target from signals directly.

### 9.3 Reduce-only usage

All protective exits and all degradation-driven reductions use reduce-only when supported. A reduce-only rejection is a reconciliation event, not a reason to send an unrestricted replacement blindly.

### 9.4 One-way position mode

The exchange account must hold one net BTC-perpetual position. Separate hedge-mode long and short positions are prohibited.

### 9.5 Isolated margin

Only the configured deployment margin allocation may support the position. Cross-margin dependence on unrelated account assets is prohibited.

### 9.6 Funding

The execution and portfolio services record:

- current funding rate;
- next funding timestamp;
- position held across each funding event;
- realised funding cashflow;
- cumulative funding by decision and position episode.

## 10. Security

### 10.1 Exchange API key

Production keys must:

- have trading permission only;
- have no withdrawal permission;
- be restricted to the required account or sub-account;
- use an IP allow-list when supported;
- have no permission for unrelated instruments when the exchange supports instrument restrictions;
- be rotated on a documented schedule and after suspected exposure.

### 10.2 Secret storage

Secrets must come from an approved secret manager. They must not be stored in source control, model artifacts, Docker images, plaintext configuration, notebooks or logs.

### 10.3 Environment separation

Use separate credentials and, where possible, separate accounts or sub-accounts for:

```text
paper
canary
production
```

Paper or canary processes must not possess production credentials.

### 10.4 Access control

Manual promotion, capital changes, risk-limit changes and kill-switch release require authenticated and auditable operator actions.

## 11. Structured logging and audit

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

Logs must not contain credentials or secret values.

`DecisionAuditRecord.v1` is immutable. Corrections are appended as new records referencing the original hash.

## 12. Monitoring dashboards

### 12.1 Data and feature dashboard

- BTC spot and perpetual watermarks;
- gaps and duplicates;
- funding and open-interest ages;
- core-feature validity;
- feature latency;
- historical/live parity;
- feature-hash mismatch count.

### 12.2 Regime dashboard

- three current probabilities;
- 4-hour forward probabilities;
- normalized entropy;
- maximum probability;
- state occupancy and duration;
- transition-matrix drift;
- state-signature distance;
- abstention rate.

### 12.3 Strategy and allocator dashboard

- expert directions, strengths and confidence;
- contribution weights;
- consensus direction;
- cash weight;
- regime certainty;
- volatility multiplier;
- preliminary target fraction;
- dominant expert and exit profile;
- disagreement frequency.

### 12.4 BTC-perpetual risk and execution dashboard

- current and approved position fraction;
- current and approved notional;
- isolated margin use;
- mark and index prices;
- mark/index divergence;
- liquidation price and buffer;
- funding rate and realised funding;
- clipping, rejection and halt counts;
- daily loss and drawdown;
- turnover;
- pending plans and orders;
- fill latency;
- realised fees and slippage;
- reconciliation status.

## 13. Alerts and runbooks

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

- wrong asset or instrument;
- non-linear or changed contract semantics;
- margin-mode or position-mode drift;
- leverage above 1×;
- artifact incompatibility;
- broken reconciliation beyond threshold;
- missing liquidation price while a position is open;
- liquidation-buffer breach;
- daily-loss or drawdown limit;
- kill switch;
- duplicate execution attempt;
- unrecognized BTC-perpetual position;
- inability to cancel exposure-increasing orders;
- authentication or secret failure.

## 14. Deployment environments

### 14.1 Historical replay

Uses production decision code with historical adapters and reproduces stored outer-fold decisions from immutable artifacts.

### 14.2 Live feature shadow

Runs live BTC spot and BTC-perpetual adapters and the feature service without execution.

### 14.3 Full decision shadow

Runs all three modules and persists decisions. Execution receives nothing.

### 14.4 Paper execution

Runs the production BTC-perpetual execution state machine against a paper environment or deterministic simulator.

### 14.5 Small-capital canary

Uses a dedicated allocation in the order of €1,000 equivalent, subject to `SmallAccountCapability.v1`, strict loss limits and materially reduced target-change limits.

### 14.6 Restricted production

Uses production credentials but retains conservative exposure, turnover and loss limits. Production V1 never exceeds absolute position fraction 1.0.

## 15. Promotion

Promotion is manual and atomic.

A challenger package contains:

- `BTCLinearPerpetualSpec.v1`;
- `BTCSpotReferenceSpec.v1`;
- `SmallAccountCapability.v1`;
- `RegimeModelArtifact.v1`;
- `AllocatorConfigArtifact.v1`;
- risk and operations configurations;
- compatible feature, cost and execution versions;
- historical, shadow, paper and canary reports;
- signed approval record.

Promotion requires:

- all hard research gates;
- no unresolved critical incidents;
- historical/live feature parity;
- acceptable realised cost and funding error;
- successful paper margin and reconciliation behaviour;
- canary operation within loss, sizing and incident limits;
- tested rollback package;
- operator approval.

A performance score alone cannot promote a challenger.

## 16. Rollback

Rollback replaces the complete `CompatibleArtifactSet.v1`.

Partial rollback is prohibited. The BTC-perpetual specification, BTC spot reference, model, scaler, affinity matrix, strategy configuration, cost model, risk configuration, operations configuration and execution adapter remain one compatible unit.

Rollback sequence:

1. disable exposure increases;
2. reconcile current BTC-perpetual position and margin;
3. cancel invalid or stale orders;
4. preserve valid reduce-only protective orders or replace them deterministically;
5. activate the previous signed compatible set;
6. verify hashes, instrument, margin mode and position mode;
7. run a dry decision without execution;
8. resume in `SAFE_READ_ONLY`;
9. require manual transition to `READY`.

If the previous set is unavailable or invalid, remain halted.

## 17. Backup and recovery

Persist and back up:

- deployment and capital configurations;
- compatible artifact sets;
- model and allocator artifacts;
- BTC-perpetual and reference-spot specifications;
- decision store;
- execution plans and exchange acknowledgements;
- margin and portfolio reconciliation snapshots;
- immutable audit records;
- incident records.

Recovery testing must show that a clean process can reconstruct analytical state and reconcile the live BTC-perpetual position without creating a duplicate plan.

## 18. Operations readiness checklist

Production activation requires:

- no-withdrawal production API key;
- secret-manager integration;
- verified linear BTC-perpetual contract;
- isolated margin and one-way mode enforcement;
- verified 1× leverage cap;
- passing small-account capability;
- deterministic decision and idempotency keys;
- distributed decision lock;
- persisted decision and execution state machines;
- position, margin and protective-order reconciliation;
- mark, index, liquidation and funding monitoring;
- tested kill switch and emergency reduction;
- concrete alerts and runbooks;
- dashboards for data, model, allocation, risk and execution;
- tested backup and recovery;
- tested atomic rollback;
- completed paper and canary stages;
- named operational owner.
