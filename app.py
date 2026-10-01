"""Three-page Streamlit cockpit for forecasts, scenarios, and French GPO actions."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.gpo.okr_engine import OBJECTIVES, evaluate, generate_smart_actions
from src.models.news_impact import (adjust_forecasts, credentials_available, load_forecasts,
                                    load_news_snapshot, run_news_impact)
from src.models.scenario import ELASTICITIES, simulate
from src.utils.config import BASELINE_VALUES, DUCKDB_PATH, INDICATOR_CODES, PROC_DIR


PRESETS: dict[str, dict[str, float]] = {
    "Hormuz closure": {"BRENT": 0.30, "USDTND": 0.10},
    "EUR/TND spike": {"EURTND": 0.20},
    "Wheat crisis": {"WHEAT": 0.35},
    "Red Sea disruption": {"BRENT": 0.10, "WHEAT": 0.10},
}
PRESET_LABELS = {
    "Hormuz closure": "Fermeture du détroit d'Ormuz",
    "EUR/TND spike": "Hausse de l'euro face au dinar",
    "Wheat crisis": "Crise du blé",
    "Red Sea disruption": "Perturbation en mer Rouge",
}
PAGE_WARNING = "Alertes et prévisions"
PAGE_SCENARIO = "Simulation budgétaire"
PAGE_GPO = "Pilotage par objectifs"
KNOWN_EVENT_TITLES = {
    "Houthi Attacks on Saudi Arabia and Regional Escalation":
        "Escalade régionale entre les Houthis et l'Arabie saoudite",
}
KNOWN_EVENT_SUMMARIES = {
    "Houthi Attacks on Saudi Arabia and Regional Escalation": (
        "Les articles retenus décrivent une escalade régionale impliquant les Houthis "
        "et l'Arabie saoudite. Le scénario retient un risque de hausse du pétrole Brent."
    ),
}
STATUS_LABELS = {"GREEN": "Stable", "YELLOW": "À surveiller", "RED": "Critique"}
STATUS_COLORS = {"GREEN": "#46C8C0", "YELLOW": "#E9A55E", "RED": "#E0717B"}
CHART_COLORS = {
    "observed": "#9BAFC3",
    "forecast": "#46C8C0",
    "scenario": "#E9A55E",
    "grid": "#2B4055",
    "text": "#E1EBF3",
}
MONTH_LABELS = ("janv.", "févr.", "mars", "avr.", "mai", "juin",
                "juil.", "août", "sept.", "oct.", "nov.", "déc.")
BUDGET_LABELS = {
    "fuel_subsidies": "Subventions aux carburants",
    "customs_revenue": "Recettes douanières",
    "food_subsidies": "Subventions alimentaires",
    "debt_service": "Service de la dette",
    "social_spending": "Dépenses sociales",
}
INDICATOR_LABELS = {
    "BRENT": "du prix du pétrole Brent",
    "USDTND": "du taux USD/TND",
    "EURTND": "du taux EUR/TND",
    "WHEAT": "du prix du blé",
    "CPI": "de l'indice des prix à la consommation",
}
CATEGORY_CONTEXT = {
    "fuel_subsidies": (
        "Soutien aux carburants : sensible au pétrole et au dollar."
    ),
    "customs_revenue": (
        "Recettes douanières : sensibles au dollar et à l'inflation selon le scénario."
    ),
    "food_subsidies": (
        "Soutien alimentaire : sensible au prix du blé et au dollar."
    ),
    "debt_service": (
        "Service de la dette : sensible au coût en dinars de l'euro et du dollar."
    ),
    "social_spending": (
        "Dépenses sociales : sensibles à l'inflation dans ce scénario."
    ),
}
SIGNAL_MECHANISMS = {
    ("fuel_subsidies", "BRENT"): (
        "Le Brent renchérit le soutien aux carburants en Tunisie."
    ),
    ("fuel_subsidies", "USDTND"): (
        "Le pétrole étant coté en dollars, une variation du taux USD/TND modifie, "
        "dans le scénario, son coût exprimé en dinars."
    ),
    ("food_subsidies", "WHEAT"): (
        "Le prix du blé modifie le coût estimé des produits céréaliers soutenus par "
        "le budget tunisien."
    ),
    ("food_subsidies", "USDTND"): (
        "Le taux USD/TND modifie le coût en dinars des achats alimentaires cotés "
        "en dollars dans le scénario."
    ),
    ("debt_service", "EURTND"): (
        "Le taux EUR/TND modifie la valeur en dinars des paiements de dette libellés "
        "en euros dans l'hypothèse du modèle."
    ),
    ("debt_service", "USDTND"): (
        "Le taux USD/TND modifie la valeur en dinars des paiements de dette libellés "
        "en dollars dans l'hypothèse du modèle."
    ),
    ("customs_revenue", "USDTND"): (
        "Le modèle applique au taux USD/TND un coefficient négatif pour les recettes "
        "douanières; cette relation est une hypothèse, pas une estimation causale."
    ),
    ("customs_revenue", "CPI"): (
        "Le modèle applique à l'inflation un coefficient positif pour les recettes "
        "douanières; cette relation est une hypothèse, pas une estimation causale."
    ),
    ("social_spending", "CPI"): (
        "Le modèle associe une inflation plus élevée à un besoin de dépenses sociales "
        "plus élevé dans le scénario tunisien."
    ),
}


def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read analytical history, named shocks, and saved anomaly scores."""
    import duckdb

    if not DUCKDB_PATH.is_file():
        raise FileNotFoundError(f"Missing {DUCKDB_PATH}; run the ETL first")
    with duckdb.connect(str(DUCKDB_PATH), read_only=True) as connection:
        history = connection.execute("""
            SELECT date, indicator_code, value FROM fact_indicators ORDER BY date
        """).df()
        shocks = connection.execute("SELECT * FROM dim_shock ORDER BY shock_id").df()
    anomaly_path = PROC_DIR / "anomalies.parquet"
    if not anomaly_path.is_file():
        raise FileNotFoundError(f"Missing {anomaly_path}; run anomaly.py first")
    return history, shocks, pd.read_parquet(anomaly_path)


