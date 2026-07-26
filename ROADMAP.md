# Fachliche Roadmap

## 1. Zweck

Diese Roadmap definiert die fachliche Reihenfolge, in der Strategy Experts, Exit-Regeln, Regime-Modelle und spätere lernende Allokatoren entwickelt, getestet und promoted werden.

Das zentrale Identifikationsprinzip lautet:

```text
Eine Verbesserung darf nur der Komponente zugerechnet werden,
die sich zwischen Candidate und Baseline tatsächlich unterscheidet.
```

Insbesondere darf ein Regime-Modell nicht dadurch wirtschaftlich besser erscheinen, dass seine Strategy Experts gleichzeitig mit anderen Take-Profit-, Stop-Loss- oder Time-Stop-Regeln getestet werden.

## 2. Kernhypothesen

Das Projekt prüft mehrere getrennte Hypothesen:

1. **Standalone-Strategiehypothese:** Trend, Momentum und Mean Reversion erzeugen jeweils nach vollständigen Kosten einen eigenständigen wirtschaftlichen Mehrwert.
2. **Regime-Inkrementalhypothese:** Ein Regime-Wahrscheinlichkeitsvektor verbessert bei unveränderten Strategy Experts und unveränderten Exit-Regeln die Auswahl, Gewichtung oder Abstention gegenüber einer No-Regime-Baseline.
3. **Regime-Exit-Hypothese:** Regimeabhängige diskrete Exit-Profile verbessern zusätzlich die Performance gegenüber festen strategy-spezifischen Exit-Profilen.
4. **Microstructure-Hypothese:** L2-Daten verbessern Entry-Gating, Liquiditätsrisiko, Slippage oder Transition-Warnungen, ohne das persistente Kernregime unnötig zu destabilisieren.
5. **Learned-Allocator-Hypothese:** Ein regularisiertes supervised Modell, Contextual Bandit oder später RL verbessert den deterministischen Allocator robust und nach Kosten.

Jede Hypothese erhält eine eigene Baseline, eigene Experimente und eigene Promotion Gates.

## 3. Nicht verhandelbare Validierungsregeln

### 3.1 Nested Walk-forward

Jeder Outer Fold besteht aus:

```text
Outer Training Window
    ├── innere chronologische Train/Validation-Folds
    ├── Modell- und Parameterselektion
    ├── State Mapping
    ├── Exit-Profilselektion
    └── vollständiges Einfrieren aller Artefakte

Outer Test Window
    └── genau eine unveränderte Auswertung
```

Der Outer Test darf niemals verwendet werden für:

- Feature-Auswahl;
- Wahl der Modellfamilie;
- Anzahl der States;
- State Mapping;
- TP-/SL-/Time-Stop-Optimierung;
- Affinity Matrix;
- Risk-Parameter;
- Kostenmodellkalibrierung;
- Hyperparameter-Tuning;
- Promotion-Schwellen.

### 3.2 Point-in-time Daten

Es dürfen ausschließlich Daten verwendet werden, die zum jeweiligen `as_of` verfügbar waren. Für Regime-Inferenz sind nur gefilterte Wahrscheinlichkeiten zulässig:

```text
P(State_t | Daten bis einschließlich t)
```

Retrospektiv geglättete Zustände sind in Trading-Backtests und Runtime-Entscheidungen verboten.

### 3.3 Vollständige Kosten

Alle wirtschaftlichen Auswertungen berücksichtigen mindestens:

```text
Fees
Spread
Slippage
Funding
Turnover
adverse intrabar assumptions
```

Kosten werden in BASE-, ELEVATED- und SEVERE-Szenarien ausgewertet.

## 4. Phase 0 — Reproduzierbare Baseline

### Ziel

Eine unveränderliche Baseline schaffen, gegen die alle späteren Candidates vergleichbar sind.

### Deliverables

- feste BTC-Perpetual-Instrumentenspezifikation;
- feste Feature- und Output-Contracts;
- deterministische Strategy-Expert-Formeln;
- deterministische Risk Engine;
- reproduzierbares Kostenmodell;
- purged beziehungsweise embargoed Walk-forward-Splits;
- MLflow Tracking Server, Backend Store und Artifact Store;
- Golden Prediction Tests;
- ein initiales Registered Model mit Alias `champion`.

