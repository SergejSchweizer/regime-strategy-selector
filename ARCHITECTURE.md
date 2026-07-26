# Architecture

## 1. Purpose

`regime-strategy-selector` is a production-oriented, probabilistic trading system for exactly one configured crypto asset per deployment:

```text
target_symbol ∈ {BTC, ETH, SOL}
```

A deployment, training run, model artifact, backtest, and live process must be bound to one immutable `target_symbol`. The system must not combine BTC, ETH, and SOL in one model instance, one allocator, or one portfolio decision.

Examples of valid deployments:

```text
BTC deployment → BTC data → BTC models → BTC positions
ETH deployment → ETH data → ETH models → ETH positions
SOL deployment → SOL data → SOL models → SOL positions
```

The same codebase and contract versions may be reused, but each asset receives independently trained and independently promoted model artifacts.

The source-of-truth market dataset for version 1 is:

```text
gold.market.history_full.m1
```

Only rows where `symbol == target_symbol` are eligible for a run.

---

## 2. System boundary

The analytical system contains three strictly separated modules:

1. **Regime Estimator** — estimates probabilities for three latent regimes of the configured asset.
2. **Strategy Allocator** — combines those probabilities with independent trend, momentum, and mean-reversion experts and proposes risk budgets, signed target exposures, and exit profiles.
3. **Deterministic Risk Engine** — validates, clips, nets, rejects, or halts the proposal before order intents are emitted.

```text
gold.market.history_full.m1
            │ filter symbol == target_symbol
            ▼
 point-in-time feature builder
            │
            ├──────────────► TrainingTargetFrame.v1
            │                 training/evaluation only
            ▼
    MarketFeatureFrame.v1
            │
            ├──────────────► Trend Expert
            ├──────────────► Momentum Expert
            └──────────────► Mean-Reversion Expert
            │                 StrategyExpertSignal.v1[]
            ▼
┌────────────────────────────────────┐
│ Module 1: Regime Estimator         │
│ current and forward probabilities  │
└─────────────────┬──────────────────┘
                  │ RegimePrediction.v1
                  ▼
┌────────────────────────────────────┐
│ Module 2: Strategy Allocator       │
│ risk budgets, exposures, exits     │
└─────────────────┬──────────────────┘
                  │ AllocationProposal.v1
                  ▼
┌────────────────────────────────────┐
│ Module 3: Deterministic Risk Engine│
│ gates, limits, clipping, halt      │
└─────────────────┬──────────────────┘
                  │ RiskDecision.v1
                  ▼
         Approved order intents
                  │
                  ▼
       External execution subsystem
```

The execution subsystem is outside the three analytical modules. It owns order placement, acknowledgements, fills, cancellations, retries, exchange reconciliation, and exchange-specific state.

All interface definitions are documented in [`CONTRACTS.md`](CONTRACTS.md).

---

## 3. Core design decisions

### 3.1 Single-asset isolation

Every process receives one `target_symbol` and rejects rows, positions, orders, artifacts, or model outputs associated with another symbol.

Required invariants:

```text
one training run = one target_symbol
one regime model = one target_symbol
one allocator model = one target_symbol
one risk decision = one target_symbol
one execution process = one target_symbol
```

This isolation avoids hidden cross-asset dependence, simplifies model attribution, and ensures that a BTC model cannot silently influence ETH or SOL positions.

Separate deployments may run concurrently, but they must communicate only through an external account-level risk service if capital is shared. Account-wide capital allocation is not part of this repository's three-module architecture.

### 3.2 Fixed decision clock

Raw data remains M1. Every research run and production model declares one decision interval. The recommended initial production candidate is hourly:

```yaml
decision_interval: 1h
feature_source_grain: 1m
decision_timestamp_rule: closed_bucket_only
```

All inputs must be computed from fully closed source buckets. Changing the decision interval requires a new training, evaluation, and artifact version.

