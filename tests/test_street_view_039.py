"""Offline safety and address URL regression tests for Instant Street View."""
import unittest
from pathlib import Path

from sytox.place_queries import instant_street_view_url, place_from_message

ROOT = Path(__file__).resolve().parents[1]


class InstantStreetViewTests(unittest.TestCase):
    def test_encoded_website_url_without_google_api_key(self):
        self.assertEqual(
            instant_street_view_url('Kärntner Straße 1, Wien'),
            'https://www.instantstreetview.com/s/K%C3%A4rntner%20Stra%C3%9Fe%201%2C%20Wien'
        )

    def test_empty_or_unreasonably_large_query_rejected(self):
        for value in (' ', 'x' * 200, 'abc' + chr(10) + 'xyz'):
            with self.subTest(value=value[:12]):
                with self.assertRaises(ValueError):
                    instant_street_view_url(value)

    def test_german_place_questions_recognized_without_network(self):
        samples = {
            'Wofür ist Wien bekannt?': 'Wien',
            'Wie sieht Schloss Schönbrunn aus?': 'Schloss Schönbrunn',
            'Wo liegt Salzburg?': 'Salzburg',
            'Erzähl mir etwas über Paris.': 'Paris',
            'Zeig mir Street View von Berlin': 'Berlin',
            'Street View für Kärntner Straße 1, Wien': 'Kärntner Straße 1, Wien',
        }
        for question, expected in samples.items():
            with self.subTest(question=question):
                self.assertEqual(place_from_message(question), expected)

    def test_no_spurious_places_or_secrets(self):
        for text in ('Programmiere einen neuen Installer',
                     'Mein Passwort ist geheim',
                     'Was weißt du über mein API Key token',
                     'Wie viel ist 4 + 5?'):
            with self.subTest(text=text):
                self.assertIsNone(place_from_message(text))

    def test_ui_offers_place_but_never_auto_opens_external_page(self):
        ui = (ROOT / 'sytox/ui.py').read_text(encoding='utf-8')
        viewer = (ROOT / 'sytox/place_view.py').read_text(encoding='utf-8')
        start = ui.index('    def offer_place_if_relevant(self, message):')
        end = ui.index('    def _animate_appearance(', start)
        offer = ui[start:end]
        self.assertIn('self.place_panel.offer_location(place)', offer)
        self.assertNotIn('.load_place(', offer)
        self.assertNotIn('.open_browser(', offer)
        self.assertIn('self.offer_place_if_relevant(txt)', ui)
        self.assertIn("self.focus_btn = QPushButton('☰')", ui)
        self.assertIn('self.viewer.load(url)', viewer)
        self.assertIn('def open_browser(self):', viewer)


if __name__ == '__main__':
    unittest.main()