### Baselines

```text
Cash
BTC spot buy-and-hold benchmark
BTC perpetual long-only benchmark
Standalone Trend
Standalone Momentum
Standalone Mean Reversion
Static equal expert mix
No-Regime deterministic allocator
```

## 5. Phase 1 — Standalone Strategy Experts und Exit-Optimierung

### 5.1 Ziel

Jeder Strategy Expert muss unabhängig vom Regime-Modell zeigen, dass er nach Kosten wirtschaftlich vertretbar ist.

Ein Expert, der standalone keine robusten Ergebnisse liefert, wird deaktiviert und nicht durch Regimegewichtung „gerettet“.

### 5.2 Zu optimierende Parameter

Für Strategie `s` wird ein Exit-Parametervektor definiert:

```text
exit_parameters_s = (
    stop_atr_multiple,
    take_profit_atr_multiple,
    time_stop_hours
)
```

Optionale spätere Erweiterungen wie Trailing Stop oder Break-even-Regel benötigen eine neue Exit-Contract-Version.

### 5.3 Strategy-spezifische Suchräume

#### Trend

```text
stop_atr_multiple ∈ {1.5, 2.0, 2.5, 3.0}
take_profit_atr_multiple ∈ {2.5, 3.0, 4.0, 5.0}
time_stop_hours ∈ {24, 48, 72, 120}
```

#### Momentum

```text
stop_atr_multiple ∈ {1.0, 1.5, 2.0}
take_profit_atr_multiple ∈ {1.5, 2.0, 2.5, 3.0}
time_stop_hours ∈ {4, 8, 12, 24}
```

#### Mean Reversion

```text
stop_atr_multiple ∈ {0.5, 0.75, 1.0, 1.25}
take_profit_atr_multiple ∈ {0.5, 1.0, 1.5, 2.0}
time_stop_hours ∈ {1, 2, 4, 8}
```

Diese Raster sind Startkonfigurationen und müssen versioniert werden. Eine Erweiterung des Suchraums zählt als neues Experimentdesign.

### 5.4 Auswahlkriterium

Es wird nicht der maximale Bruttoreturn gewählt. Primäres Ziel ist ein robuster risikoadjustierter Nettonutzen.

Empfohlene Auswahlregel:

```text
maximiere median_outer_fold_net_calmar
```

unter Hard Gates für:

- Maximum Drawdown;
- CVaR;
- profitable Fold Fraction;
- minimale Trade-Anzahl;
- PnL-Konzentration;
- Cost Stress;
- Parameterstabilität.

### 5.5 Robustheitsplateau statt Punktoptimum

Die gewählte Exit-Konfiguration soll nicht nur das absolute Maximum besitzen. Bevorzugt wird eine einfache Konfiguration:

```text
Score >= 95% des besten inneren Scores
```

und mit stabiler Performance in benachbarten Parameterkombinationen.

Zu loggende Nachbarschaftsmetriken:

```text
neighbourhood_score_mean
neighbourhood_score_std
neighbourhood_worst_score
parameter_sensitivity_rank
```

### 5.6 Ergebnis

Pro Strategy Expert entsteht ein versioniertes, eingefrorenes Exit-Profil:

```text
TrendExitProfile.v1
MomentumExitProfile.v1
MeanReversionExitProfile.v1
```

Diese Profile werden in Phase 2 für Baseline und Regime-Candidate identisch verwendet.

## 6. Phase 2 — Reiner wirtschaftlicher Regime-Inkrementaltest

### 6.1 Ziel

Isolieren, ob die Regimewahrscheinlichkeiten zusätzlichen wirtschaftlichen Wert liefern.

### 6.2 Vergleich

```text
System B: No-Regime Baseline
- gleiche Strategy Experts
- gleiche eingefrorene Exit-Profile
- gleiche Risk Engine
- gleiche Kosten
- statische Strategy-Gewichte oder zeitinvariante Average Affinity

System C: Regime Candidate
- gleiche Strategy Experts
- gleiche eingefrorene Exit-Profile
- gleiche Risk Engine
- gleiche Kosten
- dynamische Gewichtung über Regimewahrscheinlichkeiten
```

