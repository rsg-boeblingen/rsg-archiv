#!/usr/bin/env python3
"""RSG Böblingen – Facebook-Archiv sichern (Phase 2, nur lokal).

Holt ALLE Posts der Facebook-Seite mit frischen Bild-URLs und lädt sofort
alle Fotos (inkl. Alben) in einen lokalen Ordner. Es wird nichts gepostet,
nichts auf GitHub gepusht und nichts auf den Webserver geladen.

Ergebnis (Standard: ~/rsg-archiv-import/facebook/):
    posts.json        alle Posts + Liste der lokal gespeicherten Bilder
    bilder/<post-id>/01.jpg, 02.jpg, ...
    fehler.log        Bilder, die nicht geladen werden konnten

Aufruf:
    python3 rsg_fb_sichern.py                # alles sichern
    python3 rsg_fb_sichern.py --test 10      # Probelauf mit den 10 neuesten Posts
    python3 rsg_fb_sichern.py --schnell      # ohne Volle-Auflösung-Abfrage (weniger API-Aufrufe)
    python3 rsg_fb_sichern.py --ziel PFAD    # anderer Zielordner

Bereits geladene Bilder werden übersprungen – ein abgebrochener Lauf kann
einfach neu gestartet werden. Der Token wird versteckt abgefragt (oder aus
FB_PAGE_ACCESS_TOKEN gelesen) und nirgends gespeichert.
"""
import argparse
import getpass
import json
import os
import ssl
import sys
import time
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CONTEXT = ssl.create_default_context()

PAGE_ID = os.environ.get("FB_PAGE_ID", "384599494936167")
API = "https://graph.facebook.com/v26.0"
MEDIA = "media_type,type,url,title,description,target{id,url},media{image{src,width,height}}"
FIELDS = ("id,created_time,updated_time,message,permalink_url,full_picture,status_type,"
          f"attachments{{{MEDIA},subattachments.limit(100){{{MEDIA}}}}}")
PAGE_SIZE = 25
PAUSE_API = 0.4
PAUSE_DL = 0.1
UA = {"User-Agent": "rsg-fb-sichern/1.0"}
EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}


def api_get(url):
    """Graph-API-GET mit Retry bei Rate-Limit/Netzproblemen. Gibt dict zurück oder wirft RuntimeError."""
    for attempt in range(1, 4):
        try:
            with urlopen(Request(url, headers=UA), timeout=60, context=SSL_CONTEXT) as r:
                return json.loads(r.read())
        except HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            try:
                err = json.loads(body).get("error", {})
            except ValueError:
                err = {}
            code = err.get("code")
            if code in (4, 17, 32, 613) and attempt < 3:
                print(f"    Rate-Limit (Code {code}) – warte {120 * attempt} s …")
                time.sleep(120 * attempt)
                continue
            raise RuntimeError(f"HTTP {e.code}, Code {code}: {err.get('message', body[:300])}")
        except URLError as e:
            if attempt < 3:
                time.sleep(10)
                continue
            raise RuntimeError(f"Netzwerkfehler: {e.reason}")
    raise RuntimeError("Rate-Limit bleibt bestehen – später erneut starten (bereits Geladenes bleibt).")


def full_res_url(photo_id, token):
    """Größte verfügbare Version eines Fotos über /{photo-id}?fields=images."""
    data = api_get(f"{API}/{photo_id}?{urlencode({'fields': 'images', 'access_token': token})}")
    images = data.get("images") or []
    if not images:
        return None, None, None
    best = max(images, key=lambda i: i.get("width", 0) * i.get("height", 0))
    return best.get("source"), best.get("width"), best.get("height")


def collect_images(post):
    """Liste aller Bildkandidaten eines Posts: (photo_id|None, url, w, h, beschreibung)."""
    found = []
    for att in (post.get("attachments") or {}).get("data", []):
        subs = (att.get("subattachments") or {}).get("data", [])
        for a in (subs or [att]):
            img = ((a.get("media") or {}).get("image") or {})
            if not img.get("src"):
                continue
            pid = (a.get("target") or {}).get("id") if a.get("media_type") == "photo" else None
            found.append((pid, img["src"], img.get("width"), img.get("height"),
                          a.get("description") or ""))
        if (att.get("subattachments") or {}).get("paging", {}).get("next"):
            print(f"    Hinweis: Album in Post {post['id']} hat mehr als 100 Fotos – Rest fehlt.")
    if not found and post.get("full_picture"):
        found.append((None, post["full_picture"], None, None, ""))
    return found


def download(url, path_without_ext):
    with urlopen(Request(url, headers=UA), timeout=60, context=SSL_CONTEXT) as r:
        ctype = r.headers.get("Content-Type", "").split(";")[0].strip()
        data = r.read()
    if not ctype.startswith("image/"):
        raise RuntimeError(f"kein Bild (Content-Type {ctype or '?'})")
    path = path_without_ext + EXT.get(ctype, ".jpg")
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return path, len(data)


def existing(path_without_ext):
    for ext in EXT.values():
        if os.path.exists(path_without_ext + ext):
            return path_without_ext + ext
    return None


