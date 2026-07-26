# Regime Strategy Selector

A probabilistic, regime-aware trading architecture for BTC and ETH that separates market-state estimation, strategy allocation, and hard risk control.

The system is designed as a **three-module mixture-of-experts pipeline**:

1. **Regime Estimator** — estimates the probabilities of three market regimes.
2. **Strategy Allocator** — combines regime probabilities with trend, momentum, and mean-reversion signals to determine strategy weights and trade parameters.
3. **Deterministic Risk Engine** — validates and constrains all model decisions before orders can be produced.

The objective is not to assign one fixed strategy to one hard regime label. Instead, the system uses probabilistic regime information to allocate capital continuously across several independent strategy experts.

---

## Architecture

```text
Historical and live market features
                │
                ▼
┌─────────────────────────────────────┐
│ Module 1: Regime Estimator          │
│                                     │
│ - Three latent market regimes       │
│ - Current regime probabilities      │
│ - Forward regime probabilities      │
│ - Transition risk and confidence    │
└──────────────────┬──────────────────┘
                   │
                   ▼
        Regime probability vector
                   │
       ┌───────────┼───────────┐
       ▼           ▼           ▼
 Trend Expert  Momentum Expert  Mean-Reversion Expert
       │           │           │
       └───────────┼───────────┘
                   ▼
┌─────────────────────────────────────┐
│ Module 2: Strategy Allocator        │
│                                     │
│ - Strategy weights                  │
│ - Cash / neutral weight             │
│ - Position sizes                    │
│ - TP / SL profiles                  │
│ - Expected holding periods          │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│ Module 3: Deterministic Risk Engine │
│                                     │
│ - Exposure and leverage limits      │
│ - Drawdown and loss limits          │
│ - Liquidity and data-quality gates  │
│ - Correlation and concentration     │
│ - Kill switches                     │
└──────────────────┬──────────────────┘
                   │
                   ▼
             Approved orders
```

---

## Design Principles

- **Probabilities instead of hard labels.** The allocator receives all three regime probabilities rather than a single regime ID.
- **Independent strategy experts.** Trend, momentum, and mean-reversion logic remain separate and testable.
- **Out-of-fold regime signals.** The allocator is trained only on regime probabilities that could have been produced historically in real time.
- **Strict walk-forward validation.** Feature selection, scaling, model selection, and hyperparameter optimisation occur only inside training windows.
- **Deterministic risk overrides.** A learned policy may propose an action, but it cannot bypass hard portfolio constraints.
- **Simple baselines first.** Reinforcement learning must outperform static mappings, probabilistic weighting, and contextual-bandit baselines after costs.
- **Production parity.** Historical and live inference must use the same feature definitions, timestamps, transformations, and model contracts.

---

# Module 1 — Regime Estimator

The Regime Estimator analyses a rolling historical window, initially the most recent three years, and produces probabilistic estimates for three market regimes.

The economic interpretation of the regimes is not fixed in advance. Candidate models must discover states that are statistically stable and useful for strategy allocation. A resulting state set may, for example, resemble:

- directional / trending market;
- range-bound / mean-reverting market;
- stressed / high-volatility market.

State numbers such as `0`, `1`, and `2` have no permanent meaning. States must be aligned between retraining windows through economic signatures such as return, realised volatility, trend strength, drawdown, funding, and open-interest changes.

## Inputs

The estimator consumes a small, optimised subset selected from a larger historical feature universe. Candidate feature families include:

- returns and price dynamics;
- trend strength and persistence;
- realised volatility and volatility-of-volatility;
- drawdown and tail-risk proxies;
- funding and basis;
- open interest and leverage changes;
- trade-flow imbalance;
- liquidity proxies;
- BTC/ETH cross-asset relationships.

The feature universe may contain more than 100 variables, but the final regime model should normally use only a compact subset. Feature selection must be hierarchical and constrained rather than a blind binary search across every possible subset.

