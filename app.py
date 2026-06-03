#!/usr/bin/env python3
"""
JAP Tool v2 — Application web Padel FFT
Arena18 — jap.myconvi.fr
"""
from flask import Flask, request, jsonify, render_template, send_file
import io, json, base64, random, os
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors

app = Flask(__name__)

# ── PDF vierge FFT ───────────────────────
PDF_B64_PATH = os.path.join(os.path.dirname(__file__), 'static', 'tableau16_b64.txt')
with open(PDF_B64_PATH) as f:
    PDF_VIERGE_B64 = f.read().strip()

W_PDF, H_PDF = 595.2, 841.8
Y_1T = [735.4,694.8,654.3,613.7,573.2,532.6,492.0,451.4,
        410.9,370.3,329.8,289.2,248.6,208.0,167.5,126.9]
Y_QF = [715.1,634.0,552.9,471.7,390.6,309.5,228.3,147.2]
TS_COLORS = {
    'TS1':(0.10,0.45,0.25),'TS2':(0.10,0.45,0.25),
    'TS3':(0.75,0.45,0.05),'TS4':(0.75,0.45,0.05),
    'TS5':(0.60,0.15,0.10),'TS6':(0.60,0.15,0.10),
    'TS7':(0.60,0.15,0.10),'TS8':(0.60,0.15,0.10),
}

def shuffle(arr):
    a = arr[:]
    for i in range(len(a)-1, 0, -1):
        j = random.randint(0, i)
        a[i], a[j] = a[j], a[i]
    return a

def add_min(hm, m):
    h, mn = map(int, hm.split(':'))
    t = h*60 + mn + m
    return f"{t//60:02d}:{t%60:02d}"

def sub_min(hm, m):
    h, mn = map(int, hm.split(':'))
    t = h*60 + mn - m
    if t < 0: t = 0
    return f"{t//60:02d}:{t%60:02d}"

def hm_to_min(hm):
    h, mn = map(int, hm.split(':'))
    return h*60 + mn

def min_to_hm(m):
    if m < 0: m = 0
    return f"{m//60:02d}:{m%60:02d}"

# ── Parsing CSV FFT ──────────────────────
def parse_csv(text):
    text = text.replace('\r\n', '\n').replace('\r', '\n').lstrip('\ufeff')
    lines = [l for l in text.strip().split('\n') if l.strip()]
    start = 1 if 'epreuve' in lines[0].lower() or 'nom j1' in lines[0].lower() else 0
    paires = []
    for line in lines[start:]:
        c = line.split(';')
        if len(c) < 20: continue
        poids = int(c[19].strip()) if c[19].strip().isdigit() else None
        if not poids: continue
        paires.append({
            'nomJ1':   c[3].strip(),
            'prenJ1':  c[4].strip().capitalize(),
            'licJ1':   c[6].strip().replace(' (2026)','').replace(' (2025)',''),
            'telJ1':   c[10].strip().replace(' ',''),
            'nomJ2':   c[11].strip(),
            'prenJ2':  c[12].strip().capitalize(),
            'licJ2':   c[14].strip().replace(' (2026)','').replace(' (2025)',''),
            'telJ2':   c[18].strip().replace(' ',''),
            'poids':   poids,
        })
    paires.sort(key=lambda p: p['poids'])
    for i, p in enumerate(paires):
        p['id']  = i + 1
        p['nc']  = p['nomJ1'].upper() + ' / ' + p['nomJ2'].upper()
        p['nf']  = p['prenJ1'] + ' ' + p['nomJ1'] + ' / ' + p['prenJ2'] + ' ' + p['nomJ2']
        p['ts']  = 'TS' + str(i+1) if i < 8 else None
    return paires

# ── Construction tableau FFT ─────────────
def build_tableau(paires, contraintes=None):
    """
    contraintes : dict {paire_id: 'HH:MM'} — heure min de disponibilité
    """
    ts1, ts2   = paires[0], paires[1]
    ts34       = shuffle([paires[2], paires[3]])
    ts58       = shuffle([paires[4], paires[5], paires[6], paires[7]])
    autres     = shuffle(paires[8:])

    # Appliquer contraintes horaires sur les équipes sans BYE
    # Les paires avec contrainte tardive vont en matchs plus tardifs
    if contraintes:
        def get_contrainte(p):
            return hm_to_min(contraintes.get(str(p['id']), '00:00'))
        # Trier ts58 et autres selon contraintes (les plus tardives en dernier)
        ts58  = sorted(ts58,  key=get_contrainte)
        autres = sorted(autres, key=get_contrainte)

    T = [
        {'t':'bye','p':ts2},        # 0
        {'t':'emp'},                 # 1
        {'t':'eq', 'p':autres[0]},  # 2  ─┐ M1
        {'t':'ts', 'p':ts58[0]},    # 3  ─┘
        {'t':'ts', 'p':ts58[1]},    # 4  ─┐ M2
        {'t':'eq', 'p':autres[1]},  # 5  ─┘
        {'t':'bye','p':ts34[0]},    # 6
        {'t':'emp'},                 # 7
        {'t':'bye','p':ts34[1]},    # 8
        {'t':'emp'},                 # 9
        {'t':'ts', 'p':ts58[2]},    # 10 ─┐ M3
        {'t':'eq', 'p':autres[2]},  # 11 ─┘
        {'t':'eq', 'p':autres[3]},  # 12 ─┐ M4
        {'t':'ts', 'p':ts58[3]},    # 13 ─┘
        {'t':'bye','p':ts1},        # 14
        {'t':'emp'},                 # 15
    ]
    return T, ts34, ts58

