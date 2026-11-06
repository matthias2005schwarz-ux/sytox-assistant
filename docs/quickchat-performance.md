# Schnellchat: Optimierung im Entwicklungszweig

Normale Gespräche wie „Hallo“ verwenden jetzt einen eigenen Antwort-Thread mit
`qwen3:4b`, ohne Aufgaben-Agent, Werkzeug-Schema, Projekt-Backup oder Agent-Schleife.
Der Qwen3-Thinking-Modus ist für diesen Gesprächspfad deaktiviert. Tokens werden
sofort aus dem Ollama-Stream weitergereicht und während der Generierung angezeigt.
Allgemeine Definitionen wie „Was ist Python?“ warten nicht erst auf Websuchanbieter.
Ausdrückliche Recherche, aktuelle Angaben und Personenfragen behalten die Websuche.

Programmieraufträge, ausdrückliche Datei-/PC-Aktionen und Qwen-Projekte behalten
den Agenten und seine Freigaben. Qwen-Projekte bleiben beim Projektmodell
`qwen3-coder:30b`; manuelle Modellwahl und vorhandene Chatdaten bleiben erhalten.
Die Nebenunterhaltung während eines Auftrags streamt ebenfalls und kann unabhängig
abgebrochen werden. Einfache Zwischenfragen stoppen den Programmierauftrag nicht.

## Bedienung und Messwerte

- „Stopp“ bricht eine Schnellchat-Antwort ab. Teilantworten und Verbindungsabbrüche
  werden sichtbar als unvollständig gekennzeichnet und nicht automatisch vorgelesen.
- Der Modellname zeigt als Tooltip getrennt die Wartezeit auf einen Modellplatz,
  Modellladezeit, Zeit bis zum ersten sichtbaren Token und Tokens pro Sekunde.
  Dieselben Werte stehen im Aktivitätenprotokoll. Fehlende Ollama-Messwerte werden
  nicht geschätzt. Die Tokenzeit beginnt beim HTTP-Modellaufruf; eine vorgeschaltete
  Bildschirmdiagnose oder Websuche ist darin nicht enthalten.
- Neue Einstellungen halten ein ungenutztes Modell fünf Minuten bereit statt einer
  Minute. Vorhandene eigene RAM-Einstellungen, einschließlich sofortigem Entladen,
  bleiben erhalten. Bei häufigen Kaltstarts lässt sich der Wert unter Einstellungen
  auf 300 Sekunden erhöhen. Bei Speichermangel kann Ollama Modelle früher verdrängen.
- Gesprächsverlauf und Zusatzkontext erhalten ein begrenztes Zeichenbudget für den
  interaktiven Kontext. Eine einzelne Gesprächsnachricht über 12.000 Zeichen wird
  ausdrücklich abgelehnt, nicht still gekürzt. Die bestehenden Agentenlimits für
  lange Programmieraufträge werden durch diesen Schnellchat-Pfad nicht verändert.

## Vergleich messen

Ohne Ollama ist ein reproduzierbarer Transportvergleich möglich:

```bash
python tools/benchmark_quickchat.py --runs 3
```

Der lokale Testserver sendet einen ersten kurzen Text nach ungefähr 30 ms und die
fertige Antwort nach ungefähr 500 ms. Verglichen werden beim **selben** Antwortstrom
die frühere Anzeige erst nach vollständiger Antwort und die neue Anzeige ab dem
ersten Text. Dieser Test misst die Streaming-Sichtbarkeit, **keine** schnellere
Modellberechnung und keine GPU-Leistung.

In drei Cloud-Läufen lag die erste sichtbare Ausgabe im Mittel bei **0,033 s**
statt **0,504 s** beim Warten auf die gesamte simulierte Antwort. Die simulierte
Antwort selbst war dadurch nicht schneller fertig.

Auf dem Windows-PC mit bereits laufendem Ollama und installiertem Modell:

```powershell
.\.venv\Scripts\python.exe tools/benchmark_quickchat.py --live --model qwen3:4b --runs 2
```

Die Ausgabe enthält Ladezeit, Tokenzeit und Generierungsrate, keine Gesprächsinhalte.
Der Benchmark lädt keine Modelle herunter und erzwingt keine Entladung. Der erste
Lauf kann kalt, der zweite bereits warm sein; `load_s` zeigt den Unterschied.
Eine echte Vorher-Nachher-Messung auf dem Nutzer-PC liegt in der Cloud nicht vor.

## Grenzen und Tests

Die Offline-Tests prüfen echte lokale HTTP-/NDJSON-Übertragung, sichtbare Tokens vor
Antwortabschluss, Timeout, Abbruch blockierter Reads, beschädigte Streams und
Messmetadaten. Qt-Tests prüfen den tatsächlichen Senden-Pfad, Datenspeicherung,
Modellwahl, Arbeitstrennung und Chat-Navigation während des Streams.

Verbindungsaufbau und das Warten auf HTTP-Header sind durch 5 Sekunden Verbindungs-
und 45 Sekunden Lesezeitlimit begrenzt. Ein Abbruch in dieser Phase kann entsprechend
verzögert sein. Sobald die Header vorliegen, unterbricht der Abbruch auch einen
blockierten Antwort-Read. Laufende Programmieraufträge behalten ihr bisheriges
längeres Lesezeitlimit; sie erhalten kein neues Gesamtlaufzeitlimit.

Windows, reale Inferenz, Mikrofon, Sprachausgabe, Bildschirmmodell und GPU-Leistung
benötigen weiterhin Praxistests auf dem Ziel-PC. Die umfassende weitere Wunschliste
(Markdown/Code-Rendering, Umbau der Steuerzentrale, Sprachqualität, weitergehendes
Gedächtnis und Agenten-/Selbstverbesserung) ist nicht Teil dieser ersten
Schnellchat-Änderung. Updater, Prüfsummen und Rücksetzung bleiben unverändert.
Es wird dafür kein Installer gebaut, kein Release veröffentlicht und nichts auf
dem Nutzer-PC automatisch installiert.
