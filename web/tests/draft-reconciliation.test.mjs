import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
const code = ts.transpileModule(fs.readFileSync(new URL('../src/lib/draft-reconciliation.ts', import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText;
const { identifyDrafts, compareDrafts, applyDraftChange } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const draft = (sections, kind = 'scope', title = '과업지시서') => ({ kind, title, sections: sections.map(([label, text]) => ({ label, text })) });

test('reanalysis preserves edited text until a specific proposal is accepted', () => {
  const baseline = identifyDrafts([draft([['업무 범위', 'AI 최초 본문'], ['검수', '원문 검수']])]);
  const local = structuredClone(baseline); local[0].sections[0].text = '사용자가 수정한 범위와 협의 내용';
  const incoming = identifyDrafts([draft([['업무 범위', '새 범위'], ['검수', '새 검수']])], local);
  const snapshot = structuredClone(local), changes = compareDrafts(local, baseline, incoming);
  assert.deepEqual(local, snapshot);
  assert.equal(changes.length, 2); assert.equal(changes[0].protected, true); assert.equal(changes[1].protected, false);
  const updated = applyDraftChange(local, changes[1]);
  assert.equal(updated[0].sections[0].text, '사용자가 수정한 범위와 협의 내용');
  assert.equal(updated[0].sections[1].text, '새 검수');
  assert.deepEqual(local, snapshot);
});
test('identical reanalysis does not create spurious changes or reset section identities', () => {
  const local = identifyDrafts([draft([['업무 범위', '동일 문구'], ['검수', '동일 기준']])]);
  const incoming = identifyDrafts([draft([['업무 범위', '동일 문구'], ['검수', '동일 기준']])], local);
  assert.deepEqual(compareDrafts(local, local, incoming), []);
  assert.deepEqual(incoming.map(d => d.sections.map(s => s.id)), local.map(d => d.sections.map(s => s.id)));
});
test('renamed or unmatched sections are never matched by array position', () => {
  const baseline = identifyDrafts([draft([['범위', '처음 문구']])]);
  const local = structuredClone(baseline); local[0].sections[0].label = '사용자가 정한 특별 조건';
  const incoming = identifyDrafts([draft([['새로운 범위', '새로운 문구']])], local);
  const changes = compareDrafts(local, baseline, incoming);
  assert.deepEqual(changes.map(c => c.type), ['remove_section', 'add_section']);
  assert.equal(changes[0].protected, true);
  assert.equal(local[0].sections[0].label, '사용자가 정한 특별 조건');
});
test('section choices remain attached to the right content after earlier sections are removed', () => {
  const local = identifyDrafts([draft([['A', 'a'], ['B', 'b'], ['C', 'c']])]);
  const incoming = identifyDrafts([draft([['B', 'new b'], ['C', 'c'], ['D', 'd']])], local);
  const changes = compareDrafts(local, local, incoming);
  let result = applyDraftChange(local, changes.find(c => c.type === 'remove_section'));
  result = applyDraftChange(result, changes.find(c => c.type === 'section'));
  result = applyDraftChange(result, changes.find(c => c.type === 'add_section'));
  assert.deepEqual(result[0].sections.map(s => [s.label, s.text]), [['B', 'new b'], ['C', 'c'], ['D', 'd']]);
});
test('a stale proposal refuses to overwrite edits made after comparison', () => {
  const local = identifyDrafts([draft([['범위', '이전']])]);
  const incoming = identifyDrafts([draft([['범위', '제안']])], local);
  const [change] = compareDrafts(local, local, incoming);
  const edited = structuredClone(local); edited[0].sections[0].text = '비교 이후 새 수정';
  assert.throws(() => applyDraftChange(edited, change), /기존 내용이 달라졌습니다/);
  assert.equal(edited[0].sections[0].text, '비교 이후 새 수정');
});
test('title changes can be applied without replacing section edits', () => {
  const baseline = identifyDrafts([draft([['범위', '원본']])]);
  const local = structuredClone(baseline); local[0].title = '사용자가 정한 제목'; local[0].sections[0].text = '보호할 문구';
  const incoming = identifyDrafts([draft([['범위', '보호할 문구']], 'scope', '새 제목')], local);
  const changes = compareDrafts(local, baseline, incoming);
  assert.equal(changes[0].protected, true);
  const updated = applyDraftChange(local, changes[0]);
  assert.equal(updated[0].title, '새 제목'); assert.equal(updated[0].sections[0].text, '보호할 문구');
});
test('legacy drafts without baseline are conservatively protected and survive session serialization', () => {
  const local = identifyDrafts([draft([['범위', '예전 작업의 사용자 문구']])]);
  const incoming = identifyDrafts([draft([['범위', '신규 제안']])], local);
  const changes = JSON.parse(JSON.stringify(compareDrafts(local, [], incoming)));
  assert.equal(changes[0].protected, true);
  assert.equal(applyDraftChange(local, changes[0])[0].sections[0].text, '신규 제안');
});
test('retained wording stays protected on the next analysis cycle', () => {
  const local = identifyDrafts([draft([['범위', '유지하기로 한 사용자 문구']])]);
  const rejected = identifyDrafts([draft([['범위', '반영하지 않은 AI 문구']])], local);
  const latest = identifyDrafts([draft([['범위', '두 번째 AI 제안']])], local);
  assert.equal(compareDrafts(local, rejected, latest)[0].protected, true);
});
test('an added document does not modify existing documents and removal is explicit', () => {
  const local = identifyDrafts([draft([['합의', '확인 필요']], 'meeting_minutes', '회의 확인서')]);
  const incoming = identifyDrafts([...local, draft([['변경', '새 제안']], 'change_agreement', '변경 초안')], local);
  const changes = compareDrafts(local, local, incoming);
  const result = applyDraftChange(local, changes[0]);
  assert.equal(result.length, 2); assert.deepEqual(result[0], local[0]);
  const removed = compareDrafts(result, incoming, local).find(c => c.type === 'remove_document');
  assert.equal(applyDraftChange(result, removed).length, 1);
});
test('oversized additions and deletion of the only section fail without losing current content', () => {
  const local = identifyDrafts([draft(Array.from({ length: 10 }, (_, i) => [`항목 ${i}`, `${i}`]))]);
  const incoming = identifyDrafts([draft([['추가 항목', '새 문구']])], local);
  const change = compareDrafts(local, local, incoming).find(c => c.type === 'add_section');
  assert.throws(() => applyDraftChange(local, change), /1~10개/);
  assert.equal(local[0].sections.length, 10);
  const single = identifyDrafts([draft([['기존', '보호']])]);
  const removal = compareDrafts(single, single, incoming).find(c => c.type === 'remove_section');
  assert.throws(() => applyDraftChange(single, removal), /1~10개/);
});
