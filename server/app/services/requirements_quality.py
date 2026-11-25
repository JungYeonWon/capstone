"""Conservative question de-duplication and visible requirements provenance."""
import re
from difflib import SequenceMatcher


def normalized(text):
    return re.sub(r'[\W_]+', '', text).casefold()


def topic_for(text, declared='other'):
    if declared != 'other': return declared
    for topic, pattern in (
        ('login_security', r'로그인.*(?:보안|이중|2단계|실패|잠금)|인증.*(?:보안|실패)|MFA|OTP'),
        ('user_roles', r'권한|접근.*역할|사용자.*역할'),
        ('login_method', r'로그인|로그온|인증 방식|인증 방법|SSO'),
        ('cancellation_fee', r'취소.*(?:비용|수수료|환불)|환불'),
        ('cancellation_deadline', r'취소.*(?:기한|언제|전까지|시점|규칙|가능 시간)'),
        ('acceptance', r'검수|인수 기준|통과 조건'), ('deliverables', r'산출물|납품물'),
        ('schedule', r'납기|완료일|완료 기한|마감일'), ('budget', r'예산|견적|단가'),
    ):
        if re.search(pattern, text, re.I): return topic
    return 'other'


def known_answer(text):
    undecided = re.search(r'모르|미정|미확정|추후|정하지|협의 중|결정 전|아직', text)
    decision = re.search(r'(?<!미)확정|결정했|하기로|변경', text)
    return bool(text.strip()) and (not undecided or bool(decision))


def decided(citations, sources, topic='other'):
    for decision in sources:
        if decision['kind'] != 'answer' or not decision.get('confirmed') or not decision.get('resolves'): continue
        if topic != 'other' and topic_for(decision['text'].partition('\n')[0], decision.get('topic', 'other')) != topic: continue
        previous = [' '.join(value.split()) for value in decision['resolves'] if value.strip()]
        def covers(citation):
            return citation.source_id == decision['source_id'] or any(
                ' '.join(citation.quote.split()) in quote or quote in ' '.join(citation.quote.split()) for quote in previous)
        if all(covers(c) for c in citations) and any(c.source_id != decision['source_id'] for c in citations) and known_answer(decision['text'].partition('\n')[2]):
            return True
    return False


def explicit_login_conflicts(sources):
    """Backstop only for explicit, incompatible login methods for the same actor.

    Do not infer contradictions between different roles, unknown choices, or
    email-or-phone alternatives. Confirmed decisions resolve only cited text.
    """
    from app.services.ai_workflows import Question, Citation
    facts = []
    for source in sources:
        if source['kind'] not in ('input', 'answer'): continue
        text = source['text'].partition('\n')[2] if source['kind'] == 'answer' else source['text']
        answer_topic = topic_for(source['text'].partition('\n')[0], source.get('topic', 'other'))
        for part in re.split(r'\n+|(?<=[.!?。])\s+', text):
            quote = ' '.join(part.split())
            if not 5 <= len(quote) <= 350 or not known_answer(quote): continue
            if not (re.search(r'로그인|로그온|인증', quote) or (source['kind'] == 'answer' and answer_topic == 'login_method')): continue
            if re.search(r'함께|병행|복수|추가로|으로도|도\s*(?:사용|지원|허용|로그인)', quote): continue
            actor = re.search(r'관리자|환자|고객|직원|회원', quote)
            methods = set()
            for key, pattern in [('email', r'이메일|전자우편'), ('phone', r'휴대폰|휴대전화|전화번호|SMS|문자 인증'), ('sso', r'SSO|통합 로그인'), ('social', r'소셜|카카오|네이버|구글')]:
                for match in re.finditer(pattern, quote, re.I):
                    suffix = quote[match.end():match.end()+18]
                    if re.search(r'사용하지|제외|미사용|아니|대신', suffix): continue
                    methods.add(key)
            if methods: facts.append((source, quote, actor.group() if actor else '', methods))
    questions = []; seen = set()
    for index, (left, a, actor, methods) in enumerate(facts):
        for right, b, other_actor, other_methods in facts[index+1:]:
            if actor != other_actor or not methods.isdisjoint(other_methods) or actor in seen: continue
            citations = [Citation(source_id=left['source_id'], quote=a), Citation(source_id=right['source_id'], quote=b)]
            if decided(citations, sources, 'login_method'): continue
            seen.add(actor)
            questions.append(Question(question=f'{actor+"의 " if actor else ""}로그인 방식이 서로 다릅니다. 어느 방식으로 확정할까요?',
                reason='입력과 답변의 로그인 방식이 달라 임의로 한쪽을 확정하지 않았습니다.', topic='login_method', intent='conflict',
                evidence=citations))
    return questions


