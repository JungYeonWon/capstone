"""Encrypted review snapshots, human follow-up and deterministic text comparison."""
import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from io import BytesIO
from xml.sax.saxutils import escape

from fastapi import HTTPException
from sqlalchemy import select, update, func

from app.models import ClauseReview, AuditLog, Contract, Document

STATUSES={'pending':'확인 전','asking':'상대방 문의 중','resolved':'수정·확인 완료'}


def document_signature(doc):
    template=doc.template
    snapshot={'values':doc.values,'template_id':doc.template_id,'title':doc.title,
              'definition':template.definition,'fields':template.fields,'source_type':template.source_type,'source_path':template.source_path}
    return hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def document_state(db,row):
    if not row.payload.get('document_id'):return 'uploaded'
    doc=db.scalar(select(Document).where(Document.id==row.payload['document_id'],Document.contract_id==row.contract_id).execution_options(populate_existing=True))
    if not doc or doc.contract_id!=row.contract_id:return 'deleted'
    return 'current' if document_signature(doc)==row.payload.get('document_signature') else 'changed'


def get_owned(db,user,contract_id,review_id):
    row=db.scalar(select(ClauseReview).join(Contract).where(ClauseReview.id==review_id,
        ClauseReview.contract_id==contract_id,Contract.user_id==user.id))
    if row is None:raise HTTPException(404,'검토 이력을 찾을 수 없습니다.')
    return row


def file_groups(sources):
    groups={}
    for source in sources:
        key=str(source.get('file_id',source['name']))
        group=groups.setdefault(key,{'key':key,'name':source['name'],'text':''})
        group['text']+='\n'+source['text']
    return groups


def to_out(row,detail=True):
    payload=row.payload
    result={'id':row.id,'created_at':row.created_at,'revision':row.revision,'role':payload['role'],
        'document_id':payload.get('document_id'),'source_files':[{'key':g['key'],'name':g['name']} for g in file_groups(payload['sources']).values()],
        'finding_count':len(payload['findings']),'resolved_count':sum(f.get('status')=='resolved' for f in payload['findings'])}
    if detail:result.update(findings=payload['findings'],excluded=payload.get('excluded',0),warning=payload.get('warning',''))
    return result


def save(db,user,contract,body,transmission,result):
    db.scalar(select(Contract).where(Contract.id==contract.id).with_for_update())
    if db.scalar(select(func.count()).select_from(ClauseReview).where(ClauseReview.contract_id==contract.id))>=50:
        raise HTTPException(409,'다른 창의 검토 저장으로 이력이 50개가 됐습니다. 기존 이력을 정리한 뒤 다시 검토하세요.')
    snapshot=json.loads(transmission['payload_preview'])
    findings=[{**item,'status':'pending','note':''} for item in result['findings']]
    payload={'contract_title':contract.contract_title,'role':body.role,'document_id':body.document_id,'document_signature':transmission.get('document_signature'), 'sources':snapshot['sources'],
        'findings':findings,'excluded':result['excluded'],'warning':transmission.get('warning','')}
    row=ClauseReview(contract_id=contract.id,payload=payload)
    db.add(row);db.flush()
    db.add(AuditLog(user_id=user.id,action='review_save',detail=f'계약 {contract.id} 검토 이력 {row.id} 저장'))
    db.commit()
    return {**to_out(row),'document_state':document_state(db,row)}


def change_finding(db,user,row,index,status,note,revision):
    if index>=len(row.payload['findings']):raise HTTPException(404,'검토 항목을 찾을 수 없습니다.')
    payload=deepcopy(row.payload)
    payload['findings'][index].update(status=status,note=note)
    changed=db.scalar(update(ClauseReview).where(ClauseReview.id==row.id,ClauseReview.revision==revision)
        .values(payload=payload,revision=revision+1).returning(ClauseReview.id))
    if changed is None:
        db.rollback();raise HTTPException(409,'다른 창에서 수정한 이력이 있습니다. 이력을 다시 불러와 확인하세요.')
    db.add(AuditLog(user_id=user.id,action='review_followup',detail=f'검토 이력 {row.id} 항목 {index+1} 처리 상태 저장'))
    db.commit();db.refresh(row)
    return {**to_out(row),'document_state':document_state(db,row)}


def normalized(text):return re.sub(r'\s+',' ',text).strip()


