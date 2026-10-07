#!/usr/bin/env python3
"""RSG Böblingen – Archiv-Import (Phase 3, nur lokal).

Liest die gesicherten Quellen und baut daraus das gemeinsame Archiv:

    <basis>/wordpress/*.xml            WXR-Export des alten WordPress
    <basis>/wordpress/uploads/         per SFTP gesichert
    <basis>/wordpress/gallery/         NextGEN-Galerie, per SFTP gesichert
    <basis>/facebook/posts.json        von rsg_fb_sichern.py
    <basis>/sperrliste.txt             optional: IDs oder Bilddateinamen, die NICHT ins Archiv sollen

Ergebnis in <basis>/archiv/:
    archiv.json                        alle Beiträge im gemeinsamen Format
    bilder/gross/…, bilder/klein/…     verkleinerte Bilder (1600 px / 400 px, JPEG)
    bericht.txt                        Statistik, fehlende Bilder, zusammengeführte Beiträge

Es wird NICHTS hochgeladen, gepusht oder deployt. Quellordner werden nur gelesen.

Aufruf:
    python3 rsg_archiv_import.py                     # Standard-Basis ~/rsg-archiv-import
    python3 rsg_archiv_import.py --ohne-bilder       # schneller Probelauf: nur Texte, keine Bildkonvertierung
    python3 rsg_archiv_import.py --basis PFAD

Wiederholbar: bereits konvertierte Bilder werden übersprungen.
"""
import argparse
import difflib
import glob
import hashlib
import html
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen

try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CONTEXT = ssl.create_default_context()

NS = {"wp": "http://wordpress.org/export/1.2/",
      "content": "http://purl.org/rss/1.0/modules/content/",
      "excerpt": "http://wordpress.org/export/1.2/excerpt/",
      "dc": "http://purl.org/dc/elements/1.1/"}

SPARTE = "Triathlon"
WP_KATEGORIEN = {"Triathlon"}                 # WordPress-Kategorie(n) für die Sparte
WP_TAGS = {"Triathlon", "Triathlon-Team"}      # … oder einer dieser Tags
# Kategorien/Tags ohne Aussagekraft als Schlagwort
GENERISCH = {"Featured", "Sonstiges", "Archiv", "Aktuelles", "Allgemein", "Uncategorized",
             "Besonderes", "Fragen", "Jahr 2012", "2013", "2014", "2015", "Sonntag"}
# Wörter, die zwar WP-Tags sind, aber in fast jedem Triathlon-Post vorkommen -> nicht automatisch vergeben
NICHT_AUTOMATISCH = {"Laufen", "Training", "Verein", "Wettbewerb", "Wettkampf", "Winter",
                     "Triathlon-Team", "Radfahren", "Schwimmen"}
GROSS, KLEIN, QUALITAET = 1600, 400, 80
MERGE_TAGE, MERGE_AEHNLICHKEIT = 7, 0.55
BILD_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp")


# ----------------------------------------------------------------- Hilfen
def log(msg=""):
    print(msg, flush=True)


def text_aus_html(s):
    """HTML + Shortcodes -> lesbarer Text mit Absätzen."""
    s = re.sub(r"\[/?[a-zA-Z_][\w\-]*[^\]]*\]", " ", s)          # alle Shortcode-Tags
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)\s*</t[dh]>\s*<t[dh][^>]*>\s*", " · ", s)   # Tabellenzellen einer Zeile verbinden
    s = re.sub(r"(?i)</(p|div|h\d|li|tr|blockquote)>", "\n\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "• ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s).replace("\xa0", " ")
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"(?m)^\s*[•·]\s*$", "", s)                     # leere Aufzählungspunkte (nur Bilder)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def titel_aus_text(text, datum):
    erste = (text or "").strip().split("\n", 1)[0].strip()
    if not erste:
        return f"Fotos vom {datum[8:10]}.{datum[5:7]}.{datum[:4]}"
    m = re.match(r"(.{20,90}?[.!?])(\s|$)", erste)
    if m:
        return m.group(1)
    return erste if len(erste) <= 90 else erste[:87].rsplit(" ", 1)[0] + " …"


def normtext(s):
    return re.sub(r"\W+", " ", (s or "").lower()).strip()


def uploads_relpfad(url):
    """URL -> Pfad relativ zu wp-content/uploads, Größen-Suffix entfernt."""
    m = re.search(r"/wp-content/uploads/(.+?)(?:[?#].*)?$", url or "")
    if not m:
        return None, None
    rel = unquote(m.group(1))
    original = re.sub(r"-\d{2,5}x\d{2,5}(\.\w+)$", r"\1", rel)
    return rel, original


def http_get(url, timeout=30):
    with urlopen(Request(url, headers={"User-Agent": "rsg-archiv-import/1.0"}),
                 timeout=timeout, context=SSL_CONTEXT) as r:
        return r.read().decode("utf-8", errors="replace")


# ----------------------------------------------------------------- Bilder
class Bildwerk:
    """Verkleinert Bilder einmalig nach archiv/bilder/{gross,klein}/<schluessel>.jpg."""

    def __init__(self, ziel, aktiv):
        self.ziel, self.aktiv = ziel, aktiv
        self.sips = shutil.which("sips")
        self.pil = None
        if not self.sips:
            try:
                from PIL import Image  # noqa: F401
                self.pil = True
            except ImportError:
                self.pil = False
        self.neu = self.vorhanden = 0
        self.fehler = []
        if aktiv and not self.sips and not self.pil:
            log("  Hinweis: weder 'sips' (macOS) noch Pillow gefunden – Bilder werden nur kopiert.")

    def _konvertiere(self, quelle, ziel, kante):
        os.makedirs(os.path.dirname(ziel), exist_ok=True)
        tmp = ziel + ".part.jpg"
        if self.sips:
            subprocess.run(["sips", "-Z", str(kante), "-s", "format", "jpeg",
                            "-s", "formatOptions", str(QUALITAET), quelle, "--out", tmp],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        elif self.pil:
            from PIL import Image, ImageOps
            with Image.open(quelle) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                im.thumbnail((kante, kante))
                im.save(tmp, "JPEG", quality=QUALITAET, optimize=True)
        else:
            shutil.copyfile(quelle, tmp)
        os.replace(tmp, ziel)

    def _masse(self, pfad):
        try:
            if self.sips:
                out = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", pfad],
                                     capture_output=True, text=True).stdout
                w = re.search(r"pixelWidth: (\d+)", out)
                h = re.search(r"pixelHeight: (\d+)", out)
                return (int(w.group(1)), int(h.group(1))) if w and h else (None, None)
            if self.pil:
                from PIL import Image
                with Image.open(pfad) as im:
                    return im.size
        except Exception:
            pass
        return None, None

    def verarbeite(self, quelle, schluessel):
        """Gibt dict mit relativen Pfaden zurück oder None bei Fehler."""
        rel_g = f"bilder/gross/{schluessel}.jpg"
        rel_k = f"bilder/klein/{schluessel}.jpg"
        if not self.aktiv:
            return {"gross": rel_g, "klein": rel_k, "breite": None, "hoehe": None}
        abs_g, abs_k = os.path.join(self.ziel, rel_g), os.path.join(self.ziel, rel_k)
        try:
            if os.path.exists(abs_g) and os.path.exists(abs_k):
                self.vorhanden += 1
            else:
                self._konvertiere(quelle, abs_g, GROSS)
                self._konvertiere(quelle, abs_k, KLEIN)
                self.neu += 1
                if self.neu % 50 == 0:
                    log(f"    … {self.neu} Bilder konvertiert")
        except Exception as e:  # defektes Bild, unbekanntes Format …
            self.fehler.append(f"{quelle}: {e}")
            return None
        w, h = self._masse(abs_g)
        return {"gross": rel_g, "klein": rel_k, "breite": w, "hoehe": h}


# ----------------------------------------------------------------- WordPress
def lade_wordpress(basis, bericht):
    xmls = sorted(glob.glob(os.path.join(basis, "wordpress", "*.xml")))
    if not xmls:
        sys.exit(f"Kein WXR-Export in {basis}/wordpress/ gefunden.")
    log(f"WordPress: lese {os.path.basename(xmls[-1])} …")
    items = ET.parse(xmls[-1]).getroot().find("channel").findall("item")

    def t(i, k):
        return i.findtext(k, namespaces=NS) or ""

    anhang = {}  # attachment-ID -> (url, titel/caption)
    for i in items:
        if t(i, "wp:post_type") == "attachment":
            anhang[t(i, "wp:post_id")] = (t(i, "wp:attachment_url"), t(i, "excerpt:encoded") or "")

    beitraege = []
    for i in items:
        if t(i, "wp:post_type") != "post" or t(i, "wp:status") != "publish":
            continue
        kats = [c.text for c in i.findall("category") if c.get("domain") == "category" and c.text]
        tags = [c.text for c in i.findall("category") if c.get("domain") == "post_tag" and c.text]
        if not (WP_KATEGORIEN & set(kats) or WP_TAGS & set(tags)):
            continue
        roh = t(i, "content:encoded")
        meta = {m.findtext("wp:meta_key", namespaces=NS): m.findtext("wp:meta_value", namespaces=NS)
                for m in i.findall("wp:postmeta", NS)}

        # Bildunterschriften aus [caption]…[/caption] merken, dann Block aus dem Text nehmen
        captions = {}
        for cap in re.finditer(r"\[caption[^\]]*\](.*?)\[/caption\]", roh, flags=re.S):
            src = re.search(r'src="([^"]+)"', cap.group(1))
            txt = text_aus_html(re.sub(r"<img[^>]*>", "", cap.group(1)))
            if src and txt:
                captions[uploads_relpfad(src.group(1))[1]] = txt
        text_roh = re.sub(r"\[caption[^\]]*\].*?\[/caption\]", " ", roh, flags=re.S)

        # Bildkandidaten in Reihenfolge: Beitragsbild, <img> im Text, Galerien
        kandidaten = []  # (art, wert)
        if meta.get("_thumbnail_id") in anhang:
            kandidaten.append(("uploads", anhang[meta["_thumbnail_id"]][0]))
        for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', roh):
            kandidaten.append(("uploads", src))
        for m in re.finditer(r"\[(?:av_)?gallery[^\]]*ids=['\"]([\d,\s]+)['\"]", roh):
            for aid in re.findall(r"\d+", m.group(1)):
                if aid in anhang:
                    kandidaten.append(("uploads", anhang[aid][0]))
        for m in re.finditer(r"src=['\"]([^'\"]+/wp-content/uploads/[^'\"]+)['\"]", roh):  # av_image u. ä.
            kandidaten.append(("uploads", m.group(1)))
        if re.search(r"\[(singlepic|nggallery|imagebrowser|ngg)\b", roh):
            kandidaten.append(("ngg_seite", t(i, "link")))

        schlagworte = sorted({x for x in kats + tags
                              if x not in GENERISCH and x != SPARTE and not re.fullmatch(r"\d{4}", x)})
        beitraege.append({
            "id": f"wp-{t(i, 'wp:post_id')}",
            "quelle": ["wordpress"],
            "datum": t(i, "wp:post_date")[:10],
            "titel": html.unescape(t(i, "title")).strip(),
            "text": text_aus_html(text_roh),
            "sparte": SPARTE,
            "schlagworte": schlagworte,
            "original_url": t(i, "link"),
            "_kandidaten": kandidaten,
            "_captions": captions,
        })
    bericht["wp_beitraege"] = len(beitraege)
    log(f"  {len(beitraege)} Triathlon-Beiträge gefunden.")
    return beitraege


def ngg_bilder_von_seite(url, gallery_dir, cache):
    """NextGEN: Bild-URLs aus der live gerenderten alten Seite holen und lokal zuordnen.

    Erfolgreiche Zuordnungen landen in cache (relativ zu gallery_dir) und werden in
    wordpress/ngg_zuordnung.json gespeichert – so funktioniert ein Neubau auch noch,
    wenn die alte Seite abgeschaltet ist."""
    if url in cache:
        return [os.path.join(gallery_dir, r) for r in cache[url]]
    pfade = []
    try:
        seite = http_get(url)
        for u in re.findall(r"""/wp-content/gallery/([^"'\s)]+?\.(?:jpe?g|png|gif))""", seite, flags=re.I):
            u = unquote(u)
            teile = u.split("/")
            # Original statt Vorschau: …/thumbs/thumbs_x.jpg bzw. …/cache/x.jpg-nggid0…
            teile = [p for p in teile if p not in ("thumbs", "cache", "dynamic")]
            name = re.sub(r"^thumbs_", "", teile[-1])
            name = re.sub(r"-nggid\d+.*$", "", name)
            kandidat = os.path.join(gallery_dir, teile[0], name)
            if os.path.exists(kandidat) and kandidat not in pfade:
                pfade.append(kandidat)
    except Exception as e:
        log(f"  Hinweis: NextGEN-Bilder für {url} nicht abrufbar ({e})")
        return pfade          # Fehlschlag nicht speichern – beim nächsten Lauf erneut versuchen
    cache[url] = [os.path.relpath(p, gallery_dir) for p in pfade]
    return pfade


# ----------------------------------------------------------------- Facebook
def lade_facebook(basis, bericht):
    pfad = os.path.join(basis, "facebook", "posts.json")
    if not os.path.exists(pfad):
        sys.exit(f"{pfad} fehlt – erst rsg_fb_sichern.py ausführen.")
    log("Facebook: lese posts.json …")
    with open(pfad, encoding="utf-8") as f:
        posts = json.load(f)["posts"]
    beitraege, leer = [], 0
    for p in posts:
        text = (p.get("message") or "").strip()
        bilder = p.get("_bilder") or []
        if not text and not bilder:
            leer += 1
            continue
        links = []
        for a in (p.get("attachments") or {}).get("data", []):
            for u in (a.get("url"), (a.get("target") or {}).get("url")):
                if not u:
                    continue
                if "l.facebook.com/l.php" in u:
                    u = parse_qs(urlparse(u).query).get("u", [u])[0]
                links.append(u)
        links += re.findall(r"https?://\S+", text)
        datum = p["created_time"][:10]
        beitraege.append({
            "id": "fb-" + p["id"].split("_")[-1],
            "quelle": ["facebook"],
            "datum": datum,
            "titel": titel_aus_text(text, datum),
            "text": text,
            "sparte": SPARTE,          # Seite „RSG Böblingen Triathlon Team“
            "schlagworte": [],
            "original_url": p.get("permalink_url", ""),
            "_kandidaten": [("fb", os.path.join(basis, "facebook", b["datei"]), b.get("beschreibung", ""))
                            for b in bilder],
            "_links": links,
        })
    bericht["fb_beitraege"] = len(beitraege)
    bericht["fb_leer"] = leer
    log(f"  {len(beitraege)} Posts übernommen, {leer} ohne Text und Bild übersprungen.")
    return beitraege


# ----------------------------------------------------------------- Zusammenführen
def slug(url):
    m = re.search(r"rsg-boeblingen\.de/(\d{4}/\d{2}/[^/?#]+)", url or "")
    return m.group(1).rstrip("/") if m else None


def zusammenfuehren(wp, fb, bericht):
    """Facebook-Posts, die einen WordPress-Beitrag teilen oder fast gleich lauten, an diesen hängen."""
    nach_slug = {slug(b["original_url"]): b for b in wp if slug(b["original_url"])}
    behalten, merges = [], []
    for f in fb:
        ziel, grund = None, ""
        for u in f["_links"]:
            if slug(u) in nach_slug:
                ziel, grund = nach_slug[slug(u)], "Link auf WP-Beitrag"
                break
        if not ziel and len(f["text"]) > 120:
            fd = datetime.strptime(f["datum"], "%Y-%m-%d")
            ft = normtext(f["text"])[:600]
            best = (0, None)
            for w in wp:
                if abs((datetime.strptime(w["datum"], "%Y-%m-%d") - fd).days) > MERGE_TAGE:
                    continue
                r = difflib.SequenceMatcher(None, ft, normtext(w["text"])[:600]).ratio()
                if r > best[0]:
                    best = (r, w)
            if best[0] >= MERGE_AEHNLICHKEIT:
                ziel, grund = best[1], f"Textähnlichkeit {best[0]:.2f}"
        if ziel:
            ziel["quelle"] = sorted(set(ziel["quelle"]) | {"facebook"})
            ziel.setdefault("facebook_url", f["original_url"])
            if not ziel["_kandidaten"]:      # FB-Fotos nur, wenn der WP-Beitrag selbst keine hat
                ziel["_kandidaten"] += f["_kandidaten"]
            merges.append(f"{f['id']} ({f['datum']}) → {ziel['id']} „{ziel['titel'][:60]}“ [{grund}]")
        else:
            behalten.append(f)
    bericht["zusammengefuehrt"] = merges
    return wp + behalten


def verschlagworten(beitraege, bericht):
    """Facebook-Posts bekommen Schlagworte aus dem WordPress-Tag-Vokabular (Wortgrenzen, ohne Groß/Klein)."""
    zaehler = Counter(s for b in beitraege if "wordpress" in b["quelle"] for s in b["schlagworte"])
    vokabular = [s for s, n in zaehler.items() if n >= 2 and len(s) >= 4 and s not in NICHT_AUTOMATISCH]
    muster = [(s, re.compile(r"(?<!\w)" + re.escape(s) + r"(?!\w)", re.I)) for s in vokabular]
    gesetzt = 0
    for b in beitraege:
        if b["schlagworte"]:
            continue
        treffer = sorted({s for s, m in muster if m.search(b["text"])})
        if treffer:
            b["schlagworte"] = treffer
            gesetzt += 1
    bericht["fb_verschlagwortet"] = gesetzt
    bericht["vokabular"] = len(vokabular)


# ----------------------------------------------------------------- Hauptprogramm
def main():
    ap = argparse.ArgumentParser(description="RSG-Archiv aus WordPress + Facebook bauen")
    ap.add_argument("--basis", default=os.path.expanduser("~/rsg-archiv-import"))
    ap.add_argument("--ohne-bilder", action="store_true", help="nur Texte, keine Bildkonvertierung")
    args = ap.parse_args()
    basis = os.path.abspath(args.basis)
    ziel = os.path.join(basis, "archiv")
    os.makedirs(ziel, exist_ok=True)
    bericht = {}

    sperre = set()
    sp = os.path.join(basis, "sperrliste.txt")
    if os.path.exists(sp):
        with open(sp, encoding="utf-8") as f:
            sperre = {z.split("#", 1)[0].strip() for z in f if z.split("#", 1)[0].strip()}
        log(f"Sperrliste: {len(sperre)} Einträge")

    wp = lade_wordpress(basis, bericht)
    fb = lade_facebook(basis, bericht)
    alle = zusammenfuehren(wp, fb, bericht)
    verschlagworten(alle, bericht)

    gesperrt = [b["id"] for b in alle if b["id"] in sperre]
    alle = [b for b in alle if b["id"] not in sperre]

    log(f"\nBilder {'(übersprungen)' if args.ohne_bilder else 'verkleinern'} …")
    werk = Bildwerk(ziel, not args.ohne_bilder)
    uploads = os.path.join(basis, "wordpress", "uploads")
    gallery = os.path.join(basis, "wordpress", "gallery")
    ngg_datei = os.path.join(basis, "wordpress", "ngg_zuordnung.json")
    try:
        with open(ngg_datei, encoding="utf-8") as f:
            ngg_cache = json.load(f)
    except (OSError, ValueError):
        ngg_cache = {}
    fehlend, gesperrte_bilder = [], 0
    for b in alle:
        quellen = []  # (absoluter Pfad, Beschreibung)
        for k in b.pop("_kandidaten"):
            art = k[0]
            if art == "uploads":
                rel, original = uploads_relpfad(k[1])
                if not rel:
                    continue  # externes Bild (gpsies, wikimedia …) – nicht übernehmen
                treffer = next((os.path.join(uploads, p) for p in (original, rel)
                                if os.path.exists(os.path.join(uploads, p))), None)
                if treffer:
                    quellen.append((treffer, b.get("_captions", {}).get(original, "")))
                else:
                    fehlend.append(f"{b['id']}: uploads/{original}")
            elif art == "ngg_seite":
                quellen += [(p, "") for p in ngg_bilder_von_seite(k[1], gallery, ngg_cache)]
            elif art == "fb":
                if os.path.exists(k[1]):
                    quellen.append((k[1], k[2]))
                else:
                    fehlend.append(f"{b['id']}: {k[1]}")
        b.pop("_captions", None)
        b.pop("_links", None)
        gesehen, bilder = set(), []
        for pfad, beschr in quellen:
            if pfad in gesehen or not pfad.lower().endswith(BILD_EXT):
                continue
            gesehen.add(pfad)
            if os.path.basename(pfad) in sperre:
                gesperrte_bilder += 1
                continue
            # Dateiname aus der Quelldatei abgeleitet: stabil bei erneuten Läufen und Sperrungen
            schluessel = hashlib.sha1(os.path.relpath(pfad, basis).encode("utf-8")).hexdigest()[:12]
            info = werk.verarbeite(pfad, f"{b['id']}/{schluessel}")
            if info:
                info["beschreibung"] = beschr or f"{b['titel']} ({b['datum'][8:10]}.{b['datum'][5:7]}.{b['datum'][:4]})"
                bilder.append(info)
        b["bilder"] = bilder

    if ngg_cache:
        with open(ngg_datei, "w", encoding="utf-8") as f:
            json.dump(ngg_cache, f, ensure_ascii=False, indent=1)

    alle.sort(key=lambda b: b["datum"], reverse=True)
    reihenfolge = ["id", "quelle", "datum", "titel", "text", "bilder", "sparte", "schlagworte",
                   "original_url", "facebook_url"]
    alle = [{k: b[k] for k in reihenfolge if k in b} for b in alle]
    meta = {"erstellt": datetime.now().isoformat(timespec="seconds"), "sparte": SPARTE,
            "anzahl": len(alle), "bilder_konvertiert": not args.ohne_bilder}
    with open(os.path.join(ziel, "archiv.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "beitraege": alle}, f, ensure_ascii=False, indent=1)

    # Bericht
    n_bilder = sum(len(b["bilder"]) for b in alle)
    jahre = Counter(b["datum"][:4] for b in alle)
    zeilen = [
        f"RSG-Archiv-Import {meta['erstellt']} – Sparte {SPARTE}",
        "",
        f"Beiträge im Archiv:      {len(alle)}",
        f"  aus WordPress:         {bericht['wp_beitraege']}",
        f"  aus Facebook:          {bericht['fb_beitraege']} (davon {len(bericht['zusammengefuehrt'])} mit WP-Beitrag zusammengeführt)",
        f"  FB ohne Text/Bild:     {bericht['fb_leer']} übersprungen",
        f"  gesperrt:              {len(gesperrt)} Beiträge, {gesperrte_bilder} Bilder",
        f"Zeitraum:                {alle[-1]['datum']} bis {alle[0]['datum']}" if alle else "",
        "Pro Jahr:                " + ", ".join(f"{j}: {n}" for j, n in sorted(jahre.items())),
        f"Ohne Bild:               {sum(1 for b in alle if not b['bilder'])}",
        f"Bilder:                  {n_bilder} (neu konvertiert {werk.neu}, vorhanden {werk.vorhanden}, Fehler {len(werk.fehler)})",
        f"Fehlende Bilddateien:    {len(fehlend)}",
        f"FB verschlagwortet:      {bericht['fb_verschlagwortet']} Posts (Vokabular {bericht['vokabular']} Schlagworte)",
        "",
        "== Zusammengeführt (bitte stichprobenartig prüfen) ==", *bericht["zusammengefuehrt"],
        "", "== Fehlende Bilddateien ==", *fehlend,
        "", "== Bildfehler ==", *werk.fehler,
    ]
    with open(os.path.join(ziel, "bericht.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(zeilen) + "\n")

    log("\n================ ERGEBNIS ================")
    for z in zeilen[2:13]:
        log(z)
    log(f"\nAusgabe: {ziel}  (Details in bericht.txt)")
    log("Bitte diese Ausgabe ab '==== ERGEBNIS ====' in den Chat kopieren.")


if __name__ == "__main__":
    main()
