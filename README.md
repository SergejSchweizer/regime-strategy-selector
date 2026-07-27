# Regime Strategy Selector

A production-oriented research and decision system for one fixed market:

```text
target_symbol = BTC
traded_instrument_type = LINEAR_PERPETUAL
margin_mode = ISOLATED
position_mode = ONE_WAY
maximum_effective_leverage = 1x
```

Production V1 trades one configured exchange-specific linear BTC perpetual. BTC spot is reference data and a benchmark only; the system never emits spot orders. ETH, SOL, options, inverse or quanto contracts, dated futures, cross margin, hedge mode and leverage above 1x are outside Production V1.

## System flow

```text
gold.market.history_full.m1
        |
        v
point-in-time BTC feature service
        |
        v
persistent three-state regime estimator
        | RegimePrediction.v1
        v
deterministic trend, momentum and mean-reversion experts
        |
        v
deterministic probability-weighted allocator
        | AllocationProposal.v1
        v
deterministic risk engine
        | ApprovedTargetPosition.v1
        v
external BTC-perpetual execution system
```

Only the regime estimator is learned in Production V1. Strategy experts, allocation, risk enforcement and emergency actions are deterministic and versioned.

## Shared MLflow dependency

The project consumes the shared NAS-hosted MLflow platform maintained in:

```text
SergejSchweizer/mlflow
```

The shared platform owns:

```text
MLflow Tracking Server
MLflow backend PostgreSQL
RustFS artifact store
Caddy ingress
MLflow authentication
platform backups, restores and upgrades
project onboarding and capability qualification
```

This repository owns:

```text
MLflow client configuration
experiment taxonomy and run roles
dataset lineage and artifact semantics
project metrics and promotion evidence
custom model and deployment-bundle packaging
research, promotion and runtime identity requirements
```

This repository does not deploy its own MLflow PostgreSQL database or artifact store. Runtime decisions, current probabilities, positions, orders, drawdown, reconciliation and execution state remain outside MLflow.

### Canonical MLflow identity

```text
project_id = regime-strategy-selector
experiment_prefix = regime-strategy-selector/
registered_model_prefix = regime-strategy-selector--
```

Registered models:

```text
regime-strategy-selector--regime-estimator
regime-strategy-selector--deployment-bundle
```

Protected aliases:

```text
@challenger
@shadow
@champion
@rollback
```

Research workers may log runs and artifacts but cannot move protected aliases. A dedicated promotion identity performs authorised registration and alias movement. Runtime resolves immutable model versions or the approved deployment-bundle alias with read-only access.

## Documentation

The repository deliberately keeps only three detailed documentation files:

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — system design, component boundaries, persistent-state semantics, public contracts and compatibility rules.
- [`METHODOLOGY.md`](METHODOLOGY.md) — exact formulas, backtest conventions, statistical and economic validation, exit optimisation and research work packages.
- [`OPERATIONS.md`](OPERATIONS.md) — runtime state machines, security, monitoring, shared MLflow usage, Model Registry governance, promotion, rollback and implementation workflow.

