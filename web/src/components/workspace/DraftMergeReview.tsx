"use client";
import { Badge, Button, Card } from "@/components/ui";
import { DRAFT_LABELS, type DraftChange } from "@/lib/ai-workflows";

function content(change: DraftChange, incoming: boolean) {
  if (change.type === "title") return incoming ? change.after_title : change.before_title;
  if (change.type === "add_document" || change.type === "remove_document") {
    if ((change.type === "add_document") !== incoming) return "이 초안 없음";
    return `${change.document?.title}\n${change.document?.sections.map(s => `${s.label}\n${s.text}`).join("\n\n")}`;
  }
  const section = incoming ? change.after : change.before;
  return section ? `${section.label}\n${section.text}` : incoming ? "이번 제안에서 제외" : "새 항목";
}

export default function DraftMergeReview({ changes, busy, onResolve }: { changes: DraftChange[]; busy: boolean; onResolve: (id: string, accept: boolean) => void }) {
  if (!changes.length) return null;
  return <Card className="space-y-4 border-indigo-200 p-5">
    <h2 className="font-semibold">재분석 변경 제안 · {changes.length}개</h2>
    <p role="status" className="text-sm text-muted">기존 초안은 유지했습니다. 항목별로 비교한 뒤 새 제안을 반영하거나 기존 내용을 유지하세요. 선택이 끝나야 해당 초안을 편집·서류 저장하거나 다시 분석할 수 있습니다. 견적 입력은 그대로 유지됩니다.</p>
    {changes.map(change => <details key={change.id} className="rounded-lg border border-line p-3">
      <summary className="cursor-pointer text-sm font-medium">{DRAFT_LABELS[change.kind] ?? change.kind} · {change.type === "title" ? "서류 제목" : change.before?.label || change.after?.label || "서류 구성"}
        {change.protected && <span className="ml-2"><Badge tone="amber">사용자 수정·유지 문구 보호</Badge></span>}</summary>
      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <div className="rounded bg-slate-50 p-3"><h3 className="mb-2 text-xs font-semibold">기존 내용</h3><p className="whitespace-pre-wrap break-words text-sm">{content(change, false)}</p></div>
        <div className="rounded bg-indigo-50 p-3"><h3 className="mb-2 text-xs font-semibold">새 AI 제안</h3><p className="whitespace-pre-wrap break-words text-sm">{content(change, true)}</p></div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2"><Button size="sm" disabled={busy} onClick={() => onResolve(change.id, true)}>{change.type.startsWith("remove_") ? "삭제 제안 반영" : "새 제안 반영"}</Button>
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => onResolve(change.id, false)}>{change.type.startsWith("add_") ? "추가하지 않기" : "기존 내용 유지"}</Button></div>
    </details>)}
  </Card>;
}