## Candidate models

Initial candidates may include:

- Gaussian Hidden Markov Model;
- robust or heavy-tailed HMM;
- Hidden Semi-Markov Model;
- Markov-switching autoregressive model;
- Gaussian Mixture Model as a non-temporal baseline;
- change-point models as complementary detectors.

The number of regimes is fixed at three for the initial implementation.

## Outputs

```text
current_regime_probabilities
forward_regime_probabilities
transition_risk
regime_confidence
model_confidence
data_quality_status
```

Example:

```json
{
  "current": {
    "regime_1": 0.62,
    "regime_2": 0.27,
    "regime_3": 0.11
  },
  "forward_4h": {
    "regime_1": 0.48,
    "regime_2": 0.31,
    "regime_3": 0.21
  },
  "transition_risk": 0.34
}
```

## Model and feature selection

Optuna is used inside nested, time-ordered walk-forward validation to select:

- model family;
- compact feature subset;
- lookback horizons;
- feature transformations;
- covariance structure;
- regularisation;
- transition parameters;
- model initialisation and convergence settings.

The objective must not be based only on in-sample likelihood. Candidate configurations are evaluated using several dimensions:

- out-of-sample predictive log score;
- regime occupancy and persistence;
- transition stability;
- state separation;
- economic interpretability;
- stability across walk-forward folds;
- incremental usefulness for downstream strategy allocation;
- model complexity and feature count.

Degenerate trials are pruned when states are empty, unstable, excessively short-lived, numerically singular, or economically indistinguishable.

## Live-safe inference

Backtests and live inference must use **filtered probabilities**:

```text
P(S_t | X_1, ..., X_t)
```

Smoothed probabilities that use observations after time `t` are prohibited for trading evaluation:

```text
P(S_t | X_1, ..., X_T), where T > t
```

---

# Module 2 — Strategy Allocator

The Strategy Allocator acts as the gating and allocation layer of the mixture-of-experts system.

It does not receive only a hard regime label. It consumes the complete regime probability vector together with independent signals from three strategy experts:

1. **Trend strategy**
2. **Momentum strategy**
3. **Mean-reversion strategy**

A cash or neutral allocation is always available and is treated as a valid portfolio decision.

## Strategy expert outputs

Each strategy expert should expose a common contract:

```text
signal_direction
signal_strength
signal_confidence
expected_return
expected_risk
expected_holding_period
estimated_transaction_cost
current_position_state
```

The allocator may therefore combine strategies even when one regime currently has the highest probability. Trend and momentum can be active simultaneously, while mean reversion may remain useful on a shorter horizon.

## Allocator state

A practical state vector may include:

```text
current regime probabilities
forward regime probabilities
transition probability
trend signal and confidence
momentum signal and confidence
mean-reversion signal and confidence
realised volatility
liquidity state
funding and open-interest state
current strategy weights
current positions
unrealised PnL
current drawdown
time in position
recent strategy performance
estimated fees, funding, spread, and slippage
```

Three regime probabilities alone are not sufficient because they do not describe existing positions, path dependency, transaction costs, signal strength, or portfolio risk.

## Outputs

```text
trend_weight
momentum_weight
mean_reversion_weight
cash_weight
total_risk_multiplier
position_size_by_strategy
stop_loss_profile_by_strategy
take_profit_profile_by_strategy
expected_holding_period
policy_confidence
```

Example:

```json
{
  "weights": {
    "trend": 0.45,
    "momentum": 0.25,
    "mean_reversion": 0.05,
    "cash": 0.25
  },
  "total_risk_multiplier": 0.60,
  "risk_profile": "balanced",
  "policy_confidence": 0.71
}
```

## Initial action space

The first production candidate should use a constrained action space:

- strategy weights for trend, momentum, mean reversion, and cash;
- one global risk multiplier;
- TP/SL selection from a small set of predefined ATR-based profiles.

