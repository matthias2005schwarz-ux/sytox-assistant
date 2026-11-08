# Projektverständnis und Prüfschleife

Bei Programmieraufträgen liest SYTOX vor dem ersten Modellschritt passende Dateien
aus dem ausgewählten Projektordner. Die Auswahl berücksichtigt konkrete Pfade,
Bezeichner, zugehörige Tests, erkennbare lokale Python-/JavaScript-Imports und
Projektdateien wie Manifeste oder README. Auszüge enthalten echte Zeilennummern.
Die Auswahl ist regelbasiert und begrenzt; sie ist kein vollständiger Abhängigkeitsgraph.

Die Werkzeuge `project_context` und `project_search` erlauben weitere gezielte
Abfragen. `read_file` unterstützt außerdem `start_line` und `end_line` (1-basiert,
einschließlich der letzten Zeile, höchstens 400 Zeilen). Ohne Zeilenangaben bleibt
die bisherige Ausgabe unverändert. Dateien sind Kontextdaten und keine neuen
Arbeitsanweisungen. Quellen werden nicht ausgeführt, um sie zu untersuchen.

Die Suche lässt unter anderem Versionsverwaltung, virtuelle Umgebungen,
`node_modules`, Buildordner und Backups aus. Sie verfolgt keine Dateiverknüpfungen
und überspringt typische Geheimnisdateien, Binärdateien und zu große Dateien.
Diese Begrenzungen ersetzen keine Prüfung beliebiger Quelltexte auf Geheimnisse.
Quellenauszüge gehen ausschließlich an das bereits konfigurierte Modell; es gibt
keinen zusätzlichen Suchdienst und keinen automatischen Paketdownload.

## Prüfungen und Fehlerkorrektur

### Gezielte Änderungen an bestehenden Dateien

`edit_file` ersetzt genau einen vorhandenen Textausschnitt. Die alte Stelle muss
eindeutig sein; fehlende oder mehrdeutige Treffer werden abgelehnt. Die KI soll
dann mehr Originalkontext nachlesen. `write_file` bleibt für neue Dateien oder
bewusst vollständig neu geschriebene Dateien verfügbar.

`read_file` kann mit `include_hash: true` den SHA-256-Hash der tatsächlichen Bytes
ausgeben. Dieser lässt sich als `expected_sha256` an `edit_file` übergeben. Ein
abweichender Dateistand wird nicht überschrieben. Gezielt bearbeitete Dateien
behalten UTF-8-BOM, unberührte Zeilenenden, Einrückung und Dateirechte. Vorherige
Versionen werden gesichert. Eine Ersetzung durch identischen Text zählt nicht
als Änderung und macht keine gültigen Test- oder Buildnachweise ungültig.

Die Bearbeitung ist auf Dateien bis 1 MiB begrenzt. Nummerierte Leseauszüge können
innerhalb dieses Limits bis zu 400 Zeilen umfassen. Dateiinhalte in Anfragen für
gezielte Änderungen werden im Aktivitätsprotokoll durch Längenangaben ersetzt.

### Tatsächliche Projektprüfungen

`project_check_plan` zeigt erkannte Prüfungen, ohne etwas auszuführen:

- Python: vorhandene unittest-Suiten oder durch Testcode/Konfiguration belegtes
  pytest. Ohne vorhandene Tests bleibt eine ausdrücklich als Syntaxprüfung
  bezeichnete Prüfung der Python-Dateien.
- JavaScript/TypeScript: ausgewählte bestehende npm-Skripte für einmalige lokale
  Jest-, Vitest- oder Node-Tests, ESLint, TypeScript und Vite-Builds. Platzhalter,
  Watchbetrieb und Skripte mit Lifecycle-Hooks werden nicht automatisch geplant.
- Unklare Konfigurationen, andere Sprachen und verschachtelte npm-Projekte
  benötigen weiterhin gezielt gewählte Befehle bzw. die vorhandenen Buildwerkzeuge.

`project_validate` führt den Plan über die normale Befehlsausführung aus. Die
bestehenden Nutzerfreigaben, Abbruchfunktion und Zeitgrenzen bleiben wirksam.
Tests führen Projektcode aus und benötigen weiterhin die vorhandene Testfreigabe;
Installationen und Releases sind keine geplanten Prüfschritte.