Der Regime-Inkrementalwert ist:

```text
regime_incremental_value
=
Performance(System C)
-
Performance(System B)
```

### 6.3 Erforderliche Baselines

Mindestens:

- Ein-State-Modell;
- uniforme Wahrscheinlichkeiten;
- statische Average Affinity;
- zeitlich verschobene Probability Vectors;
- blockweise permutierte Probability Vectors;
- Markov-Placebo mit ähnlicher State-Dauer.

### 6.4 Statistische Gates

- bessere OOS Predictive Log-Likelihood als Ein-State-Baseline;
- mindestens 16 von 20 stabilen konvergierten Seeds;
- keine degenerierten Kovarianzen;
- minimale State Occupancy;
- plausible State Duration;
- State Alignment gültig;
- stabile State Signatures über Folds;
- gültige Probability Calibration und Entropy-Verteilung.

### 6.5 Wirtschaftliche Gates

Empfohlene Startwerte:

```text
candidate_median_outer_fold_net_calmar
>= champion_median_outer_fold_net_calmar + 0.10

paired_bootstrap_calmar_difference_ci_lower > 0

candidate_outer_fold_win_fraction >= 0.60

candidate_cvar_95_loss
<= champion_cvar_95_loss × 1.05

candidate_max_drawdown
<= champion_max_drawdown + 0.02

maximum_positive_pnl_fold_contribution <= 0.50
```

Zusätzlich müssen ELEVATED und SEVERE Cost Stress bestanden werden.

### 6.6 Ergebnis

Nur wenn System C System B robust übertrifft, wird das Regime-Modell als wirtschaftlich relevant angesehen.

## 7. Phase 3 — Mehrere Regime-Modellfamilien

### Ziel

Mehrere persistente Regime-Switching-Modelle unter einem gemeinsamen Contract vergleichen.

### Candidate-Ladder

```text
Champion baseline:
- diagonal Gaussian HMM

Challengers:
- full-covariance Gaussian HMM
- duration-aware HMM / HSMM
- Student-t HMM
- Markov-switching autoregression
```

Jeder Candidate muss exponieren:

```text
RegimePrediction.v1
```

mit identischer kanonischer State-Reihenfolge, identischen Feldnamen und identischen Probability-Invarianten.

### Promotionseinheit

Promoted wird nicht nur das Rohmodell, sondern ein kompatibles Bundle:

```text
Regime Model
Scaler
Feature Contract
State Signatures
State Mapping
Affinity Matrix
Strategy Config
Exit Profile Set
Risk Config
Cost Model
Code Commit
Dependency Lock
```

## 8. Phase 4 — Regimeabhängige diskrete Exit-Profile

### Ziel

Prüfen, ob das Regime zusätzlich zur Strategy-Gewichtung auch die Exit-Auswahl verbessern kann.

### Vergleich

```text
System C:
Regimegewichtung + feste strategy-spezifische Exit-Profile

System D:
Regimegewichtung + regimeabhängige diskrete Exit-Profile
```

Der zusätzliche Exit-Wert ist:

```text
regime_exit_incremental_value
=
Performance(System D)
-
Performance(System C)
```

### Zulässiger Aktionsraum

Keine freien kontinuierlichen TP-/SL-Werte. Stattdessen wird aus einer kleinen versionierten Profilbibliothek gewählt:

```text
MR_TIGHT
MR_NORMAL
MOMENTUM_NORMAL
TREND_DEFENSIVE
TREND_NORMAL
NO_TRADE
```

Jedes Profil besitzt feste ATR-Multiplikatoren und einen festen Time Stop.

### Begründung

Eine freie Optimierung pro `State × Strategy × Exit-Parameter` erzeugt zu viele Freiheitsgrade und erhöht das Overfitting-Risiko. Diskrete Profile reduzieren den Suchraum und verbessern Reproduzierbarkeit, Governance und Auditierbarkeit.

## 9. Phase 5 — L2 Microstructure Overlay

### Ziel

