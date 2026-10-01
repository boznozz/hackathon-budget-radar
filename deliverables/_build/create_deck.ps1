$ErrorActionPreference = 'Stop'
$root = 'C:\Users\youss\Desktop\New folder (2)\hackathon-budget-radar'
$out = Join-Path $root 'deliverables\AI_Budget_Shock_Radar_Pitch_Deck.pptx'
$preview = Join-Path $root 'deliverables\_build\slides'
New-Item -ItemType Directory -Path $preview -Force | Out-Null

function Rgb([int]$r, [int]$g, [int]$b) { return ($r + 256 * $g + 65536 * $b) }
$bg = Rgb 11 21 35
$surface = Rgb 22 38 58
$white = Rgb 238 245 250
$muted = Rgb 168 186 203
$teal = Rgb 70 200 192
$copper = Rgb 233 165 94
$line = Rgb 43 64 85
$font = 'Arial'

function AddText($slide, [string]$value, [double]$x, [double]$y,
                 [double]$w, [double]$h, [double]$size, [int]$color,
                 [bool]$bold = $false, [int]$align = 1) {
    $shape = $slide.Shapes.AddTextbox(1, $x, $y, $w, $h)
    $shape.TextFrame.MarginLeft = 0
    $shape.TextFrame.MarginRight = 0
    $shape.TextFrame.MarginTop = 0
    $shape.TextFrame.MarginBottom = 0
    $shape.TextFrame.WordWrap = -1
    $shape.TextFrame.TextRange.Text = $value
    $shape.TextFrame.TextRange.Font.Name = $font
    $shape.TextFrame.TextRange.Font.Size = $size
    $shape.TextFrame.TextRange.Font.Bold = [int]$bold * -1
    $shape.TextFrame.TextRange.Font.Color.RGB = $color
    $shape.TextFrame.TextRange.ParagraphFormat.Alignment = $align
    return $shape
}

function AddBar($slide, [double]$x, [double]$y, [double]$w, [double]$h, [int]$color) {
    $shape = $slide.Shapes.AddShape(1, $x, $y, $w, $h)
    $shape.Fill.Solid()
    $shape.Fill.ForeColor.RGB = $color
    $shape.Line.Visible = 0
    return $shape
}

function AddLine($slide, [double]$x1, [double]$y1, [double]$x2, [double]$y2,
                 [int]$color, [double]$weight = 1.5, [bool]$arrow = $false) {
    $shape = $slide.Shapes.AddLine($x1, $y1, $x2, $y2)
    $shape.Line.ForeColor.RGB = $color
    $shape.Line.Weight = $weight
    if ($arrow) { $shape.Line.EndArrowheadStyle = 3 }
    return $shape
}

