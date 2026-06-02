#!/usr/bin/env python3
"""
JAP Tool — Application web Padel FFT
Auteur : Arena18
Déployé sur : jap.myconvi.fr
"""
from flask import Flask, request, jsonify, render_template, send_file
import io, json, base64, random, os
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

app = Flask(__name__)

# ── PDF vierge FFT ───────────────────────
PDF_B64_PATH = os.path.join(os.path.dirname(__file__), 'static', 'tableau16_b64.txt')
with open(PDF_B64_PATH) as f:
    PDF_VIERGE_B64 = f.read().strip()

# ── Coordonnées exactes tableau FFT ──────
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

# ── Utilitaires ──────────────────────────
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
    return f"{t//60:02d}:{t%60:02d}"

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

# ── Construction du tableau FFT ──────────
def build_tableau(paires):
    ts1, ts2   = paires[0], paires[1]
    ts34       = shuffle([paires[2], paires[3]])
    ts58       = shuffle([paires[4], paires[5], paires[6], paires[7]])
    autres     = shuffle(paires[8:])
    T = [
        {'t':'bye','p':ts2},       # 0  BYE TS2 → QF
        {'t':'emp'},               # 1
        {'t':'eq', 'p':autres[0]}, # 2  ─┐ Match 1
        {'t':'ts', 'p':ts58[0]},   # 3  ─┘
        {'t':'ts', 'p':ts58[1]},   # 4  ─┐ Match 2
        {'t':'eq', 'p':autres[1]}, # 5  ─┘
        {'t':'bye','p':ts34[0]},   # 6  BYE TS3/4 → QF
        {'t':'emp'},               # 7
        {'t':'bye','p':ts34[1]},   # 8  BYE TS4/3 → QF
        {'t':'emp'},               # 9
        {'t':'ts', 'p':ts58[2]},   # 10 ─┐ Match 3
        {'t':'eq', 'p':autres[2]}, # 11 ─┘
        {'t':'eq', 'p':autres[3]}, # 12 ─┐ Match 4
        {'t':'ts', 'p':ts58[3]},   # 13 ─┘
        {'t':'bye','p':ts1},       # 14 BYE TS1 → QF
        {'t':'emp'},               # 15
    ]
    return T, ts34, ts58

