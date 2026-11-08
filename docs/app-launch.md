# Direkter Programmstart unter Windows

Bei aktiviertem Gesprächsmodus reicht beispielsweise:

- „Hey Sytox, öffne Spotify.“
- „Hey Sytox, starte Discord.“
- „Hey Sytox, öffne Google Chrome.“
- „Hey Sytox, starte das Programm Visual Studio Code.“
- „Hey Sytox, öffne GIMP.“

Der vorhandene Sprachrouter prüft weiterhin das Aktivierungswort bzw. das
erlaubte Zeitfenster für Anschlussbefehle. Die anschließende Programmanfrage
wird lokal erkannt und benötigt keine Modellantwort. Auch direkt getippte,
kompakte Startbefehle wie „Öffne Spotify“ verwenden diesen Weg. Das Verhalten gilt
für alle eindeutig auffindbaren Programme, nicht nur für die Beispiele.

## Vom Befehl zum geöffneten Programm

Die Suche läuft im Hintergrund, damit das Fenster bedienbar bleibt. Ein eindeutig
gefundenes Programm wird unmittelbar geöffnet. Es erscheint keine zusätzliche
Startbestätigung und es ist kein Klick auf **Starten** erforderlich. Die
Startaufforderung ist bereits im gesprochenen oder getippten Befehl enthalten.

Ist das Programm bereits geöffnet, holt SYTOX das passende Fenster direkt nach
vorne. Die Zuordnung verwendet den tatsächlichen Windows-Prozess. Ein Browser-Tab,
in dessen Titel „Spotify“ steht, gilt dadurch nicht als Spotify-App. Unmittelbar
vor dem Fensterwechsel werden Fenster-ID und ausführbare Datei erneut geprüft.

Mehrere passende Programme oder Fenster werden ohne Vorauswahl angezeigt. Ein
Klick auf den gewünschten Eintrag oder dessen Aktivierung mit Enter öffnet ihn
direkt; ein zweiter Bestätigungsklick entfällt. Das bloße Durchgehen der Liste mit
den Pfeiltasten führt noch keine Aktion aus. Exakte Namen haben
über alle bekannten Namensvarianten hinweg Vorrang vor Teiltreffern; ein Treffer
„Google Chrome Canary“ verdrängt damit keinen vorhandenen exakten Chrome-Eintrag.
Offensichtliche Installer-, Updater- und Deinstallationsverknüpfungen sind keine
Startvorschläge für das eigentliche Programm.

Bei fehlenden Treffern nennt SYTOX den gesuchten Namen und bietet **Erneut suchen**
an. Ein Fehler löst weder eine Installation noch eine Web- oder Shellsuche aus.
Veränderte oder entfernte Verknüpfungen werden nicht geöffnet. Die Meldung bietet
eine erneute Suche an.

## Verhalten während anderer Aufgaben

Ein lokaler Programmstart erstellt keinen Agentenauftrag und verändert keine
laufende Programmieraufgabe. Eine noch offene Trefferauswahl wird durch einen
weiteren Befehl nicht auf ein anderes Ziel umgestellt. Nach erfolgreicher Aktion
oder erfolgloser Suche kann ein neuer Befehl eine neue Anfrage öffnen.

Abbrechen oder Schließen verwirft noch eintreffende Suchergebnisse. Beim Beenden
wartet SYTOX auf das Ende einer bereits laufenden, ausschließlich lesenden Suche,
bevor deren Qt-Thread und Fenster entfernt werden.

## Grenzen und Verifikation

Die Änderung betrifft das Öffnen von Programmen und den zugehörigen Fensterwechsel.
Sie erteilt keine zusätzliche Freigabe für Installationen, Löschen von Dateien oder
andere PC-Aktionen.

Die Funktion benötigt Windows. Noch nicht geöffnete Apps müssen über eine
passende `.lnk`-Verknüpfung im Nutzer-/gemeinsamen Startmenü oder auf dem Desktop
auffindbar sein. Nicht jede Store-App besitzt einen solchen Eintrag. Einige
bekannte Programmnamen haben feste Aliase; unbekannte Namen werden konservativ
verglichen. Es gibt keine unscharfe Zuordnung ähnlich klingender Spracherkennung.

Fragen, Suchaufträge, Negationen, Dateipfade, URLs und zusammengesetzte Befehle
werden vom direkten Startweg ausgeschlossen. Die bisherige reine Programmsuche
unter Windows-Steuerung bleibt verfügbar. „Startbefehl an Windows übergeben“
bezeichnet den übergebenen Startaufruf und beweist nicht, dass eine App vollständig
geladen oder funktionsfähig ist.

Automatisierte Tests prüfen Sprachrouting, Namensauflösung, automatisches Öffnen,
Trefferauswahl, Abbruch, Fensteridentität, veränderte Verknüpfungen und Thread-Lebensdauer mit
kontrollierten Desktop-Adaptern. Win32-Tests verwenden API-Mocks. Ein echter
Windows-/Spotify-Test und ein Mikrofontest mit Vosk bleiben zusätzlich nötig.

```bash
python tools/app_launch_preview.py /pfad/zur/vorschau
```

Das Werkzeug erzeugt echte Qt-Screenshots für Einzel-, Mehrfach- und Fenstertreffer
mit ausdrücklich gekennzeichneten lokalen Beispieldaten. Ein kontrollierter
Desktop-Adapter zeichnet die simulierten Start-/Fokusaufrufe auf. Nur für die
Vorschau werden die sonst verborgen bleibenden Erfolgsansichten angezeigt. Es
öffnet kein echtes Programm und verwendet weder Modell, Mikrofon noch Netzwerk.
