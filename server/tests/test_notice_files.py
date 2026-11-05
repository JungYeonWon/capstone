import io
import struct
import unittest
import zlib
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

from docx import Document
from fastapi import HTTPException

from app.services.notice_files import extract_notice, hwp_records, HP, HS
from app.services.notice_analysis import analyze

SOURCE='제출서류\n1. 착수신고서 1부\n2. 사업자등록증\n제출기한: 계약 후 7일 이내'


def package(files):
    out=io.BytesIO()
    with ZipFile(out,'w',compression=ZIP_DEFLATED) as archive:
        for name,data in files:archive.writestr(name,data)
    return out.getvalue()


def word_notice():
    word=Document()
    for line in SOURCE.splitlines()[:3]:word.add_paragraph(line)
    table=word.add_table(rows=1,cols=2)
    table.cell(0,0).text='제출기한';table.cell(0,1).text='계약 후 7일 이내'
    out=io.BytesIO();word.save(out);return out.getvalue()


def hwpx_notice():
    paragraphs=''.join(f'<hp:p><hp:run><hp:t>{line}</hp:t></hp:run></hp:p>' for line in SOURCE.splitlines())
    return package([('Contents/section0.xml',f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{paragraphs}</hs:sec>')])


def hwp_notice(source=SOURCE, compressed=True, flags=0, version=5):
    """Minimal genuine CFB container, entirely synthetic, without author metadata."""
    record=source.encode('utf-16le')
    body=struct.pack('<I',67 | ((len(record) if len(record)<4095 else 4095)<<20))
    if len(record)>=4095:body+=struct.pack('<I',len(record))
    body+=record
    if compressed:
        compressor=zlib.compressobj(wbits=-15);body=compressor.compress(body)+compressor.flush()+b'padding'
    header=bytearray(256);header[:17]=b'HWP Document File';header[35]=version
    struct.pack_into('<I',header,36,flags | int(compressed))
    mini=bytes(header)+body
    mini+=b'\0'*(-len(mini)%64)
    count=len(mini)//64
    if count>128:raise ValueError('fixture mini stream too large')
    sector_count=(len(mini)+511)//512
    fat_sector=2+sector_count
    free,end,fat=0xffffffff,0xfffffffe,0xfffffffd
    file_header=bytearray(512);file_header[:8]=b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
    struct.pack_into('<HHHHH',file_header,24,0x3e,3,0xfffe,9,6)
    struct.pack_into('<IIIIIIIII',file_header,40,0,1,0,0,4096,1,1,end,0)
    struct.pack_into('<109I',file_header,76,fat_sector,*([free]*108))
    def entry(name,kind,start,size,child=free,right=free):
        row=bytearray(128);encoded=(name+'\0').encode('utf-16le');row[:len(encoded)]=encoded
        struct.pack_into('<HBBIII',row,64,len(encoded),kind,1,free,right,child)
        struct.pack_into('<IQ',row,116,start,size)
        return bytes(row)
    directory=b''.join([entry('Root Entry',5,2,len(mini),child=1),
        entry('FileHeader',2,0,256,right=2),entry('BodyText',1,end,0,child=3),entry('Section0',2,4,len(body))])
    mini_fat=[free]*128
    for start,stop in ((0,4),(4,count)):
        for i in range(start,stop):mini_fat[i]=i+1 if i+1<stop else end
    allocation=[free]*128;allocation[0]=end;allocation[1]=end
    for i in range(2,fat_sector):allocation[i]=i+1 if i+1<fat_sector else end
    allocation[fat_sector]=fat
    return bytes(file_header)+directory+struct.pack('<128I',*mini_fat)+mini.ljust(sector_count*512,b'\0')+struct.pack('<128I',*allocation)


class NoticeFileTests(unittest.TestCase):
    def test_all_office_formats_feed_the_same_notice_analysis_without_office_or_ai(self):
        for name,data in [('notice.docx',word_notice()),('notice.hwpx',hwpx_notice()),
                          ('notice.hwp',hwp_notice()),('notice.HWP',hwp_notice(compressed=False))]:
            with self.subTest(name=name),patch('app.services.ai._chat_json') as ai:
                result=extract_notice(data,name);parsed=analyze(result['text'],False);ai.assert_not_called()
                self.assertEqual(len(parsed['items']),2)
                self.assertTrue(any(f['kind']=='deadline' and '7일' in f['value'] for f in parsed['facts']))
                self.assertIsNone(result['pages']);self.assertTrue(result['warning'])

    def test_hwp_extended_lengths_and_inline_controls_preserve_visible_text(self):
        result=extract_notice(hwp_notice('긴 본문 '+('가'*2200)),'notice.hwp')
        self.assertIn('가'*2200,result['text'])
        control=struct.pack('<H',11)+b'x'*12+struct.pack('<H',11)
        raw='제출'.encode('utf-16le')+control+'서류\r착수계'.encode('utf-16le')
        record=struct.pack('<I',67|(len(raw)<<20))+raw
        self.assertEqual(list(hwp_records(record)),['제출 서류\n착수계'])

    def test_restricted_and_legacy_hwp_are_rejected(self):
        for flag in (2,4,16,256,1024):
            with self.subTest(flag=flag),self.assertRaises(HTTPException) as error:
                extract_notice(hwp_notice(flags=flag),'notice.hwp')
            self.assertEqual(error.exception.status_code,422)
        with self.assertRaises(HTTPException) as error:extract_notice(hwp_notice(version=3),'notice.hwp')
        self.assertIn('5.x',error.exception.detail)

    def test_hwpx_inline_breaks_and_tabs_do_not_drop_following_text(self):
        xml=f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}"><hp:p><hp:run><hp:t>제출서류<hp:lineBreak/>착수계<hp:tab/>과업수행계획서</hp:t></hp:run></hp:p></hs:sec>'
        result=extract_notice(package([('Contents/section0.xml',xml)]),'notice.hwpx')
        self.assertEqual(result['text'],'제출서류\n착수계\t과업수행계획서')

    def test_corrupt_mislabeled_and_old_word_files_fail_clearly(self):
        for name,data in [('notice.docx',b'broken'),('notice.hwp',b'broken'),
                          ('notice.hwpx',word_notice()),('notice.docx',hwpx_notice()),('notice.doc',b'old word')]:
            with self.subTest(name=name),self.assertRaises(HTTPException) as error:extract_notice(data,name)
            self.assertEqual(error.exception.status_code,422)
        with self.assertRaises(HTTPException):list(hwp_records(struct.pack('<I',67|(100<<20))+b'bad'))

    def test_xml_entities_duplicates_and_expansion_limits_are_rejected(self):
        xml=f'<!DOCTYPE sec [<!ENTITY x "ATTACK">]><hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}"><hp:p><hp:run><hp:t>&x;</hp:t></hp:run></hp:p></hs:sec>'
        with self.assertRaises(HTTPException):extract_notice(package([('Contents/section0.xml',xml)]),'notice.hwpx')
        with self.assertRaises(HTTPException):extract_notice(package([('Contents/section0.xml','x'),('Contents/section0.xml','y')]),'notice.hwpx')
        with patch('app.services.notice_files.MAX_EXPANDED',100),self.assertRaises(HTTPException) as error:
            extract_notice(hwp_notice('압축 본문 '+('가'*500)),'notice.hwp')
        self.assertEqual(error.exception.status_code,413)
        with patch('app.services.notice_files.MAX_EXPANDED',100),self.assertRaises(HTTPException) as error:
            extract_notice(hwpx_notice(),'notice.hwpx')
        self.assertEqual(error.exception.status_code,413)

    def test_extracted_text_and_upload_limits_apply_to_office_files(self):
        long_xml=f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}"><hp:p><hp:run><hp:t>'+('가'*20001)+'</hp:t></hp:run></hp:p></hs:sec>'
        with self.assertRaises(HTTPException) as error:extract_notice(package([('Contents/section0.xml',long_xml)]),'notice.hwpx')
        self.assertEqual(error.exception.status_code,413)
        with self.assertRaises(HTTPException) as error:extract_notice(b'x'*(3*1024*1024+1),'notice.docx')
        self.assertEqual(error.exception.status_code,413)