def improve(result, sources):
    from app.services.ai_workflows import Question
    answers = []
    for source in sources:
        if source['kind'] != 'answer': continue
        question, _, answer = source['text'].partition('\n')
        if known_answer(answer): answers.append((question, topic_for(question, source.get('topic', 'other'))))

    stable_topics = {'login_method', 'cancellation_deadline', 'cancellation_fee', 'schedule', 'budget'}
    questions = explicit_login_conflicts(sources)
    suppressed = 0
    for question in result.questions:
        question.topic = topic_for(question.question, question.topic)
        if question.intent == 'conflict' and decided(question.evidence, sources, question.topic):
            suppressed += 1; continue
        duplicate = any(normalized(question.question) == normalized(old.question) or
            (question.intent == old.intent == 'conflict' and question.topic == old.topic and
             {c.source_id for c in question.evidence} == {c.source_id for c in old.evidence}) or
            (question.intent == old.intent and question.topic == old.topic and
             SequenceMatcher(None, normalized(question.question), normalized(old.question)).ratio() >= .78)
            for old in questions)
        answered = question.intent != 'conflict' and any(
            normalized(question.question) == normalized(old) or
            (question.intent == 'clarification' and question.topic in stable_topics and question.topic == topic) or
            (question.intent == 'clarification' and question.topic == topic and SequenceMatcher(None, normalized(question.question), normalized(old)).ratio() >= .76)
            for old, topic in answers)
        if duplicate or answered: suppressed += 1
        else: questions.append(question)
    # Resolve contradictions before routine elaboration; do not suppress them as answered topics.
    result.questions = sorted(questions, key=lambda q: q.intent != 'conflict')[:12]
    conflicts = [q for q in result.questions if q.intent == 'conflict']
    conflicting_sources = {c.source_id for q in conflicts for c in q.evidence}
    by_id = {s['source_id']: s for s in sources}
    for item in result.items:
        if item.basis == 'proposal': item.confirmation = 'proposal'
        elif item.evidence and all(by_id[c.source_id].get('confirmed', False) and c.source_id not in conflicting_sources for c in item.evidence):
            item.confirmation = 'confirmed'
        else: item.confirmation = 'tentative'
        if conflicts and any(c.source_id in conflicting_sources for c in item.evidence):
            item.detail = '[충돌 확인 필요] ' + item.detail.removeprefix('[충돌 확인 필요] ')[:980]
    if suppressed: result.quality_notes.append(f'이미 답변했거나 중복된 질문 {suppressed}개를 정리했습니다. 답변이 미정이면 필요한 질문을 유지합니다.')
    if conflicts:
        result.summary = '요구사항에 서로 다른 조건이 있습니다. 충돌 확인 질문의 양쪽 근거를 확인하고 결정 내용을 답한 뒤 다시 분석하세요. 아래 내용은 확정 전 검토 후보입니다.'
        result.quality_notes.append('서로 다른 조건이 발견됐습니다. 원문과 답변을 함께 확인하고, 충돌 확인 질문에 결정 내용을 답한 뒤 다시 분석하세요.')

    scope = next(d for d in result.drafts if d.kind == 'scope')
    acceptance = next((s for s in scope.sections if '검수' in s.label), None)
    if acceptance and re.search(r'정상.{0,2}작동|요구사항.{0,3}충족|문제.{0,2}없이', acceptance.text) and not re.search(r'입력|시험|테스트|기대 결과|통과 조건|시나리오', acceptance.text):
        acceptance.text = '[확인 필요] 기능별 시험 절차·입력·기대 결과·통과 조건을 구체적으로 정하세요.\n기존 제안: ' + acceptance.text[:4500]
        result.quality_notes.append('모호한 검수 문구를 구체화가 필요한 항목으로 표시했습니다. 수치와 성능 기준은 임의로 만들지 않았습니다.')
        if not any(q.topic == 'acceptance' for q in result.questions) and len(result.questions) < 12:
            result.questions.append(Question(question='검수할 기능별 시험 절차·입력·기대 결과와 통과 조건은 무엇인가요?',
                reason='정상 작동이라는 표현만으로는 검수 완료를 판단하기 어렵습니다.', topic='acceptance'))
