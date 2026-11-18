"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useUnsavedChanges } from "@/lib/useUnsavedChanges";
import type { Doc } from "@/lib/types";
import { WORKFLOW_MODES, emptyWorkflow, estimateAmounts, type WorkflowDraft, type WorkflowFile, type WorkflowInput, type WorkflowMode,
  type WorkflowOutput, type WorkflowPreview, type WorkflowSession } from "@/lib/ai-workflows";
import { Button, Card, ErrorText, Loading, PageHeader } from "@/components/ui";
import WorkflowInputs from "./WorkflowInputs";
import WorkflowResults from "./WorkflowResults";
import WorkflowEstimate from "./WorkflowEstimate";

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
  const [consent, setConsent] = useState(false);
  const [generation, setGeneration] = useState(0);
  const [created, setCreated] = useState<Record<number, string>>({});
  useUnsavedChanges(dirty || busy);

  useEffect(() => {
    let active = true;
    Promise.all([api.get<{ payload: WorkflowSession | null; revision: number }>(`${base}/session`), api.get<Doc[]>(`/contracts/${contractId}/documents`)])
      .then(([saved, documents]) => {
        if (!active) return;
        if (saved.payload) setSession(saved.payload);
        setRevision(saved.revision); setDocs(documents); setLoaded(true); setError("");
      }).catch(e => { if (active) setError((e as Error).message); });
    return () => { active = false; };
  }, [base, contractId, retry]);

  const editInput = (input: WorkflowInput) => {
    setSession(current => ({ ...current, input, output_stale: !!current.output }));
    setPreview(null); setConsent(false); setDirty(true); setMessage("");
  };
  const answer = (question: string, text: string) => {
    const existing = session.input.answers.find(a => a.question === question);
    if (!existing && session.input.answers.length >= 12) return;
    editInput({ ...session.input, answers: existing ? session.input.answers.map(a => a.question === question ? { ...a, text } : a) : [...session.input.answers, { question, text }] });
  };
  const editDraft = (index: number, draft: WorkflowDraft) => {
    setSession(current => current.output ? { ...current, output: { ...current.output, result: { ...current.output.result,
      drafts: current.output.result.drafts.map((d, n) => n === index ? draft : d) } } } : current);
    setCreated(current => { const next = { ...current }; delete next[index]; return next; });
    setDirty(true); setMessage("");
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
    setBusy(true); setError(""); setConsent(false); setPreview(null);
    try { setPreview(await api.post<WorkflowPreview>(`${base}/preview`, session.input)); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const analyze = async () => {
    if (!preview || !consent || !preview.ai_available) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const output = await api.post<WorkflowOutput>(`${base}/analyze`, { ...session.input, consent_digest: preview.consent_digest });
      setSession(current => ({ ...current, output, output_stale: false }));
      setCreated({}); setGeneration(n => n + 1); setDirty(true); setConsent(false); setPreview(null);
      setMessage("분석 결과가 생성됐습니다. 내용을 검토하고 작업 저장 또는 서류로 저장을 진행하세요.");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const save = async () => {
    if (estimateAmounts(session.estimate_lines).total === null) { setError("견적 항목의 작업명·단위·수량·단가를 확인하세요."); return; }
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await api.put<{ revision: number }>(`${base}/session`, { payload: session, revision });
      setRevision(result.revision); setDirty(false); setMessage("작업을 저장했습니다. 이 계약에서 기능별로 마지막 저장 내용을 다시 열 수 있습니다.");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const createDocument = async (index: number) => {
    if (!session.output || session.output_stale || created[index]) return;
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
    {message && <p role="status" className="mb-4 rounded bg-indigo-50 p-3 text-sm text-primary">{message}</p>}
    <div className="grid items-start gap-5 xl:grid-cols-[minmax(320px,420px)_minmax(0,1fr)]">
      <div className="space-y-5">
        <Card className="space-y-4 p-5">
          <h2 className="font-semibold">{config.title}</h2>
          <WorkflowInputs mode={mode} input={session.input} docs={docs} busy={busy} onChange={editInput} onUpload={upload} />
          <div className="flex flex-wrap gap-2"><Button variant="secondary" disabled={busy} onClick={prepare}>AI 전송 내용 확인</Button><Button variant="secondary" disabled={busy || !dirty} onClick={save}>작업 저장</Button></div>
          <p className="text-xs text-muted">{dirty ? "미저장 변경사항이 있습니다." : "저장된 상태입니다."} 작업은 기능별 1개씩 암호화 저장됩니다. 30일간 수정하지 않은 작업은 정리될 수 있습니다. 생성해 저장한 서류는 계약에 남습니다.</p>
          {preview && <section className="space-y-3 rounded border border-line p-3">
            <h3 className="text-sm font-semibold">OpenAI에 전송할 내용</h3>
            {preview.warning && <p className="text-xs text-amber-800">{preview.warning}</p>}
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words text-xs">{preview.payload_preview}</pre>
            {!preview.ai_available && <p className="text-xs text-amber-800">외부 AI가 연결되지 않았습니다. 서버의 API 키 설정을 확인하세요.</p>}
            <label className="flex gap-2 text-xs"><input type="checkbox" disabled={busy || !preview.ai_available} checked={consent} onChange={e => setConsent(e.target.checked)} />위 마스킹된 자료를 OpenAI에 전송하는 데 동의합니다.</label>
            <Button loading={busy} disabled={busy || !consent || !preview.ai_available} onClick={analyze}>{config.action}</Button>
          </section>}
        </Card>
        {mode === "requirements" && <Card className="p-5"><WorkflowEstimate lines={session.estimate_lines} disabled={busy} onChange={estimate_lines => { setSession(current => ({ ...current, estimate_lines })); setDirty(true); setMessage(""); }} /></Card>}
      </div>
      {session.output ? <WorkflowResults key={generation} output={session.output} input={session.input} stale={session.output_stale} busy={busy}
        onAnswer={answer} onDraft={editDraft} onCreate={createDocument} created={created}
        estimateReady={session.estimate_lines.length > 0 && estimateAmounts(session.estimate_lines).total !== null} /> :
        <Card className="space-y-3 p-6"><h2 className="font-semibold">분석 결과와 서류 초안</h2><p className="text-sm text-muted">자료를 입력하고 전송 내용을 확인한 뒤 AI 분석을 실행하세요. 결과에서 근거와 확인 질문을 검토하고, 초안을 편집해 서류로 저장할 수 있습니다.</p></Card>}
    </div>
  </>;
}
