# Direkter Programmstart unter Windows

Bei aktiviertem Gesprächsmodus reicht beispielsweise:

- „Hey Sytox, öffne Spotify.“
- „Hey Sytox, starte Discord.“
- „Hey Sytox, öffne Google Chrome.“
- „Hey Sytox, starte das Programm Visual Studio Code.“

Der vorhandene Sprachrouter prüft weiterhin das Aktivierungswort bzw. das
erlaubte Zeitfenster für Anschlussbefehle. Die anschließende Programmanfrage
wird lokal erkannt und benötigt keine Modellantwort. Auch direkt getippte,
kompakte Startbefehle wie „Öffne Spotify“ verwenden diese Oberfläche.

## Vom Befehl zur Bestätigung

Die Suche läuft im Hintergrund, damit das Fenster bedienbar bleibt. Ein
eindeutiger Treffer zeigt sofort den tatsächlichen Namen und den Programmeintrag.
**Starten** ist die ausdrückliche Freigabe; es gibt keinen zusätzlichen
Auswahlklick und keine zweite Startabfrage. Standardmäßig ist **Abbrechen**
ausgewählt. Eine gesprochene Antwort wie „Ja“ erteilt keine Startfreigabe.

Ist das Programm bereits geöffnet, bietet SYTOX stattdessen **Nach vorne holen**
an. Die Zuordnung verwendet den tatsächlichen Windows-Prozess. Ein Browser-Tab,
in dessen Titel „Spotify“ steht, gilt dadurch nicht als Spotify-App. Unmittelbar
vor dem Fensterwechsel werden Fenster-ID und ausführbare Datei erneut geprüft.

Mehrere passende Programme oder Fenster werden ohne Vorauswahl angezeigt. Erst
Auswahl und anschließende Bestätigung führen eine Aktion aus. Exakte Namen haben
über alle bekannten Namensvarianten hinweg Vorrang vor Teiltreffern; ein Treffer
„Google Chrome Canary“ verdrängt damit keinen vorhandenen exakten Chrome-Eintrag.
Offensichtliche Installer-, Updater- und Deinstallationsverknüpfungen sind keine
Startvorschläge für das eigentliche Programm.

Bei fehlenden Treffern nennt SYTOX den gesuchten Namen und bietet **Erneut suchen**
an. Ein Fehler löst weder eine Installation noch eine Web- oder Shellsuche aus.
Veränderte oder entfernte Verknüpfungen benötigen eine neue Suche und Bestätigung.

## Verhalten während anderer Aufgaben

Ein lokaler Programmstart erstellt keinen Agentenauftrag und verändert keine
laufende Programmieraufgabe. Eine noch offene Startbestätigung wird durch einen
weiteren Befehl nicht auf ein anderes Ziel umgestellt. Nach erfolgreicher Aktion
oder erfolgloser Suche kann ein neuer Befehl eine neue Anfrage öffnen.

Abbrechen oder Schließen verwirft noch eintreffende Suchergebnisse. Beim Beenden
wartet SYTOX auf das Ende einer bereits laufenden, ausschließlich lesenden Suche,
bevor deren Qt-Thread und Fenster entfernt werden.

## Grenzen und Verifikation

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

Automatisierte Tests prüfen Sprachrouting, Namensauflösung, native Bestätigungen,
Abbruch, Fensteridentität, veränderte Verknüpfungen und Thread-Lebensdauer mit
kontrollierten Desktop-Adaptern. Win32-Tests verwenden API-Mocks. Ein echter
Windows-/Spotify-Test und ein Mikrofontest mit Vosk bleiben zusätzlich nötig.

```bash
python tools/app_launch_preview.py /pfad/zur/vorschau
```

Das Werkzeug erzeugt echte Qt-Screenshots für Einzel-, Mehrfach- und Fenstertreffer
mit ausdrücklich gekennzeichneten lokalen Beispieldaten. Es öffnet kein Programm
und verwendet weder Modell, Mikrofon noch Netzwerk.
