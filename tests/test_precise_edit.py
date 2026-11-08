"""Exact source editing preserves surrounding bytes and rejects stale guesses."""
import hashlib
import unittest

from sytox.precise_edit import EditError, MAX_FILE_BYTES, prepare_edit


class PreciseEditTests(unittest.TestCase):
    def test_one_function_changes_without_rewriting_neighbors_or_comments(self):
        source = ('# unverändert: Grüße 👋\n'
                  'def first(value):\n\treturn value + 1\n\n'
                  'def second(value):\n\treturn value * 2\n').encode('utf-8')
        result = prepare_edit(source, 'def first(value):\n\treturn value + 1',
                              'def first(value):\n\treturn value + 2')
        self.assertEqual(result['content'], source.replace(b'value + 1', b'value + 2'))
        self.assertTrue(result['changed'])
        self.assertEqual(result['before_sha256'], hashlib.sha256(source).hexdigest())
        self.assertEqual(result['after_sha256'], hashlib.sha256(result['content']).hexdigest())

    def test_missing_or_ambiguous_and_overlapping_text_is_rejected(self):
        for source, old in ((b'a = 1\n', 'a=1'), (b'return 1\nreturn 1\n', 'return 1'),
                            (b'aaa', 'aa'), (b'x\r\nx\n', 'x\n')):
            with self.subTest(source=source, old=old), self.assertRaises(EditError):
                prepare_edit(source, old, 'replacement')
        source = b'def one():\n    return 1\ndef two():\n    return 1\n'
        result = prepare_edit(source, 'def two():\n    return 1', 'def two():\n    return 2')
        self.assertEqual(result['content'], source.replace(b'def two():\n    return 1', b'def two():\n    return 2'))

    def test_hash_guard_checks_the_actual_bytes_including_line_endings(self):
        source = b'VALUE = 1\r\n'
        digest = hashlib.sha256(source).hexdigest()
        result = prepare_edit(source, 'VALUE = 1', 'VALUE = 2', digest.upper())
        self.assertEqual(result['content'], b'VALUE = 2\r\n')
        for supplied in (hashlib.sha256(b'VALUE = 1\n').hexdigest(), 'invalid', '', False):
            with self.subTest(supplied=supplied), self.assertRaises(EditError):
                prepare_edit(source, 'VALUE = 1', 'VALUE = 2', supplied)

    def test_bom_crlf_tabs_unicode_and_trailing_newline_are_preserved(self):
        source = b'\xef\xbb\xbf' + '# Grüße 👋\r\ndef greet():\r\n\treturn "Hallo"\r\n'.encode('utf-8')
        result = prepare_edit(source, 'def greet():\n\treturn "Hallo"',
                              'def greet():\n\treturn "Servus 👋"')
        expected = source.replace(b'"Hallo"', '"Servus 👋"'.encode('utf-8'))
        self.assertEqual(result['content'], expected)
        self.assertEqual(result['content'].count(b'\xef\xbb\xbf'), 1)

    def test_bom_from_a_full_file_read_does_not_get_lost_or_duplicated(self):
        source = b'\xef\xbb\xbfVALUE = 1\r\n'
        for replacement in ('VALUE = 2\n', '\ufeffVALUE = 2\n'):
            with self.subTest(replacement=replacement):
                result = prepare_edit(source, '\ufeffVALUE = 1\n', replacement)
                self.assertEqual(result['content'], b'\xef\xbb\xbfVALUE = 2\r\n')

    def test_mixed_untouched_line_endings_survive_inside_and_outside_the_edit(self):
        source = b'# before\r\ndef first():\n\tleft = 1\r\n\t# kept\n\treturn 1\r\n# after\r'
        old = 'def first():\n\tleft = 1\n\t# kept\n\treturn 1\n'
        new = 'def first():\n\tleft = 2\n\t# kept\n\treturn 2\n'
        result = prepare_edit(source, old, new)
        self.assertEqual(result['content'], source.replace(b'left = 1', b'left = 2').replace(b'return 1', b'return 2'))

    def test_inserted_lines_follow_the_replaced_region_convention(self):
        source = b'header\nstart\r\nfinish\r\nfooter\n'
        result = prepare_edit(source, 'start\nfinish\n', 'start\ninserted\nfinish\n')
        self.assertEqual(result['content'], b'header\nstart\r\ninserted\r\nfinish\r\nfooter\n')
        # A one-line match uses its own following line ending, not the whole file's majority.
        result = prepare_edit(source, 'start', 'start\ninserted')
        self.assertEqual(result['content'], b'header\nstart\r\ninserted\r\nfinish\r\nfooter\n')

    def test_empty_replacement_deletes_only_the_requested_region(self):
        source = 'α = 1\r\n# remove 👋\r\nω = 2'.encode('utf-8')
        result = prepare_edit(source, '# remove 👋\n', '')
        self.assertEqual(result['content'], 'α = 1\r\nω = 2'.encode('utf-8'))

    def test_noop_retains_the_original_byte_object_even_with_normalized_input(self):
        source = b'\xef\xbb\xbfVALUE = 1\r\n# unchanged\n'
        result = prepare_edit(source, 'VALUE = 1\n# unchanged\n', 'VALUE = 1\n# unchanged\n')
        self.assertIs(result['content'], source)
        self.assertFalse(result['changed'])
        self.assertEqual(result['before_sha256'], result['after_sha256'])

    def test_invalid_inputs_and_binary_files_are_rejected(self):
        for source, old, new in ((b'value', '', 'x'), (b'\xffvalue', 'value', 'x'),
                                 (b'va\0lue', 'value', 'x'), (b'value', 'value', 'x\0'),
                                 (b'value', 1, 'x'), (b'value', 'value', None),
                                 ('value', 'value', 'x'), (b'value', 'value', '\ud800')):
            with self.subTest(source=source, old=old, new=new), self.assertRaises(EditError):
                prepare_edit(source, old, new)

    def test_source_replacement_and_final_file_limits_are_enforced(self):
        with self.assertRaises(EditError):
            prepare_edit(b'x' * (MAX_FILE_BYTES + 1), 'x', 'y')
        with self.assertRaises(EditError):
            prepare_edit(b'x', 'x', 'y' * (MAX_FILE_BYTES + 1))
        source = b'x' + b' ' * (MAX_FILE_BYTES - 1)
        with self.assertRaises(EditError):
            prepare_edit(source, 'x', 'yy')

    def test_large_excerpts_with_small_changes_use_the_existing_bytes(self):
        source = b'# repeated\r\n' * 3000 + b'VALUE = 1\r\n' + b'# repeated\n' * 3000
        old = source.decode('utf-8').replace('\r\n', '\n')
        new = old.replace('VALUE = 1', 'VALUE = 2')
        result = prepare_edit(source, old, new)
        self.assertEqual(result['content'], source.replace(b'VALUE = 1', b'VALUE = 2'))

    def test_excessive_line_alignment_is_rejected_instead_of_hanging(self):
        old = 'first\n' + 'repeated\n' * 2100 + 'last\n'
        new = 'changed\n' + 'repeated\n' * 2100 + 'different\n'
        with self.assertRaises(EditError):
            prepare_edit(old.encode('utf-8'), old, new)

    def test_line_metadata_does_not_count_the_next_line_after_a_trailing_newline(self):
        result = prepare_edit(b'first\r\nsecond\n', 'first\n', 'changed\n')
        self.assertEqual((result['start_line'], result['end_line']), (1, 1))

    def test_edit_boundaries_do_not_accidentally_merge_lone_cr_and_lf(self):
        source = b'before\rDELETE\nafter'
        result = prepare_edit(source, 'DELETE', '')
        self.assertEqual(result['content'], b'before\r\r\nafter')
        self.assertEqual(result['content'].decode().replace('\r\n', '\n').replace('\r', '\n'),
                         'before\n\nafter')
        result = prepare_edit(b'before\rTARGET after', 'TARGET', '\nnew')
        self.assertEqual(result['content'], b'before\r\rnew after')


if __name__ == '__main__':
    unittest.main()
