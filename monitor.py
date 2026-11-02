#!/usr/bin/env python3
"""Build the public UPC news feed and notify its owner about newly published items."""
from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
import sys
import urllib.error
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path
from zoneinfo import ZoneInfo

from feeds import fetch_feed
from matching import classify, digest

ROOT = Path(__file__).resolve().parent
SUBJECT = "🔎 POKÉMON UPC – Neuer Drop-Hinweis"
SHOP = "https://www.pokemoncenter.com/en-de"
BERLIN = ZoneInfo("Europe/Berlin")
ATOM = "http://www.w3.org/2005/Atom"
ET.register_namespace("", ATOM)
CONFIG = ROOT / "sources.json"


def now_utc():
    return datetime.now(UTC).isoformat(timespec="seconds")


def german_time(stamp):
    return datetime.fromisoformat(stamp).astimezone(BERLIN).strftime("%d.%m.%Y, %H:%M %Z")


def load_state(folder):
    path = folder / "state.json"
    state = json.loads(path.read_text()) if path.exists() else {"initialized": False, "seen": []}
    if "version" not in state and "initialized" in state and isinstance(state.get("seen"), list):
        # v1 stored source-scoped hashes, not publication records. A silent first snapshot
        # of each new query migrates either v1 state without replaying old articles.
        return {"version": 2, "sources": {}, "known": [], "recent": [], "pending": [],
                "batch": [], "updated": ""}
    if (state.get("version") != 2 or not isinstance(state.get("sources"), dict)
            or not all(isinstance(state.get(k), list) for k in ("known", "recent", "pending", "batch"))):
        raise ValueError("Unbekanntes Zustandsformat")
    return state


def atomic_save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def save_state(folder, state):
    atomic_save(folder / "state.json", (json.dumps(state, indent=2, ensure_ascii=False) + "\n").encode())


def build_feed(folder, state):
    def node(parent, name, text="", **attrs):
        el = ET.SubElement(parent, f"{{{ATOM}}}{name}", attrs)
        el.text = text or None
        return el

    root = ET.Element(f"{{{ATOM}}}feed")
    node(root, "id", "urn:pokemon-upc-monitor:de")
    node(root, "title", "Nachtara & Psiana – Hinweise zum Pokémon Center Deutschland")
    node(root, "updated", state["updated"])
    node(node(root, "author"), "name", "Pokémon UPC Monitor")
    for item in reversed(state["recent"]):
        e = node(root, "entry")
        node(e, "id", "urn:pokemon-upc-monitor:" + item["id"])
        node(e, "updated", item["found"])
        node(e, "title", item["type"] + " · " + ", ".join(item["products"]))
        node(e, "link", href=item["link"], rel="alternate")
        node(e, "summary", "Quelle: " + item["source"] + ". Kaufbarkeit im deutschen Shop: unbekannt.")
    ET.indent(root, space="  ")
    atomic_save(folder / "meldungen.atom", ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n")


def read_source(source):
    try:
        return source, fetch_feed(source), ""
    except urllib.error.HTTPError as exc:
        return source, [], f"HTTP {exc.code}"
    except (OSError, ValueError, ET.ParseError) as exc:
        return source, [], type(exc).__name__


def collect(folder, config, snapshots, stamp):
    state = load_state(folder)
    known = set(state["known"])
    candidates, links, missed, healthy = {}, {}, [], 0
    source_checks = {}
    observed = set()
    for source, entries, error in snapshots:
        sid = source["id"]
        if error:
            missed.append(source["name"])
            source_checks[sid] = {"error": error}
            print(f"Quelle {sid}: {error}", file=sys.stderr)
            continue
        healthy += 1
        start = state["sources"].get(sid)
        state["sources"].setdefault(sid, stamp)
        matches = 0
        for item in entries:
            event = classify(item, source, config["products"])
            if not event:
                continue
            matches += 1
            key = links.setdefault(event["link_id"], event["id"])
            aliases = {key, event["id"], event["link_id"]}
            observed.update(aliases)
            if aliases & known:
                continue
            event["id"] = key
            # A source that failed to initialize previously builds its own baseline.
            # A fresh match from a healthy, initialized source still wins across sources.
            fresh = bool(start and (not item.published or item.published >= start))
            if fresh or event["id"] not in candidates:
                candidates[event["id"]] = (event, fresh)
        print(f"Quelle {sid}: {len(entries)} Einträge, {matches} passende Treffer"
              + ("; erste Bestandsaufnahme." if not start else "."))
        source_checks[sid] = {"entries": len(entries), "matches": matches}
    if not healthy:
        raise RuntimeError("Keine Quelle lieferte einen verwertbaren Feed")
    new = [{**e, "found": stamp} for e, fresh in candidates.values() if fresh]
    # Priority within each new digest; older pending messages keep their position.
    new.sort(key=lambda e: config["products"][0]["name"] not in e["products"])
    state["known"] = sorted(known | observed)
    state["pending"].extend(new)
    state["recent"] = (state["recent"] + new)[-50:]
    if new or not state["updated"]:
        state["updated"] = stamp
    if not state["batch"]:
        state["batch"] = [e["id"] for e in state["pending"][:20]]
    day = datetime.fromisoformat(stamp).astimezone(BERLIN).date().isoformat()
    if state.get("daily_check", {}).get("day") != day:
        state["daily_check"] = {"day": day, "checked": stamp, "sources": source_checks}
    save_state(folder, state)
    build_feed(folder, state)
    print(f"{len(new)} neue Meldungen veröffentlicht. {len(state['pending'])} für den Versand vorgemerkt.")
    return missed


def message_body(events):
    rows = ["Kaufbarkeit im Pokémon Center Deutschland: unbekannt.", ""]
    for event in events:
        rows.extend([", ".join(event["products"]) + " · " + event["type"],
                     "Titel: " + event["title"], "Quelle: " + event["source"] + " · " + event["index"],
                     "Erkannt: " + german_time(event["found"])])
        if event["published"]:
            rows.append("Vom Index gemeldete Veröffentlichung: " + german_time(event["published"]))
        if event["de_proof"]:
            rows.append("Deutschland-Beleg: " + event["de_proof"])
        else:
            rows.append("Deutschland-Bezug: Aus dieser Meldung lässt sich kein Verkaufsstart im deutschen Shop ableiten.")
        label = "DE-Produktlink laut Suchindex (Seitenstatus ungeprüft)" if event["type"] == "Produktseite entdeckt" else "Fundstelle"
        rows.extend([label + ": " + event["link"], ""])
    rows.extend(["Bestellbarkeit, Vorbestellung, Restock und DE-Shoppreis sind nicht unabhängig bestätigt.",
                 "Zum offiziellen deutschen Shop: " + SHOP])
    return "\n".join(rows)


def send_mail(subject, body, key=None):
    sender = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASS", "")
    recipient = os.getenv("ALERT_TO") or sender
    if not sender or not password:
        raise RuntimeError("SMTP_USER oder SMTP_PASS fehlt")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, recipient, subject
    msg["Date"] = format_datetime(datetime.now(UTC))
    msg["Message-ID"] = f"<upc.{key}@drop-monitor.invalid>" if key else make_msgid()
    msg.set_content(body)
    # Fixed Gmail TLS endpoint: a change to a public source file cannot redirect credentials.
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20, context=ssl.create_default_context()) as smtp:
        smtp.login(sender, password)
        if smtp.send_message(msg):
            raise RuntimeError("E-Mail-Empfänger wurde abgewiesen")


