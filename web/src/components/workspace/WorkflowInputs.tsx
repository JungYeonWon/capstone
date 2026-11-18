"use client";
import { Button, Input, Textarea } from "@/components/ui";
import { WORKFLOW_MODES, type WorkflowFile, type WorkflowInput, type WorkflowMode } from "@/lib/ai-workflows";
import type { Doc } from "@/lib/types";

export default function WorkflowInputs({ mode, input, docs, busy, onChange, onUpload }: {
  mode: WorkflowMode; input: WorkflowInput; docs: Doc[]; busy: boolean;
  onChange: (input: WorkflowInput) => void; onUpload: (file: File) => void;
}) {
  const config = WORKFLOW_MODES[mode];
  const editFile = (index: number, change: Partial<WorkflowFile>) => onChange({ ...input, files: input.files.map((file, n) => n === index ? { ...file, ...change } : file) });
  return <fieldset disabled={busy} className="space-y-4">
    <label className="block text-sm">우리 쪽 역할<select className="mt-1 block w-full rounded border border-line p-2 text-sm" value={input.role} onChange={e => onChange({ ...input, role: e.target.value as WorkflowInput["role"] })}><option value="supplier">수행사</option><option value="client">발주처</option></select></label>
    <label className="block text-sm">{config.input}<Textarea rows={8} maxLength={20000} placeholder={config.placeholder} value={input.text} onChange={e => onChange({ ...input, text: e.target.value })} /><span className="text-xs text-muted">입력·참고 자료·답변 합계 32,000자까지 분석합니다.</span></label>
    <label className="flex gap-2 text-xs"><input type="checkbox" checked={input.include_contract} onChange={e => onChange({ ...input, include_contract: e.target.checked })} />등록된 계약명과 과업 내용을 참고 자료에 포함</label>
    <label className="block text-sm">참고할 계약 저장본<select className="mt-1 block w-full rounded border border-line p-2 text-sm" value={input.document_id ?? ""} onChange={e => onChange({ ...input, document_id: e.target.value ? Number(e.target.value) : null })}><option value="">선택 안 함</option>{docs.filter(d => d.template_kind === "custom" || d.template_kind === "uploaded").map(doc => <option key={doc.id} value={doc.id}>{doc.title}</option>)}</select></label>
    <label className="block text-sm">자료 파일 추가<Input type="file" disabled={busy || input.files.length >= 5} accept=".pdf,.hwp,.hwpx,.docx,.txt" onChange={e => { const file = e.target.files?.[0]; e.target.value = ""; if (file) onUpload(file); }} /><span className="text-xs text-muted">PDF·한글·Word·TXT, 파일당 3MB, 최대 5개. 이미지 스캔은 텍스트를 직접 입력하세요.</span></label>
    {input.files.map((file, index) => <section key={index} className="space-y-2 rounded border border-line p-3 text-xs">
      <p className="break-all font-medium">{file.name}</p>
      <label className="block">자료 용도<select className="ml-2 rounded border border-line p-1" value={file.kind} onChange={e => editFile(index, { kind: e.target.value as WorkflowFile["kind"] })}><option value="input">분석할 요청·요구사항·회의록</option><option value="reference">기존 계약·참고 자료</option></select></label>
      {file.warning && <p className="text-amber-800">{file.warning}</p>}
      <details><summary className="cursor-pointer">추출한 내용 확인</summary><pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words p-2">{file.parts.map(part => `${part.page ? `${part.page}쪽\n` : ""}${part.text}`).join("\n\n")}</pre></details>
      <Button size="sm" variant="ghost" onClick={() => onChange({ ...input, files: input.files.filter((_, n) => n !== index) })}>자료 제거</Button>
    </section>)}
    {mode === "change" && <p className="text-xs text-muted">기존 범위 판단을 위해 계약 개요·저장본·참고 파일 중 하나 이상을 선택하세요. 개요만으로 부족하면 계약서와 과업지시서를 함께 올리세요.</p>}
    {!!input.answers.length && <details className="rounded border border-line p-3"><summary className="cursor-pointer text-sm">기존 추가 답변 {input.answers.length}개</summary><div className="mt-3 space-y-3">{input.answers.map((answer, index) => <label key={index} className="block text-xs">{answer.question}<Textarea rows={2} maxLength={1500} value={answer.text} onChange={e => onChange({ ...input, answers: input.answers.map((a, n) => n === index ? { ...a, text: e.target.value } : a) })} /><Button size="sm" variant="ghost" onClick={() => onChange({ ...input, answers: input.answers.filter((_, n) => n !== index) })}>답변 삭제</Button></label>)}</div></details>}
  </fieldset>;
}