# ── Calcul horaires TMC ──────────────────
def calc_horaires(heure_debut, nb_pistes, duree):
    vagues = [[1,2],[3,4],[5,6],[7,8,9,10],[11,12],[13,14],[15,16],[17,18,19],[20]]
    horaires = {}
    h = heure_debut
    for vague in vagues:
        nb_v = (len(vague) + nb_pistes - 1) // nb_pistes
        for i, num in enumerate(vague):
            offset = (i // nb_pistes) * duree
            horaires[num] = (add_min(h, offset), (i % nb_pistes) + 1)
        h = add_min(h, nb_v * duree)
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
    c.drawString(14, 112, "TS1,TS2,TS3,TS4 — BYE → QF direct  |  TS1 en bas / TS2 en haut (FFT p.40)")
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
def generer_pdf_feuille(matchs, nom_tournoi, date_str, sponsor, format_jeu):
    W, H = A4
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=A4)

    # Header
    c.setFillColorRGB(0,0,0)
    c.setFont("Helvetica-Bold", 16); c.drawString(40, H-42, "Arena18")
    c.setFont("Helvetica", 8); c.setFillColorRGB(0.5,0.5,0.5)
    c.drawString(40, H-53, "VOUS DE JOUER")
    c.setFillColorRGB(0,0,0)
    c.setFont("Helvetica-Bold", 20); c.drawCentredString(W/2, H-38, "TOURNOI P250")
    c.setFont("Helvetica", 10); c.drawCentredString(W/2, H-52, f"by {sponsor}")
    c.setFont("Helvetica-Bold", 13); c.drawRightString(W-40, H-38, "12 équipes")
    c.setFont("Helvetica", 8); c.drawRightString(W-40, H-50, f"Format {format_jeu}")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, H-72, f"DATE : {date_str.upper()}")
    c.setLineWidth(2); c.line(40, H-79, W-40, H-79); c.setLineWidth(0.5)

    # En-têtes
    yh = H - 92
    c.setFillColorRGB(0,0,0); c.rect(40, yh-2, W-80, 13, fill=1, stroke=0)
    c.setFillColorRGB(1,1,1); c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(57, yh+3, "M")
    c.drawString(78, yh+3, "NOM DES ÉQUIPES")
    c.drawCentredString(375, yh+3, "HEURE")
    c.drawCentredString(425, yh+3, "ORDRE")
    c.drawCentredString(505, yh+3, "TERRAIN")
    c.setFillColorRGB(0,0,0)

    y = yh - 15
    row_h = 19
    current_sec = None

    sec_colors = {
        '1/8 de finale':        (0.93,0.93,0.93),
        'Classement 9 à 12':    (1.0, 0.96,0.88),
        'Quarts de finale':     (0.88,0.95,0.88),
        'Classement suite':     (1.0, 0.96,0.88),
        'Classement 5 à 8':     (0.93,0.90,1.0),
        'Demi-finales':         (0.88,0.95,0.95),
        'Classements finaux':   (0.93,0.93,0.93),
        'Finale':               (0.10,0.10,0.10),
    }

    for m in matchs:
        sec = m.get('section')
        if sec and sec != current_sec:
            current_sec = sec
            bg = sec_colors.get(sec, (0.9,0.9,0.9))
            c.setFillColorRGB(*bg)
            c.rect(40, y-1, W-80, 11, fill=1, stroke=0)
            fc = (1,1,1) if sec == 'Finale' else (0.3,0.3,0.3)
            c.setFillColorRGB(*fc)
            c.setFont("Helvetica-Bold", 7)
            c.drawString(44, y+3, sec.upper())
            c.setFillColorRGB(0,0,0)
            y -= 11

        bg_row = (1,1,1) if m['num']%2==1 else (0.97,0.97,0.97)
        if sec == 'Finale': bg_row = (0.10,0.10,0.10)
        c.setFillColorRGB(*bg_row)
        c.rect(40, y-3, W-80, row_h, fill=1, stroke=0)

        tc = (1,1,1) if sec=='Finale' else (0,0,0)
        c.setFillColorRGB(*tc)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(57, y+4, str(m['num']))

        # Balle jaune
        if m.get('balles'):
            c.setFillColorRGB(0.78, 0.70, 0.0)
            c.circle(71, y+6, 5, fill=1, stroke=0)
            c.setFillColorRGB(*tc)

        # Équipes
        c.setFont("Helvetica", 8)
        if m.get('pA') and m.get('pB'):
            pa, pb = m['pA'], m['pB']
            c.setFont("Helvetica-Bold", 8)
            c.drawString(80, y+9, f"{pa['prenJ1']} {pa['nomJ1']} / {pa['prenJ2']} {pa['nomJ2']}")
            c.setFont("Helvetica", 7); c.setFillColorRGB(0.5,0.5,0.5)
            c.drawString(80, y+1, "VS")
            c.setFont("Helvetica-Bold", 8); c.setFillColorRGB(*tc)
            c.drawString(93, y+1, f"{pb['prenJ1']} {pb['nomJ1']} / {pb['prenJ2']} {pb['nomJ2']}")
        elif m.get('pB') and m.get('libA'):
            pb = m['pB']
            c.setFillColorRGB(0.4,0.4,0.4) if sec!='Finale' else c.setFillColorRGB(0.7,0.7,0.7)
            c.setFont("Helvetica", 7.5)
            c.drawString(80, y+9, m['libA'])
            c.setFont("Helvetica", 7); c.setFillColorRGB(0.5,0.5,0.5)
            c.drawString(80, y+2, "VS")
            c.setFont("Helvetica-Bold", 8)
            c.setFillColorRGB(0.7,0.1,0.1) if sec!='Finale' else c.setFillColorRGB(1,0.5,0.5)
            c.drawString(93, y+2, f"{pb['prenJ1']} {pb['nomJ1']} / {pb['prenJ2']} {pb['nomJ2']} ({pb['ts']})")
        elif sec == 'Finale':
            c.setFont("Helvetica-Bold", 12); c.setFillColorRGB(1,1,1)
            c.drawCentredString(W/2-40, y+5, "★   FINALE   ★")
        else:
            c.setFillColorRGB(0.35,0.35,0.35)
            c.setFont("Helvetica", 7.5)
            c.drawString(80, y+9, m.get('libA',''))
            c.setFont("Helvetica", 7); c.setFillColorRGB(0.5,0.5,0.5)
            c.drawString(80, y+2, "VS")
            c.setFont("Helvetica", 7.5); c.setFillColorRGB(0.35,0.35,0.35)
            c.drawString(93, y+2, m.get('libB',''))

        c.setFillColorRGB(*tc)
        h_m, piste = m.get('heure','?'), m.get('piste','?')
        c.setFont("Helvetica-Bold", 9); c.drawCentredString(375, y+5, str(h_m))
        c.setFont("Helvetica-Bold", 8); c.drawCentredString(425, y+5, m['ordre'])
        c.setFont("Helvetica", 7)
        if m['num'] <= 2:
            c.setFont("Helvetica-Bold", 7); c.setFillColorRGB(0,0.3,0.7)
            c.drawCentredString(505, y+5, m.get('terrain','')[:22])
            c.setFillColorRGB(*tc)
        else:
            c.drawCentredString(505, y+5, f"Terrain {piste}")

        c.setStrokeColorRGB(0.85,0.85,0.85)
        c.line(40, y-3, W-40, y-3)
        c.setStrokeColorRGB(0,0,0)
        y -= row_h

    # Footer
    c.setFont("Helvetica", 7); c.setFillColorRGB(0.5,0.5,0.5)
    c.line(40, y-8, W-40, y-8)
    for i, l in enumerate(["CONVI GROUPE","FFT PADEL", sponsor,"DÉCATHLON"]):
        c.drawString(40+i*120, y-18, l)

    c.save()
    packet.seek(0)
    return packet.getvalue()

# ── Routes Flask ─────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generer', methods=['POST'])
def generer():
    data = request.get_json()
    csv_text    = data['csv']
    heure_debut = data.get('heureDebut', '09:00')
    nb_pistes   = int(data.get('nbPistes', 2))
    duree       = int(data.get('dureeMatch', 45))
    nom_tournoi = data.get('nomTournoi', 'P250 Double Messieurs Sénior')
    date_str    = data.get('dateStr', '')
    sponsor     = data.get('sponsor', 'CUPRA LANESTER')
    format_jeu  = data.get('formatJeu', 'D2 : 1 set 9 jeux, NO-AD')

    # Parser CSV
    try:
        paires = parse_csv(csv_text)
    except Exception as e:
        return jsonify({'error': f'Erreur CSV : {str(e)}'}), 400

    if len(paires) < 8:
        return jsonify({'error': f'Minimum 8 paires requises, {len(paires)} trouvées'}), 400

    # Vérif doublons
    lm, doublons = {}, []
    for p in paires:
        for l in [p['licJ1'], p['licJ2']]:
            if not l: continue
            lu = l.lower()
            if lu in lm: doublons.append(l)
            else: lm[lu] = True

    # Tableau FFT
    T, ts34, ts58 = build_tableau(paires)
    qf_map = {
        '0': {'nom':T[0]['p']['nc'],'poids':T[0]['p']['poids'],'ts':T[0]['p']['ts']},
        '3': {'nom':T[6]['p']['nc'],'poids':T[6]['p']['poids'],'ts':T[6]['p']['ts']},
        '4': {'nom':T[8]['p']['nc'],'poids':T[8]['p']['poids'],'ts':T[8]['p']['ts']},
        '7': {'nom':T[14]['p']['nc'],'poids':T[14]['p']['poids'],'ts':T[14]['p']['ts']},
    }

    # Horaires
    horaires = calc_horaires(heure_debut, nb_pistes, duree)

    # Structure 20 matchs
    m1a,m1b = T[2]['p'],T[3]['p']
    m2a,m2b = T[4]['p'],T[5]['p']
    m3a,m3b = T[10]['p'],T[11]['p']
    m4a,m4b = T[12]['p'],T[13]['p']
    qf0,qf3,qf4,qf7 = T[0]['p'],T[6]['p'],T[8]['p'],T[14]['p']

    matchs = [
        {'num':1, 'ordre':'1/8',    'pA':m1a,'pB':m1b,  'terrain':'TERRAIN DÉCATHLON',           'section':'1/8 de finale'},
        {'num':2, 'ordre':'1/8',    'pA':m2a,'pB':m2b,  'terrain':'TERRAIN CUPRA',               'section':None},
        {'num':3, 'ordre':'1/8',    'pA':m3a,'pB':m3b,  'terrain':'1ER TERRAIN QUI SE LIBÈRE',   'section':None},
        {'num':4, 'ordre':'1/8',    'pA':m4a,'pB':m4b,  'terrain':'2ÈME TERRAIN QUI SE LIBÈRE',  'section':None},
        {'num':5, 'ordre':'9à12',   'libA':'PERDANT M1','libB':'PERDANT M2','terrain':'1ER TERRAIN', 'section':'Classement 9 à 12'},
        {'num':6, 'ordre':'9à12',   'libA':'PERDANT M3','libB':'PERDANT M4','terrain':'2ÈME TERRAIN','section':None},
        {'num':7, 'ordre':'1/4',    'libA':'GAGNANT M1','pB':qf0,'terrain':'1ER TERRAIN', 'section':'Quarts de finale'},
        {'num':8, 'ordre':'1/4',    'libA':'GAGNANT M2','pB':qf3,'terrain':'2ÈME TERRAIN','section':None},
        {'num':9, 'ordre':'1/4',    'libA':'GAGNANT M3','pB':qf4,'terrain':'1ER TERRAIN', 'section':None},
        {'num':10,'ordre':'1/4',    'libA':'GAGNANT M4','pB':qf7,'terrain':'2ÈME TERRAIN','section':None},
        {'num':11,'ordre':'11à12',  'libA':'PERDANT M5','libB':'PERDANT M6','terrain':'1ER TERRAIN','section':'Classement suite'},
        {'num':12,'ordre':'9à10',   'libA':'GAGNANT M5','libB':'GAGNANT M6','terrain':'2ÈME TERRAIN','section':None},
        {'num':13,'ordre':'5à8',    'libA':'PERDANT M7','libB':'PERDANT M8','terrain':'1ER TERRAIN', 'section':'Classement 5 à 8'},
        {'num':14,'ordre':'5à8',    'libA':'PERDANT M9','libB':'PERDANT M10','terrain':'2ÈME TERRAIN','section':None},
        {'num':15,'ordre':'1/2',    'libA':'GAGNANT M7','libB':'GAGNANT M8','terrain':'1ER TERRAIN', 'section':'Demi-finales','balles':True},
        {'num':16,'ordre':'1/2',    'libA':'GAGNANT M9','libB':'GAGNANT M10','terrain':'2ÈME TERRAIN','section':None,'balles':True},
        {'num':17,'ordre':'7/8',    'libA':'PERDANT M13','libB':'PERDANT M14','terrain':'1ER TERRAIN','section':'Classements finaux'},
        {'num':18,'ordre':'5/6',    'libA':'GAGNANT M13','libB':'GAGNANT M14','terrain':'2ÈME TERRAIN','section':None},
        {'num':19,'ordre':'3/4',    'libA':'PERDANT M15','libB':'PERDANT M16','terrain':'1ER TERRAIN','section':None},
        {'num':20,'ordre':'FINALE', 'libA':'GAGNANT M15','libB':'GAGNANT M16','terrain':'2ÈME TERRAIN','section':'Finale','balles':True},
    ]
    for m in matchs:
        h_m, piste = horaires.get(m['num'], ('?','?'))
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

        for j in [{'pr':p['prenJ1'],'nm':p['nomJ1'],'tel':p['telJ1']},
                  {'pr':p['prenJ2'],'nm':p['nomJ2'],'tel':p['telJ2']}]:
            msg = f"Bonjour {j['pr']} 👋\n\n📢 {nom_tournoi}\n📅 {date_str}\n🎯 Format : {format_jeu}\n━━━━━━━━━━━━━━\n👥 Votre paire :\n   {p['nf']}"
            if p['ts']: msg += f"\n⭐ {p['ts']}"
            if is_bye:  msg += "\n✅ Exempt du 1er tour (BYE)"
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
        'tableau':  [[s['t'], s['p'] if 't' in s and s['t']!='emp' else None] for s in T],
        'matchs':   matchs,
        'messages': messages,
        'doublons': doublons,
        'qfMap':    qf_map,
    })

