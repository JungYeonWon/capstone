"""Conservative lexical backstop, not a second legal opinion.

Candidates always quote a complete local clause. Do not combine independent
sentences: a limit/exception in the same clause must remain visible to readers.
"""
import re

# Role, category, topic, strong trigger, title, question. No trigger alone proves risk.
CHECKS = (
    ('수행사', '유지보수·하자보수', r'유지보수|하자보수|장애 대응', r'무상|무료', '무상 지원의 상한 확인', '무상 지원의 기간·횟수·대상과 유상 전환 기준을 정할 수 있을까요?'),
    ('수행사', '추가 업무·수정', r'추가 업무|추가 기능|기능 추가|과업 변경', r'무상|추가 비용 없이|별도 비용 없이', '추가 과업 비용 확인', '추가 과업의 범위와 견적·납기 변경에 대한 서면 합의 절차를 정할 수 있을까요?'),
    ('수행사', '손해배상·위약금', r'손해배상|배상|배상책임', r'무제한|한도 없이|제한 없이|간접손해|간접 손해|일실이익', '배상 범위와 한도 확인', '배상 대상과 책임 한도, 간접손해의 포함 여부를 구체적으로 정할 수 있을까요?'),
    ('수행사', '검수·대금 지급', r'검수|잔금|대금 지급', r'기한.{0,12}정하지 않|무기한|지급.{0,12}보류', '검수·지급 기한 확인', '검수 완료 기한과 대금 지급일, 보류 사유 및 해제 절차를 정할 수 있을까요?'),
    ('공통', '자동 연장·갱신', r'자동.{0,4}연장|자동.{0,4}갱신', r'연장|갱신', '자동 갱신과 종료 통지 확인', '갱신 거절 통지 기한·방법과 갱신 후 비용·의무를 확인할 수 있을까요?'),
    ('공통', '일방 변경·권리 이전', r'변경|양도|이전', r'일방적|동의 없이', '상대방 단독 변경·이전 확인', '상대방의 변경·권리 이전에 사전 서면 동의와 거절 절차를 둘 수 있을까요?'),
    ('발주처', '재위탁·보안', r'재위탁|재하도급|제삼자|제3자', r'승인 없이|동의 없이|자유롭게', '제3자 위탁 통제 확인', '재위탁의 사전 승인과 수탁자 보안·책임 범위를 정할 수 있을까요?'),
    ('발주처', '비밀유지·데이터', r'개인정보|고객정보|기밀|비밀정보|데이터', r'무기한 보관|영구 보관|목적 외|자유롭게 이용', '자료 이용·보관 범위 확인', '자료 이용 목적·보관 기한과 종료 후 반환·삭제 기준을 정할 수 있을까요?'),
)


def supplement(sources, role, findings):
    candidates = []
    seen = set()
    for source in sources:
        # Preserve line boundaries before whitespace normalization for numbered lists.
        for line in source['text'].splitlines():
            for part in re.split(r'(?<=[.!?。;；])\s+', line):
                quote = ' '.join(part.split())
                if not 8 <= len(quote) <= 350:
                    continue  # Never truncate away a qualification or negation.
                compact = re.sub(r'\s+', '', quote)
                if re.search(r'적용하지|허용하지|금지|불가|아니한다|아니하며|(?:개발|제공|부담|보관|이용)하지않', compact):
                    continue
                if re.search(r'(자동.{0,4}(갱신|연장)|무상|무제한|한도없이|동의없이).{0,8}(않|아니|없습니다)', compact):
                    continue
                for applies, category, topic, trigger, title, question in CHECKS:
                    if applies not in ('공통', role):
                        continue
                    if not (re.search(topic, quote) and re.search(trigger, quote)):
                        continue
                    # A bounded free support period is not an unlimited-support trigger.
                    if category == '유지보수·하자보수' and not re.search(r'무제한|제한 없이|기간.{0,8}제한.{0,4}없이', quote):
                        continue
                    # Supplied exceptions/consent may reverse a trigger; defer to AI.
                    if re.search(r'경우에만|에 한하여|제외한다|제외하며|다만|상호.*합의', quote):
                        continue
                    identity = (source['source_id'], category, quote)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    if any(e.get('source_id') == source['source_id'] and
                           (quote in e['quote'] or e['quote'] in quote)
                           for f in findings for e in f['evidence']):
                        continue
                    candidates.append({'category': category, 'title': title, 'method': 'rule',
                        'impact': '원문 표현이 점검 규칙과 일치합니다. 주변 조항의 예외·상한과 실제 의무 주체를 함께 확인해야 합니다.',
                        'question': question, 'evidence': [{'source_id': source['source_id'],
                            'name': source['name'], 'page': source.get('page'), 'quote': quote}]})
    return candidates[:24], max(0, len(candidates) - 24)
