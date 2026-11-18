"use client";
import { Button, Input } from "@/components/ui";
import { estimateAmounts, money, type EstimateLine } from "@/lib/ai-workflows";

export default function WorkflowEstimate({ lines, onChange, disabled }: { lines: EstimateLine[]; onChange: (lines: EstimateLine[]) => void; disabled: boolean }) {
  const calculation = estimateAmounts(lines);
  const edit = (index: number, values: Partial<EstimateLine>) => onChange(lines.map((line, n) => n === index ? { ...line, ...values } : line));
  return <section className="space-y-3 rounded-lg border border-line p-4">
    <h3 className="font-semibold">직접 입력하는 견적 계산</h3>
    <p className="text-xs text-muted">AI는 작업 항목과 산정 전제를 제안합니다. 단가·수량은 직접 정하며, 합계는 부가세·할인 미적용 금액입니다. 소수 둘째 자리까지 입력할 수 있습니다.</p>
    {lines.map((line, index) => <fieldset key={index} disabled={disabled} className="space-y-2 rounded border border-line p-3">
      <legend className="px-1 text-xs">견적 항목 {index + 1}</legend>
      <label className="block text-xs">작업명<Input value={line.label} maxLength={100} onChange={e => edit(index, { label: e.target.value })} /></label>
      <div className="grid gap-2 sm:grid-cols-3">
        <label className="text-xs">수량 (최대 10,000)<Input inputMode="decimal" value={line.quantity} onChange={e => edit(index, { quantity: e.target.value })} /></label>
        <label className="text-xs">단위<Input value={line.unit} maxLength={20} onChange={e => edit(index, { unit: e.target.value })} /></label>
        <label className="text-xs">단가 (원, 최대 1억)<Input inputMode="decimal" value={line.unit_price} onChange={e => edit(index, { unit_price: e.target.value })} /></label>
      </div>
      <div className="flex items-center justify-between gap-2"><p className="text-sm">{calculation.amounts[index] === null ? "작업명·단위·단가·수량을 확인하세요." : money(calculation.amounts[index]!)}</p>
        <Button size="sm" variant="ghost" onClick={() => onChange(lines.filter((_, n) => n !== index))}>항목 삭제</Button></div>
    </fieldset>)}
    <Button size="sm" variant="secondary" disabled={disabled || lines.length >= 30} onClick={() => onChange([...lines, { label: "", quantity: "1", unit: "건", unit_price: "" }])}>견적 항목 추가</Button>
    <p aria-live="polite" className="font-semibold">합계: {calculation.total === null ? "입력 확인 필요" : money(calculation.total)}</p>
  </section>;
}
