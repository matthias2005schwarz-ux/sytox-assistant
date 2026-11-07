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

## Grenzen der Prüfung

Automatisierte Tests prüfen, welche Vorgaben und Daten das lokale Modell erhält,
wie Projekte getrennt werden und wann Aktionen ausgelöst werden. Sie belegen
keine fehlerfreie Sprachinterpretation und keine gemessene Verbesserung einer
echten Modellantwort. Reale Ollama-/GPU- und Windows-Praxistests stehen weiterhin
aus. Bestehende Daten werden erhalten; es wird kein Modell neu trainiert und kein
Installer oder Release erstellt.
