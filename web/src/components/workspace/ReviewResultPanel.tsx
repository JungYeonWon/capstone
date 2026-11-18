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
      {!record.findings.length && <p className="text-sm text-muted">표시할 검토 항목이 없습니다. 계약에 문제가 없다는 판정을 의미하지 않습니다.</p>}
      {record.findings.map((finding, index) => {
        const edit = edits[index] || { status: finding.status, note: finding.note };
        return <article key={index} className="space-y-3 rounded-lg border border-line p-4">
          <Badge tone="amber">{finding.category}</Badge><h3 className="font-semibold">{finding.title}</h3>
          {finding.evidence.map((evidence, n) => <blockquote key={n} className="break-words rounded-lg bg-slate-50 p-3 text-sm"><p className="mb-1 text-xs font-medium text-muted">{evidence.name}{evidence.page ? ` · ${evidence.page}쪽` : ""}</p>{evidence.quote}</blockquote>)}
          <p className="text-sm">{finding.impact}</p><p className="text-sm"><strong>확인할 질문</strong> · {finding.question}</p>
          <label className="block text-xs">처리 상태<select aria-label={`항목 ${index + 1} 처리 상태`} className="mt-1 block w-full rounded border border-line bg-white p-2 text-sm" value={edit.status} disabled={busy} onChange={e => onEdit(index, { ...edit, status: e.target.value as ReviewStatus })}>{Object.entries(REVIEW_STATUS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="block text-xs">준비·협의 메모<Textarea aria-label={`항목 ${index + 1} 메모`} rows={3} maxLength={1000} value={edit.note} disabled={busy} onChange={e => onEdit(index, { ...edit, note: e.target.value })} /></label>
          <Button size="sm" variant="secondary" disabled={busy || !edits[index]} onClick={() => onSave(index)}>상태·메모 저장</Button>
        </article>;
      })}
    </>}
  </Card>;
}
