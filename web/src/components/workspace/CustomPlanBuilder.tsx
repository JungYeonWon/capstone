"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useUnsavedChanges } from "@/lib/useUnsavedChanges";
import { useWorkspaceDraft } from "@/lib/useWorkspaceDraft";
import type { CustomPlanLayout, CustomPlanSection, Doc } from "@/lib/types";
import { Badge, Button, ErrorText, Input, Textarea } from "@/components/ui";
import LayoutReviewDialog from "./LayoutReviewDialog";

type Transfer = { provider: string; ai_available: boolean; payload_preview: string; consent_digest: string };
type Proposal = { layout: CustomPlanLayout; mode: string; warning: string; matches: { id: number; name: string; reason: string; project_code: string }[] };
type BuilderDraft = { request: string; title?: string; purpose?: string; projectCode: string; layout: CustomPlanLayout | null; proposal: Proposal | null };
const EMPTY: BuilderDraft = { request: "", title: "", purpose: "", projectCode: "", layout: null, proposal: null };

export default function CustomPlanBuilder({ contractId }: { contractId: number }) {
  const router = useRouter();
  const uid = useId();
  const draft = useWorkspaceDraft<BuilderDraft>(contractId, "builder", EMPTY);
  const { request, projectCode, layout, proposal, title = "", purpose = "" } = draft.value;
  const canPropose = Boolean(title.trim() && purpose.trim() && request.trim().length >= 5);
  const setRequest = (request: string) => draft.setValue(previous => ({ ...previous, request }));
  const setProjectCode = (projectCode: string) => draft.setValue(previous => ({ ...previous, projectCode }));
  const setLayout = (layout: CustomPlanLayout | null) => draft.setValue(previous => ({ ...previous, layout }));
  const [useAi, setUseAi] = useState(true);
  const [transfer, setTransfer] = useState<Transfer | null>(null);
  const [consent, setConsent] = useState(false);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const markSaved = useUnsavedChanges(request.trim().length > 0 && draft.pending);

  const prepare = async () => {
    setBusy(true); setError(""); setConsent(false);
    try { setTransfer(await api.post<Transfer>(`/contracts/${contractId}/custom-plan/transmission`, { request, title, purpose, document_type: "free" })); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const propose = async () => {
    setBusy(true); setError("");
    try {
      const result = await api.post<Proposal>(`/contracts/${contractId}/custom-plan/propose`, {
        request, title, purpose, document_type: "free", project_code: projectCode, use_ai: useAi, consent_digest: useAi && consent ? transfer?.consent_digest : "",
      });
      draft.setValue(previous => ({ ...previous, proposal: result, layout: result.layout })); setAck(false); setEditorOpen(true);
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
      const result = await api.post<{ document: Doc }>(`/contracts/${contractId}/custom-plan`, { request, title, purpose, layout, acknowledge_unofficial: ack });
      try { await draft.replace(EMPTY); } catch { /* The document already exists; navigate to it even if draft cleanup fails. */ }
      markSaved(); router.push(`/contracts/${contractId}/documents/${result.document.id}`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };

  return <div className="space-y-4">
    <div><Badge tone="indigo">자유 양식</Badge><h3 className="mt-2 font-semibold">AI 자유 양식 만들기</h3>
      <p className="mt-1 text-xs leading-relaxed text-muted">라이브러리에 없는 문서를 만들어 보세요. 제목·목적·내용 입력 → AI 구성 제안 → 구성 수정 → 본문 작성·전체 페이지 미리보기 → 한글파일 다운로드 순서입니다. 기관 지정 서식이 있다면 양식 업로드를 이용하세요.</p></div>
    <ErrorText>{error}</ErrorText>
    <ErrorText>{draft.error}</ErrorText>
    <p role="status" className="text-xs text-muted">{draft.status} · 회사 자료는 암호화하여 서버에 저장합니다.</p>
    {!draft.ready ? <p className="text-sm">초안을 불러오는 중입니다.</p> : <>
    {!layout ? <>
      <label htmlFor={`${uid}-new-title`} className="block text-sm font-medium">문서 제목</label>
      <Input id={`${uid}-new-title`} maxLength={100} disabled={busy} value={title} placeholder="예: 행사 안전관리계획서" onChange={e => { draft.setValue(previous => ({ ...previous, title: e.target.value })); setTransfer(null); setConsent(false); }} />
      <label htmlFor={`${uid}-purpose`} className="block text-sm font-medium">작성 목적·제출 대상</label>
      <Textarea id={`${uid}-purpose`} rows={2} maxLength={1000} disabled={busy} value={purpose} placeholder="예: 행사 운영 전 발주처에 안전 대응 계획을 설명하려고 합니다." onChange={e => { draft.setValue(previous => ({ ...previous, purpose: e.target.value })); setTransfer(null); setConsent(false); }} />
      <label htmlFor={`${uid}-request`} className="block text-sm font-medium">포함할 내용·요청사항</label>
      <Textarea id={`${uid}-request`} rows={5} maxLength={2000} disabled={busy} value={request} placeholder="예: 안전 담당자 역할표, 위험요소별 대응 방안, 비상 연락망 표를 포함해 주세요. 확인하지 않은 연락처는 빈칸으로 남겨 주세요." onChange={e => { setRequest(e.target.value); setTransfer(null); setConsent(false); }} />
      <label htmlFor={`${uid}-code`} className="block text-xs text-muted">공고·사업번호 (지정 양식 확인용, 선택)</label>
      <Input id={`${uid}-code`} maxLength={80} value={projectCode} disabled={busy} onChange={e => setProjectCode(e.target.value)} />
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={useAi} disabled={busy} onChange={e => { setUseAi(e.target.checked); setConsent(false); }} className="mt-1" />AI로 항목·표 구성 제안 받기</label>
      <p className="text-xs text-muted">AI를 끄면 기본 빈 양식에서 항목과 표를 직접 구성합니다. AI 호출 전에는 전송 내용을 확인하고 동의해야 합니다.</p>
      {useAi && <div className="space-y-3 rounded-lg border border-line bg-slate-50 p-3">
        <p className="text-xs text-muted">입력한 제목·목적·요청사항을 아래 내용대로 OpenAI에 전송합니다. 회사·계약정보·인감·타인의 문서는 추가하지 않습니다. 직접 적은 영업기밀은 마스킹되지 않을 수 있습니다.</p>
        <Button variant="secondary" size="sm" disabled={!canPropose || busy} onClick={prepare}>전송할 내용 확인</Button>
        {transfer && <>
          {!transfer.ai_available && <p className="text-sm text-amber-700">현재 외부 AI가 연결되어 있지 않습니다. AI 선택을 해제하면 빈 양식을 직접 구성할 수 있습니다.</p>}
          <label htmlFor={`${uid}-payload`} className="block text-xs">{transfer.provider} 전송 내용</label>
          <Textarea id={`${uid}-payload`} readOnly rows={7} value={transfer.payload_preview} className="text-xs" />
          <label className="flex items-start gap-2 text-xs"><input type="checkbox" checked={consent} disabled={!transfer.ai_available || busy} onChange={e => setConsent(e.target.checked)} className="mt-0.5" />위 내용을 확인했으며, 이번 요청을 외부 AI에 전송하는 데 동의합니다.</label>
        </>}
      </div>}
      <Button loading={busy} disabled={!canPropose || (useAi && (!transfer?.ai_available || !consent))} onClick={propose}>{useAi ? "AI로 자유 양식 구성하기" : "빈 양식 직접 구성하기"}</Button>
    </> : <>
      <div className="space-y-3 rounded-xl border border-line bg-slate-50 p-4">
        <div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="break-words text-sm font-semibold">{layout.title}</p><p className="mt-1 text-xs text-muted">{layout.sections.length}개 항목 · 표 {layout.sections.filter(section => section.kind === "table").length}개</p></div><Badge tone="indigo">구성 준비됨</Badge></div>
        <p className="text-xs text-muted">팝업에서 항목을 편집하고 초안을 작성하세요. 닫아도 편집 내용은 임시 저장됩니다.</p>
        <div className="flex flex-wrap gap-2"><Button disabled={busy} onClick={() => setEditorOpen(true)}>구성 확인·수정</Button><Button variant="secondary" disabled={busy} onClick={() => { setLayout(null); setAck(false); }}>요청 다시 수정</Button></div>
      </div>
      {editorOpen && <LayoutReviewDialog busy={busy} onClose={() => setEditorOpen(false)} footer={<>
        <label className="flex items-start gap-2 text-xs"><input type="checkbox" checked={ack} disabled={busy} className="mt-0.5" onChange={e => setAck(e.target.checked)} />구성을 확인했으며, 발주처 지정 서식이 아닌 검토용 초안임을 이해했습니다.</label>
        <div className="flex flex-wrap items-center justify-between gap-2"><span role="status" className="text-xs text-muted">{draft.status}</span><div className="flex flex-wrap gap-2"><Button variant="secondary" disabled={busy} onClick={() => setEditorOpen(false)}>닫기</Button><Button loading={busy} disabled={!ack || !layout.title.trim() || layout.sections.some(section => !section.label.trim())} onClick={create}>확정하고 초안 작성</Button></div></div>
      </>}>
      <ErrorText>{error || draft.error}</ErrorText>
      <div className="flex flex-wrap items-center gap-2"><Badge>{proposal?.mode === "ai" ? "AI 자유 양식 구성" : "직접 편집할 기본 구성"}</Badge><Badge tone="amber">검토용 초안 · 지정 서식 아님</Badge></div>
      {proposal?.warning && <p role="status" className="text-xs text-amber-700">{proposal.warning}</p>}
      {proposal && proposal.matches.length > 0 && <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs">
        <p className="font-semibold">발주처에 맞는 등록 양식이 있습니다. 지정 양식을 먼저 확인하세요.</p>
        {proposal.matches.map(match => <Link key={match.id} href={`/templates/${match.id}`} target="_blank" rel="noopener noreferrer" className="mt-2 block text-primary underline">{match.name} · {match.reason} ↗</Link>)}
      </div>}
      <label htmlFor={`${uid}-title`} className="block text-sm font-medium">서류·양식 제목</label>
      <Input id={`${uid}-title`} value={layout.title} maxLength={100} disabled={busy} onChange={e => edit({ ...layout, title: e.target.value })} />
      <p className="text-xs text-muted">계약명·발주처·회사·기간·책임자 표가 함께 들어갑니다. 항목명, 순서, 본문/표 형식과 필수 여부를 확인하세요.</p>
      <ol className="grid gap-3 sm:grid-cols-2">
        {layout.sections.map((section, index) => <li key={section.key} className="space-y-2 rounded-lg border border-line p-3">
          <label htmlFor={`${uid}-${section.key}`} className="block text-xs font-medium">{index + 1}. 항목명</label>
          <Input id={`${uid}-${section.key}`} value={section.label} maxLength={60} disabled={busy} onChange={e => editSection(index, { label: e.target.value })} />
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <label>형식 <select aria-label={`${section.label} 형식`} value={section.kind} disabled={busy} className="rounded border border-line p-1" onChange={e => editSection(index, e.target.value === "table" ? { kind: "table", columns: ["항목", "내용"] } : { kind: "text", columns: [] })}><option value="text">본문</option><option value="table">표</option></select></label>
            <label><input type="checkbox" checked={section.required} disabled={busy} onChange={e => editSection(index, { required: e.target.checked })} /> 필수 입력</label>
            <Button variant="ghost" size="sm" aria-label={`${section.label} 위로`} disabled={busy || index === 0} onClick={() => move(index, -1)}>↑</Button>
            <Button variant="ghost" size="sm" aria-label={`${section.label} 아래로`} disabled={busy || index === layout.sections.length - 1} onClick={() => move(index, 1)}>↓</Button>
            <Button variant="ghost" size="sm" disabled={busy || layout.sections.length <= 1 || (layout.document_type !== "free" && ["work_summary", "description"].includes(section.key))} onClick={() => edit({ ...layout, sections: layout.sections.filter(item => item.key !== section.key) })}>제외</Button>
          </div>
          {section.kind === "table" && <><label htmlFor={`${uid}-${section.key}-columns`} className="block text-xs text-muted">열 이름을 |로 구분 (2~6개)</label><Input id={`${uid}-${section.key}-columns`} disabled={busy} value={section.columns.join(" | ")} onChange={e => editSection(index, { columns: e.target.value.split("|").map(value => value.trim()) })} /></>}
        </li>)}
      </ol>
      <Button variant="secondary" size="sm" disabled={busy || layout.sections.length >= 12} onClick={() => {
        const key = Array.from({ length: 99 }, (_, i) => `custom_${i + 1}`).find(key => !layout.sections.some(section => section.key === key));
        if (key) edit({ ...layout, sections: [...layout.sections, { key, label: "추가 항목", kind: "text", columns: [], required: true }] });
      }}>항목 추가</Button>
      <p className="text-xs text-muted">확정하면 내 양식에 저장되어 다른 계약에서도 사용할 수 있습니다. 다음 화면의 본문 작성 도우미에서 필요한 정보를 답하고 AI 본문을 제안받을 수 있습니다. 확인되지 않은 사실은 빈칸으로 남깁니다.</p>
      </LayoutReviewDialog>}
    </>}</>}
  </div>;
}
