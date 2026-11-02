"""Read published RSS search results. All outbound HTTP is restricted to these feeds."""
from __future__ import annotations

import html
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urlsplit

FEEDS = {("news.google.com", "/rss/search"), ("www.bing.com", "/search")}
MAX_BYTES = 2_000_000


def text_only(text: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]*>", " ", text)).split())


def parts(url: str):
    try:
        value = urlsplit(url)
        if (value.scheme == "https" and value.hostname and not value.username
                and not value.password and value.port in (443, None)
                and not re.search(r"[\x00-\x20\x7f\\]", url)):
            return value
    except ValueError:
        pass
    return None


def feed_url(source: dict) -> str:
    if source["kind"] == "shop_index":
        return "https://www.bing.com/search?" + urlencode({
            "format": "rss", "q": source["query"], "setlang": "en", "cc": "DE"})
    lang, country = source["language"], source["country"]
    return "https://news.google.com/rss/search?" + urlencode({
        "q": source["query"], "hl": lang, "gl": country, "ceid": f"{country}:{lang}"})


def accept_feed_url(url: str) -> None:
    u = parts(url)
    if not u or (u.hostname, u.path) not in FEEDS:
        raise ValueError("Feed-Ziel außerhalb der freigegebenen Suchindizes")


class FeedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        accept_feed_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def published_date(value: str) -> str:
    try:
        try:
            stamp = parsedate_to_datetime(value)
        except (ValueError, TypeError):
            stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is not None:
            return stamp.astimezone(UTC).isoformat(timespec="seconds")
    except (ValueError, TypeError, OverflowError):
        pass
    return ""


@dataclass(frozen=True)
class Item:
    title: str
    url: str
    publisher: str = ""
    origin: str = ""
    published: str = ""


def parse_feed(payload: bytes) -> list[Item]:
    # A challenge or error page is never a successful, empty baseline.
    if len(payload) > MAX_BYTES or re.search(br"<!DOCTYPE|<!ENTITY", payload, re.I):
        raise ValueError("Unzulässige XML-Antwort")
    root = ET.fromstring(payload)
    if root.tag == "{http://www.w3.org/2005/Atom}feed":
        ns = "{http://www.w3.org/2005/Atom}"
        items = []
        for e in root.findall(f"{ns}entry"):
            href = next((l.get("href", "") for l in e.findall(f"{ns}link")
                         if l.get("rel", "alternate") == "alternate"), "")
            items.append(Item(text_only(e.findtext(f"{ns}title", "")), href,
                              published=published_date(e.findtext(f"{ns}published", "") or e.findtext(f"{ns}updated", ""))))
    elif root.tag == "rss" and root.find("channel") is not None:
        items = []
        for e in root.findall("./channel/item"):
            src = e.find("source")
            name = text_only(src.text or "") if src is not None else ""
            raw = text_only(e.findtext("title", ""))
            # Google News often appends the publisher name; descriptions may contain OTHER stories.
            if name:
                raw = raw.removesuffix(" - " + name)
            items.append(Item(raw, (e.findtext("link", "")).strip(), name,
                              src.get("url", "") if src is not None else "",
                              published_date(e.findtext("pubDate", ""))))
    else:
        raise ValueError("Antwort ist kein RSS-/Atom-Feed")
    return [item for item in items if item.title and parts(item.url)]


def fetch_feed(source: dict) -> list[Item]:
    url = feed_url(source)
    accept_feed_url(url)
    req = urllib.request.Request(url, headers={
        "User-Agent": "PokemonUPCNewsMonitor/2.0 (public RSS reader)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"})
    with urllib.request.build_opener(FeedRedirect()).open(req, timeout=12) as response:
        accept_feed_url(response.geturl())
        if response.status != 200:
            raise ValueError("Unerwarteter Feed-Status")
        return parse_feed(response.read(MAX_BYTES + 1))
