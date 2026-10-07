# CLAUDE.md

Archiv-Suche der RSG Böblingen (Triathlon). Statische Seiten + Pagefind-Suchindex,
ausgeliefert unter https://rsg-boeblingen.de/archiv/ (IONOS-Pfad `/new/archiv`).
Siehe README.md für Aufbau und Arbeitsablauf.

- `site/` ist generiert (von `scripts/rsg_archiv_seiten.py` auf dem Mac) – Seiten nicht
  von Hand ändern, sondern das Script anpassen und neu bauen.
- Jeder Push auf `main`, der `site/` ändert, geht sofort live. Keine Änderungen auf
  `main` ohne Rückfrage; Branch + Pull Request.
- `site/.htaccess` enthält den Passwortschutz – nie entfernen oder ändern ohne
  ausdrückliche Freigabe.
- Header/Footer/CSS/Schriften kommen von der Hauptseite (Repo `rsg-web`) über
  root-relative Pfade (`/css/style.css?v=N`). Wird dort `style.css` geändert und die
  Version erhöht, `CSS_VERSION` in `rsg_archiv_seiten.py` nachziehen.
- Quelldaten, `archiv.json` und Bilder liegen nicht im Repo, sondern lokal unter
  `~/rsg-archiv-import/` – personenbezogene Fotos nie committen.
- Python 3.9 kompatibel halten (macOS Command Line Tools).
