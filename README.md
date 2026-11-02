# Pokémon Center Deutschland · Nachtara und Psiana

Dieses Python-Projekt baut einen öffentlichen Nachrichtenfeed zu den beiden 30th Celebration Ultra-Premium Collections. Bei einer neuen passenden Meldung schickt der Monitor eine E-Mail an den Eigentümer. Nachtara / Umbreon / Night hat im Versand Vorrang vor Psiana / Espeon / Day. Der Monitor nutzt ausschließlich öffentliche Suchfeeds. Für den Kauf öffnest du den Shop selbst.

## Was eine E-Mail bedeutet

| Ereignis | Grundlage |
| --- | --- |
| Produkt angekündigt | Der Suchindex ordnet die passende Ankündigung einer offiziellen Pokémon-Domain zu. |
| Produktseite entdeckt | Der Index liefert eine HTTPS-Produktadresse der Form `www.pokemoncenter.com/en-de/product/…` und dieselbe Fundstelle passt zur gesuchten Edition. Beim Lesen kann die Seite bereits veraltet sein. |
| Drop-Hinweis gefunden | Eine Veröffentlichung nennt die passende Jubiläums-UPC und die richtige Variante. Ein Reddit-Treffer braucht zusätzlich einen belegbaren Deutschland-Bezug. |
| Verfügbarkeit unbekannt | Dies ist der Bestellstatus in jeder E-Mail. Auch eine leere Suche oder ein technischer Ausfall lässt keine Aussage über den Bestand zu. |
| Tatsächlich bestellbar – unabhängig bestätigt | Dafür wäre ein unabhängiger, aktueller Nachweis aus dem deutschen Shop nötig. Keine der eingerichteten Quellen liefert diesen Nachweis. Der Alarm mit 🚨 bleibt deshalb gesperrt. |

Der Betreff für neue Meldungen lautet **🔎 POKÉMON UPC – Neuer Drop-Hinweis**. Die Nachricht nennt Edition, Ereignis, Quelle, Fundstelle und Erkennungszeit in Europe/Berlin. Ein im Suchindex belegter deutscher Produktlink wird entsprechend gekennzeichnet. Für den aktuellen Shoppreis gibt es ebenfalls keine belastbare Quelle.

## Quellen

Die fünf Abfragen stehen lesbar in [sources.json](sources.json). Dieselbe Datei enthält die Produktnamen und Editionsbegriffe. Für die ersten vier Abfragen dient Google News als Index.

| Abfrage | Welche Treffer zählen |
| --- | --- |
| Google News Deutschland | Deutsch- und englischsprachige Namen der Jubiläums-UPC. |
| Google News Großbritannien | Englische Bezeichnungen. Erkennbare reine Fremdmarkt- und Händlerangebote werden gefiltert. Internationale Produktankündigungen können früher erscheinen als deutsche Nachrichten. |
| Offizielle Meldungen | Ein Ergebnis muss Pokémon als Herausgeber erkennen lassen. Die abgerufene RSS-Suchseite allein gilt nicht als offizielle Mitteilung. |
| Reddit über Google News | Der Treffer muss Reddit zugeordnet sein. In seiner eigenen Überschrift muss z. B. „deutsches Pokémon Center“, „Pokémon Center Germany“ oder eine echte `pokemoncenter.com/en-de`-Adresse stehen. Belegsätze aus Nachbarartikeln, Subreddit-Namen, Europreise oder Deutschlandversand zählen nicht. Unsichere Fragen, Verneinungen und unklare Marktvergleiche werden ausgelassen. Die Mail nennt den konkreten Beleg. |
| Deutsche Produktlinks über Bing RSS | Nur Treffer mit echtem Pokémon-Center-Host, Deutschlandpfad, Produktkennung und passender Edition. US-/UK-URLs und URLs ähnlich geschriebener Domains werden verworfen. |