def main():
    ap = argparse.ArgumentParser(description="Facebook-Archiv lokal sichern")
    ap.add_argument("--ziel", default=os.path.expanduser("~/rsg-archiv-import/facebook"))
    ap.add_argument("--test", type=int, default=0, metavar="N", help="nur die N neuesten Posts")
    ap.add_argument("--schnell", action="store_true", help="keine Volle-Auflösung-Abfrage je Foto")
    args = ap.parse_args()

    token = os.environ.get("FB_PAGE_ACCESS_TOKEN") or getpass.getpass(
        "Page Access Token einfügen (Eingabe bleibt unsichtbar): ").strip()
    if not token:
        sys.exit("Kein Token angegeben – Abbruch.")

    bilder_dir = os.path.join(args.ziel, "bilder")
    os.makedirs(bilder_dir, exist_ok=True)

    # 1) Token prüfen
    try:
        page = api_get(f"{API}/{PAGE_ID}?{urlencode({'fields': 'name', 'access_token': token})}")
    except RuntimeError as e:
        sys.exit(f"Token-/Seitenprüfung fehlgeschlagen: {e}")
    print(f"Seite: {page.get('name')} – Ziel: {args.ziel}\n")

    # 2) Posts holen (frische Bild-URLs!)
    print("Schritt 1/2: Posts abrufen …")
    url = f"{API}/{PAGE_ID}/posts?{urlencode({'fields': FIELDS, 'limit': PAGE_SIZE, 'access_token': token})}"
    posts = []
    while url:
        try:
            data = api_get(url)
        except RuntimeError as e:
            sys.exit(f"Abbruch beim Abrufen der Posts: {e}")
        posts.extend(data.get("data", []))
        print(f"  {len(posts)} Posts …", end="\r")
        if args.test and len(posts) >= args.test:
            posts = posts[:args.test]
            break
        url = data.get("paging", {}).get("next")
        time.sleep(PAUSE_API)
    print(f"  {len(posts)} Posts abgerufen.      ")

    # 3) Bilder sofort laden – die URLs laufen nach einigen Tagen ab
    frueher = {}  # Bilddaten eines früheren Laufs (für Wiederaufnahme)
    try:
        with open(os.path.join(args.ziel, "posts.json"), encoding="utf-8") as f:
            for p in json.load(f).get("posts", []):
                for b in p.get("_bilder", []):
                    frueher[b["datei"]] = b
    except (OSError, ValueError):
        pass
    print("\nSchritt 2/2: Bilder laden …")
    fehler, neu, vorhanden, bytes_neu = [], 0, 0, 0
    for i, post in enumerate(posts, 1):
        pid = post["id"]
        ordner = os.path.join(bilder_dir, pid)
        lokale = []
        for n, (photo_id, src, w, h, beschr) in enumerate(collect_images(post), 1):
            basis = os.path.join(ordner, f"{n:02d}")
            pfad = existing(basis)
            if pfad:
                vorhanden += 1
                alt = frueher.get(os.path.relpath(pfad, args.ziel))
                if alt:
                    lokale.append(alt)
                    continue
            else:
                os.makedirs(ordner, exist_ok=True)
                quelle = src
                if photo_id and not args.schnell:
                    try:
                        big, bw, bh = full_res_url(photo_id, token)
                        if big:
                            quelle, w, h = big, bw, bh
                        time.sleep(PAUSE_API)
                    except RuntimeError as e:
                        fehler.append(f"{pid} #{n}: volle Auflösung nicht abrufbar ({e}) – nehme Vorschau")
                try:
                    pfad, size = download(quelle, basis)
                    neu += 1
                    bytes_neu += size
                    time.sleep(PAUSE_DL)
                except (HTTPError, URLError, RuntimeError, OSError) as e:
                    fehler.append(f"{pid} #{n}: {e}")
                    continue
            lokale.append({"datei": os.path.relpath(pfad, args.ziel), "breite": w, "hoehe": h,
                           "beschreibung": beschr, "foto_id": photo_id})
        post["_bilder"] = lokale
        print(f"  Post {i:4d}/{len(posts)}: {len(lokale):3d} Bild(er)   (neu {neu}, schon da {vorhanden}, Fehler {len(fehler)})",
              end="\r")
    print()

    # 4) Speichern (enthält keinen Token)
    meta = {"seite": page.get("name"), "page_id": PAGE_ID,
            "gesichert_am": datetime.now().isoformat(timespec="seconds"),
            "anzahl_posts": len(posts), "testlauf": bool(args.test)}
    with open(os.path.join(args.ziel, "posts.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "posts": posts}, f, ensure_ascii=False, indent=1)
    if fehler:
        with open(os.path.join(args.ziel, "fehler.log"), "w", encoding="utf-8") as f:
            f.write("\n".join(fehler) + "\n")

    total = sum(len(p["_bilder"]) for p in posts)
    print("\n================ ERGEBNIS ================")
    print(f"Posts gesichert:     {len(posts)}{'  (TESTLAUF)' if args.test else ''}")
    print(f"Bilder lokal:        {total}  (neu geladen {neu}, {bytes_neu / 1e6:.0f} MB; bereits vorhanden {vorhanden})")
    print(f"Fehler:              {len(fehler)}{'  → siehe fehler.log' if fehler else ''}")
    print(f"Ordner:              {args.ziel}")
    print("\nBitte diese Ausgabe ab '==== ERGEBNIS ====' in den Chat kopieren.")


if __name__ == "__main__":
    main()
