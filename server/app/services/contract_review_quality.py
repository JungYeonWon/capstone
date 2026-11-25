"""Evidence-preserving grouping and conservative context discovery, not legal judgments."""
import re

PRIORITY = {'high': 0, 'medium': 1, 'low': 2}
TOPICS = {
    '유지보수·하자보수': r'유지보수|하자|무상 지원|장애', '추가 업무·수정': r'추가|변경|과업|수정',
    '검수·대금 지급': r'검수|지급|잔금|보류', '손해배상·위약금': r'배상|손해|책임',
    '자동 연장·갱신': r'갱신|연장|종료 통지', '일방 변경·권리 이전': r'변경|양도|이전',
    '재위탁·보안': r'재위탁|재하도급|제3자|제삼자', '비밀유지·데이터': r'정보|데이터|자료',
}


def norm(text): return ' '.join(text.split())


def citation(source, quote):
    return {'source_id': source['source_id'], 'name': source['name'], 'page': source.get('page'), 'quote': norm(quote)}


def verified(evidence, sources):
    source = sources.get(evidence.source_id)
    quote = norm(evidence.quote)
    return citation(source, quote) if source and 8 <= len(quote) <= 350 and quote in norm(source['text']) else None


def conditions(category, sources, evidence):
    topic = TOPICS.get(category)
    if not topic: return []
    origin = next((s for s in sources if s['source_id'] == evidence['source_id']), None)
    if not origin: return []
    clauses = [(source, norm(part)) for source in sources
        for part in re.split(r'\n+|(?<=[.!?。;；])\s+', source['text']) if 8 <= len(norm(part)) <= 350]
    result = []
    for index, (source, quote) in enumerate(clauses):
        if source['source_id'] != evidence['source_id'] or evidence['quote'] not in quote: continue
        nearby = clauses[max(0, index-1):index+3]
        if re.search(r'별첨|제\s*\d+\s*조', evidence['quote']): nearby = clauses
        for candidate_source, candidate in nearby:
            if candidate == quote: continue
            same_file = candidate_source.get('file_id', candidate_source['name']) == origin.get('file_id', origin['name'])
            linked = re.match(r'다만|단[,， ]|전항|본조|위 |해당 |이 경우', candidate)
            explicit_reference = re.search(r'별첨|제\s*\d+\s*조', evidence['quote'])
            if not ((same_file and (linked or re.search(topic, candidate))) or (explicit_reference and re.search(topic, candidate))): continue
            if re.search(r'한도.{0,4}없|상한.{0,4}없|무제한|제한.{0,4}없', candidate): continue
            if not re.search(r'\d+(?:\.\d+)?\s*(?:일|개월|년|회|%|퍼센트)|서면.{0,8}(?:동의|합의)|상한|한도|면책|제외', candidate): continue
            item = citation(candidate_source, candidate)
            if item not in result: result.append(item)
        break
    return result[:3]


def group_and_rank(findings):
    grouped = []; merged = 0
    for finding in findings:
        key = (finding['category'], frozenset((e['source_id'], e['quote']) for e in finding['evidence']))
        previous = next((old for old in grouped if (old['category'], frozenset((e['source_id'], e['quote']) for e in old['evidence'])) == key), None)
        if previous is None: grouped.append(finding); continue
        values = {}
        for field in ('impact', 'question', 'context_note'):
            values[field] = '\n'.join(dict.fromkeys(filter(None, [previous.get(field, ''), finding.get(field, '')])))
        contexts = previous.get('context_evidence', []) + [e for e in finding.get('context_evidence', []) if e not in previous.get('context_evidence', [])]
        # Preserve independent material instead of truncating it to fit a merge.
        if any(len(value) > 700 for value in values.values()) or len(contexts) > 3:
            grouped.append(finding); continue
        previous.update(values, context_evidence=contexts)
        previous['priority'] = min((previous.get('priority', 'medium'), finding.get('priority', 'medium')), key=PRIORITY.get)
        if finding.get('assessment') == 'uncertain': previous['assessment'] = 'uncertain'
        merged += 1
    return sorted(grouped, key=lambda f: PRIORITY[f.get('priority', 'medium')]), merged
