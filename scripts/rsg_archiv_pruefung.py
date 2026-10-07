#!/usr/bin/env python3
"""RSG Böblingen – Prüfseite für zusammengeführte Beiträge (nur lokal).

Baut <basis>/archiv/_pruefung.html: für jeden Facebook-Post, der mit einem
WordPress-Beitrag zusammengeführt wurde, beide Texte nebeneinander –
die unsichersten Zuordnungen zuerst.

Aufruf:   python3 rsg_archiv_pruefung.py
Ansehen:  wie das Archiv über den laufenden Webserver → …:8000/_pruefung.html

Die Datei beginnt mit "_" und wird beim späteren Veröffentlichen ausgelassen.
"""
import argparse
import html
import json
import os
import re
import sys

E = html.escape


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--basis", default=os.path.expanduser("~/rsg-archiv-import"))
    basis = os.path.abspath(ap.parse_args().basis)
    archiv = os.path.join(basis, "archiv")
    try:
        with open(os.path.join(archiv, "bericht.txt"), encoding="utf-8") as f:
            bericht = f.read()
        with open(os.path.join(archiv, "archiv.json"), encoding="utf-8") as f:
            beitraege = {b["id"]: b for b in json.load(f)["beitraege"]}
        with open(os.path.join(basis, "facebook", "posts.json"), encoding="utf-8") as f:
            fb = {"fb-" + p["id"].split("_")[-1]: p for p in json.load(f)["posts"]}
    except OSError as e:
        sys.exit(f"Datei fehlt: {e} – erst rsg_archiv_import.py ausführen.")

    zeilen = []
    for m in re.finditer(r"^(fb-\d+) \((\S+)\) → (wp-\d+) .*\[(.+)\]$", bericht, flags=re.M):
        fid, fdatum, wid, grund = m.groups()
        sicher = re.search(r"([\d.]+)$", grund)
        wert = float(sicher.group(1)) if sicher else 1.0
        zeilen.append((wert, fid, fdatum, wid, grund))
    zeilen.sort()

    def kurz(t, n=700):
        t = (t or "").strip()
        return E(t if len(t) <= n else t[:n] + " …")

    blöcke = []
    for nr, (wert, fid, fdatum, wid, grund) in enumerate(zeilen, 1):
        w, p = beitraege.get(wid), fb.get(fid, {})
        if not w:
            continue
        farbe = "#cc2222" if wert < 0.7 else "#e8a019" if wert < 0.85 else "#2e7d32"
        blöcke.append(f"""
<section>
  <h2><span class="nr">{nr}</span> <span class="wert" style="background:{farbe}">{E(grund)}</span></h2>
  <div class="paar">
    <div><h3>Facebook · {E(fdatum)}</h3><p>{kurz(p.get("message"))}</p>
      <a href="{E(p.get("permalink_url", ""))}" target="_blank" rel="noopener">auf Facebook</a> · <code>{fid}</code></div>
    <div><h3>Alte Website · {E(w["datum"])}</h3><p><b>{E(w["titel"])}</b><br>{kurz(w["text"])}</p>
      <a href="b/{wid}.html" target="_blank">im Archiv öffnen</a> · <code>{wid}</code></div>
  </div>
</section>""")

    seite = f"""<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>Prüfung zusammengeführter Beiträge</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;margin:0;padding:16px;color:#2d2d2d;max-width:1170px;margin:auto;line-height:1.45}}
h1{{color:#1a3a8f;font-size:1.5rem}} .lead{{color:#555}}
section{{border:1px solid #d9dce6;border-radius:12px;padding:12px 16px;margin:14px 0}}
h2{{font-size:1rem;margin:0 0 8px;display:flex;gap:8px;align-items:center}}
.nr{{color:#555}} .wert{{color:#fff;border-radius:999px;padding:2px 10px;font-size:.8rem}}
.paar{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
h3{{font-size:.85rem;color:#1a3a8f;margin:0 0 4px}} p{{white-space:pre-line;font-size:.9rem;margin:0 0 6px}}
code{{background:#f4f6fb;padding:1px 6px;border-radius:4px;user-select:all}}
@media(max-width:700px){{.paar{{grid-template-columns:1fr}}}}
</style></head><body>
<h1>Zusammengeführte Beiträge prüfen ({len(blöcke)})</h1>
<p class="lead">Links der Facebook-Post, rechts der WordPress-Beitrag, mit dem er zusammengeführt wurde.
Rot und orange = unsicher, grün = (fast) identischer Text oder direkter Link. Falsche Paare bitte notieren (die IDs lassen sich antippen und kopieren).</p>
{''.join(blöcke)}
</body></html>"""
    ziel = os.path.join(archiv, "_pruefung.html")
    with open(ziel, "w", encoding="utf-8") as f:
        f.write(seite)
    unsicher = sum(1 for z in zeilen if z[0] < 0.85)
    print(f"{len(blöcke)} Paare, davon {unsicher} unsicher (unter 0,85) – ganz oben auf der Seite.")
    print("Öffnen: …:8000/_pruefung.html (Webserver muss laufen)")


if __name__ == "__main__":
    main()
