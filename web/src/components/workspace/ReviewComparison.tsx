"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import type { ReviewRecord, ReviewSummary, SourceFile } from "@/lib/review-history";
import { reviewDate } from "@/lib/review-history";
import { Badge, Button, Card, ErrorText } from "@/components/ui";

type Comparison = { items: { index: number; title: string; category: string; unchanged: boolean;
  evidence: { before: string; before_name: string; before_page: number | null; after: string; after_name: string | null;
    status: "unchanged" | "changed" | "removed" | "unmatched" | "ambiguous"; truncated?: boolean }[] }[];
  source_map: Record<string, string>; unmatched_before: SourceFile[]; additional_after: SourceFile[]; notice: string; source_warning?: string };
const LABELS = { unchanged: "인용문 동일", changed: "원문 변경", removed: "인용 영역 삭제", unmatched: "파일 연결 필요", ambiguous: "대조 위치 확인 필요" };

export default function ReviewComparison({ base, before, history, draftBody, draftFiles, blocked }: {
  base: string; before: ReviewRecord; history: ReviewSummary[]; draftBody: object; draftFiles: SourceFile[]; blocked: boolean;
}) {
  const [target, setTarget] = useState("draft");
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [result, setResult] = useState<Comparison | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const files = target === "draft" ? draftFiles : history.find(r => String(r.id) === target)?.source_files || [];
  return <Card className="mt-5 space-y-4 p-5">
    <h2 className="font-semibold">수정 전후 비교 · 기준 검토 #{before.id}</h2>
    <p className="text-xs text-muted">이전 지적 조항이 수정본에서 어떻게 바뀌었는지 비교합니다. 왼쪽에 수정본을 올리면 AI를 다시 호출하지 않고 대조할 수 있습니다.</p>
    <ErrorText>{error}</ErrorText>
    <label className="block text-sm">비교할 수정본<select className="mt-1 block w-full rounded border border-line bg-white p-2" value={target} disabled={busy || blocked} onChange={e => { setTarget(e.target.value); setMapping({}); setResult(null); }}>
      <option value="draft">왼쪽에 선택·업로드한 현재 자료</option>
      {history.filter(r => r.id !== before.id && r.role === before.role).map(r => <option value={r.id} key={r.id}>검토 #{r.id} · {reviewDate(r.created_at)} · {r.source_files.map(f => f.name).join(", ")}</option>)}
    </select></label>
    <p className="text-xs text-muted">파일명이 바뀌었거나 별첨이 여러 개면 대응할 파일을 직접 지정하세요. 같은 이름은 자동 연결하며, 단일 파일끼리는 자동 대조합니다.</p>
    {before.source_files.map(file => <label className="block text-xs" key={file.key}>{file.name} → 수정본<select aria-label={`${file.name} 비교 파일`} className="mt-1 block w-full rounded border border-line bg-white p-2" value={mapping[file.key] || ""} disabled={busy || blocked} onChange={e => { const next = { ...mapping }; if (e.target.value) next[file.key] = e.target.value; else delete next[file.key]; setMapping(next); setResult(null); }}><option value="">자동 연결</option>{files.map(next => <option key={next.key} value={next.key}>{next.name}</option>)}</select></label>)}
    <Button disabled={busy || blocked || !files.length} loading={busy} onClick={async () => {
      setBusy(true); setError(""); setResult(null);
      try {
        const response = target === "draft"
          ? await api.post<Comparison>(`${base}/history/${before.id}/compare-draft`, { ...draftBody, source_map: mapping })
          : await api.post<Comparison>(`${base}/history/${before.id}/compare`, { after_id: Number(target), source_map: mapping });
        setResult(response); setMapping(response.source_map);
      } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
    }}>수정 전후 원문 비교</Button>
    {result && <div className="space-y-4">
      <p role="status" className="rounded bg-amber-50 p-3 text-xs text-amber-900">{result.notice}</p>
      {result.source_warning && <p className="text-xs text-amber-800">{result.source_warning}</p>}
      <p className="text-sm">인용문 유지 {result.items.filter(i => i.unchanged).length}건 · 변경 또는 확인 필요 {result.items.filter(i => !i.unchanged).length}건</p>
      {result.unmatched_before.length > 0 && <p className="text-xs text-amber-900">연결하지 못한 원본: {result.unmatched_before.map(f => f.name).join(", ")}. 파일을 지정하고 다시 비교하세요.</p>}
      {result.additional_after.length > 0 && <p className="text-xs text-amber-900">이번 조항 대조에 포함되지 않은 수정본 자료: {result.additional_after.map(f => f.name).join(", ")}</p>}
      {result.items.map(item => <article key={item.index} className="space-y-3 rounded border border-line p-4"><h3 className="text-sm font-semibold">{item.title}</h3>{item.evidence.map((e, n) => <div className="space-y-2" key={n}>
        <Badge tone={e.status === "unchanged" ? "gray" : "amber"}>{LABELS[e.status]}</Badge>
        <div className="grid gap-3 md:grid-cols-2"><div className="rounded bg-slate-50 p-3 text-xs"><strong>이전 · {e.before_name}{e.before_page ? ` · ${e.before_page}쪽` : ""}</strong><p className="mt-2 whitespace-pre-wrap break-words">{e.before}</p></div><div className="rounded bg-indigo-50 p-3 text-xs"><strong>수정본 · {e.after_name || "미연결"} · 원문 발췌</strong><p className="mt-2 whitespace-pre-wrap break-words">{e.after || (e.status === "removed" ? "대응하는 텍스트가 삭제되었습니다. 주변 조항을 확인하세요." : "대조할 위치를 확인하지 못했습니다.")}{e.truncated && "… (일부 표시, 수정본 원문 확인 필요)"}</p></div></div>
      </div>)}</article>)}
    </div>}
  </Card>;
}
