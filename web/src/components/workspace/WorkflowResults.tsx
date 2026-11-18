"use client";
import Link from "next/link";
import { useState } from "react";
import { Badge, Button, Card, Input, Textarea } from "@/components/ui";
import { DRAFT_LABELS, ITEM_LABELS, draftText, type WorkflowDraft, type WorkflowInput, type WorkflowOutput } from "@/lib/ai-workflows";

export default function WorkflowResults({ output, input, stale, busy, onAnswer, onDraft, onCreate, created, estimateReady }: {
  output: WorkflowOutput; input: WorkflowInput; stale: boolean; busy: boolean;
  onAnswer: (question: string, text: string) => void;
  onDraft: (index: number, draft: WorkflowDraft) => void;
  onCreate: (index: number) => void; created: Record<number, string>; estimateReady: boolean;
}) {
  const [approved, setApproved] = useState<Record<number, boolean>>({});
  const [fallback, setFallback] = useState("");
  const [copied, setCopied] = useState("");
  const copy = async (draft: WorkflowDraft) => {
    setCopied(""); setFallback("");
    try { await navigator.clipboard.writeText(draftText(draft)); setCopied("초안을 복사했습니다."); }
    catch { setFallback(draftText(draft)); }
  };
  const edit = (index: number, draft: WorkflowDraft) => { setApproved({ ...approved, [index]: false }); onDraft(index, draft); };
  return <div className="space-y-5">
    <Card className="space-y-4 p-5">
      <h2 className="font-semibold">AI 분석 결과</h2>
      {stale && <p role="status" className="rounded bg-amber-50 p-3 text-sm text-amber-900">입력 또는 답변이 바뀌었습니다. 아래는 이전 자료의 결과입니다. 전송 내용을 다시 확인하고 재분석하면 서류 저장을 진행할 수 있습니다.</p>}
      <p className="whitespace-pre-wrap text-sm">{output.result.summary}</p>
      {output.warning && <p className="text-xs text-amber-800">{output.warning}</p>}
      <p className="text-xs text-muted">합의·범위 판단과 문구는 AI의 검토 후보입니다. 원문을 확인하고 초안을 수정하세요. 계약 변경이나 상대방 동의가 자동으로 확정되지는 않습니다.</p>
      {!output.result.items.length && <p className="text-sm text-muted">분류된 항목이 없습니다. 요약과 확인 질문을 검토하세요.</p>}
      {output.result.items.map((item, index) => <article key={index} className="space-y-2 rounded-lg border border-line p-4">
        <div className="flex flex-wrap gap-2"><Badge tone="indigo">{ITEM_LABELS[item.category] ?? item.category}</Badge><Badge tone={item.basis === "proposal" ? "amber" : "gray"}>{item.basis === "proposal" ? "AI 제안" : "원문 기반 후보"}</Badge></div>
        <h3 className="font-medium">{item.title}</h3><p className="whitespace-pre-wrap text-sm">{item.detail}</p>
        {item.category === "task" && <p className="text-sm">담당: {item.owner || "확인 필요"} · 기한: {item.due || "확인 필요"}</p>}
        {item.evidence.map((citation, n) => {
          const source = output.sources.find(s => s.source_id === citation.source_id);
          return <blockquote key={n} className="rounded bg-slate-50 p-3 text-sm"><p className="mb-1 text-xs text-muted">{source?.name}{source?.page ? ` · ${source.page}쪽` : ""}</p>{citation.quote}</blockquote>;
        })}
      </article>)}
    </Card>
    {!!output.result.questions.length && <Card className="space-y-4 p-5">
      <h2 className="font-semibold">AI가 확인할 질문</h2><p className="text-xs text-muted">아는 내용을 답하고 왼쪽에서 다시 분석하세요. 기존 답변도 함께 전달됩니다. 모르는 조건은 비워두세요.</p>
      {output.result.questions.map(({ question, reason }) => <label key={question} className="block text-sm">{question}<span className="mt-1 block text-xs text-muted">{reason}</span>
        <Textarea rows={2} maxLength={1500} disabled={busy || (input.answers.length >= 12 && !input.answers.some(a => a.question === question))}
          value={input.answers.find(a => a.question === question)?.text ?? ""} onChange={e => onAnswer(question, e.target.value)} /></label>)}
      {input.answers.length >= 12 && <p className="text-xs text-amber-800">답변은 최대 12개입니다. 왼쪽의 기존 답변에서 불필요한 항목을 삭제할 수 있습니다.</p>}
    </Card>}
    <Card className="space-y-4 p-5">
      <h2 className="font-semibold">후속 서류 초안</h2><p className="text-xs text-muted">문구를 직접 수정한 뒤 서류로 저장하세요. 저장하면 계약의 제출 서류 목록에 추가되며 기존 편집기에서 미리보기와 다운로드가 가능합니다.</p>
      {copied && <p role="status" className="text-sm text-primary">{copied}</p>}
      {fallback && <label className="block text-xs">직접 선택하여 복사<Textarea rows={7} readOnly value={fallback} /></label>}
      {output.result.drafts.map((draft, index) => <details key={draft.kind} className="rounded-lg border border-line p-4" open={index === 0}>
        <summary className="cursor-pointer font-medium">{DRAFT_LABELS[draft.kind] ?? draft.kind} · {draft.title}</summary>
        <fieldset disabled={busy || stale} className="mt-4 space-y-3">
          <label className="block text-xs">서류 제목<Input value={draft.title} maxLength={100} onChange={e => edit(index, { ...draft, title: e.target.value })} /></label>
          {draft.sections.map((section, n) => <div key={n} className="space-y-1">
            <label className="block text-xs">항목 {n + 1} 제목<Input value={section.label} maxLength={60} onChange={e => edit(index, { ...draft, sections: draft.sections.map((s, i) => i === n ? { ...s, label: e.target.value } : s) })} /></label>
            <label className="block text-xs">항목 {n + 1} 본문<Textarea rows={4} value={section.text} maxLength={5000} onChange={e => edit(index, { ...draft, sections: draft.sections.map((s, i) => i === n ? { ...s, text: e.target.value } : s) })} /></label>
          </div>)}
          {draft.kind === "estimate" && <p className="text-xs text-muted">별도 견적 계산에 입력한 항목과 합계가 문서에 추가됩니다. 초안 복사에는 계산표가 포함되지 않습니다.</p>}
          <label className="flex gap-2 text-xs"><input type="checkbox" checked={approved[index] ?? false} onChange={e => setApproved({ ...approved, [index]: e.target.checked })} />미확정 조건과 문구를 확인했으며, 검토용 초안으로 저장합니다.</label>
          <div className="flex flex-wrap gap-2"><Button size="sm" variant="secondary" disabled={!draft.title.trim() || draft.sections.some(s => !s.label.trim()) || !approved[index] || (draft.kind === "estimate" && !estimateReady) || !!created[index]} onClick={() => onCreate(index)}>서류로 저장</Button>
            <Button size="sm" variant="ghost" onClick={() => copy(draft)}>초안 복사</Button></div>
        </fieldset>
        {created[index] && <Link className="mt-3 inline-block text-sm font-medium text-primary underline" href={created[index]}>저장한 서류 열기 →</Link>}
      </details>)}
    </Card>
  </div>;
}
