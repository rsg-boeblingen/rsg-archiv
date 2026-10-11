# RSG Böblingen – Vereinsarchiv

Durchsuchbares Archiv früherer Beiträge der RSG Böblingen e.V. aus allen Sparten
(Triathlon, Blindensport, Radsport, Verein): die alte WordPress-Website (2006–2025,
eingefroren) und die Facebook-Seite „RSG Böblingen Triathlon Team“ (2012–heute,
nur Triathlon). Rund 540 Beiträge. Nicht aufgenommen: Vorstandsprotokolle,
Nachrufe und Facebook-Wochenpläne (Beschluss 9.10.2026, Regeln in `rsg_archiv_import.py`).

Live: https://rsg-boeblingen.de/archiv/ (öffentlich, für Suchmaschinen gesperrt)

## Aufbau

| Pfad | Inhalt |
| --- | --- |
| `scripts/` | Python-Scripts für Sicherung, Import und Seitenbau (laufen lokal auf dem Mac) |
| `site/` | fertige Website: `index.html` (Suche), `b/<id>.html` (Beiträge), `pagefind/` (Suchindex), `archiv.css/js`, `.htaccess` (Suchmaschinen-Sperre) |
| `.github/workflows/deploy.yml` + `scripts/deploy.py` | lädt bei jedem Push auf `main` nur die geänderten Dateien aus `site/` per SFTP nach `/new/archiv` und löscht entfernte Dateien dort; ein Voll-Deploy lässt sich unter Actions → Run workflow → „voll“ starten |

**Nicht im Repo** (liegen lokal unter `~/rsg-archiv-import/` auf dem Mac Studio):
Quelldaten (WXR-Export, WordPress-Uploads, Facebook-Sicherung), `archiv.json`
und die verkleinerten Bilder. Die Bilder werden einmalig per SFTP nach
`/new/archiv/bilder` hochgeladen.

Header, Navigation, Footer, `style.css` und die Schriften kommen von der
Hauptseite (Repo `rsg-web`), eingebunden über Pfade wie `/css/style.css`.
Das Archiv funktioniert deshalb nur unter derselben Domain.

## Archiv neu bauen (lokal)

```
cd ~/webdev/rsg-archiv && git pull
python3 scripts/rsg_archiv_import.py                          # Quellen → archiv.json + Bilder
python3 scripts/rsg_archiv_seiten.py --repo ~/webdev/rsg-archiv   # Seiten + Suchindex, direkt nach site/
git add -A site && git commit -m "Archiv aktualisiert" && git push
```

`--repo` kopiert die fertigen Seiten nach `site/` und entfernt dort alles, was nicht
dazugehört (außer `.htaccess`). Ohne `--repo` wird nur lokal unter
`~/rsg-archiv-import/archiv/` gebaut (Vorschau).

Neue Bilder anschließend hochladen – lädt nur die Ordner, die auf dem Server noch fehlen:

```
python3 scripts/rsg_bilder_hochladen.py --user DEIN_SFTP_USER
```

Voraussetzung: `pip3 install --user 'pagefind[extended]'`.

## Beiträge oder Fotos entfernen

Löschwünsche kommen per Mail an web@rsg-boeblingen.de (Hinweis auf jeder
Archivseite; auf Beitragsseiten enthält der Betreff die Beitrags-ID).

Die ID des Beitrags (z. B. `fb-1503906198423322` oder `wp-15017`, steht in der
Adresse der Beitragsseite) bzw. den Dateinamen des Bildes in
`~/rsg-archiv-import/sperrliste.txt` eintragen (eine Zeile pro Eintrag) und das
Archiv neu bauen und pushen. Die Beitragsseite löscht der Deploy auf dem Server
automatisch; die Bilder unter `/new/archiv/bilder/*/<id>/` (nicht im Repo) per SFTP löschen.

## Passwortschutz

Während der Feedback-Phase war das Archiv per HTTP Basic Auth geschützt
(`/.htpasswd-archiv` im Webspace-Stamm). Seit dem öffentlichen Start enthält
`site/.htaccess` nur noch die Suchmaschinen-Sperre (`X-Robots-Tag: noindex`).
Für eine erneute Vorschau-Phase die Zeilen `AuthType Basic`, `AuthName`,
`AuthUserFile /homepages/42/d115502871/htdocs/.htpasswd-archiv` und
`Require valid-user` wieder eintragen.

## Pflege

| Wann | Was |
| --- | --- |
| alle paar Monate | Neue Facebook-Posts übernehmen: `rsg_fb_sichern.py` → `rsg_archiv_import.py` → `rsg_archiv_seiten.py --repo …` → push (siehe „Archiv neu bauen“), dann `rsg_bilder_hochladen.py` |
| bei Löschwunsch | ID in `sperrliste.txt`, neu bauen, pushen; Bilder auf dem Server per SFTP löschen (siehe oben) |
| wenn `style.css?v=N` in `rsg-web` erhöht wird | `CSS_VERSION` in `scripts/rsg_archiv_seiten.py` anpassen und neu bauen |
| regelmäßig | `~/rsg-archiv-import/` sichern (Time Machine / externe Platte) – einzige Kopie der Quelldaten |

Vor dem Abschalten von alt.rsg-boeblingen.de den Import einmal laufen lassen, damit
`wordpress/ngg_zuordnung.json` (Zuordnung der NextGEN-Galeriebilder) angelegt ist.