Vor einer Fertigmeldung führt der Agent erforderliche, noch nicht aktuell
bestandene Prüfungen automatisch aus. Das echte Ergebnis geht an das Modell
zurück. Bei Fehlern soll es die betroffene Quelle lesen, die Ursache korrigieren
und dieselbe Prüfung wiederholen. Die automatische Ausführung erfolgt höchstens
einmal pro Änderungsstand; weitere gezielte Läufe sind über `project_validate`
möglich. Tests sollen dafür weder gelöscht noch abgeschwächt werden.
Wiederholt das Modell dreimal nur eine abgelehnte Fertigmeldung, pausiert SYTOX
mit gespeichertem Fortschritt, statt ohne Korrektur weiterzulaufen.

Vor Änderungen erkannte Befehle bleiben beim Fortsetzen eines Auftrags erhalten.
Ein anderer grüner Test ersetzt keinen fehlgeschlagenen Test. Null Tests und nur
übersprungene Tests gelten nicht als bestandener Funktionstest. Nach jeder
weiteren Änderung werden alte Ausführungsnachweise ungültig. Nach einem Neustart
werden die erforderlichen Projektprüfungen erneut ausgeführt.

Eine erfolgreiche Prüfung beweist nur den geprüften Umfang: Syntaxprüfung ist
kein Funktionstest, ein Build kein erfolgreicher Lauf der Anwendung. Bei begrenzter
Dateiauswahl, fehlenden Werkzeugen oder projektspezifischen Importpfaden meldet
der Plan die Einschränkungen, statt Abhängigkeiten auf Verdacht zu installieren.

### Zusätzlicher Codeprüfer

Nach bestandenen Prüfungen erhält ein separater Prüfdurchlauf am bereits
konfigurierten Modell den Auftrag, den tatsächlichen Unterschied zur ursprünglichen
Sicherheitskopie und die echten Prüfausgaben. `project_diff` macht diese Änderungen
auch als rein lesendes Werkzeug zugänglich. Der Prüfer bekommt keine Werkzeuge,
ändert keine Dateien und erhält eine eigene Unterhaltung. Er untersucht konkrete
Logikfehler, übersehene Anforderungen, unbeabsichtigte Änderungen und wichtige
fehlende Tests. Ein zweiter Modelltyp wird dafür nicht vorausgesetzt.

Konkrete Befunde verhindern die Fertigmeldung und gehen als strukturierte Daten
an den arbeitenden Agenten zurück. Nach Korrekturen sind neue Tests und ein neues
Review nötig. Auch ein zusätzlicher Testlauf ohne Codeänderung kann ein neues
Review auslösen, wenn ein vorheriger Befund nur einen fehlenden Testnachweis betraf.
Ungültige Antworten oder ein nicht verfügbarer Prüfer gelten nicht als bestanden.

Die Auswertung bindet Prüfnachweise an Datei-Hashes. Änderungen während der
Codeprüfung oder nach einem Test machen den betreffenden Nachweis ungültig. Beim
Fortsetzen bleibt die ursprüngliche Vergleichsbasis erhalten; ein gespeichertes
Modellurteil wird nicht als frische Prüfung übernommen. Aktive Vergleichskopien
bleiben bei der Aufbewahrungsbereinigung weiterer Zusatzaufträge geschützt.

Größere Diffs werden in höchstens sechs begrenzte Abschnitte aufgeteilt. Nicht
vollständig erfasste Quelländerungen bekommen kein vollständiges Review. Typische
Geheimnisdateien werden nicht als Text übertragen; Binärdateien und Assets werden
als Metadaten erfasst und nicht als inhaltlich geprüft bezeichnet. Das Modellurteil
bleibt eine zusätzliche Kontrolle innerhalb dieses Umfangs und beweist keine
Fehlerfreiheit. Der Schnellchat löst diesen Prüfdurchlauf nicht aus.

## Verifikation dieser Änderung

Automatisierte Prüfungen verwenden echte temporäre Mehrdateiprojekte und echte
lokale Python-Testprozesse. Die Modellantworten werden dabei simuliert, damit
Kontextauswahl, Fehlerweitergabe, Reparatur, erneute Prüfung, Freigabeverweigerung
und Fortsetzung reproduzierbar geprüft werden können. Das ist kein gemessener
Qualitätssprung eines laufenden Ollama-Modells. Ein praktischer Windows-/Ollama-Test
mit dem gewählten Modell und dessen Hardware bleibt zusätzlich nötig.