Example profiles:

| Profile | Stop loss | Take profit |
|---|---:|---:|
| Conservative | 1.0 × ATR | 1.5 × ATR |
| Balanced | 1.5 × ATR | 2.5 × ATR |
| Trend | 2.0 × ATR | 4.0 × ATR |
| Wide | 3.0 × ATR | 6.0 × ATR |

Continuous optimisation of every position, TP, and SL parameter should be considered only after the constrained architecture has demonstrated stable out-of-sample performance.

## Candidate allocator methods

The following methods should be evaluated in increasing order of complexity:

1. hard rule-based regime-to-strategy mapping;
2. probability-weighted strategy mapping;
3. Bayesian-optimised static allocator;
4. contextual bandit;
5. reinforcement-learning policy.

Reinforcement learning is justified only when sequential effects materially improve decisions, including open positions, switching costs, holding periods, stops, drawdowns, and capital constraints.

## RL reward

A candidate reward function should use net economic utility rather than raw PnL:

```text
Reward =
    net PnL
    - transaction costs
    - funding costs
    - slippage
    - drawdown penalty
    - tail-risk penalty
    - turnover penalty
    - strategy-switching penalty
```

The learned policy must be compared against all simpler baselines under identical costs and walk-forward periods.

---

# Module 3 — Deterministic Risk Engine

The Risk Engine is not a learned trading model. It is an independent, deterministic safety layer that validates every proposed allocation and order.

The final order is always constrained by hard limits:

```text
approved_action = risk_engine(policy_proposal, portfolio_state, market_state)
```

The policy proposal is advisory; the Risk Engine is authoritative.

## Responsibilities

- maximum gross and net exposure;
- maximum leverage;
- maximum position per asset and strategy;
- portfolio concentration limits;
- strategy-correlation limits;
- daily and rolling loss limits;
- maximum drawdown limits;
- volatility and liquidity scaling;
- minimum market-data quality;
- stale-data rejection;
- maximum order size and turnover;
- exchange and instrument constraints;
- circuit breakers and kill switches.

## Outputs

```text
approved_strategy_weights
approved_position_sizes
approved_stop_levels
approved_take_profit_levels
rejected_actions
risk_override_reason
risk_status
```

A proposed exposure of 80% may therefore become an approved exposure of 40%, or be rejected entirely if data quality, liquidity, drawdown, or operational constraints are violated.

---

# Training and Evaluation

## Rolling training window

The initial design retrains on the most recent three years of historical data. Retraining frequency and window type must be evaluated empirically:

- expanding window;
- fixed three-year rolling window;
- hybrid window with recency weighting.

## Nested walk-forward process

For every outer evaluation date:

```text
1. Select the previous three years as the outer training set.
2. Create time-ordered inner train/validation folds.
3. Optimise the Regime Estimator only inside the outer training set.
4. Generate historical out-of-fold regime probabilities.
5. Run all strategy experts on the same point-in-time data.
6. Train and validate the Strategy Allocator on out-of-fold signals.
7. Freeze both learned models.
8. Evaluate the complete pipeline once on the untouched outer test period.
9. Advance the window and repeat.
```

## Critical anti-leakage rule

The allocator must never be trained on regime states produced by a Regime Estimator fitted on the same future observations.

Incorrect:

```text
Fit regime model on all three years
→ infer retrospective states on all three years
→ train allocator on those states
```

Correct:

```text
Fit regime model on past data only
→ predict the next historical period
→ repeat through time
→ concatenate out-of-fold probabilities
→ train allocator on historically available probabilities
```

All preprocessing steps must follow the same rule, including:

- missing-value handling;
- scaling;
- correlation clustering;
- feature selection;
- PCA or other dimensionality reduction;
- model calibration;
- state alignment.

## Evaluation layers

### Regime-model quality

