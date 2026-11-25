"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useUnsavedChanges } from "@/lib/useUnsavedChanges";
import type { Doc } from "@/lib/types";
import { WORKFLOW_MODES, emptyWorkflow, estimateAmounts, type WorkflowDraft, type WorkflowFile, type WorkflowInput, type WorkflowMode,
  type WorkflowOutput, type WorkflowPreview, type WorkflowSession } from "@/lib/ai-workflows";
import { Button, Card, ErrorText, Loading, PageHeader } from "@/components/ui";
import WorkflowInputs from "./WorkflowInputs";
import WorkflowResults from "./WorkflowResults";
import WorkflowEstimate from "./WorkflowEstimate";
import DraftMergeReview from "./DraftMergeReview";
import { applyDraftChange, compareDrafts, identifyDrafts } from "@/lib/draft-reconciliation";
import { RecoveryComparison } from "./DraftRecovery";

export default function WorkflowWorkspace({ contractId, mode }: { contractId: number; mode: WorkflowMode }) {
  const base = `/contracts/${contractId}/ai-workflows/${mode}`;
  const [session, setSession] = useState<WorkflowSession>(emptyWorkflow);
  const [revision, setRevision] = useState(0);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [retry, setRetry] = useState(0);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [preview, setPreview] = useState<WorkflowPreview | null>(null);
  const [preparedInput, setPreparedInput] = useState<WorkflowInput | null>(null);
  const [consent, setConsent] = useState(false);
  const [generation, setGeneration] = useState(0);
  const [created, setCreated] = useState<Record<number, string>>({});
  const [saveFailed, setSaveFailed] = useState(false);
  const [conflicted, setConflicted] = useState(false);
  const [remote, setRemote] = useState<{ payload: WorkflowSession | null; revision: number; updated_at?: string } | null>(null);
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);
  const [retryAI, setRetryAI] = useState(false);
  const actionLock = useRef(false);
  useUnsavedChanges(dirty || busy);

  useEffect(() => {
    let active = true;
    Promise.all([api.get<{ payload: WorkflowSession | null; revision: number; updated_at?: string }>(`${base}/session`), api.get<Doc[]>(`/contracts/${contractId}/documents`)])
      .then(([saved, documents]) => {
        if (!active) return;
        if (saved.payload) setSession({ ...saved.payload, output: saved.payload.output ? { ...saved.payload.output, result: {
          ...saved.payload.output.result, drafts: identifyDrafts(saved.payload.output.result.drafts) } } : null });
        setRevision(saved.revision); setDocs(documents); setLoaded(true); setError("");
        setLastSavedAt(saved.updated_at ?? null);
      }).catch(e => { if (active) setError((e as Error).message); });
    return () => { active = false; };
  }, [base, contractId, retry]);

  const editInput = (input: WorkflowInput) => {
    setSession(current => ({ ...current, input, output_stale: !!current.output }));
    setPreview(null); setPreparedInput(null); setConsent(false); setDirty(true); setMessage("");
    setRetryAI(false);
  };
  const answer = (question: string, text: string, confirmed = false, topic = "other", resolves: string[] = []) => {
    const existing = session.input.answers.find(a => a.question === question);
    if (!existing && session.input.answers.length >= 12) return;
    editInput({ ...session.input, answers: existing ? session.input.answers.map(a => a.question === question ? { ...a, text, confirmed, topic, resolves } : a) : [...session.input.answers, { question, text, confirmed, topic, resolves }] });
  };
  const editDraft = (index: number, draft: WorkflowDraft) => {
    setSession(current => current.output ? { ...current, output: { ...current.output, result: { ...current.output.result,
      drafts: current.output.result.drafts.map((d, n) => n === index ? draft : d) } } } : current);
    setCreated(current => { const next = { ...current }; delete next[index]; return next; });
    setDirty(true); setMessage("");
    setPreview(null); setPreparedInput(null); setConsent(false);
  };
  const resolveChange = (id: string, accept: boolean) => {
    const change = session.draft_changes?.find(item => item.id === id);
    if (!change || !session.output) return;
    try {
      const drafts = accept ? applyDraftChange(session.output.result.drafts, change) : session.output.result.drafts;
      setSession(current => current.output ? { ...current, output: { ...current.output, result: { ...current.output.result, drafts } },
        draft_changes: current.draft_changes?.filter(item => item.id !== id) } : current);
      setGeneration(n => n + 1); setCreated({}); setDirty(true); setPreview(null); setPreparedInput(null); setConsent(false); setError(""); setMessage("");
    } catch (e) { setError((e as Error).message); }
  };
  const upload = async (file: File) => {
    if (file.size > 3 * 1024 * 1024) { setError("파일당 최대 3MB입니다."); return; }
    setBusy(true); setError("");
    try {
      const extracted = await api.upload<Omit<WorkflowFile, "kind">>(`/contracts/${contractId}/ai-workflows/extract`, file);
      editInput({ ...session.input, files: [...session.input.files, { ...extracted, kind: mode === "change" ? "reference" : "input" }] });
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const prepare = async () => {
    if (session.draft_changes?.length) return;
    setBusy(true); setError(""); setConsent(false); setPreview(null);
    try {
      const body = { ...session.input, draft_context: session.output?.result.drafts ?? [] };
      const response = await api.post<WorkflowPreview>(`${base}/preview`, body);
      setPreparedInput(body); setPreview(response);
    }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const analyze = async () => {
    if (!preview || !preparedInput || !consent || !preview.ai_available || session.draft_changes?.length) return;
    if (actionLock.current) return;
    actionLock.current = true;
    setBusy(true); setError(""); setMessage("");
    try {
      const output = await api.post<WorkflowOutput>(`${base}/analyze`, { ...preparedInput, consent_digest: preview.consent_digest });
      setSession(current => {
        const old = identifyDrafts(current.output?.result.drafts ?? []);
        const incoming = identifyDrafts(output.result.drafts, old);
        const changes = old.length ? compareDrafts(old, current.draft_baseline ?? [], incoming) : [];
        return { ...current, output: { ...output, result: { ...output.result, drafts: old.length ? old : incoming } },
          output_stale: false, draft_baseline: incoming, draft_changes: changes };
      });
      setCreated({}); setGeneration(n => n + 1); setDirty(true); setConsent(false); setPreview(null);
      setMessage(session.output ? "새 분석 결과를 받았습니다. 기존 초안과 견적 입력은 유지했으며, 달라진 문구는 항목별로 선택 반영할 수 있습니다." : "분석 결과가 생성됐습니다. 내용을 검토하고 작업 저장 또는 서류로 저장을 진행하세요.");
    } catch (e) { setError((e as Error).message); setRetryAI(e instanceof ApiError && e.retryable); }
    finally { actionLock.current = false; setBusy(false); }
  };
  const save = async (nextRevision = revision) => {
    if (estimateAmounts(session.estimate_lines).total === null) { setError("견적 항목의 작업명·단위·수량·단가를 확인하세요."); return; }
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await api.put<{ revision: number }>(`${base}/session`, { payload: session, revision: nextRevision });
      setRevision(result.revision); setDirty(false); setMessage("작업을 저장했습니다. 이 계약에서 기능별로 마지막 저장 내용을 다시 열 수 있습니다.");
      setLastSavedAt(new Date().toISOString()); setSaveFailed(false); setConflicted(false); setRemote(null);
    } catch (e) { setError((e as Error).message); setSaveFailed(true); if (e instanceof ApiError && e.status === 409) setConflicted(true); }
    finally { setBusy(false); }
  };
  const compareSaved = async () => {
    setBusy(true);
    try { setRemote(await api.get(`${base}/session`)); setError(""); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const useServer = () => {
    if (!remote) return;
    setSession(remote.payload ?? emptyWorkflow());
    setRevision(remote.revision); setLastSavedAt(remote.updated_at ?? null);
    setRemote(null); setConflicted(false); setSaveFailed(false); setDirty(false);
    setPreview(null); setPreparedInput(null); setConsent(false); setCreated({});
    setGeneration(n => n + 1); setError(""); setMessage("서버 저장본을 불러왔습니다.");
  };
  const createDocument = async (index: number) => {
    if (!session.output || session.output_stale || created[index] || session.draft_changes?.some(change => change.kind === session.output!.result.drafts[index].kind)) return;
    if (session.output.result.questions.some(question => question.intent === "conflict")) { setError("충돌하는 요구사항을 먼저 확인하고 다시 분석하세요."); return; }
    const draft = session.output.result.drafts[index];
    setBusy(true); setError(""); setMessage("");
    try {
      const response = await api.post<{ document: Doc }>(`${base}/documents`, { draft, acknowledge_draft: true,
        estimate_lines: draft.kind === "estimate" ? session.estimate_lines : [] });
      setCreated(current => ({ ...current, [index]: `/contracts/${contractId}/documents/${response.document.id}` }));
      setDocs(current => [...current, response.document]); setMessage(`‘${response.document.title}’을 계약 서류에 추가했습니다.`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };

  if (!loaded) return error ? <div><ErrorText>{error}</ErrorText><Button onClick={() => setRetry(n => n + 1)}>다시 불러오기</Button></div> : <Loading />;
  const config = WORKFLOW_MODES[mode];
  return <>
    <PageHeader title="AI 업무 도우미" desc={config.description} back={{ href: `/contracts/${contractId}`, label: "계약 상세" }} />
    <nav aria-label="AI 업무 기능" className="mb-5 grid gap-3 md:grid-cols-3">
      {Object.entries(WORKFLOW_MODES).map(([key, value]) => <Link key={key} aria-current={key === mode ? "page" : undefined}
        className={`rounded-lg border p-4 text-sm font-semibold ${key === mode ? "border-primary bg-indigo-50 text-primary" : "border-line bg-white"}`}
        href={`/contracts/${contractId}/assistant/${key}`}>{value.title}</Link>)}
    </nav>
    <ErrorText>{error}</ErrorText>
    {saveFailed && <div className="mb-4 space-y-2">
      <p className="text-sm text-muted">현재 입력·초안·견적 내용을 유지했습니다.</p>
      <Button variant="secondary" disabled={busy} onClick={() => conflicted ? compareSaved() : save()}>
        {conflicted ? "서버 저장본과 비교" : "작업 저장 다시 시도"}
      </Button>
    </div>}
    {remote && <RecoveryComparison local={session} remote={remote.payload ?? emptyWorkflow()} busy={busy}
      onLocal={() => void save(remote.revision)} onRemote={useServer} />}
    {lastSavedAt && <p className="mb-3 text-xs text-muted">마지막 작업 저장 {new Date(/Z$|[+-]\d\d:\d\d$/.test(lastSavedAt) ? lastSavedAt : lastSavedAt + "Z").toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })}</p>}
    {message && <p role="status" className="mb-4 rounded bg-indigo-50 p-3 text-sm text-primary">{message}</p>}
    <div className="grid items-start gap-5 xl:grid-cols-[minmax(320px,420px)_minmax(0,1fr)]">
      <div className="space-y-5">
        <Card className="space-y-4 p-5">
          <h2 className="font-semibold">{config.title}</h2>
          <WorkflowInputs mode={mode} input={session.input} docs={docs} busy={busy} onChange={editInput} onUpload={upload} />
          <div className="flex flex-wrap gap-2"><Button variant="secondary" disabled={busy || !!session.draft_changes?.length} onClick={prepare}>AI 전송 내용 확인</Button><Button variant="secondary" disabled={busy || !dirty} onClick={() => save()}>작업 저장</Button></div>
          {!!session.draft_changes?.length && <p className="text-xs text-amber-800">재분석 변경 제안을 먼저 선택하세요. 미선택 제안도 작업 저장으로 보관할 수 있습니다.</p>}
          <p className="text-xs text-muted">{dirty ? "미저장 변경사항이 있습니다." : "저장된 상태입니다."} 작업은 기능별 1개씩 암호화 저장됩니다. 30일간 수정하지 않은 작업은 정리될 수 있습니다. 생성해 저장한 서류는 계약에 남습니다.</p>
          {preview && <section className="space-y-3 rounded border border-line p-3">
            <h3 className="text-sm font-semibold">OpenAI에 전송할 내용</h3>
            {preview.warning && <p className="text-xs text-amber-800">{preview.warning}</p>}
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words text-xs">{preview.payload_preview}</pre>
            {!preview.ai_available && <p className="text-xs text-amber-800">외부 AI가 연결되지 않았습니다. 서버의 API 키 설정을 확인하세요.</p>}
            <label className="flex gap-2 text-xs"><input type="checkbox" disabled={busy || !preview.ai_available} checked={consent} onChange={e => setConsent(e.target.checked)} />위 마스킹된 자료를 OpenAI에 전송하는 데 동의합니다.</label>
            <Button loading={busy} disabled={busy || !consent || !preview.ai_available} onClick={analyze}>{retryAI ? "AI 분석 다시 시도" : config.action}</Button>
          </section>}
        </Card>
        {mode === "requirements" && <Card className="p-5"><WorkflowEstimate lines={session.estimate_lines} disabled={busy} onChange={estimate_lines => { setSession(current => ({ ...current, estimate_lines })); setDirty(true); setMessage(""); }} /></Card>}
      </div>
      {session.output ? <div className="space-y-5"><DraftMergeReview changes={session.draft_changes ?? []} busy={busy} onResolve={resolveChange} /><WorkflowResults key={generation} output={session.output} input={session.input} stale={session.output_stale} busy={busy} mode={mode} pendingKinds={(session.draft_changes ?? []).map(change => change.kind)}
        onAnswer={answer} onDraft={editDraft} onCreate={createDocument} created={created}
        estimateReady={session.estimate_lines.length > 0 && estimateAmounts(session.estimate_lines).total !== null} /></div> :
        <Card className="space-y-3 p-6"><h2 className="font-semibold">분석 결과와 서류 초안</h2><p className="text-sm text-muted">자료를 입력하고 전송 내용을 확인한 뒤 AI 분석을 실행하세요. 결과에서 근거와 확인 질문을 검토하고, 초안을 편집해 서류로 저장할 수 있습니다.</p></Card>}
    </div>
  </>;
}