### 3.3 Probability context, not hard routing

The Regime Estimator provides three probabilities rather than one mandatory hard label.

The Strategy Allocator may assign risk to several strategy experts simultaneously. Cash is always a valid action. The most likely regime is diagnostic; the complete probability vector is the decision input.

### 3.4 Independent strategy experts

Trend, momentum, and mean-reversion experts do not consume regime probabilities. Each expert must be testable as a standalone strategy on the configured asset.

This separation allows a direct comparison:

```text
same expert signals without regime context
versus
same expert signals with regime-aware allocation
```

### 3.5 Risk budgets are not signed positions

Allocator outputs distinguish:

- **risk budget** — non-negative share of deployable risk assigned to a strategy sleeve;
- **signed target exposure** — positive for long and negative for short;
- **cash budget** — non-negative unallocated risk/capital;
- **global risk multiplier** — bounded scaling applied before deterministic risk checks.

Risk budgets plus cash may sum to one. Signed exposures do not need to sum to one.

### 3.6 Three virtual strategy sleeves

For one configured asset the portfolio contains:

```text
trend sleeve
momentum sleeve
mean-reversion sleeve
cash
```

The sleeves remain separate for PnL attribution, turnover attribution, risk budgeting, stop management, and model evaluation. They may produce opposing signed exposures. Module 3 nets them into one symbol-level target before the execution subsystem creates orders.

Example:

```text
trend sleeve:          +0.50
momentum sleeve:       +0.20
mean-reversion sleeve: -0.30
--------------------------------
net target exposure:   +0.40
```

---

## 4. Data and feature architecture

### 4.1 Upstream data

The initial system uses only:

```text
gold.market.history_full.m1
```

Eligible source families:

- spot OHLCV;
- perpetual OHLCV;
- funding state and freshness;
- open-interest state and freshness;
- perpetual trade-flow aggregates;
- option trade-flow aggregates.

Missing source values remain null. Trade executions, volumes, and counts must never be forward-filled. Last-known state variables may only be consumed with their availability and age metadata.

### 4.2 Point-in-time feature builder

The feature builder filters to `target_symbol` and produces `MarketFeatureFrame.v1` at the configured decision interval.

Candidate feature families:

| Family | Candidate variables |
|---|---|
| Returns | log returns over 5m, 15m, 1h, 4h, 1d |
| Trend | EMA distance and slope, breakout distance, directional persistence, rolling regression slope and fit |
| Momentum | raw returns, volatility-scaled returns, acceleration, volume-confirmed momentum |
| Mean reversion | price z-score, VWAP distance, Bollinger distance, spot-perpetual spread z-score, half-life proxy |
| Volatility | realized volatility derived from returns, range estimators, downside volatility, volatility-of-volatility, jump proxy |
| Carry | funding level, change, z-score, direction, freshness |
| Leverage | open-interest change, price/open-interest interaction, freshness |
| Trade flow | buy-volume share, signed volume, trade-count imbalance, average trade-size proxy |
| Basis | perpetual/spot spread, spread change, spread z-score |
| Activity and capacity | turnover, volume z-score, trade-count z-score, Amihud-like proxy |
| Data quality | missingness, source age, stale-state counts, contiguous-history length |

Cross-asset variables are excluded from version 1 because the system must operate from the configured asset alone.

### 4.3 Feature registry

Optuna may select only registered features. Every registry entry specifies:

- source columns;
- lookback;
- timestamp and availability rules;
- missing-value policy;
- candidate scalers;
- production reproducibility;
- computation version.

A feature is ineligible if it uses future data, has ambiguous timestamp semantics, is not live reproducible, silently imputes event data, lacks a versioned implementation, or lacks sufficient lookback.

### 4.4 Training targets

Forward targets are derived locally from the configured asset's historical prices and cost model. They are never inference inputs.

Initial horizons:

```text
1h
4h
1d
```

Targets include forward return, forward drawdown, forward realized volatility, and cost-adjusted return. A target is null unless its complete future horizon exists.

---

## 5. Module 1 — Regime Estimator

### 5.1 Responsibility

Convert a compact point-in-time feature subset for one asset into probabilities for three latent regimes.

It does not:

- select a strategy;
- set position size;
- set TP or SL;
- access another asset;
- approve an order.

### 5.2 Candidate models

Initial candidate ladder:

```text
Gaussian HMM with diagonal covariance
Gaussian HMM with full covariance
robust or heavy-tailed HMM
Hidden Semi-Markov Model
Markov-switching autoregressive model
Gaussian Mixture Model baseline
change-point detector baseline
```

The number of regimes is fixed at three in version 1.

### 5.3 Output semantics

The model emits:

- current regime probabilities;
- forward probabilities for configured horizons;
- transition risk;
- probability entropy;
- confidence;
- abstention recommendation;
- aligned state-signature identifiers.

Only filtered probabilities are valid:

```text
P(state at t | observations available through t)
```

Retrospectively smoothed states are prohibited in backtests, allocator training, and production inference.

### 5.4 State alignment

Raw state numbers have no permanent economic meaning. Each state receives a training-only signature based on:

- mean return;
- realized and downside volatility;
- trend strength;
- drawdown state;
- funding state;
- open-interest change;
- flow imbalance;
- episode duration;
- occupancy.

States are aligned across folds and retraining dates by minimum-distance matching of normalized signatures. Downstream code must reference signature IDs, not raw state numbers.

### 5.5 Evaluation

Hard rejection gates include:

- non-convergence;
- degenerate covariance or transition parameters;
- invalid probabilities;
- insufficient regime occupancy;
- median episode duration below the useful holding horizon;
- excessive switching;
- future-data leakage;
- non-reproducible features;
- unstable state alignment;
- excessive feature count.

Evaluation dimensions:

| Dimension | Metric | Direction |
|---|---|---|
| Predictive density | out-of-sample observation log likelihood per row | maximise |
| Probability sharpness | entropy subject to stability | controlled |
| Occupancy | distance from configured occupancy band | minimise |
| Persistence | episode duration and switch rate | within bounds |
| State separation | pairwise distribution distance | maximise |
| Signature stability | aligned signature similarity across folds | maximise |
| Transition stability | variation of aligned transition matrices | minimise |
| Economic separation | differences in future return, drawdown, volatility, and fixed-expert performance | maximise |
| Benchmark uplift | frozen regime mapping versus frozen non-regime mapping | maximise |
| Parsimony | feature count and model complexity | minimise |
| Retraining stability | feature and parameter drift across adjacent windows | minimise |

There is no external ground-truth regime label. Accuracy against model-generated states is diagnostic only.

### 5.6 Feature and model selection

Optuna searches model family, feature families, compact subset, lookbacks, transformations, scaler, covariance structure, regularisation, transition constraints, and initialisation.

Initial feature constraint:

```text
minimum selected features: 3
maximum selected features: 8
```

Search is hierarchical:

```text
remove invalid features
cluster redundant features on training data
select feature families
select a limited number of representatives
fit and evaluate
```

Selection procedure:

1. Reject invalid trials.
2. Build a Pareto front.
3. Retain top `K` materially different regime candidates.
4. Apply a frozen ranking score.
5. Prefer simpler candidates under the one-standard-error rule.
6. Generate out-of-fold probabilities for every shortlisted candidate.
7. Defer final promotion until allocator compatibility is evaluated.

---

## 6. Strategy experts

Each expert consumes the same asset-specific `MarketFeatureFrame.v1` and cost snapshot.

### 6.1 Trend expert

Primary information:

- perpetual and spot price;
- high/low range;
- volume;
- EMA distance and slope;
- rolling regression slope and fit;
- breakout distance;
- directional persistence;
- realized volatility derived from returns.

### 6.2 Momentum expert

Primary information:

- return over configured horizons;
- volatility-scaled return;
- return acceleration;
- volume confirmation;
- perpetual buy-volume share;
- activity and cost state.

### 6.3 Mean-reversion expert

Primary information:

- price z-score;
- VWAP distance;
- Bollinger distance;
- spot-perpetual spread z-score;
- half-life proxy;
- short-horizon reversal;
- cost and capacity state.

Each expert emits one `StrategyExpertSignal.v1` for the configured asset.

---

## 7. Module 2 — Strategy Allocator

### 7.1 Responsibility

Convert regime probabilities, independent expert signals, portfolio state, and cost state into a proposed single-asset allocation.

It does not approve orders or override risk limits.

### 7.2 Candidate ladder

```text
cash-only baseline
equal-risk expert mix
best static expert mix
hard regime-to-expert mapping
probability-weighted mapping
regularised supervised allocator
contextual bandit
constrained reinforcement-learning policy
```

The recommended first production candidate is a regularised supervised allocator or contextual bandit. Reinforcement learning remains a challenger until it demonstrates robust sequential value beyond simpler models.

### 7.3 Constrained action space

The allocator proposes:

```text
risk budget: trend
risk budget: momentum
risk budget: mean reversion
cash budget
signed target exposure per strategy sleeve
global risk multiplier
exit profile per sleeve
```

Invariants:

```text
all risk budgets are non-negative
risk budgets plus cash sum to one
global risk multiplier is bounded
signed exposures follow expert direction and assigned risk budget
```

Exit profiles are deterministic templates expressed in trailing ATR or realized-volatility units. The allocator selects a profile ID; Module 3 resolves absolute levels.

Unrestricted continuous TP/SL optimisation is excluded from the initial production candidate.

### 7.4 Evaluation

Candidates must use identical out-of-fold regime probabilities, expert signals, portfolio simulation, and cost scenarios.

Hard rejection gates include:

- action invariant violation;
- look-ahead leakage;
- omitted fees, spread, slippage, or funding;
- excessive turnover or switching;
- drawdown-limit breach;
- numerical instability;
- performance concentrated in one fold;
- severe-cost-stress failure;
- failure to beat required simple baselines;
- action during required abstention;
- training/inference state mismatch.

Evaluation dimensions:

| Dimension | Metric | Direction |
|---|---|---|
| Net performance | return after all modeled costs | maximise |
| Risk-adjusted performance | Sharpe, Sortino, Calmar | maximise |
| Drawdown | maximum and average drawdown | minimise |
| Tail risk | CVaR and worst-period loss | minimise |
| Stability | median and dispersion across folds | maximise/minimise |
| Consistency | profitable-fold fraction | maximise |
| Regret | loss versus best ex-post expert | minimise |
| Turnover | notional turnover | minimise |
| Switching | sleeve-weight change frequency | minimise |
| Baseline uplift | improvement over static and non-regime baselines | maximise |
| Capacity | performance under notional scaling | maximise |
| Complexity | parameters, training variance, inference cost | minimise |
| Abstention quality | loss avoided versus opportunity forgone | optimise |

### 7.5 Pair-level selection

The Regime Estimator and Strategy Allocator are selected as a compatible pair:

1. Keep top `K` regime candidates.
2. Generate separate out-of-fold probabilities.
3. Train the full allocator ladder against each regime candidate.
4. Reject invalid pairs.
5. Build a pair-level Pareto front.
6. Prefer the simplest pair within one standard error of the best pair.
7. Evaluate the frozen pair once on the untouched outer test interval.
8. Aggregate across outer folds before declaring a champion.

A complex pair is not eligible unless it beats the required simpler baselines after costs.

---

## 8. Module 3 — Deterministic Risk Engine

### 8.1 Responsibility

