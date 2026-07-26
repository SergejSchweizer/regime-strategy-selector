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

## Documentation

The repository deliberately keeps only three detailed documentation files:

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — system design, component boundaries, persistent-state semantics, public contracts and compatibility rules.
- [`METHODOLOGY.md`](METHODOLOGY.md) — exact formulas, backtest conventions, standalone strategy validation, exit optimisation, regime evidence and the research sequence.
- [`OPERATIONS.md`](OPERATIONS.md) — runtime state machines, security, monitoring, MLflow experiment tracking, Model Registry, promotion and rollback.

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
- L2 microstructure overlay
- regularised supervised allocator
- contextual bandit
- reinforcement learning
```

Every promotable regime model must expose the same `RegimePrediction.v1` contract with the same persistent state order and probability invariants.

## Economic identification rule

A performance improvement is attributed only to the component that differs between candidate and baseline.

```text
standalone strategy evidence
-> strategy-specific exit profiles selected in inner walk-forward folds
-> exit profiles frozen
-> no-regime baseline and regime candidate use identical exits
-> only then measure the incremental value of regime probabilities
```

Regime-dependent exits, L2 overlays and learned allocators are evaluated later as separate incremental experiments.

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