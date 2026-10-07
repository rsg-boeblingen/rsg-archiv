#!/usr/bin/env python3
"""RSG Böblingen – Archiv-Seiten + Suchindex bauen (Phase 3, Prototyp, nur lokal).

Liest <basis>/archiv/archiv.json (von rsg_archiv_import.py) und erzeugt im selben Ordner:
    index.html            Suchseite (Suchfeld, Filter, Trefferliste)
    b/<id>.html           eine Detailseite pro Beitrag (Text + Bildergalerie), teilbar per Link
    archiv.css, archiv.js Gestaltung und Bildergalerie
    pagefind/             Suchindex (wird mit Pagefind erzeugt)

Voraussetzung (einmalig):  pip3 install --user 'pagefind[extended]'

Aufruf:
    python3 rsg_archiv_seiten.py
    python3 rsg_archiv_seiten.py --basis PFAD

Ansehen (lokal, Pagefind braucht einen Webserver):
    python3 -m http.server 8000 --directory ~/rsg-archiv-import/archiv
    → im Browser http://localhost:8000  (vom iPad über Tailscale: http://<mac-name>:8000)

Alle Seiten tragen <meta name="robots" content="noindex">. Es wird nichts hochgeladen.
"""
import argparse
import html
import json
import re
import os
import shutil
import subprocess
import sys

E = html.escape
ARCHIV_VERSION = "2"   # bei Änderungen an archiv.css / archiv.js erhöhen
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]
QUELLE_NAME = {"wordpress": "Alte Website", "facebook": "Facebook"}

CSS = r"""
/* Archiv-spezifisch. Grundlayout, Schriften, Header und Footer kommen aus der
   style.css der Hauptseite; hier nur Ergänzungen, alles unter .archiv. */
.archiv{padding:40px 0 64px}
.archiv h1{font-size:clamp(28px,5vw,44px);color:var(--rsg-blue-dark);margin:.1em 0 .35em;line-height:1.2}
.archiv a.textlink{color:var(--rsg-blue-dark);text-decoration:underline}
.archiv .lead{color:var(--rsg-text-muted);margin:0 0 24px;max-width:62ch}
.archiv .suche{background:var(--rsg-blue-soft);border-radius:var(--radius);padding:20px}
.archiv .suchzeile input{width:100%;font:inherit;font-size:1.15rem;padding:13px 16px;border:2px solid var(--rsg-blue-alt);border-radius:var(--radius);background:#fff;color:var(--rsg-text)}
.archiv .suchzeile input:focus{outline:none;border-color:var(--rsg-blue-dark)}
.archiv .filter{display:flex;flex-wrap:wrap;gap:12px 16px;margin-top:14px;align-items:end}
.archiv .filter label{display:flex;flex-direction:column;font-size:.85rem;color:var(--rsg-text-muted);gap:4px}
.archiv .filter select{font:inherit;font-size:.95rem;padding:9px 10px;border:1px solid var(--rsg-blue-alt);border-radius:var(--radius);background:#fff;min-width:160px;color:var(--rsg-text)}
.archiv .knopf{font:inherit;font-size:.95rem;font-weight:700;padding:9px 16px;border-radius:var(--radius);border:2px solid var(--rsg-blue-dark);background:#fff;color:var(--rsg-blue-dark);cursor:pointer;display:inline-block}
.archiv .knopf:hover,.archiv .knopf:focus{background:var(--rsg-yellow);border-color:var(--rsg-yellow)}
.archiv .status{margin:20px 0 10px;color:var(--rsg-text-muted);font-size:.95rem}
.archiv .treffer{list-style:none;margin:0;padding:0;display:grid;gap:12px}
.archiv .treffer li{font-size:inherit}
.archiv .karte{display:grid;grid-template-columns:132px 1fr;gap:16px;padding:12px;border:1px solid var(--rsg-blue-alt);border-radius:var(--radius);background:#fff;color:inherit;transition:border-color .15s,box-shadow .15s}
.archiv .karte:hover,.archiv .karte:focus{border-color:var(--rsg-blue-dark);box-shadow:0 4px 14px rgba(26,58,143,.12);outline:none}
.archiv .karte img,.archiv .karte .ohnebild{width:132px;height:99px;object-fit:cover;border-radius:4px;background:var(--rsg-blue-alt)}
.archiv .karte .ohnebild{display:flex;align-items:center;justify-content:center;color:var(--rsg-text-muted);font-size:.8rem}
.archiv .karte h2{font-size:1.15rem;line-height:1.3;margin:2px 0 4px;color:var(--rsg-blue-dark);font-weight:500}
.archiv .karte p{margin:0;font-size:.95rem;color:var(--rsg-text-muted);display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.archiv mark{background:#fff0a8;color:inherit;padding:0 1px}
.archiv .meta{font-size:.85rem;color:var(--rsg-text-muted);display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.archiv .badge{display:inline-block;font-size:.72rem;padding:1px 8px;border-radius:999px;background:var(--rsg-blue-alt);color:var(--rsg-blue-dark);font-weight:700}
.archiv .mehr{display:block;margin:20px auto 0}
.archiv .hinweis{margin-top:40px;padding:14px 16px;border-left:4px solid var(--rsg-yellow);background:var(--rsg-blue-soft);font-size:.9rem;color:var(--rsg-text-muted)}
.archiv .zurueck{display:inline-block;margin-bottom:8px;font-weight:700;color:var(--rsg-blue-dark)}
.archiv .zurueck:hover{color:var(--rsg-red)}
.archiv .text p{margin:0 0 1em;max-width:70ch;white-space:pre-line}
.archiv .chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 22px}
.archiv .chips a{font-size:.85rem;padding:3px 12px;border-radius:999px;border:1px solid var(--rsg-blue-alt);color:var(--rsg-blue-dark);background:#fff}
.archiv .chips a:hover,.archiv .chips a:focus{border-color:var(--rsg-blue-dark)}
.archiv .galerie{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px;margin:28px 0}
.archiv .galerie button{padding:0;border:0;background:var(--rsg-blue-alt);border-radius:4px;overflow:hidden;cursor:zoom-in;aspect-ratio:4/3}
.archiv .galerie img{width:100%;height:100%;object-fit:cover}
.archiv .galerie button:focus{outline:3px solid var(--rsg-yellow);outline-offset:2px}
.archiv .quellen{display:flex;flex-wrap:wrap;gap:10px;margin-top:20px}
.archiv .entfernen{margin-top:48px;font-size:.85rem;color:var(--rsg-text-muted)}
.unsichtbar{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}
dialog.lb{border:0;padding:0;background:#000;color:#fff;max-width:100vw;max-height:100vh;width:100vw;height:100vh}
dialog.lb::backdrop{background:rgba(0,0,0,.92)}
.lb figure{margin:0;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:48px 64px}
.lb img{max-width:100%;max-height:calc(100vh - 140px);object-fit:contain;display:block}
.lb figcaption{margin-top:10px;font-size:.9rem;opacity:.85;text-align:center}
.lb button{position:absolute;background:rgba(255,255,255,.12);color:#fff;border:0;font-size:1.6rem;width:48px;height:48px;border-radius:50%;cursor:pointer}
.lb button:hover,.lb button:focus{background:rgba(255,255,255,.3)}
.lb .zu{top:12px;right:12px}.lb .vor{right:12px;top:50%}.lb .zurueckb{left:12px;top:50%}
@media (max-width:560px){
 .archiv{padding-top:24px}
 .archiv .karte{grid-template-columns:84px 1fr;gap:12px}
 .archiv .karte img,.archiv .karte .ohnebild{width:84px;height:84px}
 .archiv .filter label{flex:1 1 140px}.archiv .filter select{min-width:0;width:100%}
 .lb figure{padding:60px 8px}
}
"""

GALERIE_JS = r"""
(function(){
  var d=document.getElementById('lb'); if(!d) return;
  var btns=[].slice.call(document.querySelectorAll('.galerie button')), i=0;
  var img=d.querySelector('img'), cap=d.querySelector('figcaption');
  function zeige(n){ i=(n+btns.length)%btns.length; var b=btns[i];
    img.src=b.dataset.gross; img.alt=b.querySelector('img').alt;
    cap.textContent=b.querySelector('img').alt+'  ('+(i+1)+' / '+btns.length+')'; }
  btns.forEach(function(b,n){ b.addEventListener('click',function(){ zeige(n); d.showModal(); }); });
  d.querySelector('.zu').onclick=function(){ d.close(); };
  d.querySelector('.vor').onclick=function(){ zeige(i+1); };
  d.querySelector('.zurueckb').onclick=function(){ zeige(i-1); };
  d.addEventListener('keydown',function(e){ if(e.key==='ArrowRight') zeige(i+1); if(e.key==='ArrowLeft') zeige(i-1); });
  var x0=null; d.addEventListener('touchstart',function(e){ x0=e.touches[0].clientX; },{passive:true});
  d.addEventListener('touchend',function(e){ if(x0===null) return; var dx=e.changedTouches[0].clientX-x0;
    if(Math.abs(dx)>50) zeige(i+(dx<0?1:-1)); x0=null; });
})();
"""

SUCHE_JS = r"""
(async function(){
  var base = location.pathname.replace(/[^/]*$/, '');
  var pf = await import(base + 'pagefind/pagefind.js');
  await pf.options({ baseUrl: base, excerptLength: 30 });
  pf.init();
  var $ = function(id){ return document.getElementById(id); };
  var q=$('q'), fJahr=$('f-jahr'), fQuelle=$('f-quelle'), fWort=$('f-wort'), sort=$('sortierung');
  var liste=$('treffer'), status=$('status'), mehr=$('mehr');
  var alle=[], gezeigt=0, lauf=0, PRO_SEITE=20;

  // Filterlisten aus dem Index füllen
  var filters = await pf.filters();
  function fuelle(sel, werte, absteigend){
    Object.keys(werte||{}).sort(function(a,b){ return absteigend ? b.localeCompare(a) : a.localeCompare(b,'de'); })
      .forEach(function(w){ var o=document.createElement('option'); o.value=w; o.textContent=w+' ('+werte[w]+')'; sel.appendChild(o); });
  }
  fuelle(fJahr, filters.jahr, true); fuelle(fQuelle, filters.quelle); fuelle(fWort, filters.schlagwort);

  // Zustand <-> URL (teilbare Suchen)
  var p = new URLSearchParams(location.search);
  q.value = p.get('q')||''; fJahr.value = p.get('jahr')||''; fQuelle.value = p.get('quelle')||'';
  fWort.value = p.get('schlagwort')||''; sort.value = p.get('sort')||'';

  function karte(d){
    var li=document.createElement('li'), a=document.createElement('a');
    a.className='karte'; a.href=d.url;
    // nur eigene Archivbilder: ohne Beitragsbild greift Pagefind sonst auf das Logo der Seite zurück
    var bild = (d.meta.image||'').indexOf('bilder/') === 0 ? '<img src="'+base+d.meta.image+'" alt="" loading="lazy">' : '<div class="ohnebild" aria-hidden="true">kein Bild</div>';
    var quellen = (d.filters.quelle||[]).map(function(x){ return '<span class="badge'+(x==='Facebook'?' fb':'')+'">'+x+'</span>'; }).join(' ');
    a.innerHTML = bild + '<div><div class="meta"><time>'+(d.meta.datum_text||'')+'</time>'+quellen+'</div>'
      + '<h2>'+(d.meta.title||'')+'</h2><p>'+(d.excerpt||'')+'</p></div>';
    li.appendChild(a); return li;
  }
  async function zeigeMehr(){
    var stueck = alle.slice(gezeigt, gezeigt+PRO_SEITE);
    var daten = await Promise.all(stueck.map(function(r){ return r.data(); }));
    daten.forEach(function(d){ liste.appendChild(karte(d)); });
    gezeigt += stueck.length;
    mehr.hidden = gezeigt >= alle.length;
  }
  async function suche(){
    var meinLauf = ++lauf;
    var filter = {};
    if (fJahr.value) filter.jahr = fJahr.value;
    if (fQuelle.value) filter.quelle = fQuelle.value;
    if (fWort.value) filter.schlagwort = fWort.value;
    var begriff = q.value.trim();
    var opts = { filters: filter };
    if (sort.value === 'neu' || !begriff) opts.sort = { datum: 'desc' };
    if (sort.value === 'alt') opts.sort = { datum: 'asc' };
    var res = await pf.debouncedSearch(begriff || null, opts, 250);
    if (res === null || meinLauf !== lauf) return;   // überholt durch neuere Eingabe
    alle = res.results; gezeigt = 0; liste.innerHTML = '';
    status.textContent = alle.length === 1 ? '1 Beitrag gefunden' : alle.length + ' Beiträge gefunden';
    await zeigeMehr();
    var u = new URLSearchParams();
    if (begriff) u.set('q', begriff); if (fJahr.value) u.set('jahr', fJahr.value);
    if (fQuelle.value) u.set('quelle', fQuelle.value); if (fWort.value) u.set('schlagwort', fWort.value);
    if (sort.value) u.set('sort', sort.value);
    history.replaceState(null, '', u.toString() ? '?' + u.toString() : location.pathname);
  }
  q.addEventListener('input', suche);
  [fJahr, fQuelle, fWort, sort].forEach(function(s){ s.addEventListener('change', suche); });
  $('zuruecksetzen').addEventListener('click', function(){ q.value=''; fJahr.value=''; fQuelle.value=''; fWort.value=''; sort.value=''; suche(); q.focus(); });
  mehr.addEventListener('click', zeigeMehr);
  suche();
})().catch(function(e){
  document.getElementById('status').textContent = 'Die Suche konnte nicht geladen werden. Läuft die Seite über einen Webserver (nicht als Datei geöffnet)?';
  console.error(e);
});
"""


# Header/Footer/CSS/Schriften kommen von der Hauptseite. Leer = gleiche Domain (Produktion:
# Archiv liegt unter rsg-boeblingen.de/archiv/). Für die lokale Vorschau auf dem Mac:
# --hauptseite https://rsg-boeblingen.de  (dann fehlen dort nur die Schriften – Browser-Sperre)
HAUPTSEITE = ""
CSS_VERSION = "20"                         # = style.css?v=… der Hauptseite
JS_VERSION = "11"


def kopf(titel, tiefe, beschreibung=""):
    up = "../" * tiefe
    h = HAUPTSEITE
    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, minimum-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{E(titel)} – Archiv – RSG Böblingen</title>
<meta name="description" content="{E(beschreibung)}">
<link rel="stylesheet" href="{h}/css/style.css?v={CSS_VERSION}">
<link rel="stylesheet" href="{up}archiv.css?v={ARCHIV_VERSION}">
<link rel="icon" href="{h}/assets/images/rsg-logo.png">
</head>
<body>
<a class="unsichtbar" href="#inhalt">Zum Inhalt springen</a>
<header class="site-header">
  <div class="container">
    <a class="logo" href="{h}/index.html#Home"><img src="{h}/assets/images/rsg-logo.png" alt="RSG Radsport Triathlon Böblingen Logo"></a>
    <button class="nav-toggle" id="navToggle" aria-label="Menü öffnen"><span class="nav-toggle-bar"></span><span class="nav-toggle-bar"></span><span class="nav-toggle-bar"></span></button>
    <nav class="main-nav" id="mainNav">
      <ul>
        <li><a href="{h}/index.html#Home">Home</a></li>
        <li><a href="{h}/aktuelles.html">Aktuelles</a></li>
        <li><a href="{h}/index.html#Training">Triathlon</a></li>
        <li><a href="{up}index.html" aria-current="page">Archiv</a></li>
        <li><a href="{h}/index.html#Blindensport">Blindensport</a></li>
        <li><a href="{h}/vereinsheim-mieten.html">Vereinsheim &amp; Vermietung</a></li>
        <li><a href="{h}/kontakt.html">Kontakt</a></li>
      </ul>
    </nav>
  </div>
</header>
"""


def fuss(tiefe):
    h = HAUPTSEITE
    return f"""<footer>
  <div class="container">
    <div class="footer-grid">
      <div>
        <img src="{h}/assets/images/rsg-logo.png" alt="RSG Böblingen Logo" class="footer-logo">
        <p>RSG Böblingen e.V. — Triathlon &amp; Radsport seit 1972.</p>
      </div>
      <div>
        <h4>Navigation</h4>
        <ul>
          <li><a href="{h}/index.html#Home">Home</a></li>
          <li><a href="{h}/aktuelles.html">Aktuelles</a></li>
          <li><a href="{h}/index.html#Training">Triathlon</a></li>
          <li><a href="{h}/index.html#Blindensport">Blindensport</a></li>
          <li><a href="{h}/vereinsheim-mieten.html">Vereinsheim &amp; Vermietung</a></li>
          <li><a href="{h}/kontakt.html">Kontakt</a></li>
        </ul>
      </div>
      <div>
        <h4>Kontakt</h4>
        <p>RSG Böblingen e.V.<br>Im Zimmerschlag 11<br>71032 Böblingen</p>
        <ul><li><a href="https://www.facebook.com/RsgBoeblingenTriathlon/" target="_blank" rel="noopener">Facebook</a></li></ul>
      </div>
      <div>
        <h4>Archiv</h4>
        <p>Frühere Beiträge der alten Vereinswebsite und der Facebook-Seite „RSG Böblingen Triathlon Team“.</p>
        <p>Sie möchten einen Beitrag oder ein Foto entfernen lassen? Eine kurze Nachricht an vorstand (at) rsg-boeblingen.de genügt.</p>
      </div>
    </div>
    <div class="footer-bottom"><span>&copy; 2026 RSG Böblingen e.V.</span><a href="{h}/impressum.html">Impressum · Datenschutz</a></div>
  </div>
</footer>
<button type="button" class="back-to-top" id="backToTop" aria-label="Nach oben"><svg viewBox="0 0 24 24"><path d="M18 15l-6-6-6 6"/></svg></button>
<script src="{h}/js/script.js?v={JS_VERSION}"></script>
"""


def datum_text(iso):
    j, m, t = iso.split("-")
    return f"{int(t)}. {MONATE[int(m) - 1]} {j}"


def detailseite(b):
    titel = b["titel"]
    datum = datum_text(b["datum"])
    quellen = [QUELLE_NAME.get(q, q) for q in b["quelle"]]
    absaetze = "".join(f"<p>{E(a.strip())}</p>" for a in b["text"].split("\n\n")
                       if a.strip() and a.strip() not in ("•", "·"))
    b["schlagworte"] = [w for w in b["schlagworte"] if not re.fullmatch(r"\d{4}", w)]
    erstes = b["bilder"][0]["klein"] if b["bilder"] else ""
    filter_spans = [f'<span data-pagefind-filter="jahr:{b["datum"][:4]}"></span>']
    filter_spans += [f'<span data-pagefind-filter="quelle:{E(q)}"></span>' for q in quellen]
    filter_spans += [f'<span data-pagefind-filter="schlagwort:{E(s.replace(",", " "))}"></span>' for s in b["schlagworte"]]
    chips = "".join(f'<a href="../index.html?schlagwort={E(s)}">{E(s)}</a>' for s in b["schlagworte"])
    galerie = ""
    if b["bilder"]:
        knoepfe = "".join(
            f'<button type="button" data-gross="../{E(x["gross"])}" aria-label="Bild {n} von {len(b["bilder"])} vergrößern">'
            f'<img src="../{E(x["klein"])}" alt="{E(x.get("beschreibung") or titel)}" loading="lazy"></button>'
            for n, x in enumerate(b["bilder"], 1))
        galerie = (f'<h2 class="unsichtbar">Bilder</h2>'
                   f'<div class="galerie">{knoepfe}</div>'
                   '<dialog class="lb" id="lb" aria-label="Bildansicht"><figure><img src="" alt=""><figcaption></figcaption></figure>'
                   '<button type="button" class="zu" aria-label="Schließen">×</button>'
                   '<button type="button" class="zurueckb" aria-label="Vorheriges Bild">‹</button>'
                   '<button type="button" class="vor" aria-label="Nächstes Bild">›</button></dialog>')
    links = []
    if "wordpress" in b["quelle"]:
        links.append(f'<a class="knopf" href="{E(b["original_url"])}" rel="noopener">Originalbeitrag (alte Website)</a>')
    fb = b.get("facebook_url") or (b["original_url"] if b["quelle"] == ["facebook"] else "")
    if fb:
        links.append(f'<a class="knopf" href="{E(fb)}" rel="noopener" target="_blank">Auf Facebook ansehen ↗</a>')
    return (kopf(titel, 1, b["text"][:150]) +
            f"""<main id="inhalt" class="archiv"><div class="container">
<a class="zurueck" href="../index.html" onclick="if(document.referrer.indexOf(location.host)>-1&&history.length>1){{history.back();return false}}">← Zur Suche</a>
<article data-pagefind-body>
<div class="meta" data-pagefind-ignore><time datetime="{b['datum']}">{datum}</time> {' '.join(f'<span class="badge">{E(q)}</span>' for q in quellen)}</div>
<h1 data-pagefind-meta="title">{E(titel)}</h1>
<span hidden data-pagefind-meta="datum_text:{datum}"></span>
<span hidden data-pagefind-sort="datum:{b['datum']}"></span>
{f'<span hidden data-pagefind-meta="image:{E(erstes)}"></span>' if erstes else ''}
<span hidden>{''.join(filter_spans)}</span>
<div class="chips" data-pagefind-ignore>{chips}</div>
<div class="text">{absaetze}</div>
<div data-pagefind-ignore>{galerie}<div class="quellen">{''.join(links)}</div></div>
</article>
</div></main>
{fuss(1)}<script src="../archiv.js?v={ARCHIV_VERSION}" defer></script>
</body></html>
""")


def indexseite(anzahl, von, bis):
    return (kopf("Suche", 0, "Durchsuchbares Archiv der Triathlon-Beiträge der RSG Böblingen") +
            f"""<main id="inhalt" class="archiv"><div class="container">
<h1>Archiv Triathlon</h1>
<p class="lead">{anzahl} Berichte, Fotos und Meldungen aus {von}–{bis}. Suche nach Namen, Wettkämpfen, Orten oder Stichworten.</p>
<div class="suche" role="search">
  <div class="suchzeile">
    <label for="q" class="unsichtbar">Suchbegriff</label>
    <input id="q" type="search" placeholder="z. B. Roth, Ironman, Mallorca …" autocomplete="off" autofocus>
  </div>
  <div class="filter">
    <label>Jahr<select id="f-jahr"><option value="">alle Jahre</option></select></label>
    <label>Quelle<select id="f-quelle"><option value="">alle Quellen</option></select></label>
    <label>Schlagwort<select id="f-wort"><option value="">alle Schlagworte</option></select></label>
    <label>Sortierung<select id="sortierung"><option value="">Relevanz</option><option value="neu">Neueste zuerst</option><option value="alt">Älteste zuerst</option></select></label>
    <button type="button" class="knopf" id="zuruecksetzen">Zurücksetzen</button>
  </div>
</div>
<p class="status" id="status" aria-live="polite">Suche wird geladen …</p>
<ul class="treffer" id="treffer"></ul>
<button type="button" class="knopf mehr" id="mehr" hidden>Weitere Beiträge laden</button>
<p class="hinweis">Die Suche läuft vollständig in Ihrem Browser – Suchbegriffe werden nicht übertragen oder gespeichert.</p>
</div></main>
{fuss(0)}<script type="module">{SUCHE_JS}</script>
</body></html>
""")


def main():
    ap = argparse.ArgumentParser(description="Archiv-Seiten und Suchindex bauen")
    ap.add_argument("--basis", default=os.path.expanduser("~/rsg-archiv-import"))
    ap.add_argument("--hauptseite", default=HAUPTSEITE,
                    help="Adresse der Hauptseite für Header/Footer/CSS (Standard: %(default)s)")
    args = ap.parse_args()
    globals()["HAUPTSEITE"] = args.hauptseite.rstrip("/")
    ziel = os.path.join(os.path.abspath(args.basis), "archiv")
    quelle = os.path.join(ziel, "archiv.json")
    if not os.path.exists(quelle):
        sys.exit(f"{quelle} fehlt – erst rsg_archiv_import.py ausführen.")
    with open(quelle, encoding="utf-8") as f:
        beitraege = json.load(f)["beitraege"]

    print(f"Erzeuge {len(beitraege)} Detailseiten …")
    bdir = os.path.join(ziel, "b")
    if os.path.isdir(bdir):
        shutil.rmtree(bdir)          # alte Seiten (z. B. inzwischen gesperrte Beiträge) entfernen
    os.makedirs(bdir)
    for b in beitraege:
        with open(os.path.join(bdir, f"{b['id']}.html"), "w", encoding="utf-8") as f:
            f.write(detailseite(b))
    jahre = sorted(b["datum"][:4] for b in beitraege)
    with open(os.path.join(ziel, "index.html"), "w", encoding="utf-8") as f:
        f.write(indexseite(len(beitraege), jahre[0], jahre[-1]))
    with open(os.path.join(ziel, "archiv.css"), "w", encoding="utf-8") as f:
        f.write(CSS.strip() + "\n")
    with open(os.path.join(ziel, "archiv.js"), "w", encoding="utf-8") as f:
        f.write(GALERIE_JS.strip() + "\n")
    with open(os.path.join(ziel, "robots.txt"), "w", encoding="utf-8") as f:
        f.write("User-agent: *\nDisallow: /\n")

    print("Erzeuge Suchindex mit Pagefind …")
    pfdir = os.path.join(ziel, "pagefind")
    if os.path.isdir(pfdir):
        shutil.rmtree(pfdir)
    try:
        r = subprocess.run([sys.executable, "-m", "pagefind", "--site", ziel, "--glob", "b/*.html"],
                           capture_output=True, text=True)
    except FileNotFoundError:
        r = None
    if r is None or r.returncode != 0:
        print((r.stdout + r.stderr)[-1500:] if r else "")
        sys.exit("Pagefind fehlt oder ist fehlgeschlagen. Einmalig installieren mit:\n"
                 "    pip3 install --user 'pagefind[extended]'")
    zeilen = [z for z in r.stdout.splitlines() if "Indexed" in z or "Total" in z or "page" in z.lower()]
    print("  " + "\n  ".join(zeilen[-6:]))

    groesse = sum(os.path.getsize(os.path.join(dp, fn)) for dp, _, fns in os.walk(pfdir) for fn in fns)
    print("\n================ ERGEBNIS ================")
    print(f"Detailseiten:        {len(beitraege)}")
    print(f"Suchindex:           {groesse / 1e6:.1f} MB in {pfdir}")
    print(f"Ordner:              {ziel}")
    print("\nAnsehen:  python3 -m http.server 8000 --directory " + ziel)
    print("          → http://localhost:8000  (iPad über Tailscale: http://<mac-name>:8000)")


if __name__ == "__main__":
    main()