# ── Calcul horaires avec contraintes ─────
def calc_horaires(heure_debut, nb_pistes, duree_principal, duree_classement, contraintes=None, T=None):
    """
    Calcule les horaires en tenant compte :
    - de deux durées différentes (principal vs classement)
    - des contraintes horaires par paire
    """
    # Matchs principaux (tableau) vs classement
    matchs_principal   = {1,2,3,4,7,8,9,10,15,16,20}
    matchs_classement  = {5,6,11,12,13,14,17,18,19}

    def duree(num):
        return duree_principal if num in matchs_principal else duree_classement

    # Structure des vagues (2 matchs simultanés max)
    vagues = [
        [1,2],       # 1/8 vague 1
        [3,4],       # 1/8 vague 2
        [5,6],       # classement 9-12
        [7,8],       # QF vague 1
        [9,10],      # QF vague 2
        [11,12],     # classement suite
        [13,14],     # classement 5-8
        [15,16],     # SF
        [17,18],     # classements
        [19],        # 3/4
        [20],        # finale
    ]

    horaires = {}
    h_cur = heure_debut

    # Mapping match → paires impliquées (pour contraintes)
    match_paires = {}
    if T:
        match_paires[1] = [T[2]['p'], T[3]['p']]
        match_paires[2] = [T[4]['p'], T[5]['p']]
        match_paires[3] = [T[10]['p'], T[11]['p']]
        match_paires[4] = [T[12]['p'], T[13]['p']]

    for vague in vagues:
        # Calculer l'heure de début de cette vague
        # en tenant compte des contraintes des paires impliquées
        h_vague = hm_to_min(h_cur)

        if contraintes and T:
            for num in vague:
                if num in match_paires:
                    for p in match_paires[num]:
                        if str(p['id']) in contraintes:
                            c_min = hm_to_min(contraintes[str(p['id'])])
                            if c_min > h_vague:
                                h_vague = c_min

        h_vague_str = min_to_hm(h_vague)

        for i, num in enumerate(vague):
            piste = (i % nb_pistes) + 1
            horaires[num] = (h_vague_str, piste)

        # Avancer au prochain créneau
        dur_max = max(duree(n) for n in vague)
        nb_v = (len(vague) + nb_pistes - 1) // nb_pistes
        h_cur = min_to_hm(h_vague + nb_v * dur_max)

    return horaires

# ── Génération PDF tableau officiel FFT ──
def write_slot(c, x, y, nom, poids, ts, is_bye, max_x=128):
    if is_bye:
        c.setFont("Helvetica-Oblique", 7)
        c.setFillColorRGB(0.62, 0.62, 0.62)
        c.drawString(x+3, y+2, "BYE")
        c.setFillColorRGB(0, 0, 0)
        return
    nx = x + 3
    if ts and ts in TS_COLORS:
        rgb = TS_COLORS[ts]
        bw, bh = 24, 8
        c.setFillColorRGB(*rgb)
        c.roundRect(nx, y-4, bw, bh, 1.5, fill=1, stroke=0)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica-Bold", 5.5)
        c.drawCentredString(nx+bw/2, y+0.8, ts)
        c.setFillColorRGB(0, 0, 0)
        nx += bw + 3
    font = "Helvetica-Bold" if ts else "Helvetica"
    zw = max_x - nx - 28
    fs = 7.5
    c.setFont(font, fs)
    while c.stringWidth(nom, font, fs) > zw and fs > 5.5:
        fs -= 0.3
        c.setFont(font, fs)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(nx, y+2.2, nom)
    if poids:
        c.setFont("Helvetica", 5.5)
        c.setFillColorRGB(0.6, 0.6, 0.6)
        c.drawRightString(max_x-2, y+2.2, str(poids))
        c.setFillColorRGB(0, 0, 0)

def generer_pdf_tableau(T, qf_map, nom_tournoi, date_str, format_jeu):
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=(W_PDF, H_PDF))
    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    c.drawCentredString(W_PDF/2, H_PDF-79, f"{nom_tournoi}  ·  {date_str}  ·  {format_jeu}")
    c.setFillColorRGB(0, 0, 0)
    for i, s in enumerate(T):
        y = Y_1T[i]
        if s['t'] == 'emp': continue
        if s['t'] == 'bye':
            write_slot(c, 14, y, '', None, None, True, max_x=129)
        else:
            p = s['p']
            write_slot(c, 14, y, p['nc'], p['poids'], p['ts'], False, max_x=129)
    for qi, qd in qf_map.items():
        if not qd: continue
        y = Y_QF[int(qi)]
        write_slot(c, 132, y, qd['nom'], qd['poids'], qd['ts'], False, max_x=244)
    c.setFont("Helvetica-Oblique", 5.8)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawString(14, 112, "TS1,TS2,TS3,TS4 — BYE → QF  |  TS1 en bas / TS2 en haut (FFT p.40)")
    c.setFillColorRGB(0, 0, 0)
    c.save()
    packet.seek(0)
    template_bytes = base64.b64decode(PDF_VIERGE_B64)
    reader  = PdfReader(io.BytesIO(template_bytes))
    overlay = PdfReader(packet)
    writer  = PdfWriter()
    page    = reader.pages[0]
    page.merge_page(overlay.pages[0])
    writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()