Der Monitor lädt keine Shop-, Warenkorb- oder Reddit-Seiten. Er führt keine Bestellungen aus. Google News erfasst nur einen Teil der Reddit-Beiträge. Steht der Deutschland-Beleg ausschließlich im Text oder in einem Kommentar, bleibt die Meldung aus. Suchindizes können Veröffentlichungen übersehen oder verspätet liefern. Der offizielle Reddit-Changelog nennt den 13. November 2026 als Ende der nativen RSS-Unterstützung. Für direkten Data-API-Zugriff verlangt Reddit eine Freigabe.

[Pokémon Center Deutschland](https://www.pokemoncenter.com/en-de) · [Crawler-Regeln des Shops](https://www.pokemoncenter.com/robots.txt) · [Reddit-Changelog](https://support.reddithelp.com/hc/en-us/articles/54353370049684-Changelog-October-8-2026) · [Reddit Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy)

## Betrieb und Kosten

Der Workflow testet den Code, aktualisiert bei Änderungen [den veröffentlichten Atom-Feed](data/meldungen.atom) und verschickt neue Meldungen. Die Feed-Datei entsteht beim ersten erfolgreichen Lauf. Im Zustandsprotokoll `data/state.json` stehen auch einmal pro Berliner Kalendertag Prüfzeit, Quellenstatus und Trefferzahlen. Der erste erfolgreiche Abruf jeder Quelle liefert die stille Ausgangsbasis.

- **Takt** · GitHub soll stündlich zu den Minuten 07, 17, 27, 37, 47 und 57 starten. In Deutschland gelten dieselben Minuten. GitHub kann Starts verzögern oder auslassen. Auch eine feste maximale Lücke von 30 Minuten ist nicht zugesichert. Im Reiter **Actions** stehen die tatsächlichen Startzeiten.
- **Kostengrenze** · Der Veröffentlichungsjob läuft nur im angegebenen öffentlichen Repository auf `main`. Alle Jobs prüfen die öffentliche Sichtbarkeit, bevor ein Runner startet. Verwendet wird der kostenlose GitHub-Standardrunner `ubuntu-slim`, ohne größere Runner, kostenpflichtige Cloud-Ressourcen, Cache- oder Artefakt-Uploads. Es fallen bei den geprüften Konditionen keine Runnergebühren an. Für den Mailversand genügt ein bestehendes kostenloses Gmail-Konto.
- **Betrieb** · Die Produktion läuft nach Aktivierung bei GitHub und Gmail, auch bei ausgeschaltetem PC. Der Monitor verwendet keine KI und benötigt keinen ChatGPT-Auftrag. GitHub kann Zeitpläne öffentlicher Repositories nach 60 Tagen ohne Repository-Aktivität deaktivieren. Den täglichen Quellenbericht und die letzten Runs kannst du im Projekt prüfen.
- **Abrufgrenzen** · Pro Lauf höchstens eine Abfrage pro Quelle, bis zu drei parallel, jeweils mit 12 Sekunden Netzwerk-Timeout und einer XML-Obergrenze von 2 MB. Zielwechsel zu Shop, Reddit oder anderen Hosts werden verworfen. Jeder Job ist auf drei Minuten begrenzt. Teilausfälle stehen im Laufprotokoll. Ein Totalausfall beendet die Erhebung mit Fehler.

[Abrechnung für GitHub Actions](https://docs.github.com/en/billing/concepts/product-billing/github-actions) · [Standardrunner](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job) · [Zeitpläne und Einschränkungen](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) · [Nutzung von Actions](https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features#actions)

## Einmalige Inbetriebnahme

1. Lege das öffentliche GitHub-Repository `oelfass-manufaktur/pokemon-center-drop-monitor` mit Standardbranch `main` an. Lade die **entpackten Dateien einschließlich `.github/workflows/monitor.yml`** ins Stammverzeichnis. Die Workflow-Datei darf nicht in einem zusätzlichen Unterordner liegen. Ein Push auf `main` startet die Tests.
2. Öffne für ein bestehendes Gmail-Konto die [Google-Seite für App-Passwörter](https://myaccount.google.com/apppasswords). 2‑Faktor-Anmeldung muss aktiv sein. Ein Konto kann durch Sicherheitsrichtlinien von App-Passwörtern ausgeschlossen sein. [Google-Hilfe](https://support.google.com/accounts/answer/185833?hl=de)
3. Hinterlege unter **Settings → Secrets and variables → Actions → New repository secret** die beiden folgenden Werte. Das App-Passwort gehört direkt in das Secret-Feld.

   | GitHub Actions Secret | Wert |
   | --- | --- |
   | `SMTP_USER` | Deine Gmail-Adresse. Sie ist standardmäßig auch die Empfangsadresse. |
   | `SMTP_PASS` | Ein für diesen Monitor erstelltes Gmail-App-Passwort. |
   | `ALERT_TO` | Optional, nur für eine abweichende Empfangsadresse. |

4. Öffne **Actions → Pokémon UPC Frühwarnsystem → Run workflow**, wähle `main` und aktiviere das Kontrollkästchen für den SMTP-Test. Wenn der Schritt „Manueller SMTP-Test“ erfolgreich ist und die Testmail im Posteingang ankommt, ist der Versand eingerichtet.
5. Starte denselben Workflow ohne das Test-Häkchen. Kontrolliere anhand der Logs „erste Bestandsaufnahme“ sowie den neuen Feed und Zustandsstand. Starte ihn erneut. Bei unveränderten Meldungen protokolliert er „Keine ausstehenden Meldungen. Keine E-Mail.“
6. Der Workflow erhält ausschließlich im Veröffentlichungsjob `contents: write`, um die zwei Dateien in `data/` zu aktualisieren. Organisationsregeln oder ein Branchschutz können den Schreibzugriff blockieren. Ein fehlgeschlagener Push vor dem Versand verhindert die Zustellung. Der Repository-Name, der Standardbranch und die Sichtbarkeit werden durch die Workflow-Bedingung geprüft.

## Wie Wiederholungen verhindert werden

Der Monitor merkt sich dauerhafte Fingerabdrücke passender Artikel, auch bei Wechsel zwischen Suchfeeds. Bei Produktseiten dient die deutsche Produktkennung als Schlüssel. Eine neu veröffentlichte Nachricht kann erneut qualifizieren. Hat eine Quelle den ersten Start verpasst, übernimmt sie bei der Wiederkehr still ihren Anfangsbestand.

Die Veröffentlichung speichert eine Versandliste **vor** der Übergabe an Gmail dauerhaft in Git. Ein SMTP-Fehler lässt die Liste unverändert, auch wenn der Artikel zwischenzeitlich aus dem Suchindex verschwindet. Der nächste Lauf versucht denselben Versand mit derselben Message-ID. Nach Annahme durch Gmail bestätigt ein zweiter Commit die Zustellung. Ein Systemabsturz genau zwischen SMTP-Annahme und diesem Commit kann eine doppelte E-Mail auslösen. Unveränderte Folgeläufe nach erfolgreicher Speicherung bleiben still.

Der öffentliche Feed enthält die letzten 50 veröffentlichten Meldungen. In Zustand und Feed stehen ausschließlich öffentliche Fundstellen und technische Daten. Die eigene Mailadresse und das App-Passwort stammen zur Laufzeit aus Actions Secrets. Zugangsdaten gehören weder in die Projektdateien noch in Commits oder Logs.

## Lokal prüfen

Benötigt wird Python 3.11 oder neuer mit IANA-Zeitzonendaten. Auf Windows lässt sich bei Bedarf das offizielle Python-Paket `tzdata` mit `py -m pip install tzdata` ergänzen. Auf dem Linux-Runner sind die Systemzeitzonen vorhanden.

```sh
python3 -m unittest discover -s tests -v
python3 monitor.py collect --data-dir .local-state
python3 monitor.py collect --data-dir .local-state
```

Unter Windows kann `py` anstelle von `python3` verwendet werden. Die lokalen Erhebungen versenden keine E-Mails. Die Tests simulieren Mailübergabe und Fehler. Nur `deliver` mit ausstehenden Meldungen oder `test-mail` baut eine SMTP-Verbindung auf.
