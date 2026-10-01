"""Apply fixed GPO risk thresholds and draft French objectives for five lines."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

if __package__ in (None, ""):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.gpo.smart_actions import LABELS, phrase_smart_actions


OBJECTIVES: dict[str, dict[str, object]] = {
    line: {
        "objective": f"Piloter le poste « {label} » et contenir son écart budgétaire",
        "key_results": [
            "Valider l'écart simulé et ses hypothèses sous 14 jours",
            "Soumettre une option chiffrée de réponse sous 30 jours",
        ],
        "kpis": ["Écart projeté (MTND)", "Écart projeté (%)", "Statut GPO"],
    }
    for line, label in LABELS.items()
}


def evaluate(budget_line: str, impact_pct: float) -> dict[str, str]:
    """Classify absolute relative impact: <2% green, <10% yellow, else red."""
    if budget_line not in OBJECTIVES:
        raise ValueError(f"Unknown budget line: {budget_line}")
    if not math.isfinite(float(impact_pct)):
        raise ValueError("impact_pct must be finite")
    magnitude = abs(float(impact_pct))
    if magnitude < 0.02:
        status, reason = "GREEN", "Écart inférieur à 2 %; suivi courant."
    elif magnitude < 0.10:
        status, reason = "YELLOW", "Écart de 2 % à moins de 10 %; examen requis."
    else:
        status, reason = "RED", "Écart d'au moins 10 %; action budgétaire prioritaire."
    return {"status": status, "reason": reason}


def generate_smart_actions(budget_line: str, impact_pct: float,
                           impact_mtnd: float) -> list[dict[str, object]]:
    """Return the French SMART action proposals for a budget-line impact."""
    return phrase_smart_actions(budget_line, impact_pct, impact_mtnd)


def main() -> None:
    """Print one standalone objective, status, and set of SMART actions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("budget_line", nargs="?", default="fuel_subsidies", choices=OBJECTIVES)
    parser.add_argument("--impact-pct", type=float, default=0.1)
    parser.add_argument("--impact-mtnd", type=float, default=800.0)
    arguments = parser.parse_args()
    print(f"[okr_engine] {OBJECTIVES[arguments.budget_line]}")
    print(f"[okr_engine] {evaluate(arguments.budget_line, arguments.impact_pct)}")
    for action in generate_smart_actions(arguments.budget_line, arguments.impact_pct,
                                         arguments.impact_mtnd):
        print(f"[okr_engine] {action}")


if __name__ == "__main__":
    main()
