"""Bounded, in-memory notice text extraction. No Office execution or external requests."""
import re
import struct
import zlib
from io import BytesIO
from pathlib import PurePath
from zipfile import ZipFile

from fastapi import HTTPException
from lxml import etree

MAX_FILE = 3 * 1024 * 1024
MAX_EXPANDED = 20 * 1024 * 1024
MAX_TEXT = 20000
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
HP = 'http://www.hancom.co.kr/hwpml/2011/paragraph'
HS = 'http://www.hancom.co.kr/hwpml/2011/section'
OFFICE_WARNING = '본문과 표의 텍스트를 가져왔습니다. 이미지·도형·각주·머리말의 내용과 읽기 순서는 원문에서 확인하세요.'


def fail(message, status=422):
    raise HTTPException(status, message)


def checked_text(text):
    text=text.strip()
    if len(text)>MAX_TEXT:fail('안내문 텍스트는 20,000자 이하여야 합니다.',413)
    if len(text)<5:fail('텍스트를 읽을 수 없습니다. 이미지 문서는 내용을 직접 붙여넣으세요.')
    if '\x00' in text:fail('문서의 텍스트 형식을 확인하세요.')
    return text


def xml_root(data, expected):
    root=etree.fromstring(data,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False))
    if root.getroottree().docinfo.doctype or root.tag!=expected:
        fail('올바른 문서 본문이 아니거나 외부 엔터티가 포함되어 있습니다.')
    return root


def paragraphs(root, namespace):
    def inline_text(node):
        parts=[node.text or '']
        for child in node:
            if child.tag==f'{{{namespace}}}tab':parts.append('\t')
            elif child.tag in (f'{{{namespace}}}lineBreak',f'{{{namespace}}}br'):parts.append('\n')
            elif child.tag in (f'{{{namespace}}}nbSpace',f'{{{namespace}}}fwSpace'):parts.append(' ')
            parts.append(child.tail or '')
        return ''.join(parts)
    chunks=[];size=0
    for paragraph in root.iter(f'{{{namespace}}}p'):
        parts=[]
        for node in paragraph.iter():
            # Textboxes may nest paragraphs; read each text node exactly once.
            if node is paragraph or next(node.iterancestors(f'{{{namespace}}}p'),None) is not paragraph:continue
            if any(a.tag in (f'{{{W}}}del',f'{{{W}}}moveFrom') for a in node.iterancestors()):continue
            if any(a.tag==f'{{{namespace}}}t' for a in node.iterancestors()):continue
            if node.tag==f'{{{namespace}}}t':parts.append(inline_text(node))
            elif node.tag in (f'{{{namespace}}}tab',):parts.append('\t')
            elif node.tag in (f'{{{namespace}}}br',f'{{{namespace}}}cr',f'{{{namespace}}}lineBreak'):parts.append('\n')
        text=''.join(parts).strip()
        if text:
            size+=len(text)+1
            if size>MAX_TEXT+1:fail('안내문 텍스트는 20,000자 이하여야 합니다.',413)
            chunks.append(text)
    return '\n'.join(chunks)


def zip_text(data, extension):
    with ZipFile(BytesIO(data)) as archive:
        entries=archive.infolist();names=[entry.filename for entry in entries]
        if len(entries)>3000 or sum(entry.file_size for entry in entries)>MAX_EXPANDED:
            fail('문서의 압축 해제 크기가 너무 큽니다.',413)
        if len(set(names))!=len(names) or any(entry.flag_bits & 1 for entry in entries):
            fail('암호화되었거나 중복 경로가 있는 문서입니다.')
        if any(entry.file_size>2*1024*1024 for entry in entries if entry.filename=='word/document.xml' or re.fullmatch(r'Contents/section\d+\.xml',entry.filename)):
            fail('문서 본문 XML이 너무 큽니다.',413)
        if extension=='.docx':
            if 'word/document.xml' not in names or '[Content_Types].xml' not in names:
                fail('DOCX 파일 형식이 아닙니다. Word에서 DOCX로 저장한 파일을 사용하세요.')
            root=xml_root(archive.read('word/document.xml'),f'{{{W}}}document')
            return paragraphs(root,W)
        sections=sorted((name for name in names if re.fullmatch(r'Contents/section\d+\.xml',name)),
                        key=lambda name:int(re.search(r'section(\d+)',name)[1]))
        if not sections:fail('HWPX 본문을 찾지 못했습니다. 암호를 해제한 HWPX 파일을 사용하세요.')
        chunks=[];size=0
        for name in sections:
            text=paragraphs(xml_root(archive.read(name),f'{{{HS}}}sec'),HP)
            size+=len(text)+1
            if size>MAX_TEXT+1:fail('안내문 텍스트는 20,000자 이하여야 합니다.',413)
            chunks.append(text)
        return '\n'.join(chunks)


def hwp_characters(data):
    if len(data)%2:fail('HWP 본문 텍스트가 손상되었습니다.')
    parts=[];position=0
    # HWP inline and extended controls occupy eight UTF-16 code units.
    wide_controls=set(range(1,10))|{11,12}|set(range(14,24))
    while position<len(data):
        code=struct.unpack_from('<H',data,position)[0]
        if code in wide_controls:
            if position+16>len(data):fail('HWP 제어문자가 손상되었습니다.')
            parts.append('\t' if code==9 else ' ');position+=16
        elif code<32:
            parts.append('\n' if code in (10,13) else '-' if code==24 else ' ');position+=2
        else:
            start=position;position+=2
            while position<len(data) and struct.unpack_from('<H',data,position)[0]>=32:position+=2
            parts.append(data[start:position].decode('utf-16le'))
    return ''.join(parts)


