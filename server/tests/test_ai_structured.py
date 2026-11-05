import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.core.config import settings
from app.services.ai import _chat_json
from app.services.custom_plans import PlanLayout, local_layout


class StructuredProposalTests(unittest.TestCase):
    def test_proposal_uses_validated_schema_without_json_text_parsing(self):
        layout = local_layout('주간 추진 일정')
        client = Mock()
        client.beta.chat.completions.parse.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=layout))])
        with patch.object(settings, 'OPENAI_API_KEY', 'fictional'), patch('app.services.ai._client', return_value=client):
            result = _chat_json('system', 'fictional request', response_model=PlanLayout)
        self.assertEqual(result, layout.model_dump())
        self.assertIs(client.beta.chat.completions.parse.call_args.kwargs['response_format'], PlanLayout)
        client.chat.completions.create.assert_not_called()

    def test_refusal_returns_no_layout_for_safe_rule_fallback(self):
        client = Mock()
        client.beta.chat.completions.parse.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=None))])
        with patch.object(settings, 'OPENAI_API_KEY', 'fictional'), patch('app.services.ai._client', return_value=client):
            self.assertIsNone(_chat_json('system', 'fictional request', response_model=PlanLayout))