# ── Génération PDF feuille de route ──────
# Fidèle au modèle Arena18 officiel
def generer_pdf_feuille(matchs, nom_tournoi, date_str, sponsor, format_jeu):
    W, H = A4
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=A4)

    # ── HEADER ──────────────────────────
    c.setFillColorRGB(1,1,1)
    c.rect(0, H-88, W, 88, fill=1, stroke=0)

    # Logo Arena18
    c.setFillColorRGB(0,0,0)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(18, H-28, "Arena18")
    c.setFont("Helvetica", 7)
    c.setFillColorRGB(0.5,0.5,0.5)
    c.drawString(18, H-38, "VOUS DE JOUER")

    # TOURNOI + P250 + by sponsor
    c.setFillColorRGB(0,0,0)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(W/2, H-18, "TOURNOI")
    c.setFont("Helvetica-Bold", 34)
    c.drawCentredString(W/2 - 20, H-52, "P250")
    c.setFont("Helvetica", 9)
    c.setFillColorRGB(0.3,0.3,0.3)
    c.drawString(W/2 + 22, H-42, "by")
    c.setFont("Helvetica-Bold", 11)
    c.setFillColorRGB(0,0,0)
    sp_parts = sponsor.upper().split()
    if len(sp_parts) >= 2:
        c.drawString(W/2 + 30, H-50, sp_parts[0])
        c.setFont("Helvetica", 8)
        c.drawString(W/2 + 30, H-60, ' '.join(sp_parts[1:]))
    else:
        c.drawString(W/2 + 30, H-52, sponsor.upper())

    # 12 équipes + format
    c.setFillColorRGB(0,0,0)
    c.setFont("Helvetica-Bold", 16)
    c.drawRightString(W-18, H-20, "12 équipes")
    c.setFont("Helvetica-Bold", 8)
    c.drawRightString(W-18, H-33, "Format D2:")
    fmt_lines = format_jeu.split(',')
    c.setFont("Helvetica", 7.5)
    for i, fl in enumerate(fmt_lines[:3]):
        c.drawRightString(W-18, H-43-i*9, fl.strip())

    # DATE
    c.setFont("Helvetica-Bold", 13)
    c.drawString(18, H-72, f"DATE :  {date_str.upper() if date_str else ''}")

    # Séparatrice
    c.setLineWidth(2)
    c.line(18, H-82, W-18, H-82)
    c.setLineWidth(0.5)

    # ── EN-TÊTES ────────────────────────
    y_hdr = H - 94
    c.setFillColorRGB(0,0,0)
    c.rect(18, y_hdr-2, W-36, 13, fill=1, stroke=0)
    c.setFillColorRGB(1,1,1)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(33, y_hdr+3, "MATCHS")
    c.drawCentredString(W/2 - 20, y_hdr+3, "NOM DES ÉQUIPES")
    c.setFont("Helvetica-Bold", 7)
    c.drawCentredString(W-112, y_hdr+3, "ORDRE")
    c.drawCentredString(W-112, y_hdr-2, "MATCHS")
    c.drawCentredString(W-48, y_hdr+3, "ORDRE A SUIVRE")
    c.setFillColorRGB(0,0,0)

    # ── LIGNES MATCHS ────────────────────
    y = y_hdr - 16
    row_h = 18.2
    BALLES = {1,2,7,8,15,16,20}

    for m in matchs:
        if y < 42: break
        num = m['num']

        # Fond
        if num == 20:
            c.setFillColorRGB(0,0,0)
        elif num % 2 == 0:
            c.setFillColorRGB(0.93,0.93,0.93)
        else:
            c.setFillColorRGB(1,1,1)
        c.rect(18, y-3, W-36, row_h, fill=1, stroke=0)

        # Bordure basse
        c.setStrokeColorRGB(0.75,0.75,0.75)
        c.line(18, y-3, W-18, y-3)
        c.setStrokeColorRGB(0,0,0)

        tc = (1,1,1) if num==20 else (0,0,0)
        c.setFillColorRGB(*tc)

        # Numéro
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(30, y+4, str(num))

        # Balle
        if num in BALLES:
            c.setFillColorRGB(0.76,0.68,0.0)
            c.circle(44, y+6, 5.5, fill=1, stroke=0)
            c.setFillColorRGB(1,1,1)
            c.setFont("Helvetica-Bold", 3.2)
            c.drawCentredString(44, y+7.5, "Balles")
            c.drawCentredString(44, y+4.5, "Neuves")
            c.setFillColorRGB(*tc)

        # Équipes
        x_eq = 52
        if num == 20:
            c.setFont("Helvetica-Bold", 14)
            c.setFillColorRGB(1,1,1)
            c.drawCentredString(W/2 - 35, y+4, "FINALE !")
        elif m.get('pA') and m.get('pB'):
            pa, pb = m['pA'], m['pB']
            ea = f"{pa['prenJ1']} {pa['nomJ1']} / {pa['prenJ2']} {pa['nomJ2']}"
            eb = f"{pb['prenJ1']} {pb['nomJ1']} / {pb['prenJ2']} {pb['nomJ2']}"
            c.setFont("Helvetica-Bold", 8)
            c.drawString(x_eq, y+9, ea[:58])
            c.setFont("Helvetica", 7); c.setFillColorRGB(0.4,0.4,0.4)
            c.drawString(x_eq, y+1, "VS")
            c.setFont("Helvetica-Bold", 8); c.setFillColorRGB(*tc)
            c.drawString(x_eq+11, y+1, eb[:58])
        elif m.get('pB') and m.get('libA'):
            pb = m['pB']
            ts_nom = f"{pb['prenJ1']} {pb['nomJ1']} / {pb['prenJ2']} {pb['nomJ2']} ({pb['ts']})"
            c.setFont("Helvetica-Bold", 8)
            c.drawString(x_eq, y+9, m['libA'])
            c.setFont("Helvetica", 7); c.setFillColorRGB(0.4,0.4,0.4)
            c.drawString(x_eq, y+1, "VS")
            c.setFont("Helvetica-Bold", 8)
            c.setFillColorRGB(0.75,0.1,0.1)
            c.drawString(x_eq+11, y+1, ts_nom[:60])
            c.setFillColorRGB(*tc)
        else:
            ea = m.get('libA','')
            eb = m.get('libB','')
            c.setFont("Helvetica-Bold", 8)
            if ea and eb:
                c.drawString(x_eq, y+4, f"{ea}   VS   {eb}")
            else:
                c.drawString(x_eq, y+4, ea or eb or '')

        c.setFillColorRGB(*tc)

        # Diagonale score
        if num != 20:
            c.setStrokeColorRGB(0.4,0.4,0.4)
            c.setLineWidth(0.7)
            xs = W - 150
            c.line(xs, y-2, xs+28, y+row_h-4)
            c.setLineWidth(0.5)
            c.setStrokeColorRGB(0,0,0)

        # Ordre match
        c.setFillColorRGB(*tc)
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(W-111, y+4, m['ordre'])

        # Terrain
        terrain = m.get('terrain_str','1ER TERRAIN\nQUI SE LIBÈRE')
        lignes_t = terrain.split('\n')
        num_match = m['num']
        if num_match <= 2:
            c.setFont("Helvetica-Bold", 7)
            c.setFillColorRGB(0,0.2,0.7) if num!=20 else None
        else:
            c.setFont("Helvetica", 7)
        if len(lignes_t) == 2:
            c.drawCentredString(W-46, y+8, lignes_t[0])
            c.drawCentredString(W-46, y+1, lignes_t[1])
        else:
            c.drawCentredString(W-46, y+4, terrain)
        c.setFillColorRGB(*tc)

        # Séparateurs verticaux
        c.setStrokeColorRGB(0.6,0.6,0.6)
        c.line(50, y-3, 50, y+row_h-3)
        c.line(W-131, y-3, W-131, y+row_h-3)
        c.line(W-79, y-3, W-79, y+row_h-3)
        c.setStrokeColorRGB(0,0,0)

        y -= row_h

    # Bordure extérieure
    c.setLineWidth(1.2)
    c.rect(18, y+row_h-3, W-36, y_hdr-2-(y+row_h-3)+16, fill=0, stroke=1)
    c.setLineWidth(0.5)

    # ── FOOTER ──────────────────────────
    yf = 16
    c.line(18, yf+18, W-18, yf+18)
    logos_f = ["CONVI GROUPE", "FFT PADEL", "TEN NIS", sponsor.upper(), "DÉCATHLON"]
    lw = (W-36) / len(logos_f)
    for i, logo in enumerate(logos_f):
        x_l = 18 + i*lw + lw/2
        c.setFillColorRGB(0,0,0)
        c.setFont("Helvetica-Bold", 7)
        c.drawCentredString(x_l, yf+7, logo)
        c.rect(18+i*lw+3, yf+2, lw-6, 13, fill=0, stroke=1)

    c.save()
    packet.seek(0)
    return packet.getvalue()