L2 zunächst nicht als Kernfeature des persistenten Regime-Modells verwenden, sondern als separates kurzfristiges Overlay.

### Output

```text
MicrostructureSignal.v1
- order_book_pressure
- liquidity_stress
- transition_risk
- expected_slippage_bps
- spread_stress
- depth_fragility
- data_quality_status
```

### Initiale Verwendung

L2 darf in der ersten produktionsnahen Stufe:

- Exposure reduzieren;
- Entry verzögern;
- Ausführungskosten erhöhen;
- `NO_NEW_ENTRY` auslösen;
- Liquiditätsstress signalisieren.

L2 darf anfangs nicht allein Exposure erhöhen.

### Evaluation

```text
A: lange Historie ohne L2
B: Common Window ohne L2
C: Common Window mit L2
```

Der isolierte L2-Wert ist zunächst `C - B`. Erst danach wird geprüft, ob `C` auch die langfristige Baseline `A` robust übertrifft.

## 10. Phase 6 — Learned Allocator

Reihenfolge:

```text
1. deterministischer Allocator
2. regularisiertes supervised Modell
3. Contextual Bandit
4. Reinforcement Learning
```

Ein späterer Agent darf zunächst nur wählen:

- Strategy Mix;
- Exposure Bucket;
- diskretes Exit-Profil;
- Cash beziehungsweise No Trade.

Die deterministische Risk Engine bleibt immer außerhalb des lernenden Modells und besitzt die letzte Entscheidung.

## 11. Experiment-Matrix

Die folgenden Systeme müssen separat ausgewiesen werden:

| System | Regime | Exit-Regeln | Zweck |
|---|---|---|---|
| A | nein | standalone optimiert | Strategy-Evidenz |
| B | nein | eingefroren | No-Regime-Baseline |
| C | ja | identisch zu B | reiner Regime-Inkrementalwert |
| D | ja | regimeabhängig diskret | zusätzlicher Exit-Wert |
| E | ja | wie D plus L2 Overlay | zusätzlicher Microstructure-Wert |
| F | ja | wie E plus learned allocator | zusätzlicher Policy-Wert |

Die zentralen Differenzen sind:

```text
C - B = Wert der Regimegewichtung
D - C = Wert regimeabhängiger Exits
E - D = Wert des L2 Overlays
F - E = Wert des learned allocators
```

## 12. MLflow-Verknüpfung

Jede Phase besitzt ein eigenes MLflow Experiment oder eine klar versionierte Run-Gruppe. Vollständige Logging-, Registry- und Promotion-Regeln stehen in [`MLFLOW.md`](MLFLOW.md).

Pflichtfelder in jedem relevanten Run:

```text
experiment_design_version
outer_fold_id
inner_fold_id
model_family
model_version
strategy_id
exit_profile_version
feature_contract_version
output_contract_version
state_schema_version
risk_config_version
cost_model_version
dataset_digest
code_commit
dependency_lock_hash
```

Outer-Test-Metriken dürfen niemals mit Inner-Validation-Metriken vermischt werden.

## 13. Promotion Lifecycle

```text
research run
→ reproducible candidate
→ statistical gates
→ economic gates
→ MLflow registered model version
→ challenger alias
→ historical replay
→ live feature shadow
→ full decision shadow
→ paper execution
→ small-capital canary
→ manual champion promotion
```

Ein Rollback setzt den Champion-Alias auf die vorherige immutable Modell- beziehungsweise Bundle-Version zurück.

## 14. Abnahmekriterien der Roadmap

Production V1 ist fachlich bereit, wenn:

- alle drei Strategy Experts standalone bewertet wurden;
- nur bestandene Experts aktiviert sind;
- ihre Exit-Profile nested walk-forward und ohne Outer-Test-Leakage gewählt wurden;
- No-Regime und Regime-System mit identischen Exits verglichen wurden;
- der Regime-Inkrementalwert statistisch und wirtschaftlich positiv ist;
- MLflow alle Runs, Artefakte, Metadaten, Lineage und Promotions reproduzierbar abbildet;
- Champion, Challenger und Rollback eindeutig referenzierbar sind;
- Shadow-, Paper- und Canary-Gates dokumentiert bestanden wurden.