Upstream dataset definitions are maintained in [`crypto-history-loader/DATASETS.md`](https://github.com/SergejSchweizer/crypto-history-loader/blob/main/DATASETS.md).

## Production V1 defaults

| Concern | Rule |
|---|---|
| Asset | BTC only |
| Traded instrument | one linear BTC perpetual |
| Reference market | BTC spot, information only |
| Decision interval | 1 hour |
| Primary evaluation horizon | 4 hours |
| Stress horizon | 1 day |
| Regime model | diagonal Gaussian HMM, 3 persistent states |
| Regime features | fixed five-feature vector |
| Strategy experts | trend, momentum, mean reversion |
| Allocator | deterministic probability-weighted mapping |
| Position | one signed net position |
| Margin mode | isolated |
| Position mode | one-way |
| Maximum exposure | absolute notional no greater than allocated equity |
| Promotion | manual and atomic |

The selected perpetual must support sufficiently fine sizing. At the configured reference capital, minimum order notional and one quantity-step notional must each be no greater than 1% of allocated equity. For EUR 1,000 equivalent capital, each must therefore be no greater than EUR 10 equivalent in settlement currency.

## Model ladder

```text
Production V1
- diagonal Gaussian HMM
- deterministic allocator
- fixed strategy-specific exit profiles

Challengers
- full-covariance Gaussian HMM
- duration-aware HMM or HSMM
- Student-t HMM
- Markov-switching autoregression
- discrete regime-dependent exit profiles

Later research
- regularised supervised allocator
- contextual bandit
- reinforcement learning
```

Every promotable regime model exposes the same `RegimePrediction.v1` contract with the same persistent-state order and probability invariants.

## Economic identification rule

A performance improvement is attributed only to the component that differs between candidate and baseline.

```text
standalone strategy evidence
-> strategy-specific exit profiles selected in inner walk-forward folds
-> exit profiles frozen
-> no-regime baseline and regime candidate use identical exits
-> incremental value of regime probabilities measured
-> regime-dependent exits evaluated separately
-> learned allocators evaluated separately
```

## MLflow run granularity

MLflow records bounded research and deployment episodes, not every hourly runtime decision.

```text
training parent run = one candidate family x dataset snapshot x outer fold
child run = one seed, inner fold, parameter combination or cost scenario
shadow run = one bounded evaluation window
paper run = one deployment bundle and paper episode
canary run = one deployment bundle and canary observation window
```

Individual hourly decisions belong in the runtime audit store and reference the exact immutable MLflow model version and source run.

## Backlog generation contract

The documentation is written so that a future backlog can be generated without inventing missing scope. A backlog item references one stable work package from `METHODOLOGY.md` or `OPERATIONS.md` and contains:

```text
work_package_id
objective
parent_dependency
input_contracts
output_contracts
files_or_modules_owned
implementation_steps
deterministic_test_fixtures
acceptance_tests
required_mlflow_evidence
non_goals
completion_gate
```

A backlog item is invalid when any field is unknown.

## Implementation dependency graph

```text
S00 Foundations
 |
 +--> S10 Data and point-in-time features
 |      |
 |      +--> S20 Shared MLflow integration
 |      |
 |      +--> S30 Persistent regime estimator
 |      |
 |      +--> S40 Strategy experts and exit research
 |              |
 |              +--> S50 Allocator and regime evidence
 |                      |
 |                      +--> S60 Deterministic risk engine
 |                              |
 |                              +--> S70 Integrated replay and audit
 |                                      |
 |                                      +--> S80 Shadow, paper, canary and promotion
 |
 +--> S90 Alternative regime models
 |
 +--> S100 Regime-dependent exits
 |
 +--> S110 Learned allocators
```

`S90`, `S100` and `S110` start only after the Production V1 evidence stack passes its required gates.

## Atomic stacked pull requests

Future implementation uses small dependency-ordered PRs.

### Identity

```text
work package: S30-P03
branch: agent/s30-p03-multi-seed-stability
PR title: [S30-P03] Implement multi-seed HMM stability
```

### Stack rules

1. one PR implements one work package and one primary behaviour;
2. a PR starts from the exact accepted parent commit declared in its metadata;
3. a dependent PR targets its parent branch until the parent merges, then rebases onto new `main`;
4. every PR is squash-merged into one deterministic mainline commit;
5. contract changes precede implementations that consume them;
6. infrastructure, domain behaviour, model research and cleanup are not mixed;
7. refactoring is allowed only when required by the work package;
8. randomness uses fixed recorded seeds;
9. research PRs log required MLflow evidence before completion;
10. a child cannot merge while its parent or compatibility checks remain unresolved.

### Required PR metadata

```yaml
work_package_id: S30-P03
depends_on:
  - S30-P02
base_commit: immutable parent SHA
contracts_added: []
contracts_changed: []
mlflow_experiment: regime-strategy-selector/20-regime-model-selection
deterministic_seeds: [recorded values]
acceptance_commands: [exact commands]
artifacts_expected: [exact paths or MLflow artifacts]
non_goals: [explicit exclusions]
```

## Deployment lifecycle

```text
offline research
-> historical replay
-> live feature shadow
-> full decision shadow
-> paper execution
-> small-capital canary
-> restricted production
```

Promotion and rollback operate on one compatible deployment bundle containing the instrument specification, model, scaler, state mapping, affinity matrix, strategy configuration, exit profiles, risk configuration, cost model, timing policy, code commit and dependency lock.
