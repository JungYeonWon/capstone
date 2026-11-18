import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
const code = ts.transpileModule(fs.readFileSync(new URL('../src/lib/ai-workflows.ts', import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText;
const { estimateAmounts, money, draftText, emptyWorkflow } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);

test('estimate uses exact decimal half-up rounding matching the server', () => {
  const lines = [{ label: '기능 개발', quantity: '1.25', unit: '일', unit_price: '123.45' }, { label: '점검', quantity: '0.5', unit: '일', unit_price: '0.01' }];
  assert.deepEqual(estimateAmounts(lines), { amounts: [15431n, 1n], total: 15432n });
  assert.equal(money(15432n), '154.32원');
});
test('incomplete, negative, overflowing and malformed quotation rows cannot become a valid total', () => {
  const row = { label: '개발', quantity: '1', unit: '일', unit_price: '100' };
  for (const patch of [{ quantity: '0' }, { quantity: '-1' }, { quantity: '10001' }, { unit_price: '100000001' }, { unit_price: 'NaN' }, { unit_price: '1.234' }, { unit_price: '' }, { label: '' }, { unit: '' }]) {
    assert.equal(estimateAmounts([{ ...row, ...patch }]).total, null);
  }
});
test('high-value rows remain precise without floating point errors', () => {
  const rows = Array.from({ length: 30 }, () => ({ label: '개발', quantity: '10000', unit: '건', unit_price: '100000000' }));
  assert.equal(estimateAmounts(rows).total, 3000000000000000n);
});
test('workflows have independent input state and copied drafts remain clearly labelled', () => {
  const a = emptyWorkflow(), b = emptyWorkflow();
  a.input.answers.push({ question: '범위?', text: '예약' });
  assert.equal(b.input.answers.length, 0);
  assert.match(draftText({ title: '회의 확인', sections: [{ label: '미결', text: '비용은 협의 필요' }] }), /^\[검토용 초안\]/);
});
