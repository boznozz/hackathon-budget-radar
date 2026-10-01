"""Build the two-page French hackathon synthesis note."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "deliverables" / "Note_de_synthese_AI_Budget_Shock_Radar.pdf"
pdfmetrics.registerFont(TTFont("Arial", "C:/Windows/Fonts/arial.ttf"))
pdfmetrics.registerFont(TTFont("Arial-Bold", "C:/Windows/Fonts/arialbd.ttf"))
pdfmetrics.registerFontFamily("Arial", normal="Arial", bold="Arial-Bold")

NAVY = colors.HexColor("#101F31")
TEAL = colors.HexColor("#168E8A")
MUTED = colors.HexColor("#526578")
PALE = colors.HexColor("#EDF5F5")
LINE = colors.HexColor("#D9E4E8")

title = ParagraphStyle(
    "title", fontName="Arial-Bold", fontSize=21, leading=25,
    textColor=NAVY, spaceAfter=6,
)
subtitle = ParagraphStyle(
    "subtitle", fontName="Arial", fontSize=9.4, leading=13,
    textColor=MUTED, spaceAfter=18,
)
heading = ParagraphStyle(
    "heading", fontName="Arial-Bold", fontSize=12.2, leading=16,
    textColor=TEAL, spaceBefore=13, spaceAfter=6,
)
body = ParagraphStyle(
    "body", fontName="Arial", fontSize=9.7, leading=14.3,
    textColor=NAVY, spaceAfter=8, alignment=TA_LEFT,
)
small = ParagraphStyle(
    "small", fontName="Arial", fontSize=8.3, leading=11.8,
    textColor=MUTED, spaceAfter=7,
)
table_head = ParagraphStyle(
    "table_head", fontName="Arial-Bold", fontSize=8.7, leading=11,
    textColor=NAVY,
)
table_cell = ParagraphStyle(
    "table_cell", fontName="Arial", fontSize=8.7, leading=11.5,
    textColor=NAVY,
)


def p(text: str, style=body):
    return Paragraph(text, style)


def section(name: str, text: str):
    return [p(name, heading), p(text)]


def footer(canvas, doc):
    canvas.saveState()
    width, _ = A4
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.7)
    canvas.line(19 * mm, 18 * mm, width - 19 * mm, 18 * mm)
    canvas.setFont("Arial", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(19 * mm, 13 * mm, "AI Budget Shock Radar | Note de synthèse")
    canvas.drawRightString(width - 19 * mm, 13 * mm, f"{doc.page} / 2")
    canvas.restoreState()


doc = SimpleDocTemplate(
    str(OUTPUT), pagesize=A4,
    leftMargin=19 * mm, rightMargin=19 * mm,
    topMargin=20 * mm, bottomMargin=26 * mm,
    title="Note de synthèse - AI Budget Shock Radar",
    author="Équipe du prototype hackathon T19",
)

story = [
    p("Note de synthèse", title),
    p("Tunisie · Analyse économique | AI Budget Shock Radar &amp; GPO Cockpit | 26 septembre 2026", subtitle),
    HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=7),
]

story += section(
    "Défi choisi",
    "Les variations du pétrole, du blé et des devises peuvent modifier rapidement les "
    "hypothèses d'un budget tunisien. Le défi consiste à relier une veille des événements "
    "extérieurs à des prévisions économiques et à rendre visibles les postes budgétaires "
    "potentiellement concernés, avant que l'exécution officielle ne confirme l'effet.",
)
story += section(
    "Approche technique",
    "Les fichiers CSV/JSON bruts restent inchangés. L'ETL normalise les séries, écrit des "
    "fichiers Parquet et construit une base analytique DuckDB. Prophet produit séparément "
    "six prévisions mensuelles pour chaque indicateur admissible. NewsAPI fournit les "
    "articles récents; Gemini retient les événements externes étayés et décrit des signaux "
    "(direction, intensité, début, durée). Le code transforme ces signaux en ajustements "
    "mensuels fixes, décroissants et plafonnés. Streamlit compare les courbes avant/après, "
    "calcule des impacts budgétaires indicatifs et propose un suivi GPO.",
)
story += [p("Données et modèles utilisés", heading)]
data_rows = [
    [p("Composant", table_head), p("État du prototype", table_head)],
    [p("Indicateurs", table_cell), p("318 observations dans DuckDB : Brent, or, EUR/TND, USD/TND, blé et CPI. Cinq séries ont une prévision mensuelle; le CPI est écarté faute d'historique suffisamment mensuel.", table_cell)],
    [p("Prévision", table_cell), p("Prophet : tendance et saisonnalité annuelle, horizon de six mois, bande basse/haute du modèle.", table_cell)],
    [p("Actualités", table_cell), p("NewsAPI et Gemini : événements sourcés, puis scénarios chiffrés par règles fixes. Gemini ne réentraîne pas Prophet.", table_cell)],
    [p("Budget", table_cell), p("Cinq références et une matrice d'élasticités illustratives. Impact (MTND) = référence × somme(élasticité × variation de l'indicateur).", table_cell)],
]
data_table = Table(data_rows, colWidths=[35 * mm, 136 * mm], hAlign="LEFT")
data_table.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), PALE),
    ("GRID", (0, 0), (-1, -1), 0.4, LINE),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LEFTPADDING", (0, 0), (-1, -1), 7),
    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
    ("TOPPADDING", (0, 0), (-1, -1), 6),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
]))
story += [data_table]
story += section(
    "Résultat obtenu lors de l'exécution locale",
    "Le traitement enregistré le 26 septembre 2026 a examiné <b>46 articles</b> et retenu "
    "<b>un événement</b>. Le scénario de hausse du Brent modifie l'écart simulé des "
    "subventions aux carburants de <b>+150,7 MTND</b>. La dépense indicative passe de "
    "5 765,9 à 5 916,6 MTND, sur une référence illustrative de 8 000 MTND. "
    "Il s'agit d'un résultat de simulation, pas d'une dépense constatée.",
)
story += [PageBreak()]

story += [p("Limites et recommandations", title),
          p("Conditions à remplir avant tout usage opérationnel", subtitle),
          HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=7)]

story += [p("Limites identifiées", heading)]
limits = [
    "<b>Budget :</b> les séries mensuelles des cinq postes sont synthétiques. Les montants de référence ne sont pas des crédits ou dépenses officiels.",
    "<b>Transmission :</b> les élasticités et les intensités des événements sont des hypothèses de prototype; aucune causalité ni calibration empirique n'est démontrée.",
    "<b>Prévision :</b> le CPI ne dispose pas ici d'une série mensuelle exploitable. Aucun test comparatif hors échantillon n'établit la précision de Prophet pour ces indicateurs.",
    "<b>Actualités :</b> la couverture dépend de NewsAPI. Un article ou une classification erronée peut produire un faux signal. La courbe après actualités n'a pas d'intervalle de confiance recalibré.",
]
for item in limits:
    story.append(p("• " + item))

story += [p("Recommandations pour la mise en production", heading)]
recommendations = [
    "<b>1. Remplacer les références synthétiques</b> par les crédits et l'exécution mensuelle officiels, avec une définition stable de chaque poste.",
    "<b>2. Mesurer les coefficients de transmission</b> sur des données tunisiennes et faire valider les mécanismes par des experts budgétaires et sectoriels.",
    "<b>3. Rétrotester les prévisions et les alertes</b> sur plusieurs fenêtres historiques; comparer Prophet à des méthodes simples et suivre erreurs et fausses alertes.",
    "<b>4. Encadrer la veille</b> par une revue humaine des sources et des événements, un journal des hypothèses, la surveillance des API et une politique de rafraîchissement adaptée.",
    "<b>5. Déployer progressivement</b> : pilote sur quelques postes, validation avec les équipes métier, puis extension lorsque la qualité des données et les seuils d'alerte sont documentés.",
]
for item in recommendations:
    story.append(p(item))

story += [
    p("Lecture du prototype", heading),
    p("Le tableau de bord permet aujourd'hui de comparer une prévision de référence avec "
      "un scénario conditionnel d'actualité, d'identifier les catégories budgétaires "
      "touchées et d'afficher des décisions à examiner. L'agriculture est présentée "
      "qualitativement : aucune référence budgétaire ni élasticité propre à ce secteur "
      "n'est disponible pour calculer un montant fiable."),
    Spacer(1, 9),
    p("Sources du présent document : code et sorties locales du projet "
      "(<i>forecast_metrics.parquet</i>, <i>news_snapshot.json</i>, prévisions et scénarios "
      "enregistrés au 26/09/2026).", small),
]

doc.build(story, onFirstPage=footer, onLaterPages=footer)
print(OUTPUT)
