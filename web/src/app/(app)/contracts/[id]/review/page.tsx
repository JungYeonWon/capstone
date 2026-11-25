"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, Card, ErrorText, PageHeader, Textarea } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useQueryParam } from "@/lib/hooks";
import type { Doc } from "@/lib/types";
import { questionText, reviewDate, type ReviewRecord, type ReviewSummary, type ReviewEdit } from "@/lib/review-history";
import { useUnsavedChanges } from "@/lib/useUnsavedChanges";
import ReviewResultPanel from "@/components/workspace/ReviewResultPanel";
import ReviewComparison from "@/components/workspace/ReviewComparison";

type ReviewFile = {
  name: string;
  parts: { page: number | null; text: string }[];
  warning: string;
};
type Transmission = { payload_preview: string; consent_digest: string; ai_available: boolean; warning: string };

export default function ContractReviewPage() {
  const { id } = useParams<{ id: string }>();
  const document = useQueryParam("document") ?? "";
  const [docs, setDocs] = useState<Doc[]>([]);
  const [selection, setSelection] = useState<string | null>(null);
  const [role, setRole] = useState<"supplier" | "client">("supplier");
  const [files, setFiles] = useState<ReviewFile[]>([]);
  const [transmission, setTransmission] = useState<Transmission | null>(null);
  const [consent, setConsent] = useState(false);
  const [result, setResult] = useState<ReviewRecord | null>(null);
  const [history, setHistory] = useState<ReviewSummary[]>([]);
  const [edits, setEdits] = useState<Record<number, ReviewEdit>>({});
  const [copyFallback, setCopyFallback] = useState("");
  const [message, setMessage] = useState("");
  const [deleting, setDeleting] = useState<number | null>(null);
  const [inputVersion, setInputVersion] = useState(0);
  useUnsavedChanges(Object.keys(edits).length > 0);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [retryAI, setRetryAI] = useState(false);
  const [unreadFiles, setUnreadFiles] = useState<string[]>([]);
  const base = `/contracts/${id}/clause-review`;
  const docId = selection ?? (docs.some(doc => String(doc.id) === document) ? document : "");

  useEffect(() => {
    let active = true;
    api.get<Doc[]>(`/contracts/${id}/documents`)
      .then(items => { if (active) setDocs(items.filter(doc => doc.template_kind !== "builtin")); })
      .catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [id]);

  async function refreshHistory() { setHistory(await api.get<ReviewSummary[]>(`${base}/history`)); }
  useEffect(() => {
    let alive = true;
    api.get<ReviewSummary[]>(`${base}/history`).then(items => { if (alive) setHistory(items); }).catch(e => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [base]);
  const currentBody = { role, document_id: docId ? Number(docId) : null, files: files.map(({ name, parts, warning }) => ({ name, parts, warning })) };
  const currentFiles = [...(docId ? [{ name: docs.find(d => String(d.id) === docId)?.title || "저장 문서" }] : []), ...files].map((f, i) => ({ key: String(i + 1), name: f.name }));
  async function loadReview(reviewId: number) {
    if (Object.keys(edits).length) { setError("미저장 상태·메모를 저장하거나 입력을 취소한 뒤 이력을 여세요."); return; }
    setBusy("검토 이력 불러오는 중"); setError("");
    try { setResult(await api.get<ReviewRecord>(`${base}/history/${reviewId}`)); setCopyFallback(""); setMessage(""); }
    catch (e) { setError((e as Error).message); } finally { setBusy(""); }
  }
  async function saveFinding(index: number) {
    if (!result || !edits[index]) return;
    setBusy("처리 기록 저장 중"); setError("");
    try {
      const next = await api.put<ReviewRecord>(`${base}/history/${result.id}/findings/${index}`, { ...edits[index], revision: result.revision });
      setResult(next); setEdits(previous => { const next = { ...previous }; delete next[index]; return next; });
      setCopyFallback(""); setMessage("처리 상태와 메모를 저장했습니다."); await refreshHistory();
    } catch (e) { setError((e as Error).message); } finally { setBusy(""); }
  }
  async function copyQuestions(all: boolean) {
    if (!result) return;
    const text = questionText(result, all);
    if (!text) { setMessage("복사할 질문이 없습니다."); setCopyFallback(""); return; }
    setCopyFallback(text);
    try { await navigator.clipboard.writeText(text); setMessage("질문을 복사했습니다."); }
    catch { setMessage("자동 복사가 허용되지 않았습니다. 질문 모음에서 직접 선택해 복사하세요."); }
  }
  async function downloadReport() {
    if (!result) return;
    setBusy("보고서 준비 중"); setError("");
    try { await api.download(`${base}/history/${result.id}/pdf`, `contract-review-${result.id}.pdf`); }
    catch (e) { setError((e as Error).message); } finally { setBusy(""); }
  }
  function invalidateReview() {
    setRetryAI(false);
    setInputVersion(previous => previous + 1);
    setTransmission(null);
    setConsent(false);
    setError("");
  }

  async function addFiles(selected: File[]) {
    if (!selected.length) return;
    if (selected.length + files.length > 5) {
      setError("계약서와 별첨을 합쳐 파일은 최대 5개까지 추가할 수 있습니다.");
      return;
    }
    invalidateReview();
    setUnreadFiles([]);
    setBusy("파일을 읽는 중");
    const failures: string[] = [];
    try {
      for (const file of selected) {
        try {
          const source = await api.upload<ReviewFile>(`${base}/extract`, file);
          setFiles(previous => [...previous, source]);
        } catch (e) {
          failures.push(`${file.name} · ${(e as Error).message}`);
        }
      }
      setUnreadFiles(failures);
    } finally {
      setBusy("");
    }
  }

  async function run(action: "preview" | "analyze") {
    if (Object.keys(edits).length) { setError("미저장 상태·메모를 먼저 저장하거나 입력을 취소하세요."); return; }
    setBusy(action === "preview" ? "전송 내용 준비 중" : "계약 조항 검토 중");
    setError("");
    const body = currentBody;
    try {
      if (action === "preview") {
        setConsent(false);
        setTransmission(null);
        setTransmission(await api.post<Transmission>(`${base}/preview`, body));
      } else {
        const saved = await api.post<ReviewRecord>(`${base}/analyze`, { ...body, consent_digest: transmission?.consent_digest });
        setResult(saved); setEdits({}); setCopyFallback(""); setConsent(false);
        setMessage("검토 결과가 암호화 저장됐습니다. 이력에서 다시 열 수 있습니다."); await refreshHistory();
      }
    } catch (e) {
      setError((e as Error).message);
      if (action === "analyze") setRetryAI(e instanceof ApiError && e.retryable);
    } finally {
      setBusy("");
    }
  }

  return <>
    <PageHeader back={{ href: `/contracts/${id}`, label: "계약으로 돌아가기" }} title="AI 계약서 검토"
      desc="체결할 계약서와 별첨에서 확인이 필요한 조건을 찾습니다." />
    <Card className="mb-5 space-y-3 p-4">
      <h2 className="font-semibold">저장된 검토 이력 ({history.length}/50)</h2>
      <p className="text-xs text-muted">검토 당시 전송 텍스트·원문 인용·결과를 암호화 보관합니다. 계약 삭제·내 데이터 삭제 시 함께 삭제됩니다.</p>
      <ErrorText>{error}</ErrorText>{message && <p role="status" className="text-sm text-primary">{message}</p>}
      {!!Object.keys(edits).length && <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => setEdits({})}>미저장 상태·메모 입력 취소</Button>}
      {!history.length && <p className="text-xs text-muted">아직 저장된 검토가 없습니다. 새 검토를 실행하면 자동 저장됩니다.</p>}
      <ul className="max-h-64 space-y-2 overflow-y-auto">{history.map(row => <li key={row.id} className="flex flex-wrap items-center gap-2 rounded border border-line p-2">
        <Button size="sm" variant={result?.id === row.id ? "primary" : "secondary"} disabled={!!busy} onClick={() => void loadReview(row.id)}>#{row.id} · {reviewDate(row.created_at)}</Button>
        <span className="break-words text-xs">{row.role === "supplier" ? "수행사" : "발주처"} · {row.source_files.map(f => f.name).join(", ")} · 처리 {row.resolved_count}/{row.finding_count}</span>
        {deleting === row.id ? <><span className="text-xs">이 이력을 삭제할까요? 복구할 수 없습니다.</span><Button size="sm" variant="danger" disabled={!!busy || !!Object.keys(edits).length} onClick={async () => {
          setBusy("이력 삭제 중"); setError("");
          try { await api.del(`${base}/history/${row.id}`); if (result?.id === row.id) { setResult(null); setCopyFallback(""); } setDeleting(null); await refreshHistory(); }
          catch (e) { setError((e as Error).message); } finally { setBusy(""); }
        }}>삭제 확인</Button><Button size="sm" variant="ghost" disabled={!!busy} onClick={() => setDeleting(null)}>취소</Button></> : <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => setDeleting(row.id)}>이력 삭제</Button>}
      </li>)}</ul>
    </Card>
    <div className="grid gap-5 lg:grid-cols-[minmax(280px,1fr)_minmax(0,1.45fr)]">
      <Card className="space-y-4 self-start p-5">
        <label className="block text-sm font-medium">우리 쪽 역할
          <select className="mt-1 block w-full rounded-lg border border-line bg-white p-2" value={role} disabled={!!busy}
            onChange={event => { setRole(event.target.value as typeof role); invalidateReview(); }}>
            <option value="supplier">수행사</option>
            <option value="client">발주처</option>
          </select>
        </label>
        {docs.length > 0 && <div className="space-y-2">
          <label className="block text-sm font-medium">계약서 저장본
            <select className="mt-1 block w-full rounded-lg border border-line bg-white p-2" value={docId} disabled={!!busy}
              onChange={event => { setSelection(event.target.value); invalidateReview(); }}>
              <option value="">저장본 선택 안 함</option>
              {docs.map(doc => <option key={doc.id} value={doc.id}>{doc.title}</option>)}
            </select>
          </label>
          {docId && <Link href={`/contracts/${id}/documents/${docId}`} target="_blank" rel="noopener"
            className="text-sm text-primary underline">저장된 문서 미리보기 ↗</Link>}
        </div>}
        <label className="block text-sm font-medium">계약서·특수조건·별첨 업로드
          <input type="file" multiple accept=".pdf,.hwp,.hwpx,.docx,.txt" disabled={!!busy || files.length >= 5}
            className="mt-2 block w-full text-sm text-muted" onChange={event => {
              const selected = Array.from(event.currentTarget.files ?? []);
              event.currentTarget.value = "";
              void addFiles(selected);
            }} />
        </label>
        <p className="text-xs text-muted">PDF·HWP·HWPX·DOCX·TXT, 파일당 3MB 이하. PDF는 20쪽까지 읽습니다.</p>
        {unreadFiles.length > 0 && <ul className="space-y-1 text-sm text-amber-800">
          {unreadFiles.map((message, index) => <li key={index}>검토에서 빠진 파일 · {message}</li>)}
        </ul>}
        {files.length > 0 && <ul className="space-y-2">{files.map((file, index) => <li key={index} className="rounded-lg border border-line p-3">
          <div className="flex items-center justify-between gap-3">
            <span className="min-w-0 break-all text-sm">{file.name}</span>
            <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => {
              setFiles(previous => previous.filter((_, i) => i !== index));
              invalidateReview();
            }}>제거</Button>
          </div>
          {file.warning && <p className="mt-1 text-xs text-amber-800">{file.warning}</p>}
        </li>)}</ul>}
        <Button variant="secondary" disabled={!!busy || (!docId && !files.length)} onClick={() => run("preview")}>AI 전송 내용 확인</Button>
        {transmission && <div className="space-y-3 border-t border-line pt-4">
          {transmission.warning && <p className="text-sm text-amber-800">{transmission.warning}</p>}
          <p className="text-xs text-muted">아래에 표시된 텍스트가 OpenAI로 전송됩니다. 마스킹 후 남아 있는 기밀 정보가 있는지 확인하세요.</p>
          <Textarea rows={8} readOnly value={transmission.payload_preview} aria-label="AI 전송 내용" className="text-xs" />
          {transmission.ai_available ? <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-1" checked={consent} disabled={!!busy}
              onChange={event => setConsent(event.target.checked)} />위 내용의 이번 AI 전송에 동의합니다.
          </label> : <p className="text-sm text-amber-800">외부 AI가 연결되어 있지 않습니다.</p>}
          <Button loading={busy === "계약 조항 검토 중"} disabled={!consent || !!busy} onClick={() => run("analyze")}>{retryAI ? "AI 검토 다시 시도" : "AI로 계약서 검토"}</Button>
        </div>}
        {busy && <p role="status" className="text-sm text-muted">{busy}</p>}
        <div className="whitespace-pre-wrap"><ErrorText>{error}</ErrorText></div>
      </Card>
      <ReviewResultPanel record={result} edits={edits} busy={!!busy} onEdit={(index, edit) => setEdits(previous => {
        const next = { ...previous }; const original = result?.findings[index];
        if (original && original.status === edit.status && original.note === edit.note) delete next[index]; else next[index] = edit;
        return next;
      })} onSave={index => void saveFinding(index)} onDownload={() => void downloadReport()} onCopy={all => void copyQuestions(all)} copyFallback={copyFallback} />
    </div>
    {result && <ReviewComparison key={`${result.id}-${inputVersion}`} base={base} before={result} history={history} draftBody={currentBody} draftFiles={currentFiles} blocked={!!busy || !!Object.keys(edits).length} />}
  </>;
}
