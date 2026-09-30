import json
import unittest
from unittest.mock import AsyncMock, patch

from app.chat import (EXCLUDED_SOURCES, ChatRequest, ParsedDraft, answer_question, clean_source,
                      has_content, validate_draft)

URL = "https://www.skatturinn.is/english/individuals/filing-a-tax-return"
PAGE = """# Filing a tax return

### [Log in to complete your tax return](https://innskraning.rsk.is/)

Information regarding your salary, real estate, vehicles, bank accounts, debt and more are pre-filled in.

![Cover photo](https://www.skatturinn.is/media/cover.jpg)

[Further information on electronic IDs](https://www.audkenni.is/en/)
"""
MENU = "\n".join(f"- [Menu item {i}](https://www.skatturinn.is/english/item-{i}/)" for i in range(12))
TABLE_BORDERS = "| --- | --- | --- | --- |\n" * 20


def source(text=PAGE, url=URL):
    return {"url": url, "title": "Filing a tax return", "text": text, "crawled_at": "2026-09-28"}


def parsed(*claims, answerable=True):
    return ParsedDraft.model_validate({"answerable": answerable, "claims": [
        {"text": text, "evidence": [{"source_id": sid, "quote": quote} for sid, quote in evidence]}
        for text, evidence in claims]})


GOOD = ("The tax return is pre-filled.", [(1, "Information regarding your salary, real estate, vehicles")])
BAD = ("Deadline is 1 May.", [(1, "The deadline for the tax return is 1 May every year.")])


class PartialValidationTests(unittest.TestCase):
    def test_one_bad_claim_does_not_discard_verified_claims(self):
        result = validate_draft(parsed(GOOD, BAD), [source()], "en")
        self.assertEqual(result.status, "answered")
        self.assertIn("pre-filled", result.answer)
        self.assertNotIn("1 May", result.answer)
        self.assertEqual(len(result.citations), 1)

    def test_all_claims_invalid_abstains(self):
        self.assertEqual(validate_draft(parsed(BAD), [source()], "en").status, "insufficient_evidence")

    def test_claim_with_any_unsupported_quote_is_dropped(self):
        mixed = ("Mixed support.", [GOOD[1][0], BAD[1][0]])
        self.assertEqual(validate_draft(parsed(mixed), [source()], "en").status, "insufficient_evidence")

    def test_quote_may_omit_link_markup(self):
        claim = ("Log in to file.", [(1, "### Log in to complete your tax return\n\nInformation regarding your salary")])
        result = validate_draft(parsed(claim), [source()], "en")
        self.assertEqual(result.status, "answered")
        self.assertNotIn("https://", result.citations[0].quote)

    def test_quote_copied_with_link_markup_still_matches(self):
        claim = ("Log in.", [(1, "[Log in to complete your tax return](https://innskraning.rsk.is/)")])
        self.assertEqual(validate_draft(parsed(claim), [source()], "en").status, "answered")

    def test_overlong_or_tiny_quotes_are_dropped(self):
        long_text = "word " * 400
        for quote in [long_text.strip(), "tiny"]:
            claim = ("Claim.", [(1, quote)])
            self.assertEqual(validate_draft(parsed(claim), [source(long_text)], "en").status,
                             "insufficient_evidence")

    def test_claim_with_link_or_marker_is_dropped_but_others_kept(self):
        result = validate_draft(parsed(("See https://evil.example", GOOD[1]), GOOD), [source()], "en")
        self.assertEqual(result.status, "answered")
        self.assertNotIn("evil", result.answer)


class SourceCleaningTests(unittest.TestCase):
    def test_links_and_images_become_plain_text(self):
        cleaned = clean_source(PAGE)
        self.assertIn("### Log in to complete your tax return", cleaned)
        self.assertNotIn("https://", cleaned)
        self.assertNotIn("Cover photo", cleaned)

    def test_menu_and_table_border_chunks_have_no_content(self):
        self.assertFalse(has_content(clean_source(MENU)))
        self.assertFalse(has_content(clean_source(TABLE_BORDERS)))
        self.assertTrue(has_content(clean_source(PAGE)))

    def test_data_tables_are_kept(self):
        car_table = "| **Tegund** | **Árgerð** | **Verð** |\n| --- | --- | --- |\n" + \
            "| Toyota Land Cruiser | 2010 | 5.890.000 |\n" * 5
        self.assertTrue(has_content(clean_source(car_table)))


class RetrievalFilterTests(unittest.IsolatedAsyncioTestCase):
    async def test_noise_is_skipped_and_generator_gets_clean_text(self):
        points = [{"payload": source(MENU)}, {"payload": source(TABLE_BORDERS)}, {"payload": source()}]
        response = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"text": json.dumps({"answerable": True, "claims": [
                {"text": GOOD[0], "evidence": [{"source_id": 1, "quote": GOOD[1][0][1]}]}]})}]}}]}
        with patch("app.chat.embed", AsyncMock(return_value=[0.1])), patch(
                "app.chat.key", return_value="test"), patch("app.chat.request", AsyncMock(side_effect=[
                    {"result": {"points": points}}, response])) as req:
            result = await answer_question(ChatRequest(question="How do I file?"))
        self.assertEqual(result.status, "answered")
        sent = json.loads(req.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"])["sources"]
        self.assertEqual(len(sent), 1)
        self.assertNotIn("https://", sent[0]["text"])

    async def test_generator_output_exceeding_schema_limits_is_still_checked(self):
        long_quote = "x" * 700
        response = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"text": json.dumps({"answerable": True, "claims": [
                {"text": GOOD[0], "evidence": [{"source_id": 1, "quote": GOOD[1][0][1]}]},
                {"text": "Too long.", "evidence": [{"source_id": 1, "quote": long_quote}]}]})}]}}]}
        with patch("app.chat.embed", AsyncMock(return_value=[0.1])), patch(
                "app.chat.key", return_value="test"), patch("app.chat.request", AsyncMock(side_effect=[
                    {"result": {"points": [{"payload": source()}]}}, response])):
            result = await answer_question(ChatRequest(question="How do I file?"))
        self.assertEqual(result.status, "answered")
        self.assertEqual(len(result.citations), 1)


class ExcludedSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_car_valuation_lists_are_filtered_and_skipped(self):
        self.assertEqual(len(EXCLUDED_SOURCES), 19)
        car = source(url="https://www.skatturinn.is/media/baeklingar/rsk_0603_2010.is.pdf")
        with patch("app.chat.embed", AsyncMock(return_value=[0.1])), patch(
                "app.chat.request", AsyncMock(return_value={"result": {"points": [{"payload": car}]}})) as req:
            result = await answer_question(ChatRequest(question="Land Cruiser 2010 valuation?"))
        self.assertEqual(result.status, "insufficient_evidence")
        self.assertEqual(req.await_count, 1)
        excluded = req.call_args.kwargs["json"]["filter"]["must_not"][0]["match"]["any"]
        self.assertIn(car["url"], excluded)


if __name__ == "__main__":
    unittest.main()
