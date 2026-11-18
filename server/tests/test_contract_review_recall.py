"""Synthetic omission fixtures; no provider calls and no assertion of legal safety."""
import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from app.services.contract_review import analyze
from app.services.contract_review_checks import supplement


def source(text, index=1):
    return {'source_id': index, 'file_id': index, 'name': f'별첨{index}.txt', 'page': index, 'text': text}


class ContractRecallTests(unittest.TestCase):
    def test_empty_ai_is_supplemented_across_all_pages_and_annexes(self):
        clauses = [
            '유지보수는 기간 제한 없이 무상으로 제공합니다.',
            '추가 기능은 별도 비용 없이 개발합니다.',
            '수행사는 간접손해를 포함한 손해배상을 한도 없이 부담합니다.',
            '검수 기한은 별도로 정하지 않습니다.',
            '계약은 별도 통지가 없으면 자동 갱신됩니다.',
            '발주처는 수행사 동의 없이 과업을 일방적으로 변경할 수 있습니다.',
        ]
        sources = [source(text, i) for i, text in enumerate(clauses, 1)]
        payload = json.dumps({'role': '수행사', 'sources': sources}, ensure_ascii=False)
        with patch('app.services.ai._chat_json', return_value={'findings': []}):
            result = analyze(payload)
        self.assertEqual(len(result['findings']), 6)
        self.assertEqual({f['evidence'][0]['source_id'] for f in result['findings']}, set(range(1, 7)))
        for f in result['findings']:
            self.assertEqual(f['method'], 'rule')
            self.assertIn(f['evidence'][0]['quote'], sources[f['evidence'][0]['source_id']-1]['text'])

    def test_qualified_and_negated_clauses_are_not_lexical_candidates(self):
        clauses = [
            '유지보수는 검수 후 12개월간 무상으로 제공합니다.',
            '추가 기능은 상호 서면 합의 후 별도 비용 없이 개발합니다.',
            '계약은 자동 갱신되지 않습니다.',
            '손해배상에 간접손해는 포함하지 아니한다.',
            '수행사 동의 없이 과업을 변경하는 것은 허용하지 않습니다.',
            '추가 기능을 별도 비용 없이 개발하지 않습니다.',
            '유지보수는 무상입니다. 별개의 납품 의무는 횟수 제한 없이 이행합니다.',
        ]
        for clause in clauses:
            with self.subTest(clause=clause):
                self.assertEqual(supplement([source(clause)], '수행사', [])[0], [])

    def test_role_and_existing_evidence_control_supplement(self):
        text = '수행사는 사전 승인 없이 제3자에게 재위탁할 수 있습니다.'
        self.assertEqual(supplement([source(text)], '수행사', [])[0], [])
        candidates, _ = supplement([source(text)], '발주처', [])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(supplement([source(text)], '발주처', candidates)[0], [])

    def test_more_than_eight_grounded_ai_findings_survive(self):
        sources = [source(f'제{i}조 검수 절차 및 지급 조건을 별도로 협의합니다.', i) for i in range(1, 13)]
        fake = {'findings': [{'category': '검수·대금 지급', 'title': f'조건 {i}', 'impact': '기준 확인 필요',
            'question': '구체적인 기한을 정할 수 있을까요?', 'evidence': [{'source_id': i, 'quote': s['text']}]}
            for i, s in enumerate(sources, 1)]}
        payload = json.dumps({'role': '수행사', 'sources': sources}, ensure_ascii=False)
        with patch('app.services.ai._chat_json', return_value=fake) as call:
            result = analyze(payload)
        self.assertEqual(len(result['findings']), 12)
        self.assertEqual(call.call_args.args[1], payload)
        self.assertEqual(call.call_args.kwargs['max_completion_tokens'], 7000)

    def test_unverified_ai_quote_never_appears_but_valid_rule_candidate_does(self):
        text = '계약은 별도 통지가 없으면 자동 갱신됩니다.'
        fake = {'findings': [{'category': '자동 연장·갱신', 'title': '갱신', 'impact': '확인 필요',
            'question': '조건 확인 가능할까요?', 'evidence': [{'source_id': 1, 'quote': '존재하지 않는 가짜 계약 문구입니다.'}]}]}
        with patch('app.services.ai._chat_json', return_value=fake):
            result = analyze(json.dumps({'role': '수행사', 'sources': [source(text)]}))
        self.assertEqual(result['excluded'], 1)
        self.assertEqual(result['findings'][0]['method'], 'rule')
        self.assertEqual(result['findings'][0]['evidence'][0]['quote'], text)

    def test_output_limits_are_visible_and_provider_failure_stays_failure(self):
        sources = [source('계약은 별도 통지가 없으면 자동 갱신됩니다.', i) for i in range(1, 31)]
        candidates, omitted = supplement(sources, '수행사', [])
        self.assertEqual((len(candidates), omitted), (24, 6))
        with patch('app.services.ai._chat_json', return_value=None):
            with self.assertRaises(HTTPException) as error:
                analyze(json.dumps({'role': '수행사', 'sources': sources}))
        self.assertEqual(error.exception.status_code, 502)