Convert an advisory allocation proposal into an approved, clipped, netted, rejected, or halted set of order intents for the configured asset.

It is not optimised by Optuna and is not statistically selected.

### 8.2 Controls

The engine enforces:

- target-symbol equality across all inputs;
- gross and net exposure limits;
- leverage and estimated margin limits;
- sleeve and symbol position limits;
- daily, rolling, and maximum-drawdown limits;
- volatility scaling;
- historical capacity and turnover limits;
- stale-data and missing-data rejection;
- confidence and entropy gates;
- maximum order size and frequency;
- funding and total-cost limits;
- exchange and instrument constraints;
- pending-order and reconciliation constraints;
- circuit breakers and kill switches.

When Module 1 or Module 2 recommends abstention, Module 3 may only preserve or reduce exposure.

### 8.3 Verification

Required verification:

- unit tests for every boundary;
- property tests for contract invariants;
- crash, gap, stale-data, missing-data, and outage scenarios;
- historical stress replays;
- integration tests against all allocator actions;
- sleeve netting and attribution tests;
- pending-order and reconciliation tests;
- idempotency tests;
- fail-closed tests;
- configuration audit tests;
- wrong-symbol rejection tests.

Success means declared rules remain enforced even when both learned models are wrong.

---

## 9. End-to-end training and validation

For each asset-specific outer evaluation date:

```text
1. Select target_symbol.
2. Filter source data to target_symbol.
3. Select the previous three years as outer training data.
4. Build point-in-time features using training data only.
5. Create time-ordered inner folds.
6. Purge overlapping target intervals.
7. Apply embargo at least as long as the maximum target horizon.
8. Optimise Module 1 only on inner folds.
9. Retain top K materially different regime candidates.
10. Generate out-of-fold filtered probabilities for each candidate.
11. Generate expert signals, portfolio paths, costs, and targets point in time.
12. Train Module 2 candidates against every retained regime candidate.
13. Select a compatible pair using inner data only.
14. Refit the selected pair on the full outer training window.
15. Freeze features, artifacts, costs, action space, and risk configuration.
16. Evaluate once on the untouched outer test interval.
17. Advance the outer window and repeat.
```

No outer-test result may be used to retune the same research run.

### 9.1 Statistical safeguards

Required safeguards:

- block-bootstrap confidence intervals;
- performance distributions across outer folds;
- one-standard-error selection;
- explicit attempted-trial count;
- multiple-testing-aware reporting;
- deflated risk-adjusted-performance diagnostics;
- parameter and feature-selection stability;
- sensitivity to cost and hyperparameter perturbations;
- exclusion of results dominated by one market episode.

---

## 10. Production deployment

### 10.1 Asset-specific artifacts

Every artifact records:

```text
target_symbol
training window
decision interval
source data hash
feature-set hash
code commit
dependency lock hash
selection configuration
validation metrics
```

An artifact trained for one symbol must fail validation when loaded by a deployment configured for another symbol.

### 10.2 Champion and challenger

Each asset has an independent champion pair and independent challengers.

Promotion requires:

- schema, hash, lineage, and target-symbol checks;
- all hard validation gates;
- improvement under the frozen pair-level objective;
- no material deterioration in drawdown, CVaR, turnover, or abstention behavior;
- acceptable elevated and severe cost stress;
- consistency between backtest and shadow behavior;
- immutable reproducibility;
- tested rollback.

A challenger is never promoted from one favorable outer fold.

### 10.3 Deployment stages

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

Each stage has asset-specific minimum observation counts, incident criteria, and rollback rules.

### 10.4 Monitoring

Data monitoring:

- source freshness;
- missingness;
- timestamp gaps and duplicates;
- observation ages;
- feature drift;
- unexpected symbol values;
- feature-set hash mismatch.

Regime monitoring:

- probability distribution;
- entropy;
- occupancy;
- episode duration;
- switch rate;
- signature drift;
- transition drift;
- abstention frequency.