$ppt = $null
$deck = $null
try {
    $ppt = New-Object -ComObject PowerPoint.Application
    $deck = $ppt.Presentations.Add(0)
    $deck.PageSetup.SlideWidth = 960
    $deck.PageSetup.SlideHeight = 540

    function NewSlide([int]$number, [string]$title) {
        $slide = $deck.Slides.Add($number, 12)
        $slide.Background.Fill.Solid()
        $slide.Background.Fill.ForeColor.RGB = $bg
        AddBar $slide 0 0 960 540 $bg | Out-Null
        if ($number -gt 1) {
            AddText $slide $title 58 42 844 64 32 $white $true | Out-Null
            AddLine $slide 58 112 902 112 $line 1 | Out-Null
            AddText $slide 'AI Budget Shock Radar · Prototype hackathon' 58 514 660 16 10 $muted | Out-Null
            AddText $slide ("{0:D2} / 12" -f $number) 830 514 72 16 10 $muted $false 3 | Out-Null
        }
        return $slide
    }

    # 1. Cover
    $s = NewSlide 1 ''
    AddText $s 'PITCH DECK · HACKATHON T19' 66 86 760 25 15 $teal $true | Out-Null
    AddText $s 'Tunisie · Analyse économique' 66 150 825 100 47 $white $true | Out-Null
    AddText $s 'Radar des chocs budgétaires' 66 270 825 55 29 $teal $true | Out-Null
    AddText $s 'Prévisions mensuelles et scénarios dʼactualité pour éclairer les décisions budgétaires' 66 362 795 70 21 $muted | Out-Null
    AddText $s 'Prototype local · 26 septembre 2026' 66 491 700 22 13 $muted | Out-Null

    # 2. Problem
    $s = NewSlide 2 'Le problème traité'
    AddText $s 'Les prix internationaux et les devises changent avant que leur effet budgétaire soit visible dans les données dʼexécution.' 62 144 836 92 24 $white $true | Out-Null
    AddText $s 'Pétrole' 62 290 236 35 22 $teal $true | Out-Null
    AddText $s 'Coût potentiel du soutien aux carburants' 62 334 230 72 18 $muted | Out-Null
    AddText $s 'Blé' 356 290 236 35 22 $teal $true | Out-Null
    AddText $s 'Pression possible sur le soutien alimentaire' 356 334 230 72 18 $muted | Out-Null
    AddText $s 'Change' 650 290 236 35 22 $teal $true | Out-Null
    AddText $s 'Dépenses et recettes sensibles au dinar' 650 334 230 72 18 $muted | Out-Null

    # 3. Solution
    $s = NewSlide 3 'Une alerte reliée à la prévision'
    $labels = @('Séries mensuelles', 'Prévision Prophet', 'Événements retenus', 'Impacts simulés')
    $xs = @(62, 286, 510, 734)
    for ($i=0; $i -lt 4; $i++) {
        AddText $s ([string]($i+1).ToString('00')) $xs[$i] 176 170 36 23 $copper $true | Out-Null
        AddText $s $labels[$i] $xs[$i] 224 184 58 20 $white $true | Out-Null
        if ($i -lt 3) { AddLine $s ($xs[$i]+180) 246 ($xs[$i+1]-18) 246 $teal 2 $true | Out-Null }
    }
    AddText $s 'Le tableau de bord rapproche la trajectoire avant et après actualités, puis affiche les catégories budgétaires concernées.' 62 348 830 82 21 $muted | Out-Null

    # 4. Data
    $s = NewSlide 4 'Données utilisées'
    AddText $s '318 observations dʼindicateurs dans DuckDB' 62 145 800 42 25 $teal $true | Out-Null
    $codes = @('Brent', 'Or', 'EUR/TND', 'USD/TND', 'Blé', 'CPI')
    $counts = @(52,52,60,60,52,42)
    for ($i=0; $i -lt 6; $i++) {
        $y = 209 + $i*41
        AddText $s $codes[$i] 62 $y 245 31 19 $white | Out-Null
        AddText $s ([string]$counts[$i]) 298 $y 65 31 19 $teal $true 3 | Out-Null
        AddLine $s 62 ($y+32) 365 ($y+32) $line 1 | Out-Null
    }
    AddText $s '5 séries disposent dʼune prévision mensuelle. Le CPI reste hors prévision car son historique disponible nʼest pas suffisamment mensuel.' 445 216 430 125 20 $white | Out-Null
    AddText $s 'Les CSV/JSON bruts restent inchangés. Les références budgétaires du prototype sont synthétiques et indicatives.' 445 373 430 92 17 $muted | Out-Null

    # 5. Technical pipeline
    $s = NewSlide 5 'Pipeline technique'
    $steps = @(
        @('01', 'ETL', 'Nettoyage des CSV/JSON et stockage Parquet'),
        @('02', 'DuckDB', 'Historique analytique et dimensions'),
        @('03', 'Prophet', 'Six mois de prévisions par indicateur'),
        @('04', 'NewsAPI + Gemini', 'Événements externes et signaux structurés'),
        @('05', 'Streamlit + GPO', 'Avant/après, impacts et décisions à examiner')
    )
    for ($i=0; $i -lt 5; $i++) {
        $y = 142 + $i*69
        AddText $s $steps[$i][0] 62 $y 56 38 22 $copper $true | Out-Null
        AddText $s $steps[$i][1] 139 $y 225 38 21 $white $true | Out-Null
        AddText $s $steps[$i][2] 390 $y 515 43 18 $muted | Out-Null
        if ($i -lt 4) { AddLine $s 62 ($y+50) 900 ($y+50) $line 1 | Out-Null }
    }

    # 6. Forecast model
    $s = NewSlide 6 'Approche IA : prévision mensuelle'
    AddText $s 'Prophet est ajusté séparément sur chaque indicateur ayant au moins 18 observations et un historique surtout mensuel.' 62 145 840 94 22 $white | Out-Null
    AddText $s 'Prévision centrale = tendance + saisonnalité annuelle' 62 265 830 58 25 $teal $true | Out-Null
    AddText $s 'Sortie : six valeurs mensuelles yhat et une bande dʼincertitude basse/haute. Le modèle ne reçoit pas directement les articles de presse.' 62 358 830 78 19 $muted | Out-Null

    # 7. News overlay
    $s = NewSlide 7 'De lʼévénement au scénario'
    AddText $s 'Gemini conserve un événement externe étayé, puis décrit le sens, lʼintensité, le début et la durée du signal.' 62 143 835 76 21 $white | Out-Null
    AddText $s 'Exemple : Brent, signal « fort », trois mois' 62 246 570 34 19 $teal $true | Out-Null
    $bars = @(160,136,112)
    $vals = @('+8,0 %','+6,8 %','+5,6 %')
    for ($i=0; $i -lt 3; $i++) {
        $x = 125 + $i*250
        AddBar $s $x 332 $bars[$i] 34 $copper | Out-Null
        AddText $s $vals[$i] ($x+$bars[$i]+10) 331 90 32 18 $white $true | Out-Null
        AddText $s ("Mois {0}" -f ($i+1)) $x 382 125 27 17 $muted | Out-Null
    }
    AddText $s 'Les pourcentages sont des hypothèses fixes et plafonnées. Prophet nʼest pas réentraîné.' 62 450 835 45 17 $muted | Out-Null

    # 8. Budget transmission
    $s = NewSlide 8 'Transmission au budget'
    AddText $s 'Impact relatif = somme des élasticités × variations des indicateurs' 62 153 836 74 27 $teal $true | Out-Null
    AddText $s 'Exemple illustratif : une hausse du Brent de 10 % et un taux USD/TND inchangé' 62 259 836 55 20 $white | Out-Null
    AddText $s 'Subventions carburants : 0,85 × 10 % = +8,5 %' 62 331 836 44 23 $white $true | Out-Null
    AddText $s 'Référence de 8 000 MTND : impact estimé de +680 MTND' 62 397 836 43 23 $copper $true | Out-Null
    AddText $s 'Référence et coefficients du prototype : hypothèses, non données budgétaires officielles.' 62 474 835 30 15 $muted | Out-Null

    # 9. Prototype screenshot
    $s = NewSlide 9 'Prototype Streamlit'
    $imagePath = Join-Path $root 'deliverables\_build\dashboard.png'
    $s.Shapes.AddPicture($imagePath, 0, -1, 142, 125, 676, 380) | Out-Null

    # 10. Recorded demonstration
    $s = NewSlide 10 'Résultat de la démonstration'
    AddText $s '46' 62 159 230 65 49 $teal $true | Out-Null
    AddText $s 'articles examinés' 62 232 225 40 19 $muted | Out-Null
    AddText $s '1' 352 159 230 65 49 $teal $true | Out-Null
    AddText $s 'événement retenu' 352 232 225 40 19 $muted | Out-Null
    AddText $s '+150,7' 638 159 260 65 45 $copper $true | Out-Null
    AddText $s 'MTND dʼeffet simulé' 638 232 260 40 19 $muted | Out-Null
    AddText $s 'Subventions aux carburants : dépense indicative de 5 765,9 à 5 916,6 MTND après prise en compte des actualités.' 62 322 820 100 22 $white | Out-Null
    AddText $s 'Exécution locale du 26/09/2026. Ce résultat est un scénario indicatif, pas une dépense observée.' 62 453 835 39 16 $muted | Out-Null

    # 11. Expected value
    $s = NewSlide 11 'Impact attendu'
    AddText $s 'Une veille qui suit les indicateurs déjà prévus' 62 153 825 48 23 $white $true | Out-Null
    AddText $s 'Le même événement apparaît dans la courbe après actualités et dans son effet budgétaire estimé.' 62 207 825 75 19 $muted | Out-Null
    AddText $s 'Une lecture budgétaire explicable' 62 311 825 48 23 $white $true | Out-Null
    AddText $s 'Chaque variation renvoie à un signal, un coefficient supposé et une catégorie concernée. Les décisions restent à valider par les responsables.' 62 365 825 88 19 $muted | Out-Null

    # 12. Limits and production
    $s = NewSlide 12 'Limites et mise en production'
    AddText $s 'Limites actuelles' 62 151 370 40 22 $copper $true | Out-Null
    AddText $s 'Budget mensuel synthétique' 62 215 360 32 19 $white | Out-Null
    AddText $s 'Élasticités non estimées sur données réelles' 62 271 360 53 19 $white | Out-Null
    AddText $s 'CPI sans série mensuelle exploitable' 62 344 360 53 19 $white | Out-Null
    AddText $s 'Pas de validation hors échantillon' 62 418 360 53 19 $white | Out-Null
    AddText $s 'Priorités de production' 512 151 386 40 22 $teal $true | Out-Null
    AddText $s 'Intégrer lʼexécution budgétaire officielle' 512 215 385 53 19 $white | Out-Null
    AddText $s 'Calibrer les coefficients avec des experts' 512 288 385 53 19 $white | Out-Null
    AddText $s 'Rétrotester les prévisions et la veille' 512 361 385 53 19 $white | Out-Null
    AddText $s 'Tracer la validation humaine des événements' 512 434 385 53 19 $white | Out-Null

    $deck.SaveAs($out, 24)
    $deck.Export($preview, 'PNG', 1280, 720)
    Write-Output "PPTX=$out"
    Write-Output "SLIDES=$($deck.Slides.Count)"
}
finally {
    if ($deck -ne $null) { $deck.Close() }
    if ($ppt -ne $null) { $ppt.Quit() }
}
