import unittest
from app.core import chunks, validate_source


class CoreTests(unittest.TestCase):
    def test_chunk_coverage_and_overlap(self):
        text = "abcdefghijklmno"
        parts = chunks(text, 6, 2)
        self.assertEqual(parts, ["abcdef", "efghij", "ijklmn", "mno"])
        self.assertEqual(parts[0] + "".join(p[2:] for p in parts[1:]), text)

    def test_empty_and_exact_boundary(self):
        self.assertEqual(chunks("  "), [])
        self.assertEqual(chunks("abcdef", 6, 2), ["abcdef"])

    def test_invalid_overlap(self):
        with self.assertRaises(ValueError):
            chunks("text", 5, 5)

    def test_source_restrictions(self):
        validate_source("https://www.skatturinn.is/english/")
        for url in ["http://www.skatturinn.is/", "https://localhost/", "https://www.skatturinn.is.evil.test/"]:
            with self.assertRaises(ValueError):
                validate_source(url)
