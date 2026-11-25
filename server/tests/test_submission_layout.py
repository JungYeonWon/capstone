"""Regression coverage for submission geometry and preserved page boundaries."""
import unittest
import base64
from io import BytesIO
from zipfile import ZipFile
from lxml import etree
import pymupdf

from app.professional_templates import BUILTIN_TEMPLATES
from app.routers.templates import SAMPLE_VALUES
from app.services.professional_renderer import render_docx, render_hwpx, item_amounts, HWP_CONTENT_WIDTH
from app.services.renderer import docx_to_pdf_bytes, pdf_preview_pages
from app.services.professional_renderer import render_quotation_xlsx
from openpyxl import load_workbook


class SubmissionLayoutTests(unittest.TestCase):
    def test_long_table_repeats_headers_keeps_all_rows_and_signature_together(self):
        definition = {'title': '장기 프로젝트 수행 결과와 납품 내역 검토서', 'signature': True,
            'recipient': '{client_name} 귀하', 'sections': [
                {'type': 'info', 'rows': [['계약명', 'contract_title'], ['주소', 'address']]},
                {'type': 'data_table', 'label': '납품 세부 내역', 'key': 'custom_1', 'columns': ['납품 항목', '금액']}]}
        values = {**SAMPLE_VALUES, 'contract_title': '지역 통합 정보 시스템 구축 및 운영 지원 사업 ' * 5,
                  'address': '서울특별시 가상구 가상로 123 테스트빌딩 ' * 4,
                  'custom_1': '\n'.join(f'항목{i:03d} ' + '긴 납품 내용 ' * 7 + f' | {1000000 + i:,}' for i in range(50))}
        with pymupdf.open(stream=docx_to_pdf_bytes(render_docx(definition, values)), filetype='pdf') as pdf:
            self.assertGreater(len(pdf), 2)
            text = ''.join(page.get_text() for page in pdf)
            for index in range(50):
                self.assertIn(f'항목{index:03d}', text)
            for page in pdf:
                if '항목0' in page.get_text():
                    self.assertIn('납품 항목', page.get_text())
                for word in page.get_text('words'):
                    self.assertGreaterEqual(word[0], 60)
                    self.assertLessEqual(word[2], page.rect.width - 60)
            signature = next(page.get_text() for page in pdf if '대표자' in page.get_text())
            self.assertIn(values['submit_date'], signature)
            self.assertIn(values['company_name'], signature)
        with ZipFile(BytesIO(render_hwpx(definition, values))) as archive:
            root = etree.fromstring(archive.read('Contents/section0.xml'))
            ns = {'hp': 'http://www.hancom.co.kr/hwpml/2011/paragraph'}
            heights = [int(node.get('height')) for node in root.xpath('//hp:cellSz', namespaces=ns)]
            self.assertGreater(max(heights), 2200)
            for table in root.xpath('//hp:tbl', namespaces=ns):
                row_heights = [max(int(node.get('height')) for node in row.xpath('./hp:tc/hp:cellSz', namespaces=ns))
                               for row in table.xpath('./hp:tr', namespaces=ns)]
                self.assertEqual(int(table.find('hp:sz', ns).get('height')), sum(row_heights))

    def test_quotation_long_rows_wrap_and_print_over_multiple_readable_pages(self):
        values = {**SAMPLE_VALUES, 'quote_items': ('설계 및 개발 상세 설명 ' * 15) + ' | 1 | 1000000 | 확인 사항'}
        workbook = load_workbook(BytesIO(render_quotation_xlsx(values)))
        sheet = workbook.active
        self.assertGreater(sheet.row_dimensions[14].height, 24)
        self.assertEqual(sheet.page_setup.fitToWidth, 1)
        self.assertEqual(sheet.page_setup.fitToHeight, 0)
        self.assertEqual(sheet.print_title_rows, '$13:$13')
    def test_editor_preview_preserves_pdf_pages_and_aspect_ratio(self):
        definition = next(t['definition'] for t in BUILTIN_TEMPLATES if t['key'] == 'completion')
        pdf = docx_to_pdf_bytes(render_docx(definition, SAMPLE_VALUES))
        pages = pdf_preview_pages(pdf)
        self.assertEqual(len(pages), 2)
        for page in pages:
            png = pymupdf.Pixmap(base64.b64decode(page['data'].split(',', 1)[1]))
            self.assertEqual((png.width, png.height), (page['width'], page['height']))
            self.assertAlmostEqual(page['width'] / page['height'], 210 / 297, places=3)

    def test_whole_won_rounding_matches_excel(self):
        self.assertEqual(item_amounts({"qty": 1, "unit": 105}), (105, 11))
        self.assertEqual(item_amounts({"qty": 0.5, "unit": 101}), (51, 5))

    def test_hwpx_tables_fit_and_stamp_has_physical_space(self):
        for template in BUILTIN_TEMPLATES:
            with self.subTest(template=template["key"]):
                with ZipFile(BytesIO(render_hwpx(template["definition"], SAMPLE_VALUES))) as z:
                    root = etree.fromstring(z.read("Contents/section0.xml"))
                    ns = {"hp": "http://www.hancom.co.kr/hwpml/2011/paragraph"}
                    for size in root.xpath('//hp:tbl/hp:sz', namespaces=ns):
                        self.assertLessEqual(int(size.get('width')), HWP_CONTENT_WIDTH)
                    if template['key'] == 'seal_registration':
                        self.assertTrue(root.xpath('//hp:cellSz[@height="9100"]', namespaces=ns))

    def test_edited_attachments_and_long_content_survive(self):
        definition = next(t["definition"] for t in BUILTIN_TEMPLATES if t["key"] == "commencement")
        values = dict(SAMPLE_VALUES, attachment_list="실제 첨부자료 1부", work_summary="세부 과업 내용입니다.\n" * 90)
        with pymupdf.open(stream=docx_to_pdf_bytes(render_docx(definition, values)), filetype="pdf") as pdf:
            text = ''.join(p.get_text() for p in pdf)
            self.assertIn('실제 첨부자료', text)
            self.assertNotIn('사용인감계 1부', text)
            self.assertGreater(len(pdf), 1)
        with ZipFile(BytesIO(render_hwpx(definition, values))) as z:
            text = z.read('Preview/PrvText.txt').decode()
            self.assertIn('실제 첨부자료', text)
            self.assertNotIn('사용인감계 1부', text)

    def test_completion_has_separate_detail_page(self):
        definition = next(t["definition"] for t in BUILTIN_TEMPLATES if t["key"] == "completion")
        with pymupdf.open(stream=docx_to_pdf_bytes(render_docx(definition, SAMPLE_VALUES)), filetype="pdf") as pdf:
            self.assertEqual(len(pdf), 2)
            self.assertIn("완 료 내 역 서", pdf[1].get_text())
        with ZipFile(BytesIO(render_hwpx(definition, SAMPLE_VALUES))) as z:
            root = etree.fromstring(z.read("Contents/section0.xml"))
            self.assertTrue(root.xpath('//*[@pageBreak="1"]'))

    def test_all_forms_are_a4_with_content(self):
        for template in BUILTIN_TEMPLATES:
            with self.subTest(template=template["key"]):
                with pymupdf.open(stream=docx_to_pdf_bytes(render_docx(template["definition"], SAMPLE_VALUES)), filetype="pdf") as pdf:
                    for page in pdf:
                        self.assertAlmostEqual(page.rect.width, 595.28, places=1)
                        self.assertAlmostEqual(page.rect.height, 841.89, places=1)
                        self.assertGreater(len(page.get_text()), 30)


if __name__ == "__main__":
    unittest.main()