def deliver(folder, sender=send_mail):
    state = load_state(folder)
    ids = state["batch"]
    if not ids:
        print("Keine ausstehenden Meldungen. Keine E-Mail.")
        return
    by_id = {e["id"]: e for e in state["pending"]}
    events = [by_id[i] for i in ids]
    sender(SUBJECT, message_body(events), digest("|".join(ids)))
    state["pending"] = [e for e in state["pending"] if e["id"] not in ids]
    state["batch"] = []
    save_state(folder, state)
    print(f"SMTP hat die Nachricht mit {len(events)} Meldung(en) angenommen.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["collect", "deliver", "test-mail"], nargs="?", default="collect")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    if args.action == "test-mail":
        send_mail("[TEST] Pokémon UPC – Versandtest aus dem Monitor",
                  "Testalarm für Nachtara und Psiana.\nKaufbarkeit: unbekannt.\n"
                  "Versand: " + german_time(now_utc()) + "\n" + SHOP)
        print("SMTP hat den Testalarm angenommen.")
    elif args.action == "deliver":
        deliver(args.data_dir)
    else:
        config = json.loads(CONFIG.read_text())
        with ThreadPoolExecutor(max_workers=3) as executor:
            errors = collect(args.data_dir, config, executor.map(read_source, config["sources"]), now_utc())
        if errors:
            print("Teilausfall: " + ", ".join(errors), file=sys.stderr)
            if summary := os.getenv("GITHUB_STEP_SUMMARY"):
                with open(summary, "a", encoding="utf-8") as log:
                    log.write("Eingeschränkte Abdeckung durch Quellausfall: " + ", ".join(errors) + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, KeyError, smtplib.SMTPException) as exc:
        # SMTP exceptions can contain addresses and server diagnostics. Log only the category.
        print(f"Monitorfehler ({type(exc).__name__}) im Schritt {sys.argv[1:2]}. "
              "Quellen, Datenstand und Actions-Secrets im Projekt prüfen.", file=sys.stderr)
        sys.exit(1)
