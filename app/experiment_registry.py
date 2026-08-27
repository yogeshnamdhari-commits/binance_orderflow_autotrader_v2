"""Experiment registry — track all experiments to prevent overfitting.

Creates and maintains research/experiment_registry.csv with every experiment's
hypothesis, configuration, and results. Prevents parameter fishing by making
all tests visible and irreversible.

Usage:
    python -m app.experiment_registry list
    python -m app.experiment_registry add --id EXP-001 --hypothesis "..." --result ...
"""

import csv
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict

REGISTRY_PATH = Path("research/experiment_registry.csv")

COLUMNS = [
    "experiment_id",
    "timestamp",
    "hypothesis",
    "features",
    "label_horizon_ms",
    "model",
    "training_period",
    "validation_period",
    "test_period",
    "cost_model_bps",
    "n_features",
    "gross_expectancy_bps",
    "net_expectancy_bps",
    "ci_low",
    "ci_high",
    "pct_above_gate",
    "verdict",
    "notes",
]


def init_registry():
    """Create registry file if it doesn't exist."""
    if not REGISTRY_PATH.exists():
        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(REGISTRY_PATH, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()


def list_experiments() -> List[Dict]:
    """List all experiments in registry."""
    init_registry()
    experiments = []
    with open(REGISTRY_PATH, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            experiments.append(row)
    return experiments


def add_experiment(
    experiment_id: str,
    hypothesis: str,
    features: str,
    label_horizon_ms: int,
    model: str,
    training_period: str,
    validation_period: str,
    test_period: str,
    cost_model_bps: float,
    n_features: int,
    gross_expectancy_bps: float,
    net_expectancy_bps: float,
    ci_low: float,
    ci_high: float,
    pct_above_gate: float,
    verdict: str,
    notes: str = "",
):
    """Add a new experiment to registry."""
    init_registry()
    
    row = {
        "experiment_id": experiment_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hypothesis": hypothesis,
        "features": features,
        "label_horizon_ms": label_horizon_ms,
        "model": model,
        "training_period": training_period,
        "validation_period": validation_period,
        "test_period": test_period,
        "cost_model_bps": cost_model_bps,
        "n_features": n_features,
        "gross_expectancy_bps": round(gross_expectancy_bps, 6),
        "net_expectancy_bps": round(net_expectancy_bps, 6),
        "ci_low": round(ci_low, 6),
        "ci_high": round(ci_high, 6),
        "pct_above_gate": round(pct_above_gate, 4),
        "verdict": verdict,
        "notes": notes,
    }
    
    with open(REGISTRY_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writerow(row)
    
    return row


def print_registry():
    """Print formatted registry."""
    experiments = list_experiments()
    
    if not experiments:
        print("No experiments recorded yet.")
        return
    
    print("=" * 100)
    print("EXPERIMENT REGISTRY")
    print("=" * 100)
    print(f"Total experiments: {len(experiments)}")
    
    # Summary
    rejected = sum(1 for e in experiments if e.get("verdict") == "HYPOTHESIS_REJECTED")
    positive = sum(1 for e in experiments if e.get("verdict") == "POSITIVE_EDGE")
    inconclusive = len(experiments) - rejected - positive
    
    print(f"  POSITIVE_EDGE: {positive}")
    print(f"  HYPOTHESIS_REJECTED: {rejected}")
    print(f"  OTHER: {inconclusive}")
    print()
    
    # Table
    print(f"{'ID':12s} {'Verdict':20s} {'Gross bps':>12s} {'Net bps':>12s} {'%Gate':>8s} {'Horizon':>8s} {'Model':>15s} {'Hypothesis':>30s}")
    print("-" * 120)
    
    for e in experiments:
        try:
            gross = float(e.get('gross_expectancy_bps', 0))
            net = float(e.get('net_expectancy_bps', 0))
            pct = float(e.get('pct_above_gate', 0))
            horizon = int(e.get('label_horizon_ms', 0))
        except (ValueError, TypeError):
            gross = 0
            net = 0
            pct = 0
            horizon = 0
        print(f"{e['experiment_id']:12s} {e.get('verdict', 'N/A'):20s} "
              f"{gross:>+12.4f} "
              f"{net:>+12.4f} "
              f"{pct:7.2f}% "
              f"{horizon:>7d}ms "
              f"{e.get('model', 'N/A'):>15s} "
              f"{e.get('hypothesis', 'N/A')[:30]:>30s}")
    
    print("=" * 100)


def seed_registry():
    """Seed registry with known experiments from prior research."""
    experiments = list_experiments()
    if experiments:
        return  # Already seeded
    
    # V5 baseline
    add_experiment(
        experiment_id="EXP-001",
        hypothesis="OFI/MLOFI ridge on 500ms horizon",
        features="V5_17_features",
        label_horizon_ms=500,
        model="Ridge",
        training_period="20260818-1907_1908",
        validation_period="20260818-1937_1943",
        test_period="20260818-1946_1952",
        cost_model_bps=2.0,
        n_features=17,
        gross_expectancy_bps=0.069,
        net_expectancy_bps=-1.931,
        ci_low=-1.94,
        ci_high=-1.92,
        pct_above_gate=0.0,
        verdict="HYPOTHESIS_REJECTED",
        notes="Gross positive but consumed by maker fee. 0% above gate.",
    )
    
    # V6
    add_experiment(
        experiment_id="EXP-002",
        hypothesis="Nonlinear MLP with OFI interactions",
        features="V5_17_plus_8_interactions",
        label_horizon_ms=500,
        model="MLP_32_16",
        training_period="20260818-1907_1908",
        validation_period="20260818-1937_1943",
        test_period="20260818-1946_1952",
        cost_model_bps=2.0,
        n_features=25,
        gross_expectancy_bps=0.100,
        net_expectancy_bps=-1.900,
        ci_low=-1.91,
        ci_high=-1.89,
        pct_above_gate=0.0,
        verdict="HYPOTHESIS_REJECTED",
        notes="MLP did not improve over ridge. Same cost constraint.",
    )
    
    # V7 full
    add_experiment(
        experiment_id="EXP-003",
        hypothesis="Multi-level OFI + queue dynamics + microprice + toxicity",
        features="V7_46_features",
        label_horizon_ms=500,
        model="Ridge",
        training_period="20260818-1907_1920",
        validation_period="20260818-1937_1943",
        test_period="20260818-1946_1952",
        cost_model_bps=2.0,
        n_features=46,
        gross_expectancy_bps=0.045,
        net_expectancy_bps=-1.955,
        ci_low=-1.959,
        ci_high=-1.951,
        pct_above_gate=0.0,
        verdict="HYPOTHESIS_REJECTED",
        notes="Best gross so far (+0.045) but 44x below maker fee. Purged split: -0.003.",
    )
    
    # V5 baseline with purged validation
    add_experiment(
        experiment_id="EXP-004",
        hypothesis="V7 features with purged chronological split",
        features="V7_46_features_purged",
        label_horizon_ms=500,
        model="Ridge_purged",
        training_period="20260818-1907_1920",
        validation_period="20260818-1937_1943_embargo",
        test_period="20260818-1946_1952",
        cost_model_bps=2.0,
        n_features=46,
        gross_expectancy_bps=-0.003,
        net_expectancy_bps=-2.003,
        ci_low=-2.01,
        ci_high=-1.99,
        pct_above_gate=0.0,
        verdict="HYPOTHESIS_REJECTED",
        notes="With proper purging/embargo, the small positive signal disappears.",
    )


def main():
    ap = argparse.ArgumentParser(description="Experiment registry")
    sub = ap.add_subparsers(dest="command")
    
    sub.add_parser("list", help="List all experiments")
    sub.add_parser("seed", help="Seed with known experiments")
    
    add_parser = sub.add_parser("add", help="Add experiment")
    add_parser.add_argument("--id", required=True)
    add_parser.add_argument("--hypothesis", required=True)
    add_parser.add_argument("--features", required=True)
    add_parser.add_argument("--horizon", type=int, required=True)
    add_parser.add_argument("--model", required=True)
    add_parser.add_argument("--gross", type=float, required=True)
    add_parser.add_argument("--net", type=float, required=True)
    add_parser.add_argument("--verdict", required=True)
    add_parser.add_argument("--notes", default="")
    
    a = ap.parse_args()
    
    if a.command == "list":
        print_registry()
    elif a.command == "seed":
        seed_registry()
        print_registry()
    elif a.command == "add":
        add_experiment(
            experiment_id=a.id,
            hypothesis=a.hypothesis,
            features=a.features,
            label_horizon_ms=a.horizon,
            model=a.model,
            training_period="",
            validation_period="",
            test_period="",
            cost_model_bps=2.0,
            n_features=0,
            gross_expectancy_bps=a.gross,
            net_expectancy_bps=a.net,
            ci_low=0,
            ci_high=0,
            pct_above_gate=0,
            verdict=a.verdict,
            notes=a.notes,
        )
        print(f"Added experiment {a.id}")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