def compare(before,after,source_map=None):
    if before['role']!=after['role']:raise HTTPException(400,'같은 역할로 검토한 자료끼리 비교하세요.')
    old=file_groups(before['sources']);new=file_groups(after['sources'])
    source_map=dict(source_map or {})
    if set(source_map)-set(old) or any(value not in new for value in source_map.values()):
        raise HTTPException(422,'비교할 파일 연결을 확인하세요.')
    if len(set(source_map.values()))!=len(source_map):raise HTTPException(422,'수정본 파일을 중복 연결할 수 없습니다.')
    # Auto-match only unique identical names, or an explicitly visible single-file pair.
    for key,group in old.items():
        candidates=[k for k,g in new.items() if g['name']==group['name']]
        if key not in source_map and len(candidates)==1 and candidates[0] not in source_map.values():source_map[key]=candidates[0]
    if len(old)==len(new)==1 and not source_map:source_map[next(iter(old))]=next(iter(new))
    source_by_id={s['source_id']:s for s in before['sources']}
    matches={}
    for key,new_key in source_map.items():
        a,b=normalized(old[key]['text']),normalized(new[new_key]['text'])
        matches[key]=(a,b,SequenceMatcher(None,a,b,autojunk=True).get_opcodes())
    rows=[]
    for index,finding in enumerate(before['findings']):
        evidence=[]
        for citation in finding['evidence']:
            source=source_by_id.get(citation.get('source_id'))
            key=str(source.get('file_id',source['name'])) if source else ''
            quote=normalized(citation['quote'])
            record={'before':citation['quote'],'before_name':citation['name'],'before_page':citation['page'],
                    'after':'','after_name':None,'status':'unmatched'}
            if key in matches:
                a,b,opcodes=matches[key];record['after_name']=new[source_map[key]]['name']
                if quote in b:record.update(status='unchanged',after=quote)
                elif a.count(quote)!=1:record['status']='ambiguous'
                else:
                    start=a.index(quote);end=start+len(quote);spans=[]
                    for tag,i1,i2,j1,j2 in opcodes:
                        if (i1<end and i2>start) or (i1==i2 and start<i1<end):
                            if tag=='equal':spans.append((j1+max(start-i1,0),j1+min(end-i1,i2-i1)))
                            else:spans.append((j1,j2))
                    if spans:
                        left=min(s[0] for s in spans);right=max(s[1] for s in spans)
                        excerpt=b[left:right]
                        if excerpt.strip():
                            # Include the surrounding sentence: a newly inserted deadline can precede the old quote.
                            start_context=b.rfind('. ',0,left)+2 if '. ' in b[:left] else 0
                            end_context=b.find('. ',max(right-1,0))
                            end_context=end_context+1 if end_context>=0 else len(b)
                            excerpt=b[start_context:end_context]
                            record.update(status='changed',after=excerpt[:700],truncated=len(excerpt)>700)
                        else:record.update(status='removed',after='',truncated=False)
                    else:record['status']='ambiguous'
            evidence.append(record)
        rows.append({'index':index,'category':finding['category'],'title':finding['title'],'evidence':evidence,
                     'unchanged':all(e['status']=='unchanged' for e in evidence)})
    mapped=set(source_map.values())
    return {'items':rows,'source_map':source_map,
        'unmatched_before':[{'key':k,'name':g['name']} for k,g in old.items() if k not in source_map],
        'additional_after':[{'key':k,'name':g['name']} for k,g in new.items() if k not in mapped],
        'notice':'이전 지적 조항의 텍스트 비교입니다. 인용문 유지·변경·삭제는 문제 해결이나 새 문서 전체 검토 완료를 의미하지 않습니다. 주변 조항과 새 의무는 별도로 확인하세요.'}


def report_pdf(row,contract_title,source_state='uploaded'):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from app.services.renderer import _register_font
    font=_register_font();out=BytesIO();story=[]
    styles={
        'title':ParagraphStyle('title',fontName=font,fontSize=19,leading=28,alignment=TA_CENTER,spaceAfter=14),
        'heading':ParagraphStyle('heading',fontName=font,fontSize=12,leading=19,spaceBefore=14,spaceAfter=6,keepWithNext=True),
        'body':ParagraphStyle('body',fontName=font,fontSize=10,leading=16,spaceAfter=7,wordWrap='CJK'),
        'quote':ParagraphStyle('quote',fontName=font,fontSize=9,leading=15,leftIndent=10,borderColor=colors.HexColor('#CBD5E1'),borderWidth=.5,borderPadding=7,spaceBefore=5,spaceAfter=10,wordWrap='CJK'),
    }
    def add(value,style='body'):story.append(Paragraph(escape(str(value)).replace('\n','<br/>'),styles[style]))
    add('계약서 검토 보고서','title');add(row.payload.get('contract_title',contract_title))
    created=row.created_at.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=9)))
    add(f"검토 이력 #{row.id} · {created:%Y-%m-%d %H:%M} (한국시간) · 우리 측: {'수행사' if row.payload['role']=='supplier' else '발주처'}")
    add('검토 당시 자료에 대한 AI 제안과 사용자 처리 기록입니다. 법적 판단·상대방 합의·최종 제출 승인으로 간주하지 않습니다.')
    if source_state in ('changed','deleted'):add('검토 대상 저장 문서가 이후 변경 또는 삭제됐습니다. 이 보고서는 이전 문서 기준입니다.')
    add('검토 자료: '+', '.join(g['name'] for g in file_groups(row.payload['sources']).values()))
    if row.payload.get('warning'):add(row.payload['warning'])
    if row.payload.get('excluded'):add(f"원문 근거 또는 표시 형식을 확인하지 못해 제외한 AI 결과: {row.payload['excluded']}건")
    if not row.payload['findings']:add('표시할 검토 항목이 없습니다. 문제가 없다는 판정을 의미하지 않습니다.')
    for index,item in enumerate(row.payload['findings'],1):
        add(f"{index}. [{item['category']}] {item['title']}",'heading')
        add('처리 상태: '+STATUSES[item.get('status','pending')])
        for evidence in item['evidence']:
            add(evidence['name']+(f" · {evidence['page']}쪽" if evidence['page'] else '')+'\n'+evidence['quote'],'quote')
        add('예상 부담: '+item['impact']);add('확인할 질문: '+item['question'])
        if item.get('note'):add('사용자 메모: '+item['note'])
        story.append(Spacer(1,3*mm))
    def footer(canvas,doc):
        canvas.setFont(font,8);canvas.drawRightString(A4[0]-20*mm,12*mm,f'{doc.page}')
    SimpleDocTemplate(out,pagesize=A4,leftMargin=20*mm,rightMargin=20*mm,topMargin=18*mm,bottomMargin=22*mm).build(story,onFirstPage=footer,onLaterPages=footer)
    return out.getvalue()
