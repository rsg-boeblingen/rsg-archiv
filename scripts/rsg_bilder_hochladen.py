#!/usr/bin/env python3
"""RSG Böblingen – fehlende Archiv-Bilder per SFTP hochladen (läuft auf dem Mac).

Vergleicht die Bildordner in ~/rsg-archiv-import/archiv/bilder/{gross,klein}/<beitrags-id>/
mit dem Server (/new/archiv/bilder/…) und lädt nur Ordner hoch, die dort noch fehlen –
z. B. nach dem Hinzufügen neuer Sparten oder neuer Facebook-Posts.

Aufruf:
    python3 rsg_bilder_hochladen.py --user DEIN_SFTP_USER            # fragt 2x nach dem Passwort
    python3 rsg_bilder_hochladen.py --user DEIN_SFTP_USER --probe    # nur anzeigen, was fehlt

Das SFTP-Passwort wird von sftp selbst abgefragt (zweimal: Liste holen, hochladen)
und nirgends gespeichert. Auf dem Server wird nichts gelöscht.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

HOST = "home115502871.1and1-data.host"
REMOTE = "/new/archiv/bilder"
GROESSEN = ("gross", "klein")


def sftp(user, zeilen):
    """Führt Batch-Befehle in einer interaktiven sftp-Sitzung aus (Passwort per Tastatur)."""
    with tempfile.NamedTemporaryFile("w", suffix=".batch", delete=False) as f:
        f.write("\n".join(zeilen) + "\n")
        batch = f.name
    try:
        # -oBatchMode=no MUSS vor -b stehen, sonst ist die Passwortabfrage abgeschaltet
        return subprocess.run(["sftp", "-oBatchMode=no", "-P", "22", "-b", batch, f"{user}@{HOST}"],
                              stdout=subprocess.PIPE, text=True)
    finally:
        os.unlink(batch)


def main():
    ap = argparse.ArgumentParser(description="Fehlende Archiv-Bilder hochladen")
    ap.add_argument("--user", required=True, help="SFTP-Benutzername (wie für rsg-web)")
    ap.add_argument("--basis", default=os.path.expanduser("~/rsg-archiv-import"))
    ap.add_argument("--probe", action="store_true", help="nur anzeigen, nichts hochladen")
    args = ap.parse_args()

    archiv = os.path.join(os.path.abspath(args.basis), "archiv")
    with open(os.path.join(archiv, "archiv.json"), encoding="utf-8") as f:
        beitraege = json.load(f)["beitraege"]
    benoetigt = sorted({b["id"] for b in beitraege if b.get("bilder")})
    lokal_fehlt = [i for i in benoetigt
                   if not all(os.path.isdir(os.path.join(archiv, "bilder", g, i)) for g in GROESSEN)]
    if lokal_fehlt:
        sys.exit(f"{len(lokal_fehlt)} Bildordner fehlen lokal (z. B. {lokal_fehlt[0]}) – "
                 "erst rsg_archiv_import.py ohne --ohne-bilder laufen lassen.")

    print(f"{len(benoetigt)} Beiträge mit Bildern im Archiv. Hole Ordnerliste vom Server …")
    r = sftp(args.user, [f"-ls -1 {REMOTE}/{g}" for g in GROESSEN])
    if r.returncode != 0:
        sys.exit("Verbindung fehlgeschlagen.")
    vorhanden = {g: set() for g in GROESSEN}
    aktuell = None
    for zeile in r.stdout.splitlines():
        zeile = zeile.strip()
        for g in GROESSEN:
            if zeile.startswith("sftp>") and zeile.endswith(f"{REMOTE}/{g}"):
                aktuell = g
        if aktuell and not zeile.startswith("sftp>") and zeile:
            vorhanden[aktuell].add(os.path.basename(zeile.rstrip("/")))

    fehlend = [(g, i) for g in GROESSEN for i in benoetigt if i not in vorhanden[g]]
    ueberzaehlig = sorted(set().union(*vorhanden.values()) - set(benoetigt))
    print(f"Auf dem Server: {len(vorhanden['gross'])} / {len(vorhanden['klein'])} Ordner (groß/klein)")
    print(f"Fehlend: {len(fehlend)} Ordner")
    if ueberzaehlig:
        print(f"Hinweis: {len(ueberzaehlig)} Ordner auf dem Server gehören zu keinem Beitrag mehr "
              f"(z. B. gesperrt): {', '.join(ueberzaehlig[:5])}{' …' if len(ueberzaehlig) > 5 else ''}")
    if not fehlend:
        print("Nichts zu tun.")
        return
    if args.probe:
        for g, i in fehlend[:20]:
            print(f"  {g}/{i}")
        print("  …" if len(fehlend) > 20 else "")
        return

    zeilen = [f"-mkdir {REMOTE}/{g}" for g in GROESSEN]
    zeilen += [f'put -r "{os.path.join(archiv, "bilder", g, i)}" "{REMOTE}/{g}/{i}"' for g, i in fehlend]
    print(f"Lade {len(fehlend)} Ordner hoch …")
    r = sftp(args.user, zeilen)
    if r.returncode != 0:
        sys.exit("Hochladen mit Fehler abgebrochen – einfach erneut starten, Vorhandenes wird übersprungen.")
    print("\n================ ERGEBNIS ================")
    print(f"Hochgeladen: {len(fehlend)} Bildordner nach {REMOTE}")


if __name__ == "__main__":
    main()