def hwp_records(data):
    position=0
    while position<len(data):
        if len(data)-position<4:fail('HWP 본문 레코드가 손상되었습니다.')
        header=struct.unpack_from('<I',data,position)[0];position+=4
        tag=header & 0x3ff;size=header>>20
        if size==0xfff:
            if len(data)-position<4:fail('HWP 본문 길이 정보가 손상되었습니다.')
            size=struct.unpack_from('<I',data,position)[0];position+=4
        if size>len(data)-position:fail('HWP 본문 길이가 올바르지 않습니다.')
        if tag==67:yield hwp_characters(data[position:position+size])
        position+=size


def hwp_text(data):
    import olefile
    with olefile.OleFileIO(BytesIO(data),raise_defects=olefile.DEFECT_INCORRECT) as ole:
        if not ole.exists('FileHeader') or ole.get_size('FileHeader')>1024:
            fail('HWP 파일 형식이 아닙니다.')
        header=ole.openstream('FileHeader').read()
        if len(header)<40 or header[:32].rstrip(b'\0')!=b'HWP Document File':fail('HWP 파일 형식이 아닙니다.')
        if header[35]!=5:fail('HWP 5.x 문서만 지원합니다. 한글에서 HWPX로 저장해 사용하세요.')
        flags=struct.unpack_from('<I',header,36)[0]
        if flags & ((1<<1)|(1<<2)|(1<<4)|(1<<8)|(1<<10)):
            fail('암호·배포용·DRM 제한 HWP는 읽을 수 없습니다. 제한을 해제하거나 HWPX로 저장해 사용하세요.')
        streams=ole.listdir()
        if len(streams)>3000:fail('HWP 내부 항목이 너무 많습니다.',413)
        sections=sorted((path for path in streams if len(path)==2 and path[0]=='BodyText' and re.fullmatch(r'Section\d+',path[1])),key=lambda path:int(path[1][7:]))
        if not sections:fail('HWP 본문을 찾지 못했습니다. HWPX로 저장해 사용하세요.')
        chunks=[];expanded=0;chars=0
        for path in sections:
            if ole.get_size(path)>MAX_FILE:fail('HWP 본문이 너무 큽니다.',413)
            raw=ole.openstream(path).read()
            if flags & 1:
                decoder=zlib.decompressobj(-15)
                raw=decoder.decompress(raw,MAX_EXPANDED-expanded+1)
                if len(raw)>MAX_EXPANDED-expanded or decoder.unconsumed_tail:fail('HWP 압축 해제 크기가 너무 큽니다.',413)
                # Hancom may append non-deflate bytes after the completed stream.
                if not decoder.eof:fail('HWP 압축 본문이 손상되었습니다.')
            expanded+=len(raw)
            if expanded>MAX_EXPANDED:fail('HWP 압축 해제 크기가 너무 큽니다.',413)
            for text in hwp_records(raw):
                chars+=len(text)+1
                if chars>MAX_TEXT+1:fail('안내문 텍스트는 20,000자 이하여야 합니다.',413)
                chunks.append(text)
        return '\n'.join(chunks)


def extract_notice(data, filename):
    if len(data)>MAX_FILE:fail('안내문 파일은 3MB 이하여야 합니다.',413)
    extension=PurePath(filename or '').suffix.lower()
    if extension=='.doc':fail('구형 Word DOC는 DOCX로 저장한 뒤 올려주세요.')
    if extension not in ('.pdf','.txt','.hwp','.hwpx','.docx'):
        fail('PDF·한글(HWP/HWPX)·Word(DOCX)·UTF-8 TXT 파일을 사용하세요.')
    try:
        pages=None;warning=''
        if extension=='.pdf':
            import pymupdf
            if not data.startswith(b'%PDF-'):fail('PDF 파일 형식이 아닙니다.')
            with pymupdf.open(stream=data,filetype='pdf') as pdf:
                if pdf.needs_pass or not 1<=pdf.page_count<=20:fail('암호 없는 1~20페이지 PDF를 사용하세요.')
                chunks=[];size=0;empty_pages=[];pages=pdf.page_count
                for page in pdf:
                    text=page.get_text(sort=True);size+=len(text)+1
                    if size>MAX_TEXT+1:fail('안내문 텍스트는 20,000자 이하여야 합니다.',413)
                    if not text.strip():empty_pages.append(page.number+1)
                    chunks.append(text)
            text='\n'.join(chunks)
            if empty_pages:warning=f"텍스트를 읽지 못한 페이지: {', '.join(map(str,empty_pages))}. 해당 페이지의 내용을 직접 보완하세요."
        elif extension=='.txt':
            try:text=data.decode('utf-8-sig')
            except UnicodeDecodeError:fail('TXT 파일은 UTF-8로 저장하거나 내용을 직접 붙여넣으세요.')
        elif extension=='.hwp':
            text=hwp_text(data);warning=OFFICE_WARNING
        else:
            text=zip_text(data,extension);warning=OFFICE_WARNING
        return {'text':checked_text(text),'pages':pages,'warning':warning,'file_type':extension[1:]}
    except HTTPException:raise
    except Exception:fail('문서를 읽을 수 없습니다. 파일 형식·손상·암호 설정을 확인하세요.')
