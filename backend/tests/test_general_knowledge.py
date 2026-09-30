import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from app.chat import (ChatRequest, Draft, ParsedDraft, answer_question, sanitize_general,
                      system_prompt, validate_draft)

SOURCE = {"url": "https://www.skatturinn.is/english/companies/value-added-tax/", "title": "VAT",
          "text": "The standard rate of VAT in Iceland is 24%.", "crawled_at": "2026-09-28"}
CLAIM = {"text": "The standard VAT rate is 24%.",
         "evidence": [{"source_id": 1, "quote": "The standard rate of VAT in Iceland is 24%."}]}


def generation(payload):
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(payload)}]}}]}


def parsed(claims=(), general="", answerable=True):
    return ParsedDraft.model_validate({"answerable": answerable, "claims": list(claims), "general_answer": general})


class GeneralKnowledgeValidationTests(unittest.TestCase):
    def test_general_only_answer_is_labelled_and_uncited(self):
        result = validate_draft(parsed(answerable=False, general="Car insurance is compulsory."), [SOURCE], "en", True)
        self.assertEqual(result.status, "general_knowledge")
        self.assertEqual(result.answer, "")
        self.assertEqual(result.citations, [])
        self.assertEqual(result.general_answer, "Car insurance is compulsory.")

    def test_verified_claims_and_general_supplement_stay_separate(self):
        result = validate_draft(parsed([CLAIM], "The reduced rate may differ; confirm with Skatturinn."),
                                [SOURCE], "en", True)
        self.assertEqual(result.status, "answered")
        self.assertIn("[1]", result.answer)
        self.assertNotIn("reduced", result.answer)
        self.assertIn("reduced", result.general_answer)
        self.assertEqual(len(result.citations), 1)

    def test_unverifiable_claims_fall_back_to_general_without_citations(self):
        bad = {"text": "VAT is 99%.", "evidence": [{"source_id": 1, "quote": "The standard rate of VAT is 99% now."}]}
        result = validate_draft(parsed([bad], "I cannot confirm that rate."), [SOURCE], "en", True)
        self.assertEqual(result.status, "general_knowledge")
        self.assertEqual(result.citations, [])
        self.assertNotIn("99", result.answer)

    def test_general_answer_is_ignored_when_fallback_disabled(self):
        result = validate_draft(parsed(answerable=False, general="Anything."), [SOURCE], "en", False)
        self.assertEqual(result.status, "insufficient_evidence")
        self.assertEqual(result.general_answer, "")

    def test_nothing_at_all_still_abstains(self):
        self.assertEqual(validate_draft(parsed(answerable=False), [SOURCE], "is", True).status,
                         "insufficient_evidence")

    def test_general_answer_cannot_carry_citations_or_external_links(self):
        text = sanitize_general("See [1] and https://evil.example/login or https://www.skatturinn.is/english/ .")
        self.assertNotIn("[1]", text)
        self.assertNotIn("evil.example", text)
        self.assertIn("https://www.skatturinn.is/english/", text)
        self.assertLessEqual(len(sanitize_general("x" * 5000)), 2500)

    def test_prompt_and_schema_describe_general_answer(self):
        self.assertIn("general_answer", Draft.model_json_schema()["properties"])
        self.assertIn("general knowledge", system_prompt(True))
        self.assertIn("Always leave general_answer empty", system_prompt(False))
        self.assertIn("untrusted", system_prompt(True))
        self.assertIn("rather than\nwriting only a disclaimer", system_prompt(True))
        self.assertIn("requested language", system_prompt(False))


class GeneralKnowledgePipelineTests(unittest.IsolatedAsyncioTestCase):
    @patch.dict(os.environ, {"GENERAL_KNOWLEDGE_FALLBACK": "true"})
    async def test_no_retrieved_sources_still_gets_a_general_answer(self):
        with patch("app.chat.embed", AsyncMock(return_value=[0.1])), patch(
                "app.chat.key", return_value="test"), patch("app.chat.request", AsyncMock(side_effect=[
                    {"result": {"points": []}},
                    generation({"answerable": False, "claims": [], "general_answer": "Life is a big question."})])) as req:
            result = await answer_question(ChatRequest(question="What is life?"))
        self.assertEqual(result.status, "general_knowledge")
        sent = req.call_args.kwargs["json"]
        self.assertEqual(json.loads(sent["contents"][0]["parts"][0]["text"])["sources"], [])
        self.assertIn("general knowledge", sent["systemInstruction"]["parts"][0]["text"])

    @patch.dict(os.environ, {"GENERAL_KNOWLEDGE_FALLBACK": "true"})
    async def test_unapproved_sources_are_still_never_sent(self):
        evil = {**SOURCE, "url": "https://evil.example/"}
        with patch("app.chat.embed", AsyncMock(return_value=[0.1])), patch(
                "app.chat.key", return_value="test"), patch("app.chat.request", AsyncMock(side_effect=[
                    {"result": {"points": [{"payload": evil}]}},
                    generation({"answerable": False, "claims": [], "general_answer": "General."})])) as req:
            await answer_question(ChatRequest(question="VAT?"))
        sent = json.loads(req.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"])
        self.assertEqual(sent["sources"], [])


if __name__ == "__main__":
    unittest.main()
