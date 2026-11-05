import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
const source = new URL('../src/lib/notice.ts', import.meta.url);
const code = ts.transpileModule(fs.readFileSync(source, 'utf8'), { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { applyNoticeAnalysis } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const item = { id: 'n_1234567890123456', title: '착수계', evidence: '착수계 1부', required: true, done: false, document_id: null, note: '' };
const analysis = { items: [item], facts: [{ kind: 'deadline', value: '7일 이내', evidence: '제출기한: 7일 이내' }] };

test('reanalysis preserves preparation, links, notes and manual entries for unchanged requirements', () => {
  const manual = { ...item, id: 'n_2222222222222222', title: '직접 준비할 서류', evidence: '' };
  const previous = { text: '새 안내문', items: [{ ...item, done: true, document_id: 7, note: '원본 보관' }, manual] };
  const result = applyNoticeAnalysis(previous, analysis);
  assert.equal(result.items[0].done, true);
  assert.equal(result.items[0].document_id, 7);
  assert.equal(result.items[0].note, '원본 보관');
  assert.equal(result.items[1], manual);
  assert.equal(result.analyzed_text, previous.text);
  assert.deepEqual(result.facts, analysis.facts);
});
test('changed evidence resets readiness without losing document association', () => {
  const result = applyNoticeAnalysis({ text: '새 안내문', items: [{ ...item, evidence: '착수계 2부', done: true, document_id: 7 }] }, analysis);
  assert.equal(result.items[0].done, false);
  assert.equal(result.items[0].document_id, 7);
});
test('reanalysis preserves the users applicability decision for unchanged conditional documents', () => {
  const conditional = { ...item, condition: '해당 시', required: false };
  const previous = { text: '원문', items: [{ ...conditional, required: true, done: true }] };
  const result = applyNoticeAnalysis(previous, { ...analysis, items: [conditional] });
  assert.equal(result.items[0].required, true);
  assert.equal(result.items[0].done, true);
});
test('removed source requirements are replaced while manual entries survive', () => {
  const result = applyNoticeAnalysis({ text: '새 안내문', items: [{ ...item, id: 'old', title: '과거 서류' }] }, analysis);
  assert.equal(result.items.length, 1);
  assert.equal(result.items[0].title, '착수계');
});
test('manual entries cannot silently overflow the saved checklist', () => {
  const manual = Array.from({ length: 30 }, (_, i) => ({ ...item, id: String(i), title: `수동 ${i}`, evidence: '' }));
  assert.throws(() => applyNoticeAnalysis({ text: '원문', items: manual }, analysis), /30개/);
});
