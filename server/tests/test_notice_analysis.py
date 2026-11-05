import unittest
from unittest.mock import patch

from app.services.notice_analysis import analyze, NoticeResponse, NoticeState


class NoticeAnalysisTests(unittest.TestCase):
    def test_multi_document_conditions_do_not_spread_to_other_documents(self):
        result=analyze('제출서류\n1. 사업자등록증, 통장사본 (해당 시)\n2. 인감증명서 (법인인 경우)\n3. 견적서 제출 생략 가능',False)
        items={item['title']:item for item in result['items']}
        self.assertTrue(items['사업자등록증']['required'])
        self.assertFalse(items['통장사본']['required'])
        self.assertFalse(items['인감증명서']['required'])
        self.assertNotIn('견적서',items)
        self.assertIn('법인',items['인감증명서']['condition'])

    def test_submission_facts_and_relative_deadlines_keep_literal_source(self):
        text='제출기한: 계약 체결 후 7일 이내\n제출방법: 이메일 또는 방문 접수\n제출처: 가상시청 계약팀\n문의처:\n계약담당 02-0000-0000\n유의사항: 사본에 원본대조필 표시\n제출서류\n1. 착수신고서 1부\n2. 현장방문계획서 2부'
        result=analyze(text,False)
        self.assertEqual([item['title'] for item in result['items']],['착수계','현장방문계획서'])
        facts={fact['kind']:fact for fact in result['facts']}
        self.assertEqual(facts['deadline']['value'],'계약 체결 후 7일 이내')
        self.assertEqual(facts['contact']['value'],'계약담당 02-0000-0000')
        self.assertEqual(len(facts),5)
        for fact in facts.values():self.assertIn(fact['evidence'],text)

    def test_conditional_heading_applies_until_next_submission_heading(self):
        result=analyze('해당 업체만 제출:\n- 사용인감계\n- 통장사본\n제출서류\n- 사업자등록증',False)
        items={i['title']:i for i in result['items']}
        self.assertFalse(items['사용인감계']['required'])
        self.assertFalse(items['통장사본']['required'])
        self.assertTrue(items['사업자등록증']['required'])

    def test_ai_cannot_add_fabricated_dates_or_change_local_conditions(self):
        text='제출서류\n사업자등록증, 통장사본 (해당 시)\n제출방법: 이메일 접수'
        fake={'items':[{'title':'통장사본','evidence':'사업자등록증, 통장사본 (해당 시)'},
                       {'title':'사업자등록증, 통장사본 (해당 시)','evidence':'사업자등록증, 통장사본 (해당 시)'},
                       {'title':'없는 서류','evidence':'사업자등록증'}],
              'facts':[{'kind':'deadline','value':'2026-12-31','evidence':'제출방법: 이메일 접수'},
                       {'kind':'method','value':'이메일 접수','evidence':'제출방법: 이메일 접수'}]}
        with patch('app.services.ai._chat_json',return_value=fake) as ai:
            result=analyze(text,True)
            self.assertIs(ai.call_args.kwargs['response_model'],NoticeResponse)
        self.assertEqual(result['mode'],'ai')
        self.assertFalse(next(i for i in result['items'] if i['title']=='통장사본')['required'])
        self.assertEqual(len(result['items']),2)
        self.assertNotIn('2026-12-31',str(result));self.assertNotIn('없는 서류',str(result))

    def test_rejected_ai_output_is_reported_as_fallback(self):
        with patch('app.services.ai._chat_json',return_value={'items':[{'title':'허구','evidence':'없는 근거'}],'facts':[]}):
            result=analyze('제출서류: 착수계',True)
        self.assertEqual(result['mode'],'rule_fallback');self.assertTrue(result['warning'])
        self.assertEqual(result['items'][0]['title'],'착수계')

    def test_empty_and_truncated_results_are_explicit(self):
        self.assertTrue(analyze('오늘 회의는 취소되었습니다.',False)['warning'])
        result=analyze('제출서류\n'+'\n'.join(f'{i}. 특수{i}확인서' for i in range(35)),False)
        self.assertEqual(len(result['items']),30);self.assertIn('30개',result['warning'])

    def test_old_saved_checklists_remain_readable(self):
        state=NoticeState.model_validate({'text':'기존 안내문','items':[]})
        self.assertEqual(state.facts,[]);self.assertEqual(state.analyzed_text,'')

    def test_long_conditional_heading_does_not_crash_analysis(self):
        result=analyze('해당 업체만 '+('설명 '*200)+'제출:\n- 사용인감계',False)
        state=NoticeState.model_validate({'text':'가상 원문','items':result['items']})
        self.assertFalse(state.items[0].required)
        self.assertLessEqual(len(state.items[0].condition),500)
