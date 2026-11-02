"""Classify one search hit at a time. Headlines cannot prove stock or price."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import unquote, urlunsplit

from feeds import Item, parts

FAMILY = r"(?:ultra[\s-]*premium(?:[\s-]+(?:collections?|kollektionen?|kollektion|collection))?|upcs?)"
ANNIVERSARY = re.compile(r"\b30(?:th\b|(?:\.|[\s-])*\s*(?:jahre[n]?|jahrig\w*|jubilaum\w*|anniversary|years?)\b)")
GERMAN_CENTER = re.compile(
    r"\b(?:(?:german|deutsche[nmrs]?)\s+pokemon\s*[- ]?center[s]?|"
    r"pokemon\s*[- ]?center[s]?\s*(?:[-–:(\[]\s*)?(?:(?:in|fur|for)\s+)?(?:deutschland|germany|de)\b)")
NEGATIVE_REDDIT = re.compile(
    r"\b(?:kein(?:e[nmrs]?)?|nicht|not|never|wann|when|maybe|perhaps|hoffentlich|gerucht|rumou?r|wish|nur in|only in)\b")
OTHER_MARKET = re.compile(r"\b(?:us|usa|uk|canada|kanada|japan|walmart|target|dreamland)\b")
ANNOUNCEMENT = re.compile(r"\b(?:announc\w*|reveal\w*|introduc\w*|releas\w*|launch\w*|coming|erscheint|vorgestellt|angekundigt|veroffentlich\w*|ab\s+dem)\b")
URL_TOKEN = re.compile(r"https?://[^\s<>\"']+", re.I)
PDP_PATH = re.compile(r"/en-de/product/([a-z0-9][a-z0-9-]{2,})(?:/[a-z0-9-]+)?/?", re.I)
OFFICIAL_DOMAINS = ("pokemon.com", "pokemoncenter.com", "pokemon.gamespress.com")


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    return re.sub(r"\s+", " ", "".join(c for c in value if not unicodedata.combining(c))
                  .translate(str.maketrans("‐‑‒–—", "-----"))).strip()


def domain(url: str) -> str:
    u = parts(url)
    return (u.hostname or "").lower().removeprefix("www.") if u else ""


def belongs(host: str, parent: str) -> bool:
    return host == parent or host.endswith("." + parent)


def de_url(url: str, *, product: bool = False) -> str:
    u = parts(url.rstrip(".,);]!"))
    if not u or u.hostname not in {"pokemoncenter.com", "www.pokemoncenter.com"}:
        return ""
    path = u.path.rstrip("/")
    if (not re.fullmatch(r"/en-de(?:/[a-zA-Z0-9_-]+)*", path)
            or product and not PDP_PATH.fullmatch(path)):
        return ""
    return urlunsplit(("https", "www.pokemoncenter.com", path, "", ""))


def variants(title: str, products: list[dict]) -> list[str]:
    t = norm(title)
    if not ANNIVERSARY.search(t) or not re.search(r"\b" + FAMILY + r"\b", t):
        return []
    result = []
    for p in products:
        names = "|".join(re.escape(norm(v)) for v in p["names"])
        editions = "|".join(re.escape(norm(v)) for v in p["editions"])
        other_editions = "|".join(re.escape(norm(v)) for other in products for v in other["editions"])
        edition = rf"(?:{editions})"
        # Night/Day count as edition names next to UPC, or in an explicit pair.
        pair = rf"(?:{edition}\s*(?:&|/|und|and|\+)\s*(?:{other_editions})|(?:{other_editions})\s*(?:&|/|und|and|\+)\s*{edition})"
        sep = r"[\s:()/-]+"
        if (re.search(rf"\b(?:{names})\b", t)
                or re.search(rf"\b(?:{FAMILY}{sep}{edition}|{edition}{sep}{FAMILY}|{pair})\b", t)):
            result.append(p["name"])
    return result


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def classify(item: Item, source: dict, products: list[dict]) -> dict | None:
    kind = source["kind"]
    origin = domain(item.origin)
    host = domain(item.url)
    reddit = any(belongs(h, "reddit.com") or h == "redd.it" for h in (origin, host))
    official = any(belongs(origin or host, d) for d in OFFICIAL_DOMAINS)
    shop_link = de_url(item.url, product=True)
    if ((kind == "reddit" and not reddit) or (kind == "official" and not official)
            or (kind == "shop_index" and not shop_link)):
        return None
    # Only a DE official result can borrow the product name from its own slug.
    title_for_match = item.title + (" " + unquote(parts(shop_link).path).replace("-", " ") if shop_link else "")
    affected = variants(title_for_match, products)
    if not affected:
        return None
    proof, typ, published_url = "", "Drop-Hinweis gefunden", item.url
    if reddit:
        # Each Google News description may aggregate several authors/links. Only this hit's
        # own headline is attributable to the Reddit post. Never borrow another item's proof.
        same_title = norm(URL_TOKEN.sub(" ", item.title))
        if "?" in same_title or NEGATIVE_REDDIT.search(same_title) or OTHER_MARKET.search(same_title):
            return None
        for raw in URL_TOKEN.findall(item.title):
            proof = de_url(raw)
            if proof:
                break
        # Do not match country words embedded inside unrelated URL strings.
        reference = GERMAN_CENTER.search(same_title)
        if not proof and not reference:
            return None
        proof = proof or reference.group(0)
    elif shop_link:
        typ, proof, published_url = "Produktseite entdeckt", "Im Suchindex veröffentlichter Produktlink für /en-de/.", shop_link
    elif official and ANNOUNCEMENT.search(norm(item.title)):
        typ = "Produkt angekündigt"
    elif not official and not GERMAN_CENTER.search(norm(item.title)) and (
            OTHER_MARKET.search(norm(item.title)) or re.search(r"\b(?:smyths|amazon|best buy|gamestop)\b", norm(item.title))):
        # A retailer's own preorder is not a signal for Pokémon Center DE.
        return None
    # Same publisher/headline in several Google editions represents one message. Product
    # pages have a SKU identity independent of slug, query string, and headline edits.
    u = parts(item.url)
    link_id = digest((u.hostname or "") + u.path + ("?" + u.query if u.query and not u.path.strip("/") else ""))
    if shop_link:
        identity = "de-pdp|" + PDP_PATH.fullmatch(parts(shop_link).path).group(1).lower()
    elif host == "news.google.com" and origin:
        identity = origin + "|" + norm(item.title) + "|" + item.published[:10]
    else:
        identity = link_id
    return {"id": digest(identity), "link_id": link_id, "type": typ, "products": affected, "title": item.title[:550],
            "link": published_url, "source": item.publisher or (host if not shop_link else source["name"]),
            "index": source["name"], "de_proof": proof, "reddit": reddit, "published": item.published}