# ── Validation règlement FFT ─────────────
def valider_tournoi(paires, heure_debut, nb_pistes, duree_principal, duree_classement, format_jeu, contraintes, format_jeu_classement=None):
    alertes = []  # {'level': 'error'|'warning'|'info', 'message': str}

    # ── ERREURS BLOQUANTES (rouge) ────────
    # 1. Nombre de paires minimum
    if len(paires) < 4:
        alertes.append({'level':'error', 'message': f'❌ Minimum 4 paires requises pour homologation FFT (actuellement {len(paires)})'})

    # 2. Doublons de licence
    lm = {}
    for p in paires:
        for l in [p.get('licJ1',''), p.get('licJ2','')]:
            if not l: continue
            lu = l.lower()
            if lu in lm:
                alertes.append({'level':'error', 'message': f'❌ Doublon de licence détecté : {l} — un joueur ne peut pas être inscrit deux fois'})
            else:
                lm[lu] = True

    # 3. Format de jeu non homologué P250
    formats_autorises = ['A2','B2','C2','D2','E','F','D1','B1','A1','C1']
    fmt_upper = format_jeu.upper()
    format_ok = any(f in fmt_upper for f in formats_autorises)
    if not format_ok:
        alertes.append({'level':'error', 'message': f'Erreur format principal non reconnu : "{format_jeu}" — Formats autorises P250 : A2, B2, C2, D2, E, F'})
    
    # Format classement
    if format_jeu_classement and format_jeu_classement != format_jeu:
        fmt_cls_upper = format_jeu_classement.upper()
        format_cls_ok = any(f in fmt_cls_upper for f in formats_autorises)
        if not format_cls_ok:
            alertes.append({'level':'error', 'message': f'Erreur format classement non reconnu : "{format_jeu_classement}"'})
        # Info si formats différents
        else:
            alertes.append({'level':'info', 'message': f'Info : Format principal = {format_jeu[:30]} | Format classement = {format_jeu_classement[:30]}'})

    # 4. Contrainte horaire impossible
    if contraintes:
        h_debut_min = hm_to_min(heure_debut)
        for pid, heure_c in contraintes.items():
            hc_min = hm_to_min(heure_c)
            if hc_min < h_debut_min:
                p = next((p for p in paires if str(p['id'])==str(pid)), None)
                nom = p['nf'] if p else f'Paire #{pid}'
                alertes.append({'level':'warning', 'message': f'⚠️ Contrainte horaire incohérente : {nom} est disponible à {heure_c} mais le tournoi commence à {heure_debut}'})

    # ── AVERTISSEMENTS (jaune) ────────────
    # 5. Durée match trop courte
    if duree_principal < 30:
        alertes.append({'level':'warning', 'message': f'⚠️ Durée match principal très courte ({duree_principal} min) — risque de matchs non terminés'})
    if duree_classement < 20:
        alertes.append({'level':'warning', 'message': f'⚠️ Durée match classement très courte ({duree_classement} min)'})

    # 6. Estimation fin de tournoi tardive
    h_debut_min = hm_to_min(heure_debut)
    # TMC 12 équipes : environ 11 vagues de matchs
    nb_vagues = 11
    duree_totale = nb_vagues * max(duree_principal, duree_classement)
    h_fin_min = h_debut_min + duree_totale
    if h_fin_min > 23*60:
        h_fin_str = min_to_hm(h_fin_min)
        alertes.append({'level':'warning', 'message': f'⚠️ Fin de tournoi estimée après minuit ({h_fin_str}) — vérifiez les durées de match'})
    elif h_fin_min > 22*60:
        h_fin_str = min_to_hm(h_fin_min)
        alertes.append({'level':'warning', 'message': f'⚠️ Fin de tournoi estimée à {h_fin_str} — tournoi long, vérifiez la disponibilité des terrains'})

    # 7. Format conseillé pour classement
    if duree_classement >= 45 and duree_principal >= 45:
        alertes.append({'level':'warning', 'message': '⚠️ Pour gagner du temps, le guide FFT conseille le Format F (4 jeux NO-AD) pour les matchs de classement — durée ~20 min'})

    # 8. Nombre de paires impair
    if len(paires) % 2 != 0:
        alertes.append({'level':'warning', 'message': f'⚠️ Nombre de paires impair ({len(paires)}) — vérifiez les inscriptions'})

    # ── INFORMATIFS (bleu) ────────────────
    # 9. Balles neuves obligatoires
    alertes.append({'level':'info', 'message': f'ℹ️ Balles neuves obligatoires : matchs 1, 2, 7, 8, 15, 16, 20 — prévoir {7*3} balles minimum (3 par terrain par match)'})

    # 10. Minimum 3 matchs par paire
    alertes.append({'level':'info', 'message': 'ℹ️ Obligation FFT : 3 matchs minimum garantis par paire — respecté avec le format TMC 20 matchs ✅'})

    # 11. Rappel licences
    sans_licence = [p for p in paires if not p.get('licJ1') or not p.get('licJ2')]
    if sans_licence:
        noms = ', '.join([p['nf'] for p in sans_licence[:3]])
        alertes.append({'level':'warning', 'message': f'⚠️ Licence manquante pour : {noms} — vérifiez avant homologation'})

    # 12. Contrainte horaire vs statut BYE/1er tour
    if contraintes and len(paires) >= 8:
        h_debut_min = hm_to_min(heure_debut)
        
        # Calcul approximatif des horaires clés
        # 1/8 vague 1 : heure début
        # 1/8 vague 2 : heure début + duree_principal
        # QF vague 1  : heure début + 2 * duree_principal (après classement 9-12)
        # QF vague 2  : heure début + 3 * duree_principal
        h_18_v1 = h_debut_min
        h_18_v2 = h_debut_min + duree_principal
        h_qf_v1 = h_debut_min + duree_principal * 2 + duree_classement  # après 2 vagues 1/8 + classement
        h_qf_v2 = h_qf_v1 + duree_principal

        for pid, heure_c in contraintes.items():
            hc_min = hm_to_min(heure_c)
            p = next((pp for pp in paires if str(pp['id'])==str(pid)), None)
            if not p: continue
            
            idx = paires.index(p)  # position dans le classement (0 = meilleure)
            est_bye = idx < 4      # TS1-4 ont un BYE → entrent en QF
            est_18_v1 = idx >= 8   # les 4 dernières paires jouent en 1/8 vague 1 ou 2

            if est_bye:
                # Paire avec BYE → entre en QF
                # QF vague 1 (matchs 7,8) ou vague 2 (matchs 9,10)
                if hc_min > h_qf_v2:
                    alertes.append({
                        'level': 'error',
                        'message': f'❌ Contrainte impossible : {p["nf"]} ({p["ts"]}) entre en QF direct (BYE) '
                                   f'mais est disponible à {heure_c} — les QF se terminent vers {min_to_hm(h_qf_v2 + duree_principal)}. '
                                   f'Impossible de respecter le placement FFT obligatoire.'
                    })
                elif hc_min > h_qf_v1:
                    alertes.append({
                        'level': 'warning',
                        'message': f'⚠️ Attention : {p["nf"]} ({p["ts"]}) a un BYE et entre en QF direct. '
                                   f'Disponible à {heure_c} → sera placé en QF vague 2 (matchs 9 ou 10, ~{min_to_hm(h_qf_v1 + duree_principal)}). '
                                   f'Le tirage au sort en tiendra compte.'
                    })
                else:
                    alertes.append({
                        'level': 'info',
                        'message': f'ℹ️ {p["nf"]} ({p["ts"]}) — BYE, entre en QF. '
                                   f'Disponible à {heure_c}, compatible avec les QF (~{min_to_hm(h_qf_v1)}). ✅'
                    })
            else:
                # Paire sans BYE → joue un 1/8 de finale
                if hc_min > h_18_v2 + duree_principal:
                    alertes.append({
                        'level': 'error',
                        'message': f'❌ Contrainte impossible : {p["nf"]} doit jouer un 1/8 de finale '
                                   f'mais est disponible à {heure_c} — apres la fin des 1/8 (~{min_to_hm(h_18_v2 + duree_principal)}). '
                                   f'Envisager de retirer la paire ou de decaler heure debut du tournoi.'
                    })
                elif hc_min > h_18_v1 + duree_principal // 2:
                    alertes.append({
                        'level': 'warning',
                        'message': f'⚠️ {p["nf"]} disponible à {heure_c} → sera placé en 1/8 vague 2 '
                                   f'(matchs 3 ou 4, ~{min_to_hm(h_18_v2)}). Le tirage au sort en tiendra compte. ✅'
                    })
                else:
                    alertes.append({
                        'level': 'info',
                        'message': f'ℹ️ {p["nf"]} — 1/8 de finale. '
                                   f'Disponible à {heure_c}, compatible avec tous les 1/8. ✅'
                    })

    return alertes

