# RSG Böblingen – Archiv Triathlon

Durchsuchbares Archiv der früheren Triathlon-Beiträge der RSG Böblingen e.V.:
die alte WordPress-Website (2007–2025) und die Facebook-Seite
„RSG Böblingen Triathlon Team“ (2012–heute), zusammen rund 670 Beiträge mit
rund 1.200 Fotos.

Live (passwortgeschützte Vorschau): https://rsg-boeblingen.de/archiv/

## Aufbau

| Pfad | Inhalt |
| --- | --- |
| `scripts/` | Python-Scripts für Sicherung, Import und Seitenbau (laufen lokal auf dem Mac) |
| `site/` | fertige Website: `index.html` (Suche), `b/<id>.html` (Beiträge), `pagefind/` (Suchindex), `archiv.css/js`, `.htaccess` (Passwortschutz) |
| `.github/workflows/deploy.yml` | lädt `site/` bei jedem Push auf `main` per SFTP nach `/new/archiv` |

**Nicht im Repo** (liegen lokal unter `~/rsg-archiv-import/` auf dem Mac Studio):
Quelldaten (WXR-Export, WordPress-Uploads, Facebook-Sicherung), `archiv.json`
und die verkleinerten Bilder. Die Bilder werden einmalig per SFTP nach
`/new/archiv/bilder` hochgeladen.

Header, Navigation, Footer, `style.css` und die Schriften kommen von der
Hauptseite (Repo `rsg-web`), eingebunden über Pfade wie `/css/style.css`.
Das Archiv funktioniert deshalb nur unter derselben Domain.

## Archiv neu bauen (lokal)

```
python3 ~/webdev/rsg-archiv/scripts/rsg_archiv_import.py     # Quellen → archiv.json + Bilder
python3 ~/webdev/rsg-archiv/scripts/rsg_archiv_seiten.py     # Seiten + Suchindex
rsync -a --delete --exclude bilder --exclude '_*' --exclude archiv.json \
      --exclude bericht.txt --exclude robots.txt --exclude .htaccess \
      ~/rsg-archiv-import/archiv/ ~/webdev/rsg-archiv/site/
cd ~/webdev/rsg-archiv && git add -A site && git commit -m "Archiv aktualisiert" && git push
```

Neue oder geänderte Bilder anschließend per SFTP nach `/new/archiv/bilder` hochladen.

Voraussetzung: `pip3 install --user 'pagefind[extended]'`.

## Beiträge oder Fotos entfernen

Die ID des Beitrags (z. B. `fb-1503906198423322` oder `wp-15017`, steht in der
Adresse der Beitragsseite) bzw. den Dateinamen des Bildes in
`~/rsg-archiv-import/sperrliste.txt` eintragen (eine Zeile pro Eintrag) und das
Archiv neu bauen. Der Deploy löscht keine Dateien auf dem Server: die Seite
`/new/archiv/b/<id>.html` und die Bilder unter `/new/archiv/bilder/*/<id>/`
zusätzlich per SFTP löschen.

## Passwortschutz

`site/.htaccess` verlangt einen Login (HTTP Basic Auth). Die Passwortdatei
`/.htpasswd-archiv` liegt im Webspace-Stamm (außerhalb von `/new`) und wird nur
per SFTP gepflegt, nie im Repo. Zum Freischalten für alle: die Zeilen
`AuthType` … `Require valid-user` aus `site/.htaccess` entfernen.