@app.route('/pdf/tableau', methods=['POST'])
def pdf_tableau():
    data        = request.get_json()
    T_raw       = data['tableau']
    qf_map      = data['qfMap']
    nom_tournoi = data.get('nomTournoi','P250')
    date_str    = data.get('dateStr','')
    format_jeu  = data.get('formatJeu','9 jeux NO-AD')
    T = [{'t':t,'p':p} if p else {'t':t} for t,p in T_raw]
    pdf_bytes = generer_pdf_tableau(T, qf_map, nom_tournoi, date_str, format_jeu)
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name='tableau_p250.pdf'
    )

@app.route('/pdf/feuille', methods=['POST'])
def pdf_feuille():
    data = request.get_json()
    pdf_bytes = generer_pdf_feuille(
        data['matchs'], data['nomTournoi'],
        data['dateStr'], data['sponsor'], data['formatJeu']
    )
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name='feuille_route.pdf'
    )

@app.route('/sms/envoyer', methods=['POST'])
def envoyer_sms():
    data         = request.get_json()
    messages     = data['messages']
    account_sid  = data.get('twilioSid','')
    auth_token   = data.get('twilioToken','')
    from_number  = data.get('twilioFrom','')

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
            results.append({'tel': m.get('tel',''), 'status': 'skipped', 'reason': 'N° invalide'})
            continue
        try:
            msg = client.messages.create(
                body=m['msg'],
                from_=from_number,
                to=f'+{tel}'
            )
            results.append({'tel': m.get('tel',''), 'status': 'sent', 'sid': msg.sid})
        except Exception as e:
            results.append({'tel': m.get('tel',''), 'status': 'error', 'reason': str(e)})

    sent  = sum(1 for r in results if r['status']=='sent')
    return jsonify({'results': results, 'sent': sent, 'total': len(results)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
