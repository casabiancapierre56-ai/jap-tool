#!/usr/bin/env python3
"""
JAP Tool v3 — Application web Padel FFT
Arena18 — jap.myconvi.fr
"""
from flask import Flask, request, jsonify, render_template, send_file
import io, json, base64, random, os, sqlite3
from datetime import datetime
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors

app = Flask(__name__)

# ── SQLite ───────────────────────────────
DB_PATH = os.environ.get('TOURNOIS_DB', os.path.join(os.path.dirname(__file__), 'tournois.db'))

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS tournois (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                nom       TEXT NOT NULL,
                date_str  TEXT,
                nb_paires INTEGER,
                niveau    TEXT,
                data_json TEXT NOT NULL,
                cree_le   TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS sms_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                tournoi_nom TEXT NOT NULL,
                tournoi_id  INTEGER,
                date_envoi  TEXT NOT NULL,
                nb_envoyes  INTEGER,
                nb_total    INTEGER,
                details     TEXT NOT NULL
            )
        ''')
        conn.commit()

init_db()

# ── PDF vierge FFT ───────────────────────
PDF_B64_PATH = os.path.join(os.path.dirname(__file__), 'static', 'tableau16_b64.txt')
with open(PDF_B64_PATH) as f:
    PDF_VIERGE_B64 = f.read().strip()

FDR_B64_PATH = os.path.join(os.path.dirname(__file__), 'static', 'feuille_route_b64.txt')
FDR_VIERGE_B64 = None

def get_fdr_b64():
    global FDR_VIERGE_B64
    if FDR_VIERGE_B64 is None:
        try:
            with open(FDR_B64_PATH) as f:
                FDR_VIERGE_B64 = f.read().strip()
        except FileNotFoundError:
            return None
    return FDR_VIERGE_B64

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
    ts1, ts2   = paires[0], paires[1]
    ts34       = shuffle([paires[2], paires[3]])
    ts58       = shuffle([paires[4], paires[5], paires[6], paires[7]])
    autres     = shuffle(paires[8:])

    if contraintes:
        def get_contrainte(p):
            return hm_to_min(contraintes.get(str(p['id']), '00:00'))
        ts58  = sorted(ts58,  key=get_contrainte)
        autres = sorted(autres, key=get_contrainte)

    T = [
        {'t':'bye','p':ts2},
        {'t':'emp'},
        {'t':'eq', 'p':autres[0]},
        {'t':'ts', 'p':ts58[0]},
        {'t':'ts', 'p':ts58[1]},
        {'t':'eq', 'p':autres[1]},
        {'t':'bye','p':ts34[0]},
        {'t':'emp'},
        {'t':'bye','p':ts34[1]},
        {'t':'emp'},
        {'t':'ts', 'p':ts58[2]},
        {'t':'eq', 'p':autres[2]},
        {'t':'eq', 'p':autres[3]},
        {'t':'ts', 'p':ts58[3]},
        {'t':'bye','p':ts1},
        {'t':'emp'},
    ]
    return T, ts34, ts58

# ── Calcul horaires ──────────────────────
def calc_horaires(heure_debut, nb_pistes, duree_principal, duree_classement, contraintes=None, T=None):
    matchs_principal  = {1,2,3,4,7,8,9,10,15,16,20}
    matchs_classement = {5,6,11,12,13,14,17,18,19}

    def duree(num):
        return duree_principal if num in matchs_principal else duree_classement

    vagues = [
        [1,2],[3,4],[5,6],[7,8],[9,10],[11,12],
        [13,14],[15,16],[17,18],[19],[20],
    ]

    horaires = {}
    h_cur = heure_debut

    match_paires = {}
    if T:
        match_paires[1] = [T[2]['p'], T[3]['p']]
        match_paires[2] = [T[4]['p'], T[5]['p']]
        match_paires[3] = [T[10]['p'], T[11]['p']]
        match_paires[4] = [T[12]['p'], T[13]['p']]

    for vague in vagues:
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
FW, FH = 595.5, 842.25
MATCH_Y_FDR = {
    1: 719, 2: 690, 3: 661, 4: 632,
    5: 602.1, 6: 567.9, 7: 533.7, 8: 499.5,
    9: 465.3, 10: 431.2, 11: 397.0, 12: 362.8,
    13: 328.6, 14: 294.4, 15: 260.2, 16: 226.0,
    17: 191.8, 18: 157.7, 19: 123.5
}
X_EQ_START = 62
X_EQ_END   = 420

def generer_pdf_feuille(matchs, nom_tournoi, date_str, sponsor, format_jeu):
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=(FW, FH))
    c.setFont("Helvetica-Bold", 12)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(60, 781, date_str.upper() if date_str else '')
    c.setFont("Helvetica-Bold", 8)
    c.setFillColorRGB(0, 0, 0)
    c.drawCentredString(527, 714, "DECATHLON")
    c.drawCentredString(527, 685, "CUPRA")
    max_w = X_EQ_END - X_EQ_START - 8
    for m in matchs:
        num = m['num']
        y = MATCH_Y_FDR.get(num)
        if not y:
            continue
        fs = 8.5
        if num <= 4:
            if m.get('pA') and m.get('pB'):
                pa, pb = m['pA'], m['pB']
                ea = f"{pa['prenJ1']} {pa['nomJ1']} / {pa['prenJ2']} {pa['nomJ2']}"
                eb = f"{pb['prenJ1']} {pb['nomJ1']} / {pb['prenJ2']} {pb['nomJ2']}"
                texte = f"{ea}     {eb}"
                c.setFont("Helvetica-Bold", fs)
                while c.stringWidth(texte, "Helvetica-Bold", fs) > max_w and fs > 5.5:
                    fs -= 0.2
                c.setFillColorRGB(0, 0, 0)
                c.drawString(X_EQ_START, y, texte)
        elif num in (7, 8, 9, 10):
            if m.get('pB'):
                pb = m['pB']
                ts_str = f"{pb['prenJ1']} {pb['nomJ1']} / {pb['prenJ2']} {pb['nomJ2']} ({pb['ts']})"
                c.setFont("Helvetica-Bold", fs)
                while c.stringWidth(ts_str, "Helvetica-Bold", fs) > max_w and fs > 6:
                    fs -= 0.3
                c.setFillColorRGB(0.75, 0.1, 0.05)
                c.drawRightString(X_EQ_END, y - 7, ts_str)
                c.setFillColorRGB(0, 0, 0)
    c.save()
    packet.seek(0)
    fdr_b64 = get_fdr_b64()
    if not fdr_b64:
        raise FileNotFoundError("Modele feuille de route non trouve")
    template_bytes = base64.b64decode(fdr_b64)
    reader  = PdfReader(io.BytesIO(template_bytes))
    overlay = PdfReader(packet)
    writer  = PdfWriter()
    page    = reader.pages[0]
    page.merge_page(overlay.pages[0])
    writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()

# ── Validation règlement FFT ─────────────
def valider_tournoi(paires, heure_debut, nb_pistes, duree_principal, duree_classement, format_jeu, contraintes, format_jeu_classement=None):
    alertes = []
    if len(paires) < 4:
        alertes.append({'level':'error', 'message': f'Minimum 4 paires requises ({len(paires)} trouvees)'})
    lm = {}
    for p in paires:
        for l in [p.get('licJ1',''), p.get('licJ2','')]:
            if not l: continue
            lu = l.lower()
            if lu in lm:
                alertes.append({'level':'error', 'message': f'Doublon de licence : {l}'})
            else:
                lm[lu] = True
    formats_autorises = ['A1','A2','B1','B2','C1','C2','D1','D2','E','F']
    fmt_upper = format_jeu.upper()
    if not any(f in fmt_upper for f in formats_autorises):
        alertes.append({'level':'error', 'message': f'Format principal non reconnu : {format_jeu}'})
    if format_jeu_classement and format_jeu_classement != format_jeu:
        fmt_cls = format_jeu_classement.upper()
        if not any(f in fmt_cls for f in formats_autorises):
            alertes.append({'level':'error', 'message': f'Format classement non reconnu : {format_jeu_classement}'})
        else:
            alertes.append({'level':'info', 'message': f'Formats differents : Principal={format_jeu[:25]} | Classement={format_jeu_classement[:25]}'})
    if duree_principal < 30:
        alertes.append({'level':'warning', 'message': f'Duree match principal courte ({duree_principal} min)'})
    if duree_classement < 20:
        alertes.append({'level':'warning', 'message': f'Duree match classement courte ({duree_classement} min)'})
    h_debut_min = hm_to_min(heure_debut)
    duree_totale = 11 * max(duree_principal, duree_classement)
    h_fin_min = h_debut_min + duree_totale
    if h_fin_min > 23*60:
        alertes.append({'level':'warning', 'message': f'Fin de tournoi estimee apres minuit ({min_to_hm(h_fin_min)})'})
    elif h_fin_min > 22*60:
        alertes.append({'level':'warning', 'message': f'Fin de tournoi estimee a {min_to_hm(h_fin_min)}'})
    if duree_classement >= 45 and duree_principal >= 45:
        alertes.append({'level':'warning', 'message': 'Pour gagner du temps : Format F conseille pour les matchs de classement (~20 min)'})
    if len(paires) % 2 != 0:
        alertes.append({'level':'warning', 'message': f'Nombre de paires impair ({len(paires)})'})
    sans_lic = [p for p in paires if not p.get('licJ1') or not p.get('licJ2')]
    if sans_lic:
        noms = ', '.join([p['nf'] for p in sans_lic[:3]])
        alertes.append({'level':'warning', 'message': f'Licence manquante : {noms}'})
    alertes.append({'level':'info', 'message': f'Balles neuves : matchs 1,2,7,8,15,16,20 - prevoir {7*3} balles minimum'})
    alertes.append({'level':'info', 'message': '3 matchs minimum garantis par paire - respect FFT OK'})
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
    nom_tournoi      = data.get('nomTournoi', 'P250 Double Messieurs Senior')
    date_str         = data.get('dateStr', '')
    sponsor          = data.get('sponsor', 'CUPRA LANESTER')
    format_jeu            = data.get('formatJeu', 'D2 : 1 set 9 jeux, NO-AD')
    format_jeu_classement = data.get('formatJeuClassement', format_jeu)
    contraintes      = data.get('contraintes', {})

    try:
        paires = parse_csv(csv_text)
    except Exception as e:
        return jsonify({'error': f'Erreur CSV : {str(e)}'}), 400

    if len(paires) < 4:
        return jsonify({'error': f'Minimum 4 paires requises, {len(paires)} trouvees'}), 400

    alertes = valider_tournoi(paires, heure_debut, nb_pistes, duree_principal, duree_classement, format_jeu, contraintes, format_jeu_classement)

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
        {'num':1,  'ordre':'1/8',    'pA':m1a,'pB':m1b},
        {'num':2,  'ordre':'1/8',    'pA':m2a,'pB':m2b},
        {'num':3,  'ordre':'1/8',    'pA':m3a,'pB':m3b},
        {'num':4,  'ordre':'1/8',    'pA':m4a,'pB':m4b},
        {'num':5,  'ordre':'9 a 12', 'libA':'PERDANT MATCH 1','libB':'PERDANT MATCH 2'},
        {'num':6,  'ordre':'9 a 12', 'libA':'PERDANT MATCH 3','libB':'PERDANT MATCH 4'},
        {'num':7,  'ordre':'1/4',    'libA':'GAGNANT MATCH 1','pB':qf0},
        {'num':8,  'ordre':'1/4',    'libA':'GAGNANT MATCH 2','pB':qf3},
        {'num':9,  'ordre':'1/4',    'libA':'GAGNANT MATCH 3','pB':qf4},
        {'num':10, 'ordre':'1/4',    'libA':'GAGNANT MATCH 4','pB':qf7},
        {'num':11, 'ordre':'11 a 12','libA':'PERDANT MATCH 5','libB':'PERDANT MATCH 6'},
        {'num':12, 'ordre':'9 a 10', 'libA':'GAGNANT MATCH 5','libB':'GAGNANT MATCH 6'},
        {'num':13, 'ordre':'5 a 8',  'libA':'PERDANT MATCH 7','libB':'PERDANT MATCH 8'},
        {'num':14, 'ordre':'5 a 8',  'libA':'PERDANT MATCH 9','libB':'PERDANT MATCH 10'},
        {'num':15, 'ordre':'1/2',    'libA':'GAGNANT MATCH 7','libB':'GAGNANT MATCH 8'},
        {'num':16, 'ordre':'1/2',    'libA':'GAGNANT MATCH 9','libB':'GAGNANT MATCH 10'},
        {'num':17, 'ordre':'7/8',    'libA':'PERDANT MATCH 13','libB':'PERDANT MATCH 14'},
        {'num':18, 'ordre':'5/6',    'libA':'GAGNANT MATCH 13','libB':'GAGNANT MATCH 14'},
        {'num':19, 'ordre':'3/4',    'libA':'PERDANT MATCH 15','libB':'PERDANT MATCH 16'},
        {'num':20, 'ordre':'FINALE', 'libA':'GAGNANT MATCH 15','libB':'GAGNANT MATCH 16'},
    ]

    for m in matchs:
        h_m, piste = horaires.get(m['num'], ('?', '?'))
        m['heure'] = h_m
        m['piste'] = piste

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

        for j in [{'pr':p['prenJ1'],'nm':p['nomJ1'],'tel':p['telJ1']},
                  {'pr':p['prenJ2'],'nm':p['nomJ2'],'tel':p['telJ2']}]:

            if is_bye:
                entree = "🔥 Entrée en lice directement en Quart de Finale"
            else:
                entree = f"🔥 Entrée en lice en {tour}"

            ts_line = ''
            if p['ts']: ts_line += f"\n⭐ {p['ts']}"
            if is_bye:  ts_line += " ✅ Exempt du 1er tour"

            adv_line = ''
            if adv_str: adv_line = f"\n🆚 Adversaires : {adv_str}"

            if str(p['id']) in contraintes:
                contrainte_info = f"\n⏳ Disponible à partir de {contraintes[str(p['id'])]}h"
            else:
                contrainte_info = ''

            # Liste des paires du tournoi
            liste_paires_lines = []
            for idx_p, pp in enumerate(paires):
                ts_tag = f" ({pp['ts']})" if pp['ts'] else ""
                liste_paires_lines.append(f"{idx_p+1}. {pp['prenJ1']} {pp['nomJ1']} / {pp['prenJ2']} {pp['nomJ2']}{ts_tag}")
            liste_paires_str = "\n".join(liste_paires_lines)

            # Format jeu lisible
            fmt_parts = format_jeu.split(':',1)
            fmt_display = fmt_parts[1].strip() if len(fmt_parts)>1 else format_jeu

            # Ligne TS / BYE
            if p['ts']:
                ts_num = int(p['ts'].replace('TS',''))
                ts_label = f"Tête de série n°{ts_num}"
                if is_bye:
                    ts_label += " — Exempt du 1er tour"
            else:
                ts_label = ''

            # Ligne match
            if is_bye:
                match_line = f"Entrée en compétition directement en quart de finale."
            else:
                match_line = f"Entrée en compétition en {tour}."

            msg = (
                f"ARENA18 – TOURNOI\n"
                f"Votre tournoi commence ici.\n\n"
                f"Bonjour {j['pr']},\n\n"
                f"{nom_tournoi} 📅 {date_str}\n"
                f"Format {fmt_display}\n"
                f"━━━━━━━━━━━━━━\n"
                f"Votre paire : {p['nf']}\n"
                + (f"{ts_label}\n" if ts_label else "")
                + (f"⏳ Disponible à partir de {contraintes[str(p['id'])]}h\n" if str(p['id']) in contraintes else "")
                + f"━━━━━━━━━━━━━━\n"
                f"Convocation : {h_conv}h\n"
                f"Afin d'optimiser le lancement des matchs et le bon déroulement du tournoi, les joueurs sont convoqués 15 minutes avant leur heure d'entrée en piste.\n"
                f"Un temps d'échauffement de 5 minutes est recommandé avant le début de la rencontre.\n"
                f"{match_line}\n"
                f"Match M{num_m} 🕗 Début prévu : {h_m}h 📍 Terrain {piste}"
                + (f"\n🆚 Adversaires : {adv_str}" if adv_str else "")
                + f"\n━━━━━━━━━━━━━━\n"
                f"🎾 Les {len(paires)} paires du tournoi :\n"
                f"{liste_paires_str}\n"
                f"━━━━━━━━━━━━━━\n"
                f"Toute l'équipe d'ARENA18 vous souhaite un excellent tournoi.\n"
                f"ARENA18 PADEL CLUB — PLAY HARD. ENJOY MORE."
            )

            tel_raw = j['tel'].replace(' ','').replace('.','').replace('-','')
            if tel_raw.startswith('+33'):
                tel_c = tel_raw[1:]
            elif tel_raw.startswith('0033'):
                tel_c = tel_raw[2:]
            elif tel_raw.startswith('33') and len(tel_raw) == 11:
                tel_c = tel_raw
            elif tel_raw.startswith('0') and len(tel_raw) == 10:
                tel_c = '33' + tel_raw[1:]
            elif len(tel_raw) == 9 and not tel_raw.startswith('33'):
                tel_c = '33' + tel_raw
            else:
                tel_c = tel_raw
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

# ══════════════════════════════════════════
# ROUTES TOURNOIS (SQLite)
# ══════════════════════════════════════════

@app.route('/tournoi/sauvegarder', methods=['POST'])
def sauvegarder_tournoi():
    """Sauvegarde ou met à jour un tournoi en base SQLite.
    Si tournoiId est fourni, met à jour l'entrée existante."""
    data = request.get_json()
    nom        = data.get('nom', 'Tournoi sans nom')
    date_str   = data.get('dateStr', '')
    nb_paires  = data.get('nbPaires', 0)
    niveau     = data.get('niveau', '')
    gen_data   = data.get('genData', {})
    params     = data.get('params', {})
    tournoi_id = data.get('tournoiId')  # None = nouveau, int = mise à jour

    payload = json.dumps({
        'genData': gen_data,
        'params':  params,
    }, ensure_ascii=False)

    now = datetime.now().strftime('%d/%m/%Y %H:%M')

    with get_db() as conn:
        if tournoi_id:
            # Mise à jour tournoi existant par ID
            conn.execute(
                'UPDATE tournois SET nom=?, date_str=?, nb_paires=?, niveau=?, data_json=?, cree_le=? WHERE id=?',
                (nom, date_str, nb_paires, niveau, payload, now, tournoi_id)
            )
            conn.commit()
            msg = f'Tournoi #{tournoi_id} mis à jour'
        else:
            # Vérifier doublon par nom + date
            existing = conn.execute(
                'SELECT id FROM tournois WHERE nom=? AND date_str=? ORDER BY id DESC LIMIT 1',
                (nom, date_str)
            ).fetchone()
            if existing:
                # Mettre à jour le tournoi existant
                tournoi_id = existing['id']
                conn.execute(
                    'UPDATE tournois SET nb_paires=?, niveau=?, data_json=?, cree_le=? WHERE id=?',
                    (nb_paires, niveau, payload, now, tournoi_id)
                )
                conn.commit()
                msg = f'Tournoi #{tournoi_id} mis à jour (même nom/date)'
            else:
                # Nouveau tournoi
                cur = conn.execute(
                    'INSERT INTO tournois (nom, date_str, nb_paires, niveau, data_json, cree_le) VALUES (?,?,?,?,?,?)',
                    (nom, date_str, nb_paires, niveau, payload, now)
                )
                conn.commit()
                tournoi_id = cur.lastrowid
                msg = f'Tournoi #{tournoi_id} sauvegardé'

    return jsonify({'ok': True, 'id': tournoi_id, 'message': msg})


@app.route('/tournoi/liste', methods=['GET'])
def liste_tournois():
    """Retourne la liste de tous les tournois sauvegardés (sans le JSON complet)."""
    with get_db() as conn:
        rows = conn.execute(
            'SELECT id, nom, date_str, nb_paires, niveau, cree_le FROM tournois ORDER BY id DESC'
        ).fetchall()

    tournois = [dict(r) for r in rows]
    return jsonify(tournois)


@app.route('/tournoi/charger/<int:tid>', methods=['GET'])
def charger_tournoi(tid):
    """Retourne un tournoi complet par son ID."""
    with get_db() as conn:
        row = conn.execute('SELECT * FROM tournois WHERE id=?', (tid,)).fetchone()

    if not row:
        return jsonify({'error': 'Tournoi introuvable'}), 404

    t = dict(row)
    t['data'] = json.loads(t['data_json'])
    del t['data_json']
    return jsonify(t)


@app.route('/tournoi/supprimer/<int:tid>', methods=['DELETE'])
def supprimer_tournoi(tid):
    """Supprime un tournoi de la base."""
    with get_db() as conn:
        conn.execute('DELETE FROM tournois WHERE id=?', (tid,))
        conn.commit()
    return jsonify({'ok': True})


# ══════════════════════════════════════════
# ROUTES SMS / PDF (inchangées)
# ══════════════════════════════════════════


@app.route('/tournoi/modifier', methods=['POST'])
def modifier_tournoi():
    """Modifie un tournoi en minimisant les changements.
    Compare les horaires AVANT et APRES pour ne lister que les paires
    dont la convocation change réellement."""
    data = request.get_json()
    paires_actuelles = data['paires']
    action           = data['action']
    nouvelle_paire   = data.get('nouvellePaire')
    forfait_id       = data.get('forfaitId')
    # Params horaires pour calcul avant/après
    heure_debut      = data.get('heureDebut', '09:00')
    nb_pistes        = int(data.get('nbPistes', 2))
    duree_principal  = int(data.get('dureeMatchPrincipal', 45))
    duree_classement = int(data.get('dureeMatchClassement', 45))

    def calc_hconv_paires(paires):
        """Calcule l'heure de convocation de chaque paire (heure match - 15min)."""
        if len(paires) < 8:
            return {}
        try:
            T, _, _ = build_tableau(paires)
            horaires = calc_horaires(heure_debut, nb_pistes, duree_principal, duree_classement, {}, T)
            result = {}
            # Matchs 1/8
            for num, (sa, sb) in {1:(2,3), 2:(4,5), 3:(10,11), 4:(12,13)}.items():
                h_m, _ = horaires[num]
                result[T[sa]['p']['nf']] = sub_min(h_m, 15)
                result[T[sb]['p']['nf']] = sub_min(h_m, 15)
            # BYE → QF
            for slot_idx, qf_num in [(0,7),(6,8),(8,9),(14,10)]:
                p = T[slot_idx]['p']
                h_m, _ = horaires[qf_num]
                result[p['nf']] = sub_min(h_m, 15)
        except Exception:
            result = {}
        return result

    # Horaires AVANT
    hconv_avant = calc_hconv_paires(paires_actuelles)

    # Snapshot avant
    avant = {}
    for p in paires_actuelles:
        avant[p['nf']] = {
            'ts': p.get('ts'), 'poids': p['poids'],
            'nf': p['nf'], 'id': p['id'],
            'bye': p.get('ts') and int(p['ts'].replace('TS','')) <= 4,
        }

    nouvelles_paires = [p.copy() for p in paires_actuelles]

    if action == 'ajout' and nouvelle_paire:
        nv = nouvelle_paire
        nv['nc'] = nv['nomJ1'].upper() + ' / ' + nv['nomJ2'].upper()
        nv['nf'] = nv['prenJ1'] + ' ' + nv['nomJ1'] + ' / ' + nv['prenJ2'] + ' ' + nv['nomJ2']
        nouvelles_paires.append(nv)

    elif action == 'forfait' and forfait_id is not None:
        nouvelles_paires = [p for p in nouvelles_paires if p['id'] != forfait_id]
        remplacante = data.get('remplacante')
        if remplacante:
            remplacante['nc'] = remplacante['nomJ1'].upper() + ' / ' + remplacante['nomJ2'].upper()
            remplacante['nf'] = remplacante['prenJ1'] + ' ' + remplacante['nomJ1'] + ' / ' + remplacante['prenJ2'] + ' ' + remplacante['nomJ2']
            nouvelles_paires.append(remplacante)

    # Retrier et recalculer TS
    nouvelles_paires.sort(key=lambda p: p['poids'])
    for i, p in enumerate(nouvelles_paires):
        p['id']  = i + 1
        p['ts']  = 'TS' + str(i+1) if i < 8 else None
        p['nc']  = p['nomJ1'].upper() + ' / ' + p['nomJ2'].upper()
        p['nf']  = p['prenJ1'] + ' ' + p['nomJ1'] + ' / ' + p['prenJ2'] + ' ' + p['nomJ2']

    # Horaires APRÈS
    hconv_apres = calc_hconv_paires(nouvelles_paires)

    # Détecter paires impactées — uniquement si heure convocation change
    paires_impactees = []
    for p in nouvelles_paires:
        ancien = avant.get(p['nf'])
        h_av   = hconv_avant.get(p['nf'], '?')
        h_ap   = hconv_apres.get(p['nf'], '?')
        ancien_bye = ancien and ancien.get('bye', False)
        nouveau_bye = p['ts'] and int(p['ts'].replace('TS','')) <= 4

        if ancien is None:
            # Nouvelle paire
            paires_impactees.append({
                'paire': p, 'raison': 'nouvelle',
                'ancien_ts': None, 'nouveau_ts': p['ts'],
                'hconv_avant': None, 'hconv_apres': h_ap,
            })
        elif ancien_bye and not nouveau_bye:
            # Perd le BYE — toujours impactée même si heure identique
            paires_impactees.append({
                'paire': p, 'raison': 'perd_bye',
                'ancien_ts': ancien['ts'], 'nouveau_ts': p['ts'],
                'hconv_avant': h_av, 'hconv_apres': h_ap,
            })
        elif not ancien_bye and nouveau_bye:
            # Gagne un BYE
            paires_impactees.append({
                'paire': p, 'raison': 'gagne_bye',
                'ancien_ts': ancien['ts'], 'nouveau_ts': p['ts'],
                'hconv_avant': h_av, 'hconv_apres': h_ap,
            })
        elif h_av != h_ap and h_av != '?' and h_ap != '?':
            # Heure de convocation change
            paires_impactees.append({
                'paire': p, 'raison': 'heure_change',
                'ancien_ts': ancien['ts'], 'nouveau_ts': p['ts'],
                'hconv_avant': h_av, 'hconv_apres': h_ap,
            })

    # Paire forfait sortante
    if action == 'forfait' and forfait_id is not None:
        paire_sortie = next((p for p in paires_actuelles if p['id'] == forfait_id), None)
        if paire_sortie:
            paires_impactees.append({
                'paire': paire_sortie, 'raison': 'forfait',
                'ancien_ts': paire_sortie.get('ts'), 'nouveau_ts': None,
                'hconv_avant': hconv_avant.get(paire_sortie['nf']), 'hconv_apres': None,
            })

    # CSV synthetique
    csv_lines = ['Epreuve;Equipe;Num;Nom J1;Prenom J1;Age J1;Lic J1;Clt J1;Nat J1;Ent J1;Tel J1;Nom J2;Prenom J2;Age J2;Lic J2;Clt J2;Nat J2;Ent J2;Tel J2;Poids']
    for i, p in enumerate(nouvelles_paires):
        tel1 = p.get('telJ1','').strip()
        tel2 = p.get('telJ2','').strip()
        csv_lines.append(f";P{i+1};;{p['nomJ1']};{p['prenJ1']};;{p.get('licJ1','')};;;;{tel1};{p['nomJ2']};{p['prenJ2']};;{p.get('licJ2','')};;;;{tel2};{p['poids']}")

    return jsonify({
        'ok': True,
        'nouvellesPaires': nouvelles_paires,
        'pairesImpactees': paires_impactees,
        'csvSynthetique':  '\n'.join(csv_lines),
        'nbImpactees':     len(paires_impactees),
    })


@app.route('/sms/historique/sauvegarder', methods=['POST'])
def sauvegarder_historique_sms():
    """Sauvegarde un envoi SMS en base."""
    data = request.get_json()
    tournoi_nom = data.get('tournoiNom', 'Tournoi inconnu')
    tournoi_id  = data.get('tournoiId')
    nb_envoyes  = data.get('nbEnvoyes', 0)
    nb_total    = data.get('nbTotal', 0)
    details     = json.dumps(data.get('details', []), ensure_ascii=False)
    date_envoi  = datetime.now().strftime('%d/%m/%Y %H:%M')

    with get_db() as conn:
        conn.execute(
            'INSERT INTO sms_history (tournoi_nom, tournoi_id, date_envoi, nb_envoyes, nb_total, details) VALUES (?,?,?,?,?,?)',
            (tournoi_nom, tournoi_id, date_envoi, nb_envoyes, nb_total, details)
        )
        conn.commit()

    return jsonify({'ok': True})


@app.route('/sms/historique/liste', methods=['GET'])
def liste_historique_sms():
    """Retourne l'historique des envois SMS."""
    with get_db() as conn:
        rows = conn.execute(
            'SELECT id, tournoi_nom, tournoi_id, date_envoi, nb_envoyes, nb_total FROM sms_history ORDER BY id DESC LIMIT 100'
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/sms/historique/detail/<int:hid>', methods=['GET'])
def detail_historique_sms(hid):
    """Retourne le détail d'un envoi SMS."""
    with get_db() as conn:
        row = conn.execute('SELECT * FROM sms_history WHERE id=?', (hid,)).fetchone()
    if not row:
        return jsonify({'error': 'Introuvable'}), 404
    r = dict(row)
    r['details'] = json.loads(r['details'])
    return jsonify(r)


@app.route('/sms/historique/supprimer/<int:hid>', methods=['DELETE'])
def supprimer_historique_sms(hid):
    """Supprime une entrée de l'historique."""
    with get_db() as conn:
        conn.execute('DELETE FROM sms_history WHERE id=?', (hid,))
        conn.commit()
    return jsonify({'ok': True})


@app.route('/pdf/accueil', methods=['POST'])
def pdf_accueil():
    """Génère la feuille d'accueil caisse A4 portrait."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Données manquantes'}), 400

        messages  = data.get('messages', [])
        nom_tournoi = data.get('nomTournoi', '')
        date_str    = data.get('dateStr', '')
        nb_pistes   = data.get('nbPistes', 2)

        # Construire liste joueurs dédupliquée par paire, triée par heure convocation
        paires_vues = {}
        for m in messages:
            key = m.get('paire','')
            if key and key not in paires_vues:
                paires_vues[key] = m

        def hconv_to_min(h):
            try:
                parts = h.replace('h','').split(':')
                return int(parts[0])*60 + int(parts[1]) if len(parts)==2 else 0
            except:
                return 0

        joueurs = []
        for m in messages:
            # Extraire infos depuis le message
            msg = m.get('msg','')
            hconv_m = re.search(r"Convocation\s*:\s*(\d{2}:\d{2})h", msg)
            hmatch_m = re.search(r"D.but pr.vu\s*:\s*(\d{2}:\d{2})h", msg)
            terrain_m = re.search(r"Terrain\s*(\d+)", msg)
            match_m = re.search(r"Match\s*M(\d+)", msg)
            adv_m = re.search(r"Adversaires\s*:\s*(.+)", msg)
            bye_m = 'Exempt du 1er tour' in msg or 'quart de finale' in msg.lower()

            hconv   = hconv_m.group(1) if hconv_m else '?'
            hmatch  = hmatch_m.group(1) if hmatch_m else '?'
            terrain = terrain_m.group(1) if terrain_m else '?'
            num_match = match_m.group(1) if match_m else '?'
            adversaire = adv_m.group(1).strip() if adv_m else ('BYE → Quart de finale' if bye_m else '—')

            joueurs.append({
                'prenom': m.get('prenom',''),
                'nom':    m.get('nom','').upper(),
                'paire':  m.get('paire',''),
                'ts':     m.get('ts',''),
                'hconv':  hconv,
                'hmatch': hmatch,
                'terrain':terrain,
                'match':  num_match,
                'adv':    adversaire,
                'bye':    bye_m,
                'hconv_min': hconv_to_min(hconv),
            })

        joueurs.sort(key=lambda j: (j['hconv_min'], j['nom']))

        # Générer le PDF
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4,
            leftMargin=15*mm, rightMargin=15*mm,
            topMargin=15*mm, bottomMargin=15*mm)

        styles = getSampleStyleSheet()
        or_color = colors.HexColor('#E8500A')
        dk_color = colors.HexColor('#1A1A1A')

        story = []

        # En-tête
        title_style = ParagraphStyle('title', fontSize=16, fontName='Helvetica-Bold',
            textColor=or_color, alignment=TA_CENTER, spaceAfter=4)
        sub_style = ParagraphStyle('sub', fontSize=10, fontName='Helvetica',
            textColor=colors.HexColor('#555555'), alignment=TA_CENTER, spaceAfter=2)
        info_style = ParagraphStyle('info', fontSize=9, fontName='Helvetica',
            textColor=colors.HexColor('#333333'), alignment=TA_CENTER, spaceAfter=8)

        story.append(Paragraph('ARENA18 PADEL CLUB', title_style))
        story.append(Paragraph(nom_tournoi, sub_style))
        story.append(Paragraph(f'{date_str}  ·  {len(joueurs)} joueurs  ·  {nb_pistes} piste(s)', info_style))

        # Ligne séparatrice
        from reportlab.platypus import HRFlowable
        story.append(HRFlowable(width='100%', thickness=2, color=or_color, spaceAfter=8))

        # Tableau
        col_w = [42*mm, 22*mm, 20*mm, 22*mm, 47*mm, 17*mm]  # Joueur, Convoc, Match, Terrain, Adversaire, Payé

        header = ['JOUEUR', 'CONVOC.', 'MATCH', 'TERRAIN', 'ADVERSAIRE', 'PAYÉ ☐']
        rows = [header]

        for j in joueurs:
            nom_aff = f"{j['prenom']} {j['nom']}"
            if j['ts']:
                nom_aff += f"  ({j['ts']})"
            terrain_aff = f"T.{j['terrain']}" if j['terrain'] != '?' else '?'
            match_aff = f"M{j['match']}" if j['match'] != '?' else '?'
            rows.append([
                nom_aff,
                j['hconv'] + 'h',
                match_aff,
                terrain_aff,
                j['adv'],
                '☐',
            ])

        t = Table(rows, colWidths=col_w, repeatRows=1)
        t.setStyle(TableStyle([
            # Header
            ('BACKGROUND', (0,0), (-1,0), or_color),
            ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
            ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE',   (0,0), (-1,0), 8),
            ('ALIGN',      (0,0), (-1,0), 'CENTER'),
            ('BOTTOMPADDING', (0,0), (-1,0), 6),
            ('TOPPADDING',    (0,0), (-1,0), 6),
            # Data
            ('FONTNAME',   (0,1), (-1,-1), 'Helvetica'),
            ('FONTSIZE',   (0,1), (-1,-1), 8),
            ('ALIGN',      (1,1), (3,-1), 'CENTER'),
            ('ALIGN',      (0,1), (0,-1), 'LEFT'),
            ('ALIGN',      (4,1), (4,-1), 'LEFT'),
            ('ALIGN',      (5,0), (5,-1), 'CENTER'),
            ('FONTSIZE',   (5,1), (5,-1), 12),
            ('TOPPADDING',    (0,1), (-1,-1), 5),
            ('BOTTOMPADDING', (0,1), (-1,-1), 5),
            # Alternance lignes
            *[('BACKGROUND', (0,i), (-1,i), colors.HexColor('#F8F5F2') if i%2==0 else colors.white)
              for i in range(1, len(rows))],
            # Grille
            ('GRID',    (0,0), (-1,-1), 0.5, colors.HexColor('#CCCCCC')),
            ('LINEBELOW', (0,0), (-1,0), 1.5, or_color),
        ]))
        story.append(t)

        story.append(Spacer(1, 8*mm))

        # Pied de page
        footer_style = ParagraphStyle('footer', fontSize=7, fontName='Helvetica',
            textColor=colors.HexColor('#999999'), alignment=TA_CENTER)
        story.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#CCCCCC'), spaceAfter=4))
        story.append(Paragraph('ARENA18 PADEL CLUB  ·  PLAY HARD. ENJOY MORE.  ·  Document généré par JAP Tool', footer_style))

        doc.build(story)
        buf.seek(0)

        nom_fichier = f"accueil_{nom_tournoi[:20].replace(' ','_')}.pdf"
        return send_file(io.BytesIO(buf.read()), mimetype='application/pdf',
            as_attachment=True, download_name=nom_fichier)

    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'detail': traceback.format_exc()}), 500

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
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Donnees JSON manquantes'}), 400
        pdf_bytes = generer_pdf_feuille(
            data['matchs'], data.get('nomTournoi',''),
            data.get('dateStr',''), data.get('sponsor',''), data.get('formatJeu',''))
        return send_file(io.BytesIO(pdf_bytes), mimetype='application/pdf',
            as_attachment=True, download_name='feuille_route.pdf')
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'detail': traceback.format_exc()}), 500

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
        return jsonify({'error': 'Module Twilio non installe'}), 500
    results = []
    for m in messages:
        tel = m.get('telClean','')
        if not tel or not tel.startswith('33'):
            results.append({'tel':m.get('tel',''),'status':'skipped','reason':'N invalide'})
            continue
        try:
            msg = client.messages.create(body=m['msg'], from_=from_number, to=f'+{tel}')
            results.append({'tel':m.get('tel',''),'status':'sent','sid':msg.sid})
        except Exception as e:
            results.append({'tel':m.get('tel',''),'status':'error','reason':str(e)})
    sent = sum(1 for r in results if r['status']=='sent')
    return jsonify({'results':results,'sent':sent,'total':len(results)})

@app.route('/sms/reponse', methods=['GET', 'POST'])
def sms_reponse():
    from twilio.twiml.messaging_response import MessagingResponse
    from twilio.rest import Client
    import os
    expediteur = request.form.get('From', '')
    message    = request.form.get('Body', '')
    REDIRECT_TO = '+33685603907'
    account_sid = os.environ.get('TWILIO_SID', '')
    auth_token  = os.environ.get('TWILIO_TOKEN', '')
    from_number = '+33939247914'
    if auth_token:
        try:
            client = Client(account_sid, auth_token)
            corps = f"📱 Réponse de {expediteur}:\n\n{message}"
            client.messages.create(body=corps, from_=from_number, to=REDIRECT_TO)
        except Exception as e:
            print(f"Erreur redirection SMS: {e}")
    resp = MessagingResponse()
    return str(resp)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
