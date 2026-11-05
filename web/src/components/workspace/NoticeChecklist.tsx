"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspaceDraft } from "@/lib/useWorkspaceDraft";
import { useUnsavedChanges } from "@/lib/useUnsavedChanges";
import { applyNoticeAnalysis, FACT_LABELS, type NoticeAnalysis, type NoticeState, type NoticeItem, type NoticeFact } from "@/lib/notice";
import type { Doc, Template } from "@/lib/types";
import { Badge, Button, ErrorText, Input, Textarea } from "@/components/ui";

type Transfer = { payload_preview: string; consent_digest: string; ai_available: boolean };
type Match = { template: Template; reason: string };
function Facts({ facts }: { facts: NoticeFact[] }) {
  return <div className="space-y-2">{facts.map((fact, i) => <div key={i} className="text-xs"><strong>{FACT_LABELS[fact.kind]}:</strong> <span className="whitespace-pre-wrap">{fact.value}</span><details><summary className="cursor-pointer text-muted">원문 근거</summary><p className="whitespace-pre-wrap">{fact.evidence}</p></details></div>)}</div>;
}

export default function NoticeChecklist({ contractId, active, onDocumentsChanged, onChecklistChanged }: { contractId: number; active: boolean; onDocumentsChanged: () => Promise<void>; onChecklistChanged: () => void }) {
  const draft = useWorkspaceDraft<NoticeState>(contractId, "notice", { text: "", items: [], facts: [] });
  const [docs, setDocs] = useState<Doc[]>([]);
  const [useAi, setUseAi] = useState(false);
  const [transfer, setTransfer] = useState<Transfer | null>(null);
  const [consent, setConsent] = useState(false);
  const [confirmed, setConfirmed] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [preview, setPreview] = useState<{ source: string; result: NoticeAnalysis } | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const [matches, setMatches] = useState<Record<string, Match[]>>({});
  const [projectCode, setProjectCode] = useState("");
  const { text, items, facts = [] } = draft.value;
  const stale = Boolean((text.trim() || draft.value.analyzed_text) && text !== draft.value.analyzed_text);
  useUnsavedChanges(draft.pending);
  useEffect(() => {
    if (!active) return;
    let alive = true;
    api.get<Doc[]>(`/contracts/${contractId}/documents`).then(d => { if (alive) setDocs(d); }).catch(e => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [contractId, active]);
  const act = async (fn: () => Promise<void>) => {
    setBusy(true); setError(""); setMessage("");
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const changeText = (next: string) => {
    onChecklistChanged();
    draft.setValue(previous => ({ ...previous, text: next }));
    setConsent(false); setTransfer(null); setPreview(null); setMessage("");
  };
  const edit = (id: string, changes: Partial<NoticeItem>) => {
    onChecklistChanged();
    draft.setValue(previous => ({ ...previous, items: previous.items.map(item => item.id === id ? { ...item, ...changes } : item) }));
  };
  const removed = preview ? items.filter(old => old.evidence && !preview.result.items.some(next => next.id === old.id || next.title.replaceAll(" ", "") === old.title.replaceAll(" ", ""))) : [];
  return <div className="space-y-4" aria-busy={busy}>
    <h3 className="font-semibold">안내문 분석 · 제출 준비</h3>
    <p className="text-xs text-muted">안내문을 넣으면 제출 서류와 기한·방법·문의처를 원문 근거와 함께 정리합니다. 분석 결과를 확인하고 적용하세요.</p>
    <ErrorText>{error || draft.error}</ErrorText><p role="status" className="text-xs text-muted">{draft.status}</p>
    {draft.ready && <>
      <label className="block text-sm">안내문 파일 (PDF·한글·Word·TXT)<input aria-label="안내문 파일 선택" type="file" accept=".pdf,.hwp,.hwpx,.docx,.txt,application/pdf,application/haansofthwp,application/vnd.hancom.hwp,application/vnd.hancom.hwpx,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain" className="mt-1 block w-full text-xs" disabled={busy} onChange={e => {
        const file = e.target.files?.[0]; if (!file) return;
        void act(async () => {
          if (file.size > 3 * 1024 * 1024) throw new Error("안내문 파일은 3MB 이하여야 합니다.");
          const result = await api.upload<{ text: string; warning: string }>(`/contracts/${contractId}/notice/extract`, file);
          changeText(result.text); setMessage(`${file.name}에서 ${result.text.length.toLocaleString()}자를 가져왔습니다. ${result.warning || ""}`);
        }); e.target.value = "";
      }} /></label>
      <p className="text-xs text-muted">PDF·HWP(5.x)·HWPX·DOCX·UTF-8 TXT, 파일당 3MB·추출 텍스트 20,000자까지 지원합니다. PDF는 20페이지 이하입니다. 원본 파일은 저장하지 않습니다. 암호·배포용 제한 문서와 스캔 이미지는 내용을 직접 붙여넣으세요. 구형 DOC는 DOCX로 저장해 주세요.</p>
      <label className="block text-sm">안내문 원문<Textarea aria-label="제출 안내문 원문" maxLength={20000} rows={8} value={text} disabled={busy} onChange={e => changeText(e.target.value)} /></label>
      <p className="text-right text-xs text-muted">{text.length.toLocaleString()} / 20,000자</p>
      {stale && <p role="status" className="rounded bg-amber-50 p-3 text-xs text-amber-900">현재 원문과 적용된 분석 결과가 다릅니다. 기존 목록은 유지되며, 재분석 후 결과를 적용해야 최신 안내문이 반영됩니다.</p>}
      <label className="flex gap-2 text-sm"><input type="checkbox" checked={useAi} disabled={busy} onChange={e => { setUseAi(e.target.checked); setConsent(false); setPreview(null); }} />AI로 분석 보완하기</label>
      {useAi && <div className="space-y-2 rounded border border-line p-3"><Button variant="secondary" size="sm" disabled={busy || text.trim().length < 5} onClick={() => act(async () => { setTransfer(await api.post<Transfer>(`/contracts/${contractId}/notice/preview`, { text })); setConfirmed(text); setConsent(false); })}>전송 내용 확인</Button>
        {transfer && confirmed === text && <><Textarea aria-label="안내문 AI 전송 내용" rows={6} value={transfer.payload_preview} readOnly /><label className="flex gap-2 text-xs"><input type="checkbox" checked={consent} disabled={busy || !transfer.ai_available} onChange={e => setConsent(e.target.checked)} />전송 내용을 확인했으며 이번 OpenAI 전송에 동의합니다.</label>{!transfer.ai_available && <p className="text-xs text-amber-800">외부 AI 미연결 · AI 선택을 해제하면 기본 분석을 사용할 수 있습니다.</p>}</>}
      </div>}
      <Button loading={busy} disabled={text.trim().length < 5 || (useAi && (!consent || !transfer?.ai_available || confirmed !== text))} onClick={() => act(async () => {
        const result = await api.post<NoticeAnalysis>(`/contracts/${contractId}/notice/analyze`, { text, use_ai: useAi, consent_digest: useAi ? transfer?.consent_digest : "" });
        setPreview({ source: text, result }); setConsent(false);
      })}>안내문 분석하기</Button>
      {message && <p role="status" className="text-xs text-amber-800">{message}</p>}
      {preview && preview.source === text && <section aria-label="분석 결과 미리보기" className="space-y-3 rounded-lg border border-primary bg-indigo-50/40 p-3">
        <h4 className="text-sm font-semibold">분석 결과 확인 · 아직 적용하지 않음</h4><Badge>{preview.result.mode === "ai" ? "AI 분석" : preview.result.mode === "rule_fallback" ? "AI 실패·기본 분석" : "기본 분석"}</Badge>
        <p className="text-xs">서류 {preview.result.items.length}개 · 제출 정보 {preview.result.facts.length}개</p>
        {preview.result.warning && <p role="status" className="text-xs text-amber-900">{preview.result.warning}</p>}
        <ul className="space-y-2">{preview.result.items.map(item => <li key={item.id} className="rounded border border-line bg-white p-2 text-xs"><strong>{item.title}</strong> · {item.required ? "필수" : "조건부·선택"}{item.condition && <p>조건: {item.condition}</p>}<p className="mt-1 whitespace-pre-wrap text-muted">근거: {item.evidence}</p></li>)}</ul>
        <Facts facts={preview.result.facts} />
        {removed.length > 0 && <p className="text-xs text-amber-900">적용 시 이전 분석 항목 {removed.length}개가 제외됩니다: {removed.map(i => i.title).join(", ")}</p>}
        <p className="text-xs text-muted">직접 추가한 항목과 같은 서류의 연결·메모는 유지합니다. 원문 근거나 필수 조건이 바뀐 서류는 준비 확인을 해제합니다.</p>
        <div className="flex gap-2"><Button size="sm" disabled={busy} onClick={() => act(async () => {
          if (preview.source !== text) throw new Error("원문이 변경되었습니다. 다시 분석하세요.");
          await draft.replace(applyNoticeAnalysis(draft.value, preview.result));
          onChecklistChanged();
          setPreview(null); setMatches({}); setMessage("분석 결과를 적용하고 저장했습니다. 원문과 대조해 준비 여부를 확인하세요.");
        })}>확인한 결과 적용·저장</Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => setPreview(null)}>분석 결과 닫기</Button></div>
      </section>}
      {(facts.length > 0 || draft.value.analyzed_text) && <section aria-label="적용된 제출 정보" className="space-y-2 rounded border border-line p-3"><h4 className="text-sm font-semibold">제출 정보 {stale && "· 이전 분석"}</h4><Facts facts={facts} />{!facts.some(f => f.kind === "deadline") && <p className="text-xs text-amber-800">제출기한을 찾지 못했습니다. 원문에서 별도로 확인하세요.</p>}</section>}
      <div className="flex flex-wrap items-center gap-2"><Badge>필수 {items.filter(i => i.required && i.done).length}/{items.filter(i => i.required).length} 준비 확인</Badge><Badge>조건부·선택 {items.filter(i => !i.required).length}개</Badge><Button size="sm" variant="secondary" disabled={busy || items.length >= 30} onClick={() => { onChecklistChanged(); draft.setValue(previous => ({ ...previous, items: [...previous.items, { id: `n_${crypto.randomUUID().replaceAll("-", "").slice(0,16)}`, title: "추가 제출서류", evidence: "", required: true, done: false, document_id: null, note: "" }] })); }}>직접 항목 추가</Button></div>
      {items.length === 0 && <p className="rounded border border-dashed border-line p-4 text-center text-xs text-muted">아직 적용된 제출 서류가 없습니다. 안내문을 분석하거나 직접 추가하세요.</p>}
      <Input aria-label="양식 추천용 공고번호" maxLength={100} value={projectCode} disabled={busy} onChange={e => { setProjectCode(e.target.value); setMatches({}); }} placeholder="공고·사업번호 (지정 양식이 있을 때 입력)" />
      <ol className="space-y-3">{items.map((item, index) => <li key={item.id} className="space-y-2 rounded border border-line p-3">
        <label className="block text-xs">{index + 1}. 제출서류 이름<Input aria-label={`제출서류 ${index + 1} 이름`} value={item.title} maxLength={100} disabled={busy} onChange={e => { edit(item.id, { title: e.target.value }); setMatches({}); }} /></label>
        <details className="text-xs"><summary className="cursor-pointer text-muted">원문 근거 보기</summary><p className="whitespace-pre-wrap">{item.evidence || "사용자가 직접 추가함"}</p></details>
        {item.condition && <p className="text-xs text-amber-900">조건: {item.condition} · 해당하면 필수로 바꾸세요.</p>}
        <label className="mr-3 text-xs"><input type="checkbox" checked={item.required} disabled={busy} onChange={e => edit(item.id, { required: e.target.checked })} /> 필수</label>
        <label className="text-xs"><input type="checkbox" checked={item.done} disabled={busy} onChange={e => edit(item.id, { done: e.target.checked })} /> 준비 확인</label>
        <label className="block text-xs">연결할 작성 서류<select aria-label={`${item.title} 연결 서류`} value={item.document_id ?? ""} disabled={busy} className="mt-1 w-full rounded border border-line p-1" onChange={e => edit(item.id, { document_id: e.target.value ? Number(e.target.value) : null })}><option value="">외부 첨부·수동 준비</option>{docs.map(doc => <option value={doc.id} key={doc.id}>{doc.title}</option>)}</select></label>
        {item.document_id && docs.some(d => d.id === item.document_id) && <Link href={`/contracts/${contractId}/documents/${item.document_id}`} className="block text-xs text-primary underline">연결된 서류 작성하기</Link>}
        {item.document_id && !docs.some(d => d.id === item.document_id) && <p className="text-xs text-amber-900">연결 서류가 삭제되었습니다. 연결할 서류를 다시 선택하세요.</p>}
        <Input aria-label={`${item.title} 준비 메모`} value={item.note} maxLength={500} placeholder="조건·준비 메모" disabled={busy} onChange={e => edit(item.id, { note: e.target.value })} />
        <Button size="sm" variant="secondary" disabled={busy || !item.title.trim()} onClick={() => act(async () => {
          const result = await api.get<Match[]>(`/contracts/${contractId}/notice/templates?title=${encodeURIComponent(item.title)}&project_code=${encodeURIComponent(projectCode)}`);
          setMatches(previous => ({ ...previous, [item.id]: result }));
        })}>작성 가능한 양식 찾기</Button>
        {matches[item.id]?.length === 0 && <p className="text-xs text-muted">등록된 일치 양식이 없습니다. 외부에서 준비하거나 <Link className="text-primary underline" href={`/templates/upload?contract=${contractId}`}>받은 양식을 등록</Link>하세요.</p>}
        {matches[item.id]?.map(match => <div key={match.template.id} className="space-y-1 rounded bg-gray-50 p-2 text-xs"><Link className="text-primary underline" href={`/templates/${match.template.id}`} target="_blank" rel="noopener noreferrer">{match.template.name}</Link><p>{match.reason}</p><Button size="sm" variant="secondary" disabled={busy} onClick={() => act(async () => {
          const latest = await api.get<Doc[]>(`/contracts/${contractId}/documents`);
          const doc = latest.find(d => d.template_id === match.template.id) || await api.post<Doc>(`/contracts/${contractId}/documents`, { template_id: match.template.id, project_code: projectCode });
          setDocs(await api.get<Doc[]>(`/contracts/${contractId}/documents`));
          await draft.replace({ ...draft.value, items: draft.value.items.map(i => i.id === item.id ? { ...i, document_id: doc.id } : i) });
          await onDocumentsChanged(); setMessage("서류를 연결했습니다. 내용을 작성하고 검토한 뒤 준비 확인을 표시하세요.");
        })}>{docs.some(d => d.template_id === match.template.id) ? "기존 서류 연결" : "서류 생성·연결"}</Button></div>)}
        {removing === item.id ? <div className="flex items-center gap-2 text-xs"><span>이 항목을 제외할까요?</span><Button size="sm" variant="secondary" disabled={busy} onClick={() => { onChecklistChanged(); draft.setValue(previous => ({ ...previous, items: previous.items.filter(i => i.id !== item.id) })); setRemoving(null); }}>제외</Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => setRemoving(null)}>취소</Button></div> : <Button size="sm" variant="ghost" disabled={busy} onClick={() => setRemoving(item.id)}>항목 제외</Button>}
      </li>)}</ol>
      <Button size="sm" variant="secondary" disabled={busy} onClick={() => act(() => draft.saveNow())}>체크리스트 지금 저장</Button>
      <p className="text-xs text-muted">원문·분석 정보·체크리스트는 서버에 암호화 저장됩니다. 필수 미완료 항목과 미반영 안내문은 제출 전 점검에 표시됩니다. 준비 확인은 실제 제출이나 첨부 검증을 의미하지 않습니다.</p>
    </>}
  </div>;
}