# ── Routes Flask ─────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generer', methods=['POST'])
def generer():
    data = request.get_json()
    csv_text         = data['csv']
    heure_debut      = data.get('heureDebut', '09:00')
    nb_pistes        = int(data.get('nbPistes', 2))
    duree_principal  = int(data.get('dureeMatchPrincipal', 45))
    duree_classement = int(data.get('dureeMatchClassement', 45))
    nom_tournoi      = data.get('nomTournoi', 'P250 Double Messieurs Sénior')
    date_str         = data.get('dateStr', '')
    sponsor          = data.get('sponsor', 'CUPRA LANESTER')
    format_jeu            = data.get('formatJeu', 'D2 : 1 set 9 jeux, NO-AD')
    format_jeu_classement = data.get('formatJeuClassement', format_jeu)
    contraintes      = data.get('contraintes', {})  # {paire_id: 'HH:MM'}

    try:
        paires = parse_csv(csv_text)
    except Exception as e:
        return jsonify({'error': f'Erreur CSV : {str(e)}'}), 400

    if len(paires) < 4:
        return jsonify({'error': f'Minimum 4 paires requises, {len(paires)} trouvées'}), 400

    # Validation règlement FFT
    alertes = valider_tournoi(paires, heure_debut, nb_pistes, duree_principal, duree_classement, format_jeu, contraintes, format_jeu_classement)
    
    # Bloquer si erreurs critiques (sauf doublons qui sont dans les alertes)
    erreurs_bloquantes = [a for a in alertes if a['level']=='error' and 'Doublon' not in a['message'] and 'Minimum 4' not in a['message']]
    
    # Vérif doublons
    lm, doublons = {}, []
    for p in paires:
        for l in [p['licJ1'], p['licJ2']]:
            if not l: continue
            lu = l.lower()
            if lu in lm: doublons.append(l)
            else: lm[lu] = True

    T, ts34, ts58 = build_tableau(paires, contraintes)

    qf_map = {
        '0': {'nom':T[0]['p']['nc'],'poids':T[0]['p']['poids'],'ts':T[0]['p']['ts']},
        '3': {'nom':T[6]['p']['nc'],'poids':T[6]['p']['poids'],'ts':T[6]['p']['ts']},
        '4': {'nom':T[8]['p']['nc'],'poids':T[8]['p']['poids'],'ts':T[8]['p']['ts']},
        '7': {'nom':T[14]['p']['nc'],'poids':T[14]['p']['poids'],'ts':T[14]['p']['ts']},
    }

    horaires = calc_horaires(heure_debut, nb_pistes, duree_principal, duree_classement, contraintes, T)

    m1a,m1b = T[2]['p'],T[3]['p']
    m2a,m2b = T[4]['p'],T[5]['p']
    m3a,m3b = T[10]['p'],T[11]['p']
    m4a,m4b = T[12]['p'],T[13]['p']
    qf0,qf3,qf4,qf7 = T[0]['p'],T[6]['p'],T[8]['p'],T[14]['p']

    matchs = [
        {'num':1,  'ordre':'1/8',    'pA':m1a,'pB':m1b,  'terrain_str':'TERRAIN\nDÉCATHLON'},
        {'num':2,  'ordre':'1/8',    'pA':m2a,'pB':m2b,  'terrain_str':'TERRAIN\nCUPRA'},
        {'num':3,  'ordre':'1/8',    'pA':m3a,'pB':m3b,  'terrain_str':'1ER TERRAIN\nQUI SE LIBÈRE'},
        {'num':4,  'ordre':'1/8',    'pA':m4a,'pB':m4b,  'terrain_str':'2EME TERRAIN\nQUI SE LIBÈRE'},
        {'num':5,  'ordre':'9 à 12', 'libA':'PERDANT MATCH 1','libB':'PERDANT MATCH 2','terrain_str':'1ER TERRAIN\nQUI SE LIBÈRE'},
        {'num':6,  'ordre':'9 à 12', 'libA':'PERDANT MATCH 3','libB':'PERDANT MATCH 4','terrain_str':'2EME TERRAIN\nQUI SE LIBÈRE'},
        {'num':7,  'ordre':'1/4',    'libA':'GAGNANT MATCH 1','pB':qf0,'terrain_str':'1ER TERRAIN\nQUI SE LIBÈRE'},
        {'num':8,  'ordre':'1/4',    'libA':'GAGNANT MATCH 2','pB':qf3,'terrain_str':'2EME TERRAIN\nQUI SE LIBÈRE'},
        {'num':9,  'ordre':'1/4',    'libA':'GAGNANT MATCH 3','pB':qf4,'terrain_str':'1ER TERRAIN\nQUI SE LIBÈRE'},
        {'num':10, 'ordre':'1/4',    'libA':'GAGNANT MATCH 4','pB':qf7,'terrain_str':'2EME TERRAIN\nQUI SE LIBÈRE'},
        {'num':11, 'ordre':'11 à 12','libA':'PERDANT MATCH 5','libB':'PERDANT MATCH 6','terrain_str':'1ER TERRAIN\nQUI SE LIBÈRE'},
        {'num':12, 'ordre':'9 à 10', 'libA':'GAGNANT MATCH 5','libB':'GAGNANT MATCH 6','terrain_str':'2EME TERRAIN\nQUI SE LIBÈRE'},
        {'num':13, 'ordre':'5 à 8',  'libA':'PERDANT MATCH 7','libB':'PERDANT MATCH 8','terrain_str':'1ER TERRAIN\nQUI SE LIBÈRE'},
        {'num':14, 'ordre':'5 à 8',  'libA':'PERDANT MATCH 9','libB':'PERDANT MATCH 10','terrain_str':'2EME TERRAIN\nQUI SE LIBÈRE'},
        {'num':15, 'ordre':'1/2',    'libA':'GAGNANT MATCH 7','libB':'GAGNANT MATCH 8','terrain_str':'1ER TERRAIN\nQUI SE LIBÈRE'},
        {'num':16, 'ordre':'1/2',    'libA':'GAGNANT MATCH 9','libB':'GAGNANT MATCH 10','terrain_str':'2EME TERRAIN\nQUI SE LIBÈRE'},
        {'num':17, 'ordre':'7/8',    'libA':'PERDANT MATCH 13','libB':'PERDANT MATCH 14','terrain_str':'1ER TERRAIN\nQUI SE LIBÈRE'},
        {'num':18, 'ordre':'5/6',    'libA':'GAGNANT MATCH 13','libB':'GAGNANT MATCH 14','terrain_str':'2EME TERRAIN\nQUI SE LIBÈRE'},
        {'num':19, 'ordre':'3/4',    'libA':'PERDANT MATCH 15','libB':'PERDANT MATCH 16','terrain_str':'1ER TERRAIN\nQUI SE LIBÈRE'},
        {'num':20, 'ordre':'FINALE', 'libA':'GAGNANT MATCH 15','libB':'GAGNANT MATCH 16','terrain_str':'2EME TERRAIN\nQUI SE LIBÈRE'},
    ]

    for m in matchs:
        h_m, piste = horaires.get(m['num'], ('?', '?'))
        m['heure'] = h_m
        m['piste'] = piste

    # Messages WhatsApp
    paire_match = {}
    for num, (sa,sb) in {1:(2,3),2:(4,5),3:(10,11),4:(12,13)}.items():
        h_m, piste = horaires[num]
        pa, pb = T[sa]['p'], T[sb]['p']
        paire_match[pa['id']] = {'num':num,'h':h_m,'piste':piste,'adv':pb,'tour':'1/8 de finale'}
        paire_match[pb['id']] = {'num':num,'h':h_m,'piste':piste,'adv':pa,'tour':'1/8 de finale'}
    for slot_idx, qf_num in [(0,7),(6,8),(8,9),(14,10)]:
        p = T[slot_idx]['p']
        h_m, piste = horaires[qf_num]
        paire_match[p['id']] = {'num':qf_num,'h':h_m,'piste':piste,'adv':None,'tour':'Quart de finale','bye':True}

    messages = []
    for p in paires:
        pm = paire_match.get(p['id'], {})
        h_m    = pm.get('h','?')
        piste  = pm.get('piste','?')
        tour   = pm.get('tour','?')
        num_m  = pm.get('num','?')
        is_bye = pm.get('bye', False)
        adv    = pm.get('adv')
        h_conv = sub_min(h_m, 15) if h_m != '?' else '?'
        adv_str = f"{adv['prenJ1']} {adv['nomJ1']} / {adv['prenJ2']} {adv['nomJ2']}" if adv else ''

        contrainte_info = ''
        if str(p['id']) in contraintes:
            contrainte_info = f"\n⏳ Disponible à partir de {contraintes[str(p['id'])]}h"

        for j in [{'pr':p['prenJ1'],'nm':p['nomJ1'],'tel':p['telJ1']},
                  {'pr':p['prenJ2'],'nm':p['nomJ2'],'tel':p['telJ2']}]:
            msg = f"Bonjour {j['pr']} 👋\n\n📢 {nom_tournoi}\n📅 {date_str}\n🎯 Format : {format_jeu}\n━━━━━━━━━━━━━━\n👥 Votre paire :\n   {p['nf']}"
            if p['ts']: msg += f"\n⭐ {p['ts']}"
            if is_bye:  msg += "\n✅ Exempt du 1er tour (BYE)"
            if contrainte_info: msg += contrainte_info
            msg += f"\n\n⏰ Convocation : {h_conv}h\n🏸 1er match — {tour} (M{num_m})\n   Heure : {h_m}h · Terrain {piste}"
            if adv_str: msg += f"\n🆚 Adversaires : {adv_str}"
            msg += "\n━━━━━━━━━━━━━━\nBonne chance ! 🏆\n— Organisation Arena18"

            tel_c = j['tel'].replace(' ','').lstrip('0')
            tel_c = '33' + tel_c if tel_c and not tel_c.startswith('33') else tel_c
            messages.append({
                'prenom': j['pr'], 'nom': j['nm'],
                'tel': j['tel'], 'telClean': tel_c,
                'paire': p['nf'], 'ts': p['ts'],
                'msg': msg,
            })

    return jsonify({
        'paires':   paires,
        'tableau':  [[s['t'], s['p'] if s['t'] != 'emp' else None] for s in T],
        'matchs':   matchs,
        'messages': messages,
        'doublons': doublons,
        'qfMap':    qf_map,
        'alertes':  alertes,
        'formatJeuClassement': format_jeu_classement,
    })

