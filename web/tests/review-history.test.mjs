import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
const code = ts.transpileModule(fs.readFileSync(new URL('../src/lib/review-history.ts', import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { questionText, reviewDate } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
test('question copy keeps unanswered items and can explicitly include completed questions', () => {
  const record = { findings: [{ status: 'pending', category: '검수', title: '검수 기한', question: '기한은 며칠인가요?' },
    { status: 'resolved', category: '배상', title: '배상 범위', question: '배상 한도는 얼마인가요?' }] };
  assert.match(questionText(record, false), /기한은 며칠/);
  assert.doesNotMatch(questionText(record, false), /배상 한도/);
  assert.match(questionText(record, true), /2\. \[배상\]/);
  assert.equal(questionText({ findings: [] }, true), '');
});
test('review timestamps are displayed in Korean time regardless of host timezone', () => {
  assert.equal(reviewDate('2026-11-18T01:00:00'), reviewDate('2026-11-18T01:00:00Z'));
  assert.match(reviewDate('2026-11-18T01:00:00Z'), /10:00:00/);
});
