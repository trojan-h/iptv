#!/usr/bin/env python3
"""Programm (EPG) fuer die israelischen Sender der Webseite israel.html.

Laeuft per GitHub Action alle paar Stunden und schreibt epg_israel.json -
klein genug fuer den Browser, und im selben Repo, also ohne CORS-Probleme.

Zwei Quellen, je Sender kombiniert:
  1. open-epg.com - ausfuehrlichere Titel (mit Folge), reicht ~40 Stunden,
     kennt als einzige HOT Zone, HOT Drama, Yes Movies Action, Zoom und Viva
  2. epgshare01 IL1 - reicht ~58 Stunden; fuellt Luecken und die Zeit nach
     open-epg (Zuordnung per Titelvergleich geprueft, siehe IL1_ZUORDNUNG)

Faellt eine Quelle aus (open-epg erlaubt jede Datei nur 20-mal am Tag),
reicht die andere. Fallen beide aus, bleibt die alte epg_israel.json stehen.

Aufruf: python3 epg_israel.py playlist.m3u8 epg_israel.json [open-epg-datei [il1-datei]]
"""
import datetime as dt
import gzip
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

OPEN_EPG = "https://www.open-epg.com/files/israel.xml.gz"
IL1 = "https://epgshare01.online/epgshare01/epg_ripper_IL1.xml.gz"
VORHER = 3 * 3600        # laufende und gerade beendete Sendungen
NACHHER = 72 * 3600      # so weit voraus, wie die Quellen reichen

# tvg-id in playlist.m3u8 -> anders benannter Kanal in open-epg. HOT Drama
# heisst dort „HOT HBO“ (gleiche Sendungen auf die Minute, geprueft 16.10.2026).
OPEN_EPG_ZUORDNUNG = {
    "HOTDrama.il": "hothbo.il",
}

# tvg-id in playlist.m3u8 -> Kanal in IL1. Nur Paare, bei denen zur selben
# Zeit dieselben Sendungen laufen (geprueft 16.10.2026). Nicht dabei: Zoom
# („ZOOM Toon“ ist ein anderer Sender) und Viva Premium (passt nicht).
# Die IL1-Varianten „… שידור חי“ haben Loecher und wiederholen danach den
# Vortag - deshalb fuer 11 und 12 die einfachen Varianten.
LOCH = 6 * 3600          # danach traut man den IL1-Daten nicht mehr
IL1_ZUORDNUNG = {
    "channel11.il": "כאן.11.il",
    "channel12.il": "קשת.il",
    "channel13.il": "רשת.il",
    "kaneducation.il": "כאן.חינוכית.il",
    "goodlifeplus.il": "GOOD.LIFE+.il",
    "channel14.il": "ערוץ.14.HD.il",
    "i24hebrew.il": "עברית.i24.il",
    "knesset.il": "ערוץ.הכנסת.il",
    "tve.il": "ערוץ.24.בשידור.חי.il",
    "finance.il": "ערוץ.הכלכלה.il",
    "yamtichoni.il": "ים.תיכוני.il",
    "channel9.il": "ערוץ.9.il",
}


def sender_ids(playlist):
    ids = set()
    for z in open(playlist, encoding="utf-8").read().splitlines():
        if not z.startswith("#EXTINF"):
            continue
        attr = dict(re.findall(r'([\w-]+)="([^"]*)"', z))
        if attr.get("group-title", "").split(";")[0].strip() == "Israel" and attr.get("tvg-id"):
            ids.add(attr["tvg-id"])
    return ids


def holen(url, lokal=None):
    if lokal:
        daten = open(lokal, "rb").read()
    else:
        anfrage = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (EPG fuer israel.html)"})
        daten = urllib.request.urlopen(anfrage, timeout=120).read()
    if daten[:2] == b"\x1f\x8b":
        daten = gzip.decompress(daten)
    if b"<tv" not in daten[:4096]:
        raise ValueError("keine Programmdatei: " + daten[:200].decode("utf-8", "replace"))
    return ET.fromstring(daten)


def zeit(s):
    # "20261016180000 +0300"
    return int(dt.datetime.strptime(s.strip()[:20], "%Y%m%d%H%M%S %z").timestamp())


def sendungen(wurzel, kanal_zu_id, jetzt):
    """Sendungen je tvg-id aus einer XMLTV-Datei."""
    ergebnis = {}
    for p in wurzel.iter("programme"):
        sid = kanal_zu_id(p.get("channel", ""))
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
        ergebnis.setdefault(sid, []).append([start, stop, titel, text])
    for liste in ergebnis.values():
        liste.sort()
    return ergebnis


def bis_zum_loch(liste):
    """Nur bis zum ersten grossen Loch - dahinter stand in IL1 schon
    einmal der wiederholte Vortag."""
    for i in range(1, len(liste)):
        if liste[i][0] - liste[i - 1][1] > LOCH:
            return liste[:i]
    return liste


def main():
    playlist, ziel = sys.argv[1], sys.argv[2]
    lokal_oe = sys.argv[3] if len(sys.argv) > 3 else None
    lokal_il1 = sys.argv[4] if len(sys.argv) > 4 else None
    ids = sender_ids(playlist)
    jetzt = time.time()
    # Abgleich nachsichtig wie in der App: klein, nur Buchstaben/Ziffern
    kennung = lambda s: re.sub(r"[^0-9a-z]", "", s.split("@")[0].lower())
    nach_kennung = {kennung(i): i for i in ids}
    for sid, kanal in OPEN_EPG_ZUORDNUNG.items():
        if sid in ids:
            nach_kennung[kennung(kanal)] = sid
    il1_zu_id = {v: k for k, v in IL1_ZUORDNUNG.items() if k in ids}

    quellen, oe, il1 = [], {}, {}
    try:
        oe = sendungen(holen(OPEN_EPG, lokal_oe), lambda k: nach_kennung.get(kennung(k)), jetzt)
        quellen.append("open-epg.com")
    except Exception as fehler:
        print("open-epg nicht geladen:", fehler)
    try:
        il1 = sendungen(holen(IL1, lokal_il1), il1_zu_id.get, jetzt)
        quellen.append("epgshare01")
    except Exception as fehler:
        print("epgshare01 nicht geladen:", fehler)

    # Je Sender: open-epg zuerst; IL1 fuellt alles, was dort fehlt - Luecken
    # mittendrin (open-epg laesst etwa den Schabbat aus) und die Zeit danach.
    # Eine IL1-Sendung kommt dazu, wenn sie sich mit keiner open-epg-Sendung
    # mehr als 5 Minuten ueberschneidet.
    sender = {}
    for sid in ids:
        liste = list(oe.get(sid, []))
        basis = list(liste)
        for p in bis_zum_loch(il1.get(sid, [])):
            if all(min(p[1], q[1]) - max(p[0], q[0]) <= 300 for q in basis):
                liste.append(p)
        liste.sort()
        if liste:
            sender[sid] = liste
    if not sender:
        print("Keine Sendungen geladen, alte Datei bleibt.")
        return
    ergebnis = {"stand": int(jetzt), "quelle": " + ".join(quellen), "sender": sender}
    with open(ziel, "w", encoding="utf-8") as f:
        json.dump(ergebnis, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{ziel}: {len(sender)} Sender, {sum(len(l) for l in sender.values())} Sendungen ({ergebnis['quelle']})")


if __name__ == "__main__":
    main()