@app.route('/pdf/tableau', methods=['POST'])
def pdf_tableau():
    data = request.get_json()
    T_raw = data['tableau']
    qf_map = data['qfMap']
    T = [{'t':t,'p':p} if p else {'t':t} for t,p in T_raw]
    pdf_bytes = generer_pdf_tableau(T, qf_map,
        data.get('nomTournoi','P250'),
        data.get('dateStr',''),
        data.get('formatJeu','9 jeux NO-AD'))
    return send_file(io.BytesIO(pdf_bytes), mimetype='application/pdf',
        as_attachment=True, download_name='tableau_p250.pdf')

@app.route('/pdf/feuille', methods=['POST'])
def pdf_feuille():
    data = request.get_json()
    pdf_bytes = generer_pdf_feuille(
        data['matchs'], data['nomTournoi'],
        data['dateStr'], data['sponsor'], data['formatJeu'])
    return send_file(io.BytesIO(pdf_bytes), mimetype='application/pdf',
        as_attachment=True, download_name='feuille_route.pdf')

@app.route('/sms/envoyer', methods=['POST'])
def envoyer_sms():
    data = request.get_json()
    messages    = data['messages']
    account_sid = data.get('twilioSid','')
    auth_token  = data.get('twilioToken','')
    from_number = data.get('twilioFrom','')
    if not all([account_sid, auth_token, from_number]):
        return jsonify({'error': 'Identifiants Twilio manquants'}), 400
    try:
        from twilio.rest import Client
        client = Client(account_sid, auth_token)
    except ImportError:
        return jsonify({'error': 'Module Twilio non installé'}), 500
    results = []
    for m in messages:
        tel = m.get('telClean','')
        if not tel or not tel.startswith('33'):
            results.append({'tel':m.get('tel',''),'status':'skipped','reason':'N° invalide'})
            continue
        try:
            msg = client.messages.create(body=m['msg'], from_=from_number, to=f'+{tel}')
            results.append({'tel':m.get('tel',''),'status':'sent','sid':msg.sid})
        except Exception as e:
            results.append({'tel':m.get('tel',''),'status':'error','reason':str(e)})
    sent = sum(1 for r in results if r['status']=='sent')
    return jsonify({'results':results,'sent':sent,'total':len(results)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
