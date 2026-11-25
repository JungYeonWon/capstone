"use client";
import { Badge, Button, Card, Textarea } from "@/components/ui";
import { REVIEW_STATUS, reviewDate, type ReviewRecord, type ReviewEdit, type ReviewStatus } from "@/lib/review-history";

export default function ReviewResultPanel({ record, edits, busy, onEdit, onSave, onDownload, onCopy, copyFallback }: {
  record: ReviewRecord | null; edits: Record<number, ReviewEdit>; busy: boolean;
  onEdit: (index: number, edit: ReviewEdit) => void; onSave: (index: number) => void;
  onDownload: () => void; onCopy: (all: boolean) => void; copyFallback: string;
}) {
  return <Card className="space-y-4 self-start p-5">
    <h2 className="font-semibold">{record ? `저장된 검토 #${record.id}` : "검토 결과"}</h2>
    {!record ? <p className="text-sm text-muted">AI 검토를 실행하면 결과가 암호화 저장됩니다. 위 검토 이력에서 이전 결과를 다시 열 수 있습니다.</p> : <>
      <p className="text-xs text-muted">{reviewDate(record.created_at)} · {record.role === "supplier" ? "수행사" : "발주처"} 입장 · 확인할 조항 {record.findings.length}건</p>
      <p className="break-words text-xs text-muted">검토 자료: {record.source_files.map(f => f.name).join(", ")}</p>
      <p className="text-xs text-muted">검토 당시 자료에 대한 결과입니다. 왼쪽의 새 입력과 구분해서 확인하세요. 처리 완료 표시는 사용자의 기록이며 상대방 합의나 인감 승인을 대신하지 않습니다.</p>
      {(record.document_state === "changed" || record.document_state === "deleted") && <p role="status" className="rounded bg-amber-50 p-3 text-xs text-amber-900">{record.document_state === "changed" ? "검토 이후 저장 문서가 변경됐습니다. 이 결과는 이전 문서 기준입니다." : "검토 대상 저장 문서가 삭제됐습니다. 당시 검토 이력만 표시합니다."}</p>}
      {record.warning && <p className="text-xs text-amber-800">{record.warning}</p>}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" disabled={busy || !record.findings.length || !!Object.keys(edits).length} onClick={() => onCopy(false)}>미완료 질문 복사</Button>
        <Button size="sm" variant="secondary" disabled={busy || !record.findings.length || !!Object.keys(edits).length} onClick={() => onCopy(true)}>전체 질문 복사</Button>
        <Button size="sm" variant="secondary" disabled={busy || !!Object.keys(edits).length} onClick={onDownload}>검토 보고서 PDF</Button>
      </div>
      {!!Object.keys(edits).length && <p role="status" className="text-xs text-amber-800">미저장 상태·메모가 있습니다. 항목별로 저장한 뒤 복사·다운로드하세요.</p>}
      {copyFallback && <label className="block text-xs">질문 모음 (직접 선택해 복사 가능)<Textarea aria-label="질문 모음" rows={6} value={copyFallback} readOnly /></label>}
      {record.excluded > 0 && <p className="text-xs text-amber-800">근거 또는 형식을 확인하지 못한 AI 결과 {record.excluded}건을 제외했습니다.</p>}
      {!!record.deduplicated && <p className="text-xs text-muted">같은 근거의 중복 지적 {record.deduplicated}건을 묶었습니다.</p>}
      {(record.review_version ?? 1) >= 2 && <p className="text-xs text-muted">AI 검토 후 원문 표현을 규칙으로 추가 점검했습니다. ‘규칙 기반 확인 후보’는 주변 예외·상한과 의무 주체를 함께 확인하세요. 표시되지 않은 조건이 안전하다는 뜻은 아닙니다.</p>}
      {!!record.supplement_omitted && <p role="status" className="text-xs text-amber-800">표시 한도로 규칙 후보 {record.supplement_omitted}건을 생략했습니다. 자료를 나누어 다시 검토하세요.</p>}
      {!record.findings.length && <p className="text-sm text-muted">표시할 검토 항목이 없습니다. 계약에 문제가 없다는 판정을 의미하지 않습니다.</p>}
      {record.findings.map((finding, index) => {
        const edit = edits[index] || { status: finding.status, note: finding.note };
        return <article key={index} className="space-y-3 rounded-lg border border-line p-4">
          <Badge tone="amber">{finding.category}</Badge><h3 className="font-semibold">{finding.title}</h3>
          {finding.priority && <p className="text-xs font-medium">확인 우선순위: {{ high: "높음", medium: "보통", low: "참고·확인" }[finding.priority]}{finding.assessment === "uncertain" ? " · 판단 보류, 적용 관계·자료 확인 필요" : ""}</p>}
          {finding.method === "rule" && <p className="text-xs text-amber-800">규칙 기반 확인 후보 · 원문과 주변 조건 확인 필요</p>}
          {finding.evidence.map((evidence, n) => <blockquote key={n} className="break-words rounded-lg bg-slate-50 p-3 text-sm"><p className="mb-1 text-xs font-medium text-muted">{evidence.name}{evidence.page ? ` · ${evidence.page}쪽` : ""}</p>{evidence.quote}</blockquote>)}
          {finding.context_note && <p className="text-sm text-indigo-900">함께 확인할 조건 · {finding.context_note}</p>}
          {finding.context_evidence?.map((evidence, n) => <blockquote key={`context-${n}`} className="break-words rounded-lg bg-indigo-50 p-3 text-sm"><p className="mb-1 text-xs font-medium">제한·예외 근거 · {evidence.name}{evidence.page ? ` · ${evidence.page}쪽` : ""}</p>{evidence.quote}</blockquote>)}
          <p className="text-sm">{finding.impact}</p><p className="text-sm"><strong>확인할 질문</strong> · {finding.question}</p>
          <label className="block text-xs">처리 상태<select aria-label={`항목 ${index + 1} 처리 상태`} className="mt-1 block w-full rounded border border-line bg-white p-2 text-sm" value={edit.status} disabled={busy} onChange={e => onEdit(index, { ...edit, status: e.target.value as ReviewStatus })}>{Object.entries(REVIEW_STATUS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="block text-xs">준비·협의 메모<Textarea aria-label={`항목 ${index + 1} 메모`} rows={3} maxLength={1000} value={edit.note} disabled={busy} onChange={e => onEdit(index, { ...edit, note: e.target.value })} /></label>
          <Button size="sm" variant="secondary" disabled={busy || !edits[index]} onClick={() => onSave(index)}>상태·메모 저장</Button>
        </article>;
      })}
      {!!record.addressed?.length && <details className="rounded-lg border border-line p-3"><summary className="cursor-pointer text-sm font-medium">제한·예외 확인 메모 {record.addressed.length}건</summary><p className="mt-2 text-xs text-muted">원래 의무와 제한 조건을 함께 검토한 메모입니다. 안전하거나 해결됐다는 판정은 아닙니다.</p>
        {record.addressed.map((item, index) => <article key={index} className="mt-3 space-y-2 text-sm"><h3 className="font-medium">{item.category}</h3><p>{item.reason}</p>{[item.original, item.qualification].map((e, n) => <blockquote key={n} className="rounded bg-slate-50 p-3"><p className="text-xs text-muted">{e.name}{e.page ? ` · ${e.page}쪽` : ""}</p>{e.quote}</blockquote>)}</article>)}</details>}
    </>}
  </Card>;
}
