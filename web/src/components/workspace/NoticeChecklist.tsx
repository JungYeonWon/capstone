"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspaceDraft } from "@/lib/useWorkspaceDraft";
import { useUnsavedChanges } from "@/lib/useUnsavedChanges";
import type { Doc, Template } from "@/lib/types";
import { Badge, Button, ErrorText, Input, Textarea } from "@/components/ui";

type Item = { id: string; title: string; evidence: string; required: boolean; done: boolean; document_id: number | null; note: string };
type State = { text: string; items: Item[] };
type Transfer = { payload_preview: string; consent_digest: string; ai_available: boolean };

export default function NoticeChecklist({ contractId, active }: { contractId: number; active: boolean }) {
  const draft = useWorkspaceDraft<State>(contractId, "notice", { text: "", items: [] });
  const [docs, setDocs] = useState<Doc[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [useAi, setUseAi] = useState(false);
  const [transfer, setTransfer] = useState<Transfer | null>(null);
  const [consent, setConsent] = useState(false);
  const [confirmed, setConfirmed] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const { text, items } = draft.value;
  useUnsavedChanges(draft.pending);
  useEffect(() => {
    if (!active) return;
    let alive = true;
    Promise.all([api.get<Doc[]>(`/contracts/${contractId}/documents`), api.get<Template[]>("/templates")]).then(([d,t]) => { if (alive) { setDocs(d); setTemplates(t); } }).catch(e => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [contractId, active]);
  const act = async (fn: () => Promise<void>) => {
    setBusy(true); setError("");
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const edit = (id: string, changes: Partial<Item>) => draft.setValue(previous => ({ ...previous, items: previous.items.map(item => item.id === id ? { ...item, ...changes } : item) }));
  const candidate = (item: Item) => templates.find(t => t.status === "ready" && (t.name.replaceAll(" ", "").includes(item.title.replaceAll(" ", "")) || t.aliases.some(alias => alias.replaceAll(" ", "") === item.title.replaceAll(" ", ""))));
  return <div className="space-y-4">
    <h3 className="font-semibold">제출 안내문 → 준비 체크리스트</h3>
    <p className="text-xs text-muted">안내문 내용을 붙여넣거나 텍스트 PDF(3MB·20페이지 이하)를 가져오세요. 원본은 저장하지 않으며, 스캔 이미지의 OCR은 지원하지 않습니다.</p>
    <ErrorText>{error || draft.error}</ErrorText>
    <p role="status" className="text-xs text-muted">{draft.status}</p>
    {draft.ready && <>
      <label className="block text-sm">안내문 PDF<input aria-label="안내문 PDF 선택" type="file" accept="application/pdf,.pdf" className="mt-1 block w-full text-xs" disabled={busy} onChange={e => {
        const file = e.target.files?.[0]; if (!file) return;
        void act(async () => { const result = await api.upload<{ text: string }>(`/contracts/${contractId}/notice/extract`, file); draft.setValue(previous => ({ ...previous, text: result.text })); setConsent(false); setTransfer(null); });
        e.target.value = "";
      }} /></label>
      <Textarea aria-label="제출 안내문 원문" maxLength={20000} rows={7} value={text} disabled={busy} onChange={e => { draft.setValue(previous => ({ ...previous, text: e.target.value })); setConsent(false); setTransfer(null); }} />
      <label className="flex gap-2 text-sm"><input type="checkbox" checked={useAi} disabled={busy} onChange={e => { setUseAi(e.target.checked); setConsent(false); }} />외부 AI로 서류 목록 보완 (선택)</label>
      {useAi && <div className="space-y-2 rounded border border-line p-3"><Button variant="secondary" size="sm" disabled={busy || text.trim().length < 5} onClick={() => act(async () => { setTransfer(await api.post<Transfer>(`/contracts/${contractId}/notice/preview`, { text })); setConfirmed(text); setConsent(false); })}>전송 내용 확인</Button>
        {transfer && confirmed === text && <><Textarea aria-label="안내문 AI 전송 내용" rows={6} value={transfer.payload_preview} readOnly /><label className="flex gap-2 text-xs"><input type="checkbox" checked={consent} disabled={busy || !transfer.ai_available} onChange={e => setConsent(e.target.checked)} />원문에 영업기밀이 남아 있는지 확인했으며 이번 전송에 동의합니다.</label>{!transfer.ai_available && <p className="text-xs text-amber-800">외부 AI 미연결 · 로컬 분석은 사용 가능</p>}</>}
      </div>}
      <Button loading={busy} disabled={text.trim().length < 5 || (useAi && (!consent || !transfer?.ai_available || confirmed !== text))} onClick={() => act(async () => {
        const result = await api.post<{ items: Item[]; warning: string; notice: string }>(`/contracts/${contractId}/notice/analyze`, { text, use_ai: useAi, consent_digest: useAi ? transfer?.consent_digest : "" });
        // Keep existing manual state/unknown attachments; reanalysis never silently deletes work.
        const merged = [...items]; for (const item of result.items) if (!merged.some(old => old.id === item.id || old.title === item.title)) merged.push(item);
        if (merged.length > 30) throw new Error("기존 항목과 합쳐 30개를 초과합니다. 불필요한 항목을 먼저 제외하세요.");
        await draft.replace({ text, items: merged }); setMessage(result.warning || result.notice);
      })}>서류 목록 분석·추가</Button>
      {message && <p role="status" className="text-xs text-amber-800">{message}</p>}
      <div className="flex flex-wrap items-center gap-2"><Badge>{items.filter(i => i.done).length}/{items.length} 준비 확인</Badge><Button size="sm" variant="secondary" disabled={busy || items.length >= 30} onClick={() => draft.setValue(previous => ({ ...previous, items: [...previous.items, { id: `n_${crypto.randomUUID().replaceAll("-", "").slice(0,16)}`, title: "추가 제출서류", evidence: "", required: true, done: false, document_id: null, note: "" }] }))}>직접 항목 추가</Button></div>
      <ol className="space-y-3">{items.map(item => {
        const matched = candidate(item);
        return <li key={item.id} className="space-y-2 rounded border border-line p-3">
          <Input aria-label="제출서류 이름" value={item.title} maxLength={100} disabled={busy} onChange={e => edit(item.id, { title: e.target.value })} />
          <p className="whitespace-pre-wrap text-xs text-muted">원문 근거: {item.evidence || "사용자가 직접 추가함"}</p>
          <label className="mr-3 text-xs"><input type="checkbox" checked={item.required} disabled={busy} onChange={e => edit(item.id, { required: e.target.checked })} /> 필수</label>
          <label className="text-xs"><input type="checkbox" checked={item.done} disabled={busy} onChange={e => edit(item.id, { done: e.target.checked })} /> 준비 확인</label>
          <label className="block text-xs">연결할 작성 서류<select aria-label={`${item.title} 연결 서류`} value={item.document_id ?? ""} disabled={busy} className="mt-1 w-full rounded border border-line p-1" onChange={e => edit(item.id, { document_id: e.target.value ? Number(e.target.value) : null })}><option value="">외부 첨부·수동 준비</option>{docs.map(doc => <option value={doc.id} key={doc.id}>{doc.title}</option>)}</select></label>
          <Input aria-label={`${item.title} 준비 메모`} value={item.note} maxLength={500} placeholder="제출기한·조건·준비 메모 (원문 확인 후 입력)" disabled={busy} onChange={e => edit(item.id, { note: e.target.value })} />
          {matched && <Link href={`/templates/${matched.id}`} target="_blank" rel="noopener noreferrer" className="block text-xs text-primary underline">등록된 관련 양식 보기: {matched.name}</Link>}
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => { if (confirm("이 항목을 체크리스트에서 제외할까요?")) draft.setValue(previous => ({ ...previous, items: previous.items.filter(i => i.id !== item.id) })); }}>항목 제외</Button>
        </li>;
      })}</ol>
      <Button size="sm" variant="secondary" disabled={busy} onClick={() => act(() => draft.saveNow())}>체크리스트 지금 저장</Button>
      <p className="text-xs text-muted">필수 미완료 항목은 계약의 제출 전 점검 결과에도 표시됩니다. 준비 표시는 제출 완료나 첨부 파일 검증을 의미하지 않습니다.</p>
    </>}
  </div>;
}