def event_display_title(event: dict) -> str:
    """Use French event copy for the saved legacy snapshot and new assessments."""
    title = str(event.get("title") or "").strip()
    return KNOWN_EVENT_TITLES.get(title, title or "Événement extérieur")


def event_display_summary(event: dict) -> str:
    title = str(event.get("title") or "").strip()
    return KNOWN_EVENT_SUMMARIES.get(title, str(event.get("summary") or ""))


def apply_dashboard_style() -> None:
    """Load the shared visual system without adding styling logic to each page."""
    import streamlit as st

    css = (PROJECT_ROOT / "assets" / "dashboard.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def style_chart(chart, *, height: int = 350, y_title: str | None = None) -> None:
    """Use one readable Plotly treatment for all dashboard charts."""
    chart.update_layout(
        template="plotly_dark", height=height,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#16263A",
        font=dict(family="Arial, sans-serif", color=CHART_COLORS["text"], size=12),
        margin=dict(l=28, r=24, t=48, b=32),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#1C3046", font_color=CHART_COLORS["text"]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    font=dict(size=11), bgcolor="rgba(0,0,0,0)"),
    )
    chart.update_xaxes(showgrid=False, showline=True, linecolor=CHART_COLORS["grid"],
                       tickfont=dict(color="#A7BACB", size=11), title=None)
    chart.update_yaxes(showgrid=True, gridcolor=CHART_COLORS["grid"],
                       zeroline=False, tickfont=dict(color="#A7BACB", size=11),
                       title=y_title)


def french_month_axis(chart, dates, *, max_ticks: int = 7) -> None:
    """Label a date axis in French without relying on browser locale packs."""
    values = sorted(pd.Timestamp(date) for date in pd.unique(dates))
    if not values:
        return
    count = min(len(values), max_ticks)
    indexes = sorted({round(index * (len(values) - 1) / max(count - 1, 1))
                      for index in range(count)})
    ticks = [values[index] for index in indexes]
    chart.update_xaxes(tickmode="array", tickvals=ticks,
                       ticktext=[f"{MONTH_LABELS[date.month - 1]} {date.year}"
                                 for date in ticks])


def forecast_chart(code: str, history: pd.DataFrame, news_snapshot: dict | None = None) -> None:
    """Plot observed values, Prophet, and an optional event-adjusted scenario."""
    import plotly.graph_objects as go
    import streamlit as st

    observed = history.loc[history["indicator_code"] == code].sort_values("date")
    if observed.empty:
        st.info(f"{code} : aucune observation disponible")
        return
    chart = go.Figure()
    chart.add_trace(go.Scatter(
        x=observed["date"], y=observed["value"], name="Observé", mode="lines",
        line=dict(color=CHART_COLORS["observed"], width=2.3),
        hovertemplate="%{y:,.2f}<extra></extra>",
    ))
    forecast_path = PROC_DIR / f"forecast_{code}.parquet"
    if forecast_path.is_file():
        forecast = pd.read_parquet(forecast_path)
        chart.add_trace(go.Scatter(x=forecast["ds"], y=forecast["yhat_upper"],
                                   mode="lines", line=dict(width=0),
                                   hoverinfo="skip", showlegend=False))
        chart.add_trace(go.Scatter(x=forecast["ds"], y=forecast["yhat_lower"],
                                   mode="lines", fill="tonexty", name="Intervalle Prophet",
                                   line=dict(width=0), fillcolor="rgba(70,200,192,0.14)",
                                   hoverinfo="skip"))
        bridge = pd.concat([observed.tail(1).rename(columns={"date": "ds", "value": "yhat"})
                            [["ds", "yhat"]], forecast[["ds", "yhat"]]], ignore_index=True)
        chart.add_trace(go.Scatter(
            x=bridge["ds"], y=bridge["yhat"], name="Prévision Prophet",
            mode="lines+markers", marker=dict(size=5, color=CHART_COLORS["forecast"]),
            line=dict(color=CHART_COLORS["forecast"], width=3),
            hovertemplate="%{y:,.2f}<extra></extra>",
        ))
    else:
        st.caption("Prévision mensuelle indisponible; cette série peut être annuelle ou trop courte.")
    adjusted_path = PROC_DIR / f"news_adjusted_{code}.parquet"
    if news_snapshot and news_snapshot.get("events") and forecast_path.is_file() and adjusted_path.is_file():
        chart.data[-1].name = "Avant actualités (Prophet)"
        adjusted = pd.read_parquet(adjusted_path)
        bridge = pd.concat([
            observed.tail(1).rename(columns={"date": "ds", "value": "yhat"})[["ds", "yhat"]],
            adjusted[["ds", "yhat"]],
        ], ignore_index=True)
        chart.add_trace(go.Scatter(
            x=bridge["ds"], y=bridge["yhat"], name="Après actualités",
            mode="lines+markers", marker=dict(size=5, color=CHART_COLORS["scenario"]),
            line=dict(color=CHART_COLORS["scenario"], width=3),
            hovertemplate="%{y:,.2f}<extra></extra>",
        ))
    style_chart(chart, height=340)
    french_month_axis(chart, pd.concat([
        observed["date"], forecast["ds"] if forecast_path.is_file() else observed["date"],
    ]))
    st.plotly_chart(chart, width="stretch", config={"displayModeBar": False})


def news_budget_impacts(history: pd.DataFrame) -> tuple[dict, dict]:
    """Compute illustrative budget impacts before and after the news overlay."""
    before, after = {}, {}
    for code in INDICATOR_CODES:
        source = PROC_DIR / f"forecast_{code}.parquet"
        adjusted = PROC_DIR / f"news_adjusted_{code}.parquet"
        observed = history.loc[history["indicator_code"] == code].sort_values("date")
        if not source.is_file() or not adjusted.is_file() or observed.empty:
            continue
        latest = float(observed.iloc[-1]["value"])
        if latest <= 0:
            continue
        before[code] = float(pd.read_parquet(source)["yhat"].mean() / latest - 1)
        after[code] = float(pd.read_parquet(adjusted)["yhat"].mean() / latest - 1)
    return simulate(before, BASELINE_VALUES), simulate(after, BASELINE_VALUES)


def affected_budget_categories(before: dict, after: dict, snapshot: dict) -> list[dict]:
    """Keep only budget lines changed by cited news signals."""
    categories = []
    for line in BASELINE_VALUES:
        difference = after[line]["impact_mtnd"] - before[line]["impact_mtnd"]
        drivers = [
            {"event": event_display_title(event), "signal": signal,
             "elasticity": ELASTICITIES[line][signal["code"]]}
            for event in snapshot.get("events", [])
            for signal in event["signals"]
            if signal["code"] in ELASTICITIES[line]
        ]
        if drivers and abs(difference) > 1e-6:
            categories.append({
                "line": line, "label": BUDGET_LABELS[line],
                "before": before[line], "after": after[line],
                "difference_mtnd": difference,
                "difference_pct_points": (after[line]["impact_pct"] - before[line]["impact_pct"]) * 100,
                "drivers": drivers,
            })
    return sorted(categories, key=lambda item: abs(item["difference_mtnd"]), reverse=True)


def format_mtnd(amount: float) -> str:
    """Format an illustrative amount with French separators."""
    return f"{amount:,.1f}".replace(",", "\u202f").replace(".", ",")


def format_signed_mtnd(amount: float) -> str:
    return f"{'+' if amount > 0 else ''}{format_mtnd(amount)} MTND"


def category_impact_explanation(category: dict) -> str:
    """Explain the fiscal meaning of the before/after comparison."""
    baseline = category["before"]["baseline"]
    before_impact = category["before"]["impact_mtnd"]
    after_impact = category["after"]["impact_mtnd"]
    difference = category["difference_mtnd"]
    before_total = baseline + before_impact
    after_total = baseline + after_impact
    kind = "Recette" if category["line"] == "customs_revenue" else "Dépense"
    explanation = (
        f"{kind} estimée : {format_mtnd(before_total)} → "
        f"{format_mtnd(after_total)} MTND ({format_signed_mtnd(difference)})."
    )
    if kind == "Dépense" and before_impact < 0 and after_impact < 0:
        explanation += " L'économie attendue se réduit." if difference > 0 else " L'économie attendue augmente."
    return explanation


def driver_impact_explanation(line: str, driver: dict) -> str:
    """Explain the selected event's assumed transmission to a Tunisian budget line."""
    signal = driver["signal"]
    code = signal["code"]
    direction = "hausse" if signal["direction"] == "up" else "baisse"
    strength = {"high": "forte", "medium": "modérée", "low": "faible"}.get(
        signal.get("strength"), "non précisée"
    )
    elasticity = f"{driver['elasticity']:+.2f}".replace(".", ",")
    explanation = (
        f"« {driver['event']} » : {direction} {strength} "
        f"{INDICATOR_LABELS.get(code, f'de {code}')}. "
        f"{SIGNAL_MECHANISMS.get((line, code), 'Cet indicateur influence ce poste dans le scénario.')} "
        f"Élasticité supposée : {elasticity}."
    )
    start = signal.get("start_month")
    duration = signal.get("duration_months")
    if isinstance(start, int) and isinstance(duration, int):
        explanation += (
            f" Prévision : dès le mois {start}, pendant {duration} mois."
        )
    return explanation


def scenario_forecasts(shocks: dict[str, float], proc_dir: Path = PROC_DIR,
                       *, event: dict | None = None,
                       event_defaults: dict[str, float] | None = None) -> pd.DataFrame:
    """Apply selected shocks, preserving a news event's monthly timing."""
    event_adjusted = adjust_forecasts(load_forecasts(proc_dir), [event]) if event else {}
    event_defaults = event_defaults or {}
    frames = []
    for code in ("BRENT", "EURTND", "USDTND", "WHEAT", "GOLD"):
        path = Path(proc_dir) / f"forecast_{code}.parquet"
        if not path.is_file():
            continue
        forecast = pd.read_parquet(path)[["ds", "yhat"]].sort_values("ds").reset_index(drop=True)
        forecast["indicator_code"] = code
        if code in event_adjusted:
            preset_value = event_defaults.get(code, 0.0)
            adjustment = (event_adjusted[code]["relative_adjustment"].to_numpy()
                          * shocks.get(code, 0.0) / preset_value
                          if abs(preset_value) > 1e-9 else shocks.get(code, 0.0))
        else:
            adjustment = shocks.get(code, 0.0)
        forecast["scenario_yhat"] = (forecast["yhat"] * (1 + adjustment)).clip(lower=0)
        forecast["change_pct"] = 0.0
        positive = forecast["yhat"] > 0
        forecast.loc[positive, "change_pct"] = (
            forecast.loc[positive, "scenario_yhat"] / forecast.loc[positive, "yhat"] - 1
        ).mul(100).round(8)
        frames.append(forecast)
    if not frames:
        return pd.DataFrame(columns=["ds", "yhat", "indicator_code", "scenario_yhat", "change_pct"])
    return pd.concat(frames, ignore_index=True)


def news_event_shocks(event: dict, proc_dir: Path = PROC_DIR) -> dict[str, float]:
    """Convert one time-limited news event into six-month mean scenario controls."""
    forecasts = load_forecasts(proc_dir)
    adjusted = adjust_forecasts(forecasts, [event])
    return {
        code: float(adjusted[code]["yhat"].mean() / frame["yhat"].mean() - 1)
        for code, frame in forecasts.items()
        if not frame.empty and float(frame["yhat"].mean()) > 0
    }


AGRICULTURE_CHANNELS = {
    "BRENT": {
        "label": "Pétrole Brent",
        "up": "Pression possible sur le carburant agricole, l'irrigation et le transport.",
        "down": "Détente possible des coûts de carburant et de transport.",
        "actions": (
            "Suivre les prix du carburant et les coûts d'irrigation des exploitations.",
            "Examiner un appui ciblé si la hausse se confirme sur le terrain.",
        ),
    },
    "WHEAT": {
        "label": "Blé",
        "up": "Risque de hausse du coût des céréales importées et de l'alimentation animale.",
        "down": "Détente possible des coûts d'approvisionnement en céréales.",
        "actions": (
            "Vérifier les stocks et les prix des intrants céréaliers.",
            "Ajuster le calendrier des achats et cibler les filières exposées.",
        ),
    },
    "USDTND": {
        "label": "Dollar / dinar",
        "up": "Renchérissement possible des intrants agricoles facturés en dollars.",
        "down": "Allègement possible du coût des intrants facturés en dollars.",
        "actions": (
            "Recenser les achats agricoles exposés au dollar.",
            "Réexaminer les commandes et les besoins de soutien des filières concernées.",
        ),
    },
    "EURTND": {
        "label": "Euro / dinar",
        "up": "Renchérissement possible des équipements et intrants facturés en euros.",
        "down": "Allègement possible des équipements et intrants facturés en euros.",
        "actions": (
            "Recenser les achats agricoles exposés à l'euro.",
            "Revoir le calendrier des achats avec les organismes concernés.",
        ),
    },
    "CPI": {
        "label": "Prix à la consommation",
        "up": "Pression possible sur les coûts et les marges des filières agricoles.",
        "down": "Détente possible des coûts des filières agricoles.",
        "actions": (
            "Comparer les prix observés avec les coûts des exploitations.",
            "Réévaluer les mesures ciblées uniquement si la pression persiste.",
        ),
    },
}


def agriculture_assessment(shocks: dict[str, float]) -> list[dict[str, object]]:
    """Describe plausible agriculture channels without inventing a budget amount."""
    results = []
    for code, channel in AGRICULTURE_CHANNELS.items():
        change = shocks.get(code, 0.0)
        if abs(change) < 1e-6:
            continue
        results.append({
            "code": code,
            "label": channel["label"],
            "change_pct": change * 100,
            "impact": channel["up"] if change > 0 else channel["down"],
            "actions": channel["actions"] if change > 0 else (
                "Vérifier que la baisse se transmet aux coûts agricoles observés.",
                "Réviser les besoins de soutien selon les prix réellement constatés.",
            ),
        })
    return results


def agriculture_chart(assessment: list[dict[str, object]]):
    """Plot indicator changes without implying a quantified agriculture impact."""
    import plotly.graph_objects as go

    changes = [float(item["change_pct"]) for item in assessment]
    labels = [str(item["label"]) for item in assessment]
    chart = go.Figure()
    chart.add_trace(go.Bar(
        x=changes, y=labels, orientation="h", width=0.38,
        marker=dict(color=[CHART_COLORS["scenario"] if value > 0
                           else CHART_COLORS["forecast"] for value in changes],
                    line=dict(width=0)),
        text=[f"{value:+.1f}".replace(".", ",") + " %" for value in changes],
        textposition="outside", cliponaxis=False,
        hovertemplate=("%{y}<br>Variation de l'indicateur : %{x:+.1f} %"
                       "<extra></extra>"),
        name="Variation",
    ))
    style_chart(chart, height=max(280, 80 * len(assessment) + 130))
    chart.update_layout(showlegend=False, margin=dict(l=20, r=45, t=30, b=55),
                        hovermode="closest")
    lower = min(0.0, *changes)
    upper = max(0.0, *changes)
    chart.update_xaxes(range=[lower * 1.3, upper * 1.3],
                       title="Variation de l'indicateur (%)",
                       zeroline=True, zerolinecolor="#7B92A7")
    chart.update_yaxes(autorange="reversed", showgrid=False)
    return chart


def activate_shock(shock_id: str | None) -> None:
    """Open the simulator with the chosen sidebar shock."""
    import streamlit as st

    st.session_state["active_shock"] = shock_id
    st.session_state["page"] = PAGE_SCENARIO


def select_sidebar_shock(options: dict[str, str | None]) -> None:
    """Turn the sidebar selection into the active simulation."""
    import streamlit as st

    activate_shock(options[st.session_state["shock_choice"]])


def news_panel(snapshot: dict | None) -> None:
    """Show current news status, warning, evidence, and budget comparison."""
    import streamlit as st

    if snapshot is None:
        if st.session_state.get("news_error"):
            st.error(f"La veille a échoué : {st.session_state['news_error']}")
        else:
            has_news, has_gemini = credentials_available()
            missing = [name for name, present in (("NEWSAPI_KEY", has_news),
                                                    ("GEMINI_API_KEY", has_gemini)) if not present]
            if missing:
                st.info("Clé(s) absente(s) : " + ", ".join(missing)
                        + ". Ajoutez-les dans le fichier .env du projet.")
            else:
                st.info("Clés API détectées, mais aucune analyse n'a encore été enregistrée. "
                        "Cliquez sur Actualiser les actualités pour réessayer.")
        return
    checked = pd.Timestamp(snapshot["created_at"])
    if (pd.Timestamp.now(tz="UTC") - checked).total_seconds() > 72 * 3600:
        st.warning("La veille a plus de 72 heures; actualisez-la avant toute décision.")
    if snapshot.get("search_errors"):
        st.caption(f"{len(snapshot['search_errors'])} recherches NewsAPI ont échoué; couverture partielle.")
    if not snapshot["events"]:
        st.info("Aucun événement externe suffisamment étayé n'a été retenu. "
                "Les prévisions Prophet restent inchangées.")
        return
    major = any(signal["strength"] == "high" for event in snapshot["events"]
                for signal in event["signals"])
    if not major:
        major = any(
            (PROC_DIR / f"news_adjusted_{code}.parquet").is_file()
            and pd.read_parquet(PROC_DIR / f"news_adjusted_{code}.parquet")
                  ["relative_adjustment"].abs().max() >= .05
            for code in INDICATOR_CODES
        )
    titles = "; ".join(event_display_title(event) for event in snapshot["events"][:3])
    forecast_paths = [PROC_DIR / f"forecast_{code}.parquet" for code in INDICATOR_CODES]
    first_month = min(pd.Timestamp(pd.read_parquet(path)["ds"].min())
                      for path in forecast_paths if path.is_file())
    first_signal = min(signal["start_month"] for event in snapshot["events"]
                       for signal in event["signals"])
    projected_month = (first_month + pd.DateOffset(months=first_signal - 1)).strftime("%Y-%m")
    message = (f"Changement externe potentiel dès {projected_month} pour les prévisions "
               f"tunisiennes : {titles}.")
    if major:
        st.warning(message)
    else:
        st.info(message)
    with st.expander("Événements retenus et articles sources", expanded=False):
        for event in snapshot["events"]:
            confidence = {"high": "élevée", "medium": "moyenne", "low": "faible"}.get(
                event["confidence"], "non précisée")
            st.markdown(f"**{event_display_title(event)}** · fiabilité {confidence}")
            st.write(event_display_summary(event))
            st.caption(", ".join(
                f"{signal['code']} : {'hausse' if signal['direction'] == 'up' else 'baisse'} "
                f"{'forte' if signal['strength'] == 'high' else 'modérée' if signal['strength'] == 'medium' else 'faible'}"
                for signal in event["signals"]
            ))
            for index, article in enumerate(event["sources"], start=1):
                st.link_button(
                    f"Source {index} · {article['source']} · {article['published_at'][:10]}",
                    article["url"],
                )


def warning_page(history: pd.DataFrame, anomalies: pd.DataFrame,
                 news_snapshot: dict | None = None) -> None:
    """Render news, before/after forecasts, anomalies, and affected categories."""
    import streamlit as st

    st.header(PAGE_WARNING)
    news_panel(news_snapshot)
    for code in INDICATOR_CODES:
        with st.expander(code, expanded=code == "BRENT"):
            forecast_chart(code, history, news_snapshot)
    st.subheader("Anomalies détectées")
    flagged = anomalies.loc[anomalies["is_anomaly"]].sort_values("date", ascending=False)
    if flagged.empty:
        st.info("Aucune anomalie détectée dans les séries mensuelles disponibles.")
    else:
        display = flagged.drop(columns=["is_anomaly"]).rename(columns={
            "date": "Date", "indicator_code": "Indicateur",
            "value": "Valeur observée", "zscore": "z-score",
        })
        st.dataframe(display, hide_index=True, width="stretch")

    st.subheader("Catégories budgétaires impactées par les actualités")
    if not news_snapshot or not news_snapshot.get("events"):
        st.info("Aucun impact attribuable aux actualités n'est disponible pour cette prévision.")
        return
    before, after = news_budget_impacts(history)
    categories = affected_budget_categories(before, after, news_snapshot)
    if not categories:
        st.info("Les événements retenus ne touchent aucune catégorie couverte par "
                "les élasticités du prototype.")
        return
    st.caption("Montants indicatifs du prototype, non officiels.")
    for category in categories:
        with st.expander(category["label"], expanded=True):
            st.write(CATEGORY_CONTEXT[category["line"]])
            columns = st.columns(3)
            columns[0].metric("Avant actualités", format_signed_mtnd(category['before']['impact_mtnd']))
            columns[1].metric("Après actualités", format_signed_mtnd(category['after']['impact_mtnd']))
            columns[2].metric("Effet des actualités", format_signed_mtnd(category['difference_mtnd']))
            kind = "recettes" if category["line"] == "customs_revenue" else "dépenses"
            st.caption(f"Écarts à la référence de {format_mtnd(category['before']['baseline'])} MTND "
                       f"pour ce poste de {kind}.")
            st.write(category_impact_explanation(category))
            st.markdown("**Origine de l'impact**")
            for driver in category["drivers"]:
                st.write(driver_impact_explanation(category["line"], driver))


def scenario_page(defaults: dict[str, float] | None = None,
                  selected_label: str | None = None,
                  control_key: str = "reference",
                  event: dict | None = None) -> dict[str, float]:
    """Display fixed conditional indicator paths and budget impacts."""
    import plotly.graph_objects as go
    import streamlit as st

    st.header(PAGE_SCENARIO)
    defaults = defaults or {}
    if selected_label:
        st.markdown(f"**Scénario sélectionné :** {selected_label}")
        if control_key.startswith("news:"):
            st.caption("Les valeurs affichées sont l'effet moyen de l'événement; la courbe "
                       "conserve les mois réellement touchés dans la projection.")
    controls = st.columns(5)
    shocks = {"CPI": defaults["CPI"]} if "CPI" in defaults else {}
    for column, code in zip(controls, ("BRENT", "EURTND", "USDTND", "WHEAT", "GOLD")):
        shocks[code] = defaults.get(code, 0.0)
        precision = 1 if event else 0
        column.metric(code, f"{shocks[code] * 100:+.{precision}f} %")

    projections = scenario_forecasts(shocks, event=event, event_defaults=defaults)
    st.subheader("Trajectoire des indicateurs")
    if projections.empty:
        st.warning("Aucune prévision mensuelle trouvée. Lancez forecast.py d'abord.")
    else:
        codes = projections["indicator_code"].unique().tolist()
        selected_by_default = next((item for item in codes if abs(shocks.get(item, 0)) > 1e-6),
                                   codes[0])
        code = st.selectbox("Indicateur à comparer", codes,
                            index=codes.index(selected_by_default),
                            key=f"indicator_{control_key}")
        selected = projections.loc[projections["indicator_code"] == code]
        chart = go.Figure()
        chart.add_trace(go.Scatter(
            x=selected["ds"], y=selected["yhat"], name="Prévision Prophet",
            mode="lines+markers", marker=dict(size=6, color=CHART_COLORS["forecast"]),
            line=dict(color=CHART_COLORS["forecast"], width=3),
            hovertemplate="%{y:,.2f}<extra></extra>",
        ))
        chart.add_trace(go.Scatter(
            x=selected["ds"], y=selected["scenario_yhat"], name="Scénario",
            mode="lines+markers", marker=dict(size=6, color=CHART_COLORS["scenario"]),
            line=dict(color=CHART_COLORS["scenario"], width=3,
                      dash="dot" if (selected["change_pct"].abs() < 1e-9).all() else "solid"),
            hovertemplate="%{y:,.2f}<extra></extra>",
        ))
        style_chart(chart, height=370)
        french_month_axis(chart, selected["ds"])
        st.plotly_chart(chart, width="stretch", config={"displayModeBar": False})
        display = projections.rename(columns={
            "ds": "Mois", "indicator_code": "Indicateur",
            "yhat": "Prophet", "scenario_yhat": "Scénario",
            "change_pct": "Choc (%)",
        })[["Mois", "Indicateur", "Prophet", "Scénario", "Choc (%)"]]
        display["Mois"] = pd.to_datetime(display["Mois"]).dt.strftime("%m/%Y")
        st.markdown("**Données mensuelles détaillées**")
        st.dataframe(display, hide_index=True, width="stretch",
                     column_config={
                         "Prophet": st.column_config.NumberColumn(format="%.2f"),
                         "Scénario": st.column_config.NumberColumn(format="%.2f"),
                         "Choc (%)": st.column_config.NumberColumn(format="%.1f%%"),
                     })
    impacts = simulate(shocks, BASELINE_VALUES)
    st.subheader("Impact budgétaire estimé par catégorie")
    rows = []
    for line, values in impacts.items():
        assessment = evaluate(line, values["impact_pct"])
        rows.append({"Catégorie": BUDGET_LABELS[line], "Référence (MTND)": values["baseline"],
                     "Impact (%)": values["impact_pct"] * 100,
                     "Impact (MTND)": values["impact_mtnd"],
                     "Statut GPO": STATUS_LABELS[assessment["status"]],
                     "status_code": assessment["status"]})
    table = pd.DataFrame(rows)
    chart_table = table.loc[table["Impact (MTND)"].abs() > 1e-6]
    if chart_table.empty:
        st.info("Ce scénario ne modifie aucun poste budgétaire du prototype.")
    else:
        chart = go.Figure(go.Bar(
            x=chart_table["Impact (MTND)"], y=chart_table["Catégorie"], orientation="h",
            marker=dict(color=[STATUS_COLORS[status] for status in chart_table["status_code"]],
                        line=dict(width=0)),
            text=[f"{value:+,.0f}" for value in chart_table["Impact (MTND)"]],
            textposition="outside", cliponaxis=False,
            customdata=chart_table["Statut GPO"],
            hovertemplate="%{y}<br>Impact : %{x:,.1f} MTND<br>Statut : %{customdata}<extra></extra>",
        ))
        style_chart(chart, height=max(230, 85 * len(chart_table) + 100), y_title=None)
        chart.update_layout(showlegend=False, margin=dict(l=22, r=80, t=20, b=32))
        chart.update_yaxes(autorange="reversed", showgrid=False)
        chart.update_xaxes(showgrid=True, gridcolor=CHART_COLORS["grid"],
                           zeroline=True, zerolinecolor="#7B92A7", title="Impact (MTND)")
        st.plotly_chart(chart, width="stretch", config={"displayModeBar": False})
        st.caption("Couleurs du statut GPO : turquoise = stable, cuivre = à surveiller, "
                   "rouge = critique.")
    st.markdown("**Détail des impacts par catégorie**")
    st.dataframe(table.drop(columns="status_code"), hide_index=True, width="stretch",
                 column_config={
                     "Référence (MTND)": st.column_config.NumberColumn(format="%.1f"),
                     "Impact (%)": st.column_config.NumberColumn(format="%.1f%%"),
                     "Impact (MTND)": st.column_config.NumberColumn(format="%+.1f"),
                 })
    st.caption("L'or est suivi dans les prévisions mais ne dispose pas d'élasticité "
               "budgétaire dans les hypothèses du prototype.")
    return shocks


def gpo_page(impacts: dict[str, dict[str, float]],
             agriculture_shocks: dict[str, float] | None = None,
             event: dict | None = None) -> None:
    """Render objectives, key results, KPIs, and French SMART action cards."""
    import streamlit as st

    st.header(PAGE_GPO)
    st.subheader("Agriculture : impacts et décisions")
    if event:
        st.markdown(f"**Événement :** {event_display_title(event)}")
    st.caption("Analyse qualitative : aucun montant MTND n'est calculé pour l'agriculture, "
               "faute de référence budgétaire et d'élasticité propres à ce secteur.")
    agriculture = agriculture_assessment(agriculture_shocks or {})
    if not agriculture:
        st.info("Aucun effet agricole direct identifié pour ce scénario.")
    else:
        st.plotly_chart(agriculture_chart(agriculture), width="stretch",
                        config={"displayModeBar": False})
        for item in agriculture:
            change = f"{item['change_pct']:+.1f}".replace(".", ",")
            st.markdown(f"**{item['label']} · {change} %**")
            st.write(f"Impact possible : {item['impact']}")
            st.markdown("**Décisions à examiner**")
            for action in item["actions"]:
                st.write(f"• {action}")

    st.subheader("Autres catégories budgétaires")
    for line, values in impacts.items():
        assessment = evaluate(line, values["impact_pct"])
        with st.expander(f"{BUDGET_LABELS[line]} — {STATUS_LABELS[assessment['status']]}"):
            st.markdown(
                f'<span class="status-badge status-{assessment["status"].lower()}">'
                f'{STATUS_LABELS[assessment["status"]]}</span>',
                unsafe_allow_html=True,
            )
            objective = OBJECTIVES[line]
            st.markdown(f"**Objectif :** {objective['objective']}")
            st.markdown("**Résultats clés**")
            for key_result in objective["key_results"]:
                st.write(f"• {key_result}")
            st.markdown("**Indicateurs de suivi**")
            st.write(", ".join(objective["kpis"]))
            st.write(f"{assessment['reason']} Impact simulé: {values['impact_mtnd']:+,.1f} MTND.")
            for action in generate_smart_actions(line, values["impact_pct"], values["impact_mtnd"]):
                with st.container(border=True):
                    st.markdown(f"**{action['action']}**")
                    st.write(f"Spécifique: {action['specific']} · Mesurable: {action['measurable']}")
                    st.write(f"Atteignable: {action['achievable']}")
                    st.write(f"Pertinent: {action['relevant']}")
                    st.write(f"Échéance: {action['time_bound']}")


def main() -> None:
    """Run the three-page Streamlit interface with shared scenario controls."""
    import streamlit as st

    st.set_page_config(page_title="Tunisie · Analyse économique", page_icon=":material/monitoring:",
                       layout="wide")
    apply_dashboard_style()
    st.markdown(
        '<div class="dashboard-brand"><h1>Tunisie · Analyse économique</h1>'
        '<div class="brand-subtitle">Radar des chocs budgétaires</div>'
        '<p>Anticiper les risques extérieurs et éclairer les décisions budgétaires</p></div>',
        unsafe_allow_html=True,
    )
    st.sidebar.markdown('<div class="sidebar-brand">Tunisie · Analyse économique</div>',
                        unsafe_allow_html=True)
    try:
        history, shocks_table, anomalies = load_data()
        import plotly  # noqa: F401 - checked here to show a clear install instruction.
    except ImportError as exc:
        st.error(f"Dépendance manquante : {exc}. Exécutez "
                 "`python -m pip install -r requirements.txt`.")
        st.stop()
    except FileNotFoundError as exc:
        st.error(str(exc))
        st.code("python src/etl/clean.py\npython src/etl/build_star.py\n"
                "python src/etl/load_duckdb.py\npython src/models/forecast.py\n"
                "python src/models/anomaly.py")
        st.stop()
    pages = [PAGE_WARNING, PAGE_SCENARIO, PAGE_GPO]
    if st.session_state.get("page") not in pages:
        st.session_state["page"] = PAGE_WARNING
    page = st.sidebar.radio("Navigation", pages, key="page")
    refresh_requested = st.sidebar.button("Actualiser la veille",
                                          help="Interroger NewsAPI et Gemini une fois",
                                          type="primary", width="content")
    try:
        news_snapshot = load_news_snapshot()
    except (ValueError, FileNotFoundError, OSError):
        news_snapshot = None
    keys_ready = all(credentials_available())
    snapshot_old = (news_snapshot is not None
                    and pd.Timestamp.now(tz="UTC") - pd.Timestamp(news_snapshot["created_at"])
                    > pd.Timedelta(hours=24))
    auto_refresh = (page == PAGE_WARNING and (news_snapshot is None or snapshot_old)
                    and keys_ready and not st.session_state.get("news_auto_attempted"))
    if refresh_requested or auto_refresh:
        st.session_state["news_auto_attempted"] = True
        try:
            with st.spinner("Recherche et analyse des actualités..."):
                run_news_impact()
            news_snapshot = load_news_snapshot()
            st.session_state.pop("news_error", None)
            st.sidebar.success("Actualités analysées.")
        except Exception as exc:
            st.session_state["news_error"] = str(exc)
            st.sidebar.error(f"Veille indisponible : {exc}")
    available_shocks: dict[str, tuple[str, dict[str, float] | dict]] = {}
    if news_snapshot and news_snapshot.get("events"):
        for index, event in enumerate(news_snapshot["events"], start=1):
            shock_id = f"news:{news_snapshot['created_at']}:{index}"
            available_shocks[shock_id] = (event_display_title(event), event)
    for name in shocks_table["name"]:
        if name not in PRESETS:
            continue
        shock_id = f"preset:{name}"
        available_shocks[shock_id] = (PRESET_LABELS[name], PRESETS[name])
    active_shock = st.session_state.get("active_shock")
    if active_shock not in available_shocks:
        active_shock = next(iter(available_shocks), None)
        st.session_state["active_shock"] = active_shock
    choice_to_id: dict[str, str] = {}
    for shock_id, (label, _) in available_shocks.items():
        prefix = "Référence" if shock_id.startswith("preset:") else "Actualité"
        choice_to_id[f"{prefix} · {label}"] = shock_id
    if choice_to_id.get(st.session_state.get("shock_choice")) != active_shock:
        st.session_state["shock_choice"] = next(
            (label for label, shock_id in choice_to_id.items() if shock_id == active_shock),
            None,
        )
    if choice_to_id:
        st.sidebar.selectbox("Scénario à examiner", list(choice_to_id),
                             key="shock_choice", on_change=select_sidebar_shock,
                             args=(choice_to_id,))
    if page == PAGE_WARNING:
        warning_page(history, anomalies, news_snapshot)
    elif page == PAGE_SCENARIO:
        selected_label = None
        defaults: dict[str, float] = {}
        selected_event = None
        if active_shock:
            selected_label, selected = available_shocks[active_shock]
            if active_shock.startswith("news:"):
                selected_event = selected
                defaults = news_event_shocks(selected_event)
            else:
                defaults = selected
        st.session_state["scenario_shocks"] = scenario_page(
            defaults, selected_label, active_shock or "reference", selected_event)
    else:
        selected_event = None
        selected_shocks: dict[str, float] = {}
        if active_shock:
            _, selected = available_shocks[active_shock]
            selected_event = selected if active_shock.startswith("news:") else None
            selected_shocks = (news_event_shocks(selected_event) if selected_event else selected)
        impacts = simulate(selected_shocks, BASELINE_VALUES)
        gpo_page(impacts, agriculture_shocks=selected_shocks, event=selected_event)


if __name__ == "__main__":
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except ImportError:
        print("[app] Install Streamlit: python -m pip install streamlit")
        raise SystemExit(1)
    if get_script_run_ctx() is None:
        print("[app] Start the interface with: streamlit run app.py")
    else:
        main()
