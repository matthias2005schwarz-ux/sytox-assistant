# Aufgabenerkennung und Gesprächskontext im Entwicklungszweig

SYTOX unterscheidet ausdrückliche Aufträge von Erklärungsfragen, Beispielen und
verneinten Aktionen. „Was ist Python? Erstelle danach eine App“ enthält weiterhin
einen Programmierauftrag. Zitierte Befehle oder „Starte das Programm nicht neu“
lösen dagegen keine entsprechende Werkzeugroute aus. Manuelle Modellwahl und
die feste Projektmodell-Auswahl bleiben erhalten. Die Erkennung verwendet lokale
Regeln; mehrdeutige natürliche Sprache kann weiterhin falsch eingeordnet werden.

## Relevante lokale Erinnerungen

Der Gedächtnisabruf berücksichtigt ausdrücklich benannte Projekte und die
Zugehörigkeit zu einem Qwen-Projektchat. Gemeinsame Wörter wie „Oberfläche“ reichen
nicht mehr aus, um Vorgaben eines fremden Projekts einzumischen. Aktuelle
Nutzerkorrekturen und bearbeitete Fakten erhalten Vorrang vor alten Textauszügen.
Modellantworten werden dabei nicht als bestätigte Nutzerangaben abgerufen.

Auch ältere Nutzerangaben aus dem aktuellen Chat können wieder eingeblendet
werden, wenn sie zur neuen Frage passen und außerhalb des jüngsten Verlaufs
liegen. Eine überholte Farbaussage wird entfernt, während eine unabhängige
Schriftgrößenvorgabe im selben alten Beitrag erhalten bleiben kann.

Dieser Abruf erfolgt lokal mit Text-/Themenabgleich und SQLite. Es wird keine
zusätzliche Modellanfrage zur Zusammenfassung benötigt. Auszüge tragen eine
Herkunftsangabe und bleiben unbestätigter Kontext. Die jüngsten vollständigen
Frage-Antwort-Paare haben im begrenzten Gesprächskontext Vorrang vor zusätzlichen
Randnotizen; die aktuelle Nutzerfrage wird nicht still gekürzt.

Die Datenbankabfragen für den Schnellchat laufen im Antwort-Thread. Einfache
Begrüßungen überspringen den Gedächtnisabruf weiterhin. Persönliche Erinnerungs-,
Projekt-, Konto- und Gerätefragen lösen keine automatische öffentliche Websuche
aus. Ausdrückliche Rechercheaufträge bleiben möglich; Offline-Wünsche haben Vorrang.

## Programmieraufträge abschließen und fortsetzen

Auch der Modus „Einmal“ führt Programmieraufträge durch Werkzeugschritte,
Prüfungen und eine ausdrückliche Abschlussmeldung. Ein bloßes „Fertig“ reicht
nicht. Fehlgeschlagene Prüfungen werden pro normalisiertem Befehl gespeichert
und bleiben bei einer Fortsetzung offen. Ein anderer grüner Test oder eine
Syntaxprüfung beseitigt einen fehlgeschlagenen Funktionstest nicht. Der
ursprüngliche Prüfaufruf muss erfolgreich wiederholt werden; veränderte
Prüfbefehle werden konservativ als andere Prüfung behandelt.

Eine Abschlussmeldung vor weiteren angekündigten Werkzeugaufrufen wird
abgelehnt. Nachfolgende Änderungen werden ausgeführt und brauchen erneut einen
Nachweis. Freigaben, Backups, Abbruch und vorhandene Arbeitszeitmodi bleiben
erhalten. Leere, nur gesammelte oder vollständig übersprungene Tests gelten
nicht als bestandener Funktionstest.

Bei langen Aufgaben ersetzt eine protokollgerechte Kontextkürzung das bisherige
Abschneiden nach Nachrichtenanzahl. Ursprünglicher Auftrag, neuere echte
Nutzeranweisungen, Zusatzauftrag und offene Prüfanforderungen bleiben verfügbar.
Werkzeugaufrufe und ihre Ergebnisse werden zusammengehalten. Historische Daten
aus Dateien, Bildschirm oder Suche werden nicht zu neuen Nutzeranweisungen
erklärt. Diese Zuordnung verbessert die Kontextaufbereitung, ist aber keine
Garantie gegen Prompt-Injection durch ein lokales Modell.

Lange Werkzeugausgaben behalten Anfang und Ende mit sichtbarer Kürzungsmarkierung,
damit terminale Fehlermeldungen nicht verloren gehen. Das Zeichenbudget ist eine
Heuristik, kein exakter Tokenzähler; unverzichtbare Anweisungen werden dafür nicht
still gekürzt. Ein zu großer Pflichtkontext kann weiterhin das Modellfenster
überschreiten. Es wurde kein neues Gesamtlaufzeitlimit für Programmieraufträge
eingeführt.

Python-Dateiänderungen verwerfen nur zugehörige, im Projekt liegende generierte
Bytecode-Dateien. Damit verwenden Reparaturtests auch bei gleich großen Änderungen
innerhalb einer Sekunde den aktuellen Quelltext. Exklusiv erzeugte temporäre Dateien
schützen den Schreibpfad vor vorbereiteten temporären Symlinks.

## Grenzen der Prüfung

Automatisierte Tests prüfen, welche Vorgaben und Daten das lokale Modell erhält,
wie Projekte getrennt werden und wann Aktionen ausgelöst werden. Sie belegen
keine fehlerfreie Sprachinterpretation und keine gemessene Verbesserung einer
echten Modellantwort. Reale Ollama-/GPU- und Windows-Praxistests stehen weiterhin
aus. Bestehende Daten werden erhalten; es wird kein Modell neu trainiert und kein
Installer oder Release erstellt.