- out-of-sample log score;
- state occupancy;
- mean and median regime duration;
- transition entropy;
- transition-matrix stability;
- economic state separation;
- state-signature stability;
- model convergence rate.

### Strategy-allocation quality

- net return after all costs;
- Sharpe and Sortino ratios;
- maximum drawdown;
- CVaR;
- Calmar ratio;
- turnover;
- switching frequency;
- probability of loss;
- performance stability across folds;
- regret relative to the best ex-post expert;
- uplift over non-regime baselines.

### Production quality

- feature freshness;
- live/historical feature parity;
- inference latency;
- missing-data behaviour;
- model and feature drift;
- probability calibration;
- risk override frequency;
- execution quality;
- shadow-versus-backtest divergence.

---

# Model Outputs

The production system produces at least two learned model artefacts and one deterministic configuration artefact.

## 1. Regime model artefact

```text
selected feature subset
preprocessing pipeline
regime model parameters
state signatures
state alignment metadata
current probability estimator
forward probability estimator
calibration metadata
```

## 2. Strategy-allocation model artefact

```text
policy or allocator parameters
strategy expert contracts
strategy weight logic
position-sizing logic
TP/SL profile selection
policy confidence estimator
```

## 3. Risk configuration artefact

```text
exposure limits
leverage limits
loss and drawdown limits
liquidity constraints
data-quality constraints
kill-switch rules
```

---

# Suggested Repository Structure

```text
regime-strategy-selector/
├── configs/
│   ├── features/
│   ├── models/
│   ├── strategies/
│   └── risk/
├── src/regime_strategy_selector/
│   ├── data/
│   │   ├── adapters/
│   │   ├── validation/
│   │   └── feature_store/
│   ├── features/
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
│   │   ├── rules/
│   │   ├── bandits/
│   │   └── reinforcement_learning/
│   ├── risk/
│   ├── backtesting/
│   ├── optimization/
│   ├── evaluation/
│   └── monitoring/
├── tests/
├── notebooks/
├── scripts/
└── README.md
```

---

# Development Roadmap

## Phase 1 — Historical feature and backtest foundation

- Define point-in-time feature contracts.
- Build the historical model dataset.
- Add transaction fees, funding, spread, and slippage assumptions.
- Implement trend, momentum, mean-reversion, and cash baselines.
- Establish time-ordered walk-forward evaluation.

## Phase 2 — Regime Estimator

- Implement HMM and baseline regime models.
- Add Optuna model and hierarchical feature selection.
- Generate filtered and out-of-fold regime probabilities.
- Implement state signatures and alignment.
- Compare statistical and economic regime quality.

## Phase 3 — Strategy Allocator

- Implement fixed and probability-weighted mappings.
- Add Bayesian-optimised allocator baseline.
- Evaluate contextual-bandit methods.
- Add a constrained RL policy only after baseline validation.

## Phase 4 — Risk and production controls

- Implement deterministic portfolio limits.
- Add data-quality gates and kill switches.
- Add model, feature, and probability monitoring.
- Run the complete system in shadow mode.

## Phase 5 — Incremental data enrichment

- Add L2 liquidity features when sufficient history exists.
- Add IV/RV and options-surface features.
- Measure incremental value against the unchanged historical-core baseline.
- Promote new feature blocks only after robust outer walk-forward improvement.

---

# Success Criteria

The architecture is successful only when the complete system demonstrates that it:

- outperforms simple non-regime baselines after all costs;
- remains stable across multiple outer walk-forward periods;
- uses live-reproducible features;
- avoids excessive strategy switching and turnover;
- improves drawdown or tail-risk behaviour, not only gross return;
- produces calibrated and interpretable regime probabilities;
- survives shadow-live validation without material degradation;
- remains safe when the learned models are uncertain or wrong.

---

## Status

This repository currently defines the target architecture and research methodology. Implementation should proceed incrementally, with every learned component required to outperform a simpler baseline under identical point-in-time data, costs, and walk-forward evaluation.