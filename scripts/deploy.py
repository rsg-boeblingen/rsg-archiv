#!/usr/bin/env python3
"""Inkrementeller SFTP-Deploy von site/ nach IONOS (läuft in der GitHub Action).

Auf dem Server liegt <REMOTE_DIR>/.deploy-sha mit dem zuletzt hochgeladenen Commit.
Hochgeladen werden nur die Dateien unter site/, die sich seitdem geändert haben;
gelöschte Dateien werden auch auf dem Server gelöscht. Alles in EINER SFTP-Sitzung.

Fehlt .deploy-sha (erster Lauf), dient der Commit vor dem Push als Basis
(github.event.before, Umgebungsvariable BASIS_SHA). Ist auch der unbrauchbar
oder ist VOLL=true gesetzt, wird alles hochgeladen.

Umgebung: SFTP_HOST, SFTP_USER, SSHPASS (Passwort), REMOTE_DIR (Standard /new/archiv),
          VOLL (true/false), BASIS_SHA (optional),
          SFTP_BEFEHL (nur für Tests: Ersatz für "sshpass -e sftp …").
Aufruf zum Ausprobieren ohne Verbindung:  python3 scripts/deploy.py --probe
"""
import os
import posixpath
import shlex
import subprocess
import sys
import tempfile

REMOTE = os.environ.get("REMOTE_DIR", "/new/archiv").rstrip("/")
NULL_SHA = "0" * 40


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def ist_commit(sha):
    if not sha or sha == NULL_SHA:
        return False
    return subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"],
                          capture_output=True).returncode == 0


def sftp_befehl():
    if os.environ.get("SFTP_BEFEHL"):
        return shlex.split(os.environ["SFTP_BEFEHL"])
    return ["sshpass", "-e", "sftp", "-oStrictHostKeyChecking=accept-new", "-oBatchMode=no",
            "-P", "22", f"{os.environ['SFTP_USER']}@{os.environ['SFTP_HOST']}"]


def sftp_batch(zeilen, pruefen=True):
    """Führt Batch-Befehle in einer SFTP-Sitzung aus. Zeilen mit '-' vorn dürfen fehlschlagen."""
    with tempfile.NamedTemporaryFile("w", suffix=".batch", delete=False) as f:
        f.write("\n".join(zeilen) + "\n")
        name = f.name
    r = subprocess.run([*sftp_befehl(), "-b", name], capture_output=True, text=True)
    os.unlink(name)
    if pruefen and r.returncode != 0:
        print(r.stdout[-3000:])
        print(r.stderr[-3000:], file=sys.stderr)
        sys.exit(f"SFTP fehlgeschlagen (Exit {r.returncode})")
    return r


def q(pfad):
    return '"' + pfad.replace('"', '\\"') + '"'


def remote_pfad(datei):  # site/b/x.html -> /new/archiv/b/x.html
    return posixpath.join(REMOTE, posixpath.relpath(datei, "site"))


def main():
    probe = "--probe" in sys.argv
    neu = git("rev-parse", "HEAD").strip()

    # 1) Zuletzt deployten Stand vom Server holen
    alt = ""
    if not probe:
        with tempfile.TemporaryDirectory() as tmp:
            ziel = os.path.join(tmp, "sha")
            sftp_batch([f"-get {q(REMOTE + '/.deploy-sha')} {q(ziel)}"], pruefen=False)
            if os.path.exists(ziel):
                alt = open(ziel).read().strip()

    voll = os.environ.get("VOLL", "false").lower() == "true"
    basis, herkunft = None, ""
    if not voll:
        if ist_commit(alt):
            basis, herkunft = alt, "Stand auf dem Server"
        elif ist_commit(os.environ.get("BASIS_SHA", "")):
            basis, herkunft = os.environ["BASIS_SHA"], "Commit vor dem Push"

    # 2) Änderungen ermitteln
    hoch, weg = [], []
    if basis:
        for zeile in git("diff", "--no-renames", "--name-status", basis, neu, "--", "site/").splitlines():
            status, datei = zeile.split("\t", 1)
            (weg if status == "D" else hoch).append(datei)
        modus = f"inkrementell seit {basis[:7]} ({herkunft})"
    else:
        hoch = [d for d in git("ls-files", "site/").splitlines()]
        modus = "voll (alle Dateien)"
    # Passwortschutz immer zuerst
    hoch.sort(key=lambda d: (d != "site/.htaccess", d))

    # 3) Batch bauen: Ordner anlegen (Fehler = existiert schon), hochladen, löschen
    ordner = set()
    for d in hoch:
        teil = posixpath.dirname(remote_pfad(d))
        while teil.startswith(REMOTE) and teil not in ordner:
            ordner.add(teil)
            teil = posixpath.dirname(teil)
    zeilen = [f"-mkdir {q(o)}" for o in sorted(ordner, key=lambda o: (o.count("/"), o))]
    zeilen += [f"put {q(d)} {q(remote_pfad(d))}" for d in hoch]
    zeilen += [f"-rm {q(remote_pfad(d))}" for d in weg]

    print(f"Deploy {neu[:7]}: {modus}")
    print(f"  hochladen: {len(hoch)} Datei(en), löschen: {len(weg)} Datei(en)")
    if probe:
        print("\n".join(zeilen[:40]) + ("\n…" if len(zeilen) > 40 else ""))
        return

    if zeilen:
        sftp_batch(zeilen)
    # 4) Neuen Stand auf dem Server vermerken
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        f.write(neu + "\n")
        sha_datei = f.name
    sftp_batch([f"put {q(sha_datei)} {q(REMOTE + '/.deploy-sha')}"])
    os.unlink(sha_datei)

    zusammenfassung = os.environ.get("GITHUB_STEP_SUMMARY")
    if zusammenfassung:
        with open(zusammenfassung, "a") as f:
            f.write(f"### Archiv-Deploy\n\n- Modus: {modus}\n- hochgeladen: {len(hoch)}\n"
                    f"- gelöscht: {len(weg)}\n- Stand: `{neu[:7]}`\n")
    print("Fertig.")


if __name__ == "__main__":
    main()
