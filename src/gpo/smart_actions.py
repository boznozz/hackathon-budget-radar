"""Phrase measurable French SMART proposals for simulated budget impacts."""

from __future__ import annotations

import argparse


LABELS = {
    "fuel_subsidies": "Subventions énergie",
    "customs_revenue": "Recettes douanières",
    "food_subsidies": "Subventions alimentaires",
    "debt_service": "Service de la dette",
    "social_spending": "Dépenses sociales",
}


def phrase_smart_actions(budget_line: str, impact_pct: float,
                         impact_mtnd: float) -> list[dict[str, object]]:
    """Return two French review actions with explicit SMART fields."""
    if budget_line not in LABELS:
        raise ValueError(f"Unknown budget line: {budget_line}")
    label = LABELS[budget_line]
    amount = abs(float(impact_mtnd))
    direction = "hausse" if impact_mtnd >= 0 else "baisse"
    return [
        {
            "action": f"Vérifier l'exposition de {label} au scénario simulé",
            "specific": True,
            "measurable": f"Écart estimé de {amount:,.1f} MTND ({direction} de {abs(impact_pct):.1%})",
            "achievable": "Contrôle des hypothèses et des chiffres par l'équipe budgétaire",
            "relevant": f"Répond à l'impact simulé sur {label}",
            "time_bound": "Note de validation sous 14 jours",
        },
        {
            "action": f"Proposer un ajustement ou un suivi pour {label}",
            "specific": True,
            "measurable": f"Une option chiffrée couvrant jusqu'à {amount:,.1f} MTND",
            "achievable": "Option soumise à validation dans le cadre budgétaire existant",
            "relevant": f"Aligne la réponse GPO sur le risque de {label}",
            "time_bound": "Décision proposée sous 30 jours",
        },
    ]


def main() -> None:
    """Print standalone French action examples for a specified budget line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("budget_line", nargs="?", default="fuel_subsidies", choices=LABELS)
    parser.add_argument("--impact-pct", type=float, default=0.1)
    parser.add_argument("--impact-mtnd", type=float, default=800.0)
    arguments = parser.parse_args()
    for action in phrase_smart_actions(arguments.budget_line,
                                       arguments.impact_pct, arguments.impact_mtnd):
        print(f"[smart_actions] {action}")


if __name__ == "__main__":
    main()
