import io
import json
import os
import smtplib
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from feeds import FeedRedirect, Item, accept_feed_url, feed_url, parse_feed
from matching import classify, de_url, variants
from monitor import CONFIG, SUBJECT, collect, deliver, german_time, load_state, read_source, send_mail

CONFIG_DATA = json.loads(CONFIG.read_text())
PRODUCTS = CONFIG_DATA["products"]
DE, EN, OFFICIAL, REDDIT, INDEX = CONFIG_DATA["sources"][:5]
INDEX_NIGHT, INDEX_DAY = CONFIG_DATA["sources"][5:7]
FIRST = "2026-11-02T09:00:00+00:00"
LATER = "2026-11-02T10:00:00+00:00"
LAST = "2026-11-02T11:00:00+00:00"
NIGHT = "30th Celebration Ultra-Premium Collection – Night"
DAY = "30 Jahre Ultra-Premium-Kollektion – Psiana"
PDP = "https://www.pokemoncenter.com/en-de/product/AB-12345/30th-celebration-ultra-premium-night"


def item(title=NIGHT, ident="a", stamp=LATER, publisher="tcg.example"):
    return Item(title, "https://news.google.com/rss/articles/" + ident, publisher,
                "https://" + publisher, stamp)


class Matching(unittest.TestCase):
    def test_editions_and_accents(self):
        self.assertEqual(variants(NIGHT, PRODUCTS), ["Nachtara / Night"])
        self.assertEqual(variants(DAY, PRODUCTS), ["Psiana / Day"])
        self.assertEqual(len(variants("30th Celebration Day & Night Ultra-Premium Collections", PRODUCTS)), 2)
        self.assertEqual(variants("Pokémon UPC zum 30-jährigen Jubiläum mit Nachtara", PRODUCTS), ["Nachtara / Night"])

    def test_no_partial_edition_or_false_anniversary(self):
        for title in ("30th Celebration UPC arrives on Friday", "30th Celebration UPC on release day",
                      "30th Celebration UPC may ship tonight", "30th Pokémon Nachtara-Deck",
                      "Umbreon ex Ultra-Premium Collection", "Pokémon 30 Jahre mit Feelinara"):
            with self.subTest(title=title):
                self.assertEqual(variants(title, PRODUCTS), [])

    def test_configurable_names(self):
        p = [{"name": "Test", "names": ["Folipurba"], "editions": ["Green"]}]
        self.assertEqual(variants("30th Celebration Ultra-Premium Green", p), ["Test"])

    def test_reddit_requires_same_post_german_shop(self):
        for text in ("r/PokemonTCG_DE 299 €", "Germany shipping", "Deutschland Release",
                     "DE-Karten verfügbar", "Pokémon Center UK", "bei Dreamland", "Pokémon Center versendet nach Deutschland"):
            with self.subTest(text=text):
                self.assertIsNone(classify(item(NIGHT + " " + text, publisher="reddit.com"), REDDIT, PRODUCTS))
        for text in ("Deutsches Pokémon Center meldet Vorbestellung", "Pokémon Center Deutschland", "German Pokémon Center",
                     "Pokémon Center (DE)", "Pokémon Center in Germany", PDP, PDP + "?utm_source=reddit"):
            with self.subTest(text=text):
                event = classify(item(NIGHT + " · " + text, publisher="www.reddit.com"), REDDIT, PRODUCTS)
                self.assertTrue(event["de_proof"])
                self.assertEqual(event["type"], "Drop-Hinweis gefunden")

    def test_comparisons_and_questions_suppressed(self):
        for suffix in ("auch im Pokémon Center DE?", "out in UK, no EU date, Pokémon Center DE",
                       "nicht im deutschen Pokémon Center", "maybe German Pokémon Center"):
            with self.subTest(suffix=suffix):
                self.assertIsNone(classify(item(NIGHT + " " + suffix, publisher="reddit.com"), EN, PRODUCTS))

    def test_reddit_evidence_in_all_feeds_and_spoofing(self):
        self.assertIsNone(classify(item(NIGHT, publisher="reddit.com"), DE, PRODUCTS))
        self.assertIsNone(classify(item(NIGHT + " Pokémon Center DE", publisher="reddit.com.attacker.example"), REDDIT, PRODUCTS))
        for url in ("https://pokemoncenter.com.evil.example/en-de/abc", "https://evil.example/pokemoncenter.com/en-de/abc",
                    "https://evil.example/?q=Pokemon-Center-DE", "https://pokemoncenter.com@evil.example/en-de",
                    "https://www.pokemoncenter.com/en-us/product/123", "https://pokemoncenter.com/en-de/../en-us"):
            with self.subTest(url=url):
                self.assertIsNone(classify(item(NIGHT + " " + url, publisher="reddit.com"), REDDIT, PRODUCTS))

    def test_index_only_verifies_de_product_url(self):
        hit = classify(Item("Shop: " + NIGHT, PDP + "?utm_campaign=x"), INDEX, PRODUCTS)
        self.assertEqual(hit["type"], "Produktseite entdeckt")
        self.assertEqual(hit["link"], PDP)
        self.assertEqual(hit["id"], classify(Item(NIGHT, PDP.rsplit("/", 1)[0]), INDEX, PRODUCTS)["id"])
        for url in (PDP.replace("/en-de/", "/en-us/"), PDP.replace("pokemoncenter.com", "fake-pokemoncenter.com"),
                    PDP.replace("/product/", "/search/"), "https://www.pokemoncenter.com/en-de"):
            with self.subTest(url=url):
                self.assertFalse(de_url(url, product=True))
                self.assertIsNone(classify(Item(NIGHT, url), INDEX, PRODUCTS))

    def test_variant_specific_de_product_index_sources(self):
        self.assertEqual(len(CONFIG_DATA["sources"]), 7)
        self.assertEqual(INDEX_NIGHT["kind"], "shop_index")
        self.assertEqual(INDEX_DAY["kind"], "shop_index")
        for source, title, url, expected in (
            (INDEX_NIGHT, NIGHT, PDP, ["Nachtara / Night"]),
            (INDEX_DAY, "30th Celebration Ultra-Premium Collection – Day",
             PDP.replace("night", "day"), ["Psiana / Day"]),
        ):
            with self.subTest(source=source["id"]):
                event = classify(Item(title, url), source, PRODUCTS)
                self.assertEqual(event["type"], "Produktseite entdeckt")
                self.assertEqual(event["products"], expected)
                self.assertEqual(event["link"], url)

    def test_official_announcement_and_unverified_retailer(self):
        title = NIGHT + " announced"
        self.assertEqual(classify(item(title, publisher="press.pokemon.com"), OFFICIAL, PRODUCTS)["type"], "Produkt angekündigt")
        self.assertIsNone(classify(item(title, publisher="pokemon.com.example.org"), OFFICIAL, PRODUCTS))
        self.assertIsNone(classify(item(title + " Walmart preorder"), EN, PRODUCTS))
        self.assertEqual(classify(item(NIGHT + " IN STOCK now"), EN, PRODUCTS)["type"], "Drop-Hinweis gefunden")

    def test_different_publication_on_a_later_date_has_new_identity(self):
        previous = classify(item(stamp="2026-11-01T09:00:00+00:00"), DE, PRODUCTS)
        following = classify(item(stamp=LATER, ident="new"), EN, PRODUCTS)
        self.assertNotEqual(previous["id"], following["id"])

    def test_german_dates(self):
        self.assertIn("10:00 CET", german_time(FIRST))
        self.assertIn("11:00 CEST", german_time("2026-08-01T09:00:00+00:00"))


