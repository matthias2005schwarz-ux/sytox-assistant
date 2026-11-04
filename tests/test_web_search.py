"""Offline regression tests for read-only public web research."""
import threading
import unittest
from unittest.mock import MagicMock, patch

from sytox.web_search import should_search, search_web, format_results
from sytox.actions import tool_schema, Toolkit
from sytox.agent import Agent


class SearchHeuristicTests(unittest.TestCase):
    def test_factual_and_live_questions(self):
        self.assertTrue(should_search('Wer ist Jenna Ortega?'))
        self.assertTrue(should_search('Hey Sytox, wer ist Jenna Ortega?'))
        self.assertTrue(should_search('Suche im Internet nach dem Wetter'))
        self.assertTrue(should_search('Was ist GPT-6?'))
        self.assertTrue(should_search('Was sind die neuesten Nachrichten?'))

    def test_does_not_search_task_controls_or_private_prompts(self):
        self.assertFalse(should_search('Wie weit bist du?'))
        self.assertFalse(should_search('Hör kurz auf zu programmieren'))
        self.assertFalse(should_search('Programmiere ein Python-Skript'))
        self.assertFalse(should_search('Wer ist Jenna Ortega ohne Internet?'))
        self.assertFalse(should_search('Wer ist ' + 'A' * 300))

    def test_rss_search_has_source_links(self):
        xml = '''<?xml version="1.0"?>
        <rss><channel><item><title>Jenna Ortega — Profil</title>
        <link>https://example.org/jenna</link><description>US-Schauspielerin</description>
        </item></channel></rss>'''
        response = MagicMock()
        response.text = xml
        response.content = xml.encode()
        with patch('sytox.web_search.requests.get', return_value=response) as get:
            items = search_web('Wer ist Jenna Ortega?')
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]['url'], 'https://example.org/jenna')
            self.assertIn('Schauspielerin', format_results('Jenna Ortega', items))
            self.assertEqual(get.call_count, 1)
            self.assertEqual(get.call_args.kwargs['params']['format'], 'rss')

    def test_duckduckgo_fallback_and_untrusted_redirect(self):
        first = MagicMock()
        first.text, first.content = 'not RSS', b'not RSS'
        duck = ('<div class="result"><a class="result__a" '
                'href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fprofile">'
                'Jenna <b>Ortega</b></a>'
                '<a class="result__snippet">Bekannte Schauspielerin</a></div>')
        second = MagicMock()
        second.text, second.content = duck, duck.encode()
        with patch('sytox.web_search.requests.get', side_effect=[first, second]) as get:
            items = search_web('Jenna Ortega')
        self.assertEqual(get.call_count, 2)
        self.assertEqual(items[0]['url'], 'https://example.org/profile')
        self.assertEqual(items[0]['title'], 'Jenna Ortega')
        self.assertIn('Bekannte', items[0]['snippet'])

    def test_network_failure_stays_transparent(self):
        import requests
        with patch('sytox.web_search.requests.get', side_effect=requests.Timeout('offline')):
            items = search_web('Wer ist Jenna Ortega?')
        self.assertEqual(items, [])
        self.assertIn('Keine Live-Suchergebnisse', format_results('Jenna Ortega', items))

    def test_cancelled_search_sends_no_network_request(self):
        stop = threading.Event()
        stop.set()
        with patch('sytox.web_search.requests.get') as get:
            self.assertEqual(search_web('Jenna Ortega', stop_event=stop), [])
            get.assert_not_called()

    def test_agent_exposes_web_search(self):
        tools = [tool['function']['name'] for tool in tool_schema()]
        self.assertIn('web_search', tools)


if __name__ == '__main__':
    unittest.main()
