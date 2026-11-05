"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useUnsavedChanges } from "@/lib/useUnsavedChanges";
import { useWorkspaceDraft } from "@/lib/useWorkspaceDraft";
import type { CustomPlanLayout, CustomPlanSection, Doc, DocumentType } from "@/lib/types";
import { Badge, Button, ErrorText, Input, Textarea } from "@/components/ui";

type Transfer = { provider: string; ai_available: boolean; payload_preview: string; consent_digest: string };
type Proposal = { layout: CustomPlanLayout; mode: string; warning: string; matches: { id: number; name: string; reason: string; project_code: string }[] };
type BuilderDraft = { request: string; projectCode: string; layout: CustomPlanLayout | null; proposal: Proposal | null; documentType: DocumentType };
const EMPTY: BuilderDraft = { request: "", projectCode: "", layout: null, proposal: null, documentType: "work_plan" };

export default function CustomPlanBuilder({ contractId }: { contractId: number }) {
  const router = useRouter();
  const uid = useId();
  const draft = useWorkspaceDraft<BuilderDraft>(contractId, "builder", EMPTY);
  const { request, projectCode, layout, proposal, documentType } = draft.value;
  const setRequest = (request: string) => draft.setValue(previous => ({ ...previous, request }));
  const setProjectCode = (projectCode: string) => draft.setValue(previous => ({ ...previous, projectCode }));
  const setLayout = (layout: CustomPlanLayout | null) => draft.setValue(previous => ({ ...previous, layout }));
  const [useAi, setUseAi] = useState(false);
  const [transfer, setTransfer] = useState<Transfer | null>(null);
  const [consent, setConsent] = useState(false);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const markSaved = useUnsavedChanges(request.trim().length > 0 && draft.pending);

  const prepare = async () => {
    setBusy(true); setError(""); setConsent(false);
    try { setTransfer(await api.post<Transfer>(`/contracts/${contractId}/custom-plan/transmission`, { request, document_type: documentType })); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const propose = async () => {
    setBusy(true); setError("");
    try {
      const result = await api.post<Proposal>(`/contracts/${contractId}/custom-plan/propose`, {
        request, document_type: documentType, project_code: projectCode, use_ai: useAi, consent_digest: useAi && consent ? transfer?.consent_digest : "",
      });
      draft.setValue(previous => ({ ...previous, proposal: result, layout: result.layout })); setAck(false);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const edit = (next: CustomPlanLayout) => { setLayout(next); setAck(false); };
  const editSection = (index: number, change: Partial<CustomPlanSection>) => {
    if (layout) edit({ ...layout, sections: layout.sections.map((section, i) => i === index ? { ...section, ...change } : section) });
  };
  const move = (index: number, offset: number) => {
    if (!layout) return;
    const sections = [...layout.sections];
    [sections[index], sections[index + offset]] = [sections[index + offset], sections[index]];
    edit({ ...layout, sections });
  };
  const create = async () => {
    if (!layout) return;
    setBusy(true); setError("");
    try {
      const result = await api.post<{ document: Doc }>(`/contracts/${contractId}/custom-plan`, { request, layout, acknowledge_unofficial: ack });
      try { await draft.replace(EMPTY); } catch { /* The document already exists; navigate to it even if draft cleanup fails. */ }
      markSaved(); router.push(`/contracts/${contractId}/documents/${result.document.id}`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };

  return <div className="space-y-4">
    <div><Badge tone="indigo">맞춤 서류</Badge><h3 className="mt-2 font-semibold">맞춤 서류 초안 만들기</h3>
      <p className="mt-1 text-xs leading-relaxed text-muted">요청 → 구성 확인·수정 → 초안 작성 순서입니다. 담당자·일정·산출물 등 확인되지 않은 사실은 빈칸으로 남깁니다.</p></div>
    <ErrorText>{error}</ErrorText>
    <ErrorText>{draft.error}</ErrorText>
    <p role="status" className="text-xs text-muted">{draft.status} · 회사 자료는 암호화하여 서버에 저장합니다.</p>
    {!draft.ready ? <p className="text-sm">초안을 불러오는 중입니다.</p> : <>
    {!layout ? <>
      <label className="block text-sm">서류 종류<select aria-label="맞춤 서류 종류" className="mt-1 w-full rounded-lg border border-line p-2" value={documentType} disabled={busy} onChange={e => { draft.setValue(previous => ({ ...previous, documentType: e.target.value as DocumentType })); setTransfer(null); setConsent(false); }}>
        <option value="work_plan">과업수행계획서</option><option value="proposal">제안서</option><option value="report">보고서</option><option value="pledge">확약서</option>
      </select></label>
      <label htmlFor={`${uid}-request`} className="block text-sm font-medium">어떤 구성이 필요한가요?</label>
      <Textarea id={`${uid}-request`} rows={5} maxLength={2000} disabled={busy} value={request} placeholder="예: 참여인력표와 주간 추진 일정, 산출물 목록을 포함한 과업수행계획서를 만들어줘" onChange={e => { setRequest(e.target.value); setTransfer(null); setConsent(false); }} />
      <label htmlFor={`${uid}-code`} className="block text-xs text-muted">공고·사업번호 (지정 양식 확인용, 선택)</label>
      <Input id={`${uid}-code`} maxLength={80} value={projectCode} disabled={busy} onChange={e => setProjectCode(e.target.value)} />
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={useAi} disabled={busy} onChange={e => { setUseAi(e.target.checked); setConsent(false); }} className="mt-1" />외부 AI로 구성 제안 받기 (선택)</label>
      <p className="text-xs text-muted">선택하지 않으면 서버 내부의 공통 구성과 요청 키워드로 제안하며 외부로 전송하지 않습니다.</p>
      {useAi && <div className="space-y-3 rounded-lg border border-line bg-slate-50 p-3">
        <p className="text-xs text-muted">전송 대상은 아래에 표시되는 요청 문장과 공통 항목 목록입니다. 회사·계약정보·인감·타인의 문서는 추가하지 않습니다. 요청 문장에 적은 영업기밀은 마스킹되지 않을 수 있습니다.</p>
        <Button variant="secondary" size="sm" disabled={request.trim().length < 5 || busy} onClick={prepare}>전송할 내용 확인</Button>
        {transfer && <>
          {!transfer.ai_available && <p className="text-sm text-amber-700">현재 외부 AI가 연결되어 있지 않습니다. 선택을 해제하면 로컬 구성을 사용할 수 있습니다.</p>}
          <label htmlFor={`${uid}-payload`} className="block text-xs">{transfer.provider} 전송 내용</label>
          <Textarea id={`${uid}-payload`} readOnly rows={7} value={transfer.payload_preview} className="text-xs" />
          <label className="flex items-start gap-2 text-xs"><input type="checkbox" checked={consent} disabled={!transfer.ai_available || busy} onChange={e => setConsent(e.target.checked)} className="mt-0.5" />위 내용을 확인했으며, 이번 요청을 외부 AI에 전송하는 데 동의합니다.</label>
        </>}
      </div>}
      <Button loading={busy} disabled={request.trim().length < 5 || (useAi && (!transfer?.ai_available || !consent))} onClick={propose}>구성 제안 받기</Button>
    </> : <>
      <div className="flex flex-wrap items-center gap-2"><Badge>{proposal?.mode === "ai" ? "AI 구성 제안" : "로컬 구성 제안"}</Badge><Badge tone="amber">검토용 초안 · 지정 서식 아님</Badge></div>
      {proposal?.warning && <p role="status" className="text-xs text-amber-700">{proposal.warning}</p>}
      {proposal && proposal.matches.length > 0 && <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs">
        <p className="font-semibold">발주처에 맞는 등록 양식이 있습니다. 지정 양식을 먼저 확인하세요.</p>
        {proposal.matches.map(match => <Link key={match.id} href={`/templates/${match.id}`} target="_blank" rel="noopener noreferrer" className="mt-2 block text-primary underline">{match.name} · {match.reason} ↗</Link>)}
      </div>}
      <label htmlFor={`${uid}-title`} className="block text-sm font-medium">서류·양식 제목</label>
      <Input id={`${uid}-title`} value={layout.title} maxLength={100} disabled={busy} onChange={e => edit({ ...layout, title: e.target.value })} />
      <p className="text-xs text-muted">계약명·발주처·회사·기간·책임자 표가 함께 들어갑니다. 항목명, 순서, 본문/표 형식과 필수 여부를 확인하세요.</p>
      <ol className="space-y-3">
        {layout.sections.map((section, index) => <li key={section.key} className="space-y-2 rounded-lg border border-line p-3">
          <label htmlFor={`${uid}-${section.key}`} className="block text-xs font-medium">{index + 1}. 항목명</label>
          <Input id={`${uid}-${section.key}`} value={section.label} maxLength={60} disabled={busy} onChange={e => editSection(index, { label: e.target.value })} />
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <label>형식 <select aria-label={`${section.label} 형식`} value={section.kind} disabled={busy} className="rounded border border-line p-1" onChange={e => editSection(index, e.target.value === "table" ? { kind: "table", columns: ["항목", "내용"] } : { kind: "text", columns: [] })}><option value="text">본문</option><option value="table">표</option></select></label>
            <label><input type="checkbox" checked={section.required} disabled={busy} onChange={e => editSection(index, { required: e.target.checked })} /> 필수 입력</label>
            <Button variant="ghost" size="sm" aria-label={`${section.label} 위로`} disabled={busy || index === 0} onClick={() => move(index, -1)}>↑</Button>
            <Button variant="ghost" size="sm" aria-label={`${section.label} 아래로`} disabled={busy || index === layout.sections.length - 1} onClick={() => move(index, 1)}>↓</Button>
            <Button variant="ghost" size="sm" disabled={busy || ["work_summary", "description"].includes(section.key)} onClick={() => edit({ ...layout, sections: layout.sections.filter(item => item.key !== section.key) })}>제외</Button>
          </div>
          {section.kind === "table" && <><label htmlFor={`${uid}-${section.key}-columns`} className="block text-xs text-muted">열 이름을 |로 구분 (2~6개)</label><Input id={`${uid}-${section.key}-columns`} disabled={busy} value={section.columns.join(" | ")} onChange={e => editSection(index, { columns: e.target.value.split("|").map(value => value.trim()) })} /></>}
        </li>)}
      </ol>
      <Button variant="secondary" size="sm" disabled={busy || layout.sections.length >= 12} onClick={() => {
        const key = Array.from({ length: 99 }, (_, i) => `custom_${i + 1}`).find(key => !layout.sections.some(section => section.key === key));
        if (key) edit({ ...layout, sections: [...layout.sections, { key, label: "추가 항목", kind: "text", columns: [], required: true }] });
      }}>항목 추가</Button>
      <p className="text-xs text-muted">서비스 공통 구성만 참고합니다. 확정하면 내 양식으로 저장되어 다른 계약에서도 다시 사용할 수 있습니다. 본문은 확인된 정보와 검토용 공통 문구로 작성합니다.</p>
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={ack} disabled={busy} className="mt-1" onChange={e => setAck(e.target.checked)} />구성을 확인했으며, 발주처 지정 서식이 아닌 검토용 초안임을 이해했습니다.</label>
      <div className="flex flex-wrap gap-2"><Button variant="secondary" disabled={busy} onClick={() => { setLayout(null); setAck(false); }}>요청 다시 수정</Button><Button loading={busy} disabled={!ack || !layout.title.trim() || layout.sections.some(section => !section.label.trim())} onClick={create}>확정하고 초안 작성</Button></div>
    </>}</>}
  </div>;
}