class Feeds(unittest.TestCase):
    def test_google_cluster_may_not_supply_german_evidence(self):
        xml = f"""<rss><channel><item><title>{NIGHT} - Reddit</title><link>https://news.google.com/rss/articles/a</link>
        <source url="https://www.reddit.com">Reddit</source><description>Other story: German Pokémon Center {PDP}
        </description><pubDate>Mon, 02 Nov 2026 10:00:00 GMT</pubDate></item></channel></rss>"""
        row = parse_feed(xml.encode())[0]
        self.assertEqual(row.title, NIGHT)
        self.assertEqual(row.published, LATER)
        self.assertIsNone(classify(row, REDDIT, PRODUCTS))

    def test_feed_errors_and_genuine_empty_result(self):
        self.assertEqual(parse_feed(b"<rss><channel/></rss>"), [])
        for xml in (b"<html>Forbidden</html>", b"<rss/>", b"<!DOCTYPE x><rss/>", b"<rss>", b"x" * 2_000_001):
            with self.subTest(sample=xml[:12]):
                with self.assertRaises((ValueError, ET.ParseError)):
                    parse_feed(xml)

    def test_accepts_only_publishers_feeds_even_on_redirect(self):
        for s in CONFIG_DATA["sources"]:
            accept_feed_url(feed_url(s))
        for url in (PDP, "https://www.reddit.com/new/.rss", "https://news.google.com.evil.example/rss/search",
                    "http://news.google.com/rss/search", "https://www.bing.com:444/search",
                    "https://account@news.google.com/rss/search", "https://www.bing.com/other"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    FeedRedirect().redirect_request(None, None, 302, None, None, url)

    def test_atom_and_invalid_items(self):
        data = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Title</title><link href="https://example.com/a"/></entry></feed>'
        self.assertEqual(parse_feed(data)[0].title, "Title")
        self.assertEqual(parse_feed(b"<rss><channel><item><title>x</title><link>javascript:bad</link></item></channel></rss>"), [])

    def test_failure_category_is_logged_without_server_body(self):
        err = HTTPError("https://news.google.com/rss/search", 403, "personal details", {}, None)
        with patch("monitor.fetch_feed", side_effect=err):
            self.assertEqual(read_source(DE), (DE, [], "HTTP 403"))


class Persistence(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.mail = Mock()
        log = redirect_stdout(io.StringIO())
        errors = redirect_stderr(io.StringIO())
        log.__enter__()
        errors.__enter__()
        self.addCleanup(log.__exit__, None, None, None)
        self.addCleanup(errors.__exit__, None, None, None)

    def snapshot(self, rows, date=LATER):
        return collect(self.folder, CONFIG_DATA, rows, date)

    def empty(self):
        self.snapshot([(DE, [], ""), (EN, [], "")], FIRST)

    def test_baseline_restart_and_second_run_silent(self):
        self.snapshot([(DE, [item(stamp=FIRST)], "")], FIRST)
        for _ in range(2):
            self.snapshot([(DE, [item(stamp=FIRST)], "")])
            deliver(self.folder, self.mail)
        self.mail.assert_not_called()
        self.assertEqual(load_state(self.folder)["pending"], [])

    def test_one_mail_across_feeds_restarts_and_unchanged_results(self):
        self.empty()
        hits = [(DE, [item()], ""), (EN, [item(ident="second-index-id")], "")]
        self.snapshot(hits)
        deliver(self.folder, self.mail)
        self.snapshot(hits, LAST)
        deliver(self.folder, self.mail)
        self.mail.assert_called_once()
        subject, body, _ = self.mail.call_args.args
        self.assertEqual(subject, SUBJECT)
        self.assertIn("Kaufbarkeit im Pokémon Center Deutschland: unbekannt", body)
        self.assertIn("CET", body)
        self.assertIn("Nachtara / Night", body)
        self.assertEqual(len(load_state(self.folder)["recent"]), 1)

    def test_revised_headline_same_url_only_once(self):
        self.empty()
        self.snapshot([(DE, [item()], "")])
        deliver(self.folder, self.mail)
        self.snapshot([(DE, [item(title=NIGHT + " !!!")], "")], LAST)
        deliver(self.folder, self.mail)
        self.mail.assert_called_once()

    def test_failure_keeps_frozen_batch_after_item_disappears(self):
        self.empty()
        self.snapshot([(DE, [item()], "")])
        pending = load_state(self.folder)
        failure = Mock(side_effect=smtplib.SMTPException("simulated"))
        with self.assertRaises(smtplib.SMTPException):
            deliver(self.folder, failure)
        self.assertEqual(load_state(self.folder), pending)
        self.snapshot([(DE, [item(DAY, ident="other")], "")], LAST)
        deliver(self.folder, self.mail)
        self.assertEqual(failure.call_args, self.mail.call_args)
        self.assertEqual(len(load_state(self.folder)["pending"]), 1)
        self.snapshot([(DE, [], "")], LAST)
        deliver(self.folder, self.mail)
        self.assertEqual(self.mail.call_count, 2)

    def test_new_de_shop_index_source_reports_discovered_pdp_once(self):
        self.empty()
        indexed = Item(NIGHT, PDP)
        self.snapshot([(INDEX_NIGHT, [indexed], "")])
        deliver(self.folder, self.mail)
        self.mail.assert_called_once()
        self.assertIn("Produktseite entdeckt", self.mail.call_args.args[1])
        self.assertIn(PDP, self.mail.call_args.args[1])
        self.assertIn("unbekannt", self.mail.call_args.args[1])
        self.snapshot([(INDEX_DAY, [indexed], ""), (INDEX, [indexed], "")], LAST)
        deliver(self.folder, self.mail)
        self.mail.assert_called_once()

    def test_partial_outage_has_own_silent_baseline(self):
        self.assertEqual(self.snapshot([(DE, [], ""), (EN, [], "HTTP 429")], FIRST), [EN["name"]])
        self.snapshot([(EN, [item()], "")], LAST)
        deliver(self.folder, self.mail)
        self.mail.assert_not_called()

    def test_healthy_source_new_item_survives_other_baseline(self):
        self.snapshot([(DE, [], "")], FIRST)
        self.snapshot([(EN, [item()], ""), (DE, [item()], "")])
        deliver(self.folder, self.mail)
        self.mail.assert_called_once()

    def test_delayed_old_index_items_are_silent(self):
        self.empty()
        self.snapshot([(EN, [item(stamp="2026-10-29T12:00:00+00:00")], "")], LAST)
        deliver(self.folder, self.mail)
        self.mail.assert_not_called()

    def test_all_sources_down_leave_state_and_feed_intact(self):
        self.empty()
        state = (self.folder / "state.json").read_bytes()
        atom = (self.folder / "meldungen.atom").read_bytes()
        with self.assertRaises(RuntimeError):
            self.snapshot([(DE, [], "TimeoutError")])
        self.assertEqual((self.folder / "state.json").read_bytes(), state)
        self.assertEqual((self.folder / "meldungen.atom").read_bytes(), atom)

    def test_more_than_twenty_events_are_delivered_in_batches(self):
        self.empty()
        entries = [item(NIGHT + f" news {n}", str(n)) for n in range(23)]
        self.snapshot([(DE, entries, "")])
        deliver(self.folder, self.mail)
        self.assertEqual(len(load_state(self.folder)["pending"]), 3)
        self.snapshot([(DE, [], "")], LAST)
        deliver(self.folder, self.mail)
        self.assertEqual(self.mail.call_count, 2)
        self.assertFalse(load_state(self.folder)["pending"])

    def test_publication_is_valid_and_unchanged_when_no_new_items(self):
        self.empty()
        self.snapshot([(DE, [item(NIGHT + " & news", "example")], "")])
        body = (self.folder / "meldungen.atom").read_bytes()
        e = ET.fromstring(body).find("{http://www.w3.org/2005/Atom}entry")
        self.assertIn("Nachtara", e.findtext("{http://www.w3.org/2005/Atom}title"))
        self.snapshot([(DE, [], "")], LAST)
        self.assertEqual((self.folder / "meldungen.atom").read_bytes(), body)

    def test_v1_migration_rebaselines_and_corruption_fails_closed(self):
        path = self.folder / "state.json"
        path.write_text('{"initialized":true,"seen":["a"]}')
        self.snapshot([(DE, [item()], "")])
        deliver(self.folder, self.mail)
        self.mail.assert_not_called()
        path.write_text('{"version":7}')
        with self.assertRaises(ValueError):
            self.snapshot([(DE, [], "")])
        self.assertEqual(path.read_text(), '{"version":7}')


class SMTP(unittest.TestCase):
    def test_tls_mime_recipient_defaults_to_sender_and_stable_message_id(self):
        env = {"SMTP_USER": "test@example.invalid", "SMTP_PASS": "fixture-only"}
        with patch.dict(os.environ, env, clear=True), patch("monitor.smtplib.SMTP_SSL") as tls:
            conn = tls.return_value.__enter__.return_value
            conn.send_message.return_value = {}
            send_mail(SUBJECT, "Prüftext", "abc")
            self.assertEqual(tls.call_args.args, ("smtp.gmail.com", 465))
            self.assertTrue(tls.call_args.kwargs["context"].check_hostname)
            msg = conn.send_message.call_args.args[0]
            self.assertEqual(msg["To"], env["SMTP_USER"])
            self.assertEqual(msg["Message-ID"], "<upc.abc@drop-monitor.invalid>")
            self.assertEqual(str(msg["Subject"]), SUBJECT)
            self.assertIn("Prüftext", msg.get_content())

    def test_missing_secret_never_attempts_smtp(self):
        with patch.dict(os.environ, {}, clear=True), patch("monitor.smtplib.SMTP_SSL") as tls:
            with self.assertRaises(RuntimeError):
                send_mail("Test", "body")
            tls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
