#!/usr/bin/env python3
"""Programm (EPG) fuer die israelischen Sender der Webseite israel.html.

Laeuft per GitHub Action alle paar Stunden: holt die Programmdatei von
open-epg.com, nimmt nur die Sender der Gruppe Israel aus playlist.m3u8 (nach
tvg-id) und schreibt epg_israel.json - klein genug fuer den Browser, und im
selben Repo, also ohne CORS-Probleme.

Kommt statt der Programmdatei etwas anderes (open-epg erlaubt jede Datei nur
20-mal am Tag), bleibt die alte epg_israel.json stehen.

Aufruf: python3 epg_israel.py playlist.m3u8 epg_israel.json [lokale-datei.xml.gz]
"""
import datetime as dt
import gzip
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

QUELLE = "https://www.open-epg.com/files/israel.xml.gz"
VORHER = 3 * 3600        # laufende und gerade beendete Sendungen
NACHHER = 48 * 3600      # so weit voraus, wie die Quelle reicht


def sender_ids(playlist):
    ids = set()
    zeilen = open(playlist, encoding="utf-8").read().splitlines()
    for z in zeilen:
        if not z.startswith("#EXTINF"):
            continue
        attr = dict(re.findall(r'([\w-]+)="([^"]*)"', z))
        gruppe = attr.get("group-title", "").split(";")[0].strip()
        if gruppe == "Israel" and attr.get("tvg-id"):
            ids.add(attr["tvg-id"])
    return ids


def holen(lokal=None):
    if lokal:
        daten = open(lokal, "rb").read()
    else:
        anfrage = urllib.request.Request(QUELLE, headers={"User-Agent": "Mozilla/5.0 (EPG fuer israel.html)"})
        daten = urllib.request.urlopen(anfrage, timeout=120).read()
    if daten[:2] == b"\x1f\x8b":
        daten = gzip.decompress(daten)
    if b"<tv" not in daten[:4096]:
        raise ValueError("keine Programmdatei: " + daten[:200].decode("utf-8", "replace"))
    return daten


def zeit(s):
    # "20261016180000 +0300"
    return int(dt.datetime.strptime(s.strip()[:20], "%Y%m%d%H%M%S %z").timestamp())


def main():
    playlist, ziel = sys.argv[1], sys.argv[2]
    lokal = sys.argv[3] if len(sys.argv) > 3 else None
    ids = sender_ids(playlist)
    # Abgleich nachsichtig wie in der App: klein, nur Buchstaben/Ziffern
    kennung = lambda s: re.sub(r"[^0-9a-z]", "", s.split("@")[0].lower())
    nach_kennung = {kennung(i): i for i in ids}
    try:
        daten = holen(lokal)
    except Exception as fehler:
        print("Programm nicht geladen, alte Datei bleibt:", fehler)
        return
    jetzt = time.time()
    sender = {}
    for p in ET.fromstring(daten).iter("programme"):
        sid = nach_kennung.get(kennung(p.get("channel", "")))
        if not sid:
            continue
        try:
            start, stop = zeit(p.get("start")), zeit(p.get("stop"))
        except (TypeError, ValueError):
            continue
        if stop < jetzt - VORHER or start > jetzt + NACHHER:
            continue
        titel = (p.findtext("title") or "").replace("(ש.ח.)", "").strip()
        text = " ".join((p.findtext("desc") or "").split())
        if len(text) > 300:
            text = text[:297].rstrip() + "…"
        sender.setdefault(sid, []).append([start, stop, titel, text])
    for liste in sender.values():
        liste.sort()
    if not sender:
        print("Keine passenden Sendungen gefunden, alte Datei bleibt.")
        return
    ergebnis = {"stand": int(jetzt), "quelle": "open-epg.com", "sender": sender}
    with open(ziel, "w", encoding="utf-8") as f:
        json.dump(ergebnis, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{ziel}: {len(sender)} Sender, {sum(len(l) for l in sender.values())} Sendungen")


if __name__ == "__main__":
    main()