Allocator monitoring:

- risk-budget distribution;
- signed exposure distribution;
- cash allocation;
- turnover and switching;
- confidence;
- expert disagreement;
- expected versus realized costs and utility.

Risk and execution monitoring:

- clipping and rejection rate;
- triggered rules;
- exposure and margin;
- pending-order age;
- fills and cancellations;
- reconciliation breaks;
- realized slippage;
- kill-switch state.

### 10.5 Safe degradation

The system must define deterministic behavior for missing rows, stale funding or open interest, inference failure, hash mismatch, unavailable artifacts, high entropy, expert disagreement, reconciliation failure, exchange disconnection, and symbol mismatch.

Default safe behavior is reduced exposure or cash.

---

## 11. Recommended repository structure

```text
regime-strategy-selector/
├── README.md
├── ARCHITECTURE.md
├── CONTRACTS.md
├── configs/
│   ├── datasets/
│   ├── features/
│   ├── models/
│   ├── selection/
│   ├── strategies/
│   ├── costs/
│   └── risk/
├── contracts/
├── src/regime_strategy_selector/
│   ├── data/
│   ├── features/
│   ├── regimes/
│   ├── strategies/
│   ├── allocation/
│   ├── portfolio/
│   ├── costs/
│   ├── risk/
│   ├── backtesting/
│   ├── optimization/
│   ├── evaluation/
│   ├── artifacts/
│   └── monitoring/
├── tests/
├── notebooks/
└── scripts/
```

---

## 12. Implementation roadmap

### Phase 1 — Deterministic foundation

- Implement source validation and asset filtering.
- Implement `MarketFeatureFrame.v1` and the feature registry.
- Implement `TrainingTargetFrame.v1`.
- Fix the hourly decision clock.
- Implement cost scenarios and an asset-specific portfolio simulator.
- Implement cash-only, equal-risk, static-mix, and standalone-expert baselines.
- Implement virtual sleeves, netting, and attribution.

### Phase 2 — Regime Estimator

- Implement Gaussian HMM baselines.
- Add robust and duration-aware challengers.
- Add hierarchical Optuna feature selection.
- Add purged walk-forward and embargo.
- Generate filtered out-of-fold probabilities.
- Implement signatures and alignment.
- Produce the top-K shortlist.

### Phase 3 — Allocator

- Implement independently testable experts.
- Implement hard and probability-weighted mappings.
- Implement a regularised supervised allocator.
- Evaluate a contextual bandit.
- Add constrained RL only as a challenger.
- Select compatible model pairs.

### Phase 4 — Risk and execution contracts

- Implement limits and data-quality gates.
- Implement abstention and safe degradation.
- Implement order-intent, reconciliation, and portfolio-state contracts.
- Add wrong-symbol rejection, stress replay, and fail-closed tests.

### Phase 5 — Production operations

- Build immutable asset-specific artifacts.
- Add monitoring and audit trails.
- Run shadow and paper stages.
- Run a small-capital canary.
- Establish incident response and rollback.

---

## 13. Production-readiness criteria

The system is not production-ready until:

- point-in-time features are deterministic and live reproducible;
- the configured asset is enforced across every contract and artifact;
- all three experts have defensible standalone behavior after costs;
- Module 1 produces stable, live-safe probabilities from a compact subset;
- a compatible pair beats required simpler baselines across outer folds;
- uplift survives cost stress;
- no single fold or episode dominates;
- feature and parameter selection are reasonably stable;
- abstention avoids losses without eliminating most opportunity;
- sleeve attribution reconciles with the net exchange position;
- Module 3 passes boundary, stress, replay, idempotency, wrong-symbol, and fail-closed tests;
- historical replay and live shadow decisions are consistent;
- paper execution confirms cost and order-state assumptions;
- canary deployment remains within predefined limits;
- every decision is reproducible and auditable;
- rollback is operationally tested.
