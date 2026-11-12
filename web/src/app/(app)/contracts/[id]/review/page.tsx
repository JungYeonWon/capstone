"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Badge, Button, Card, ErrorText, PageHeader, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { useQueryParam } from "@/lib/hooks";
import type { Doc } from "@/lib/types";

type ReviewFile = {
  name: string;
  parts: { page: number | null; text: string }[];
  warning: string;
};
type Transmission = { payload_preview: string; consent_digest: string; ai_available: boolean; warning: string };
type Finding = {
  category: string;
  title: string;
  impact: string;
  question: string;
  evidence: { name: string; page: number | null; quote: string }[];
};
type Result = { findings: Finding[]; excluded: number };

export default function ContractReviewPage() {
  const { id } = useParams<{ id: string }>();
  const document = useQueryParam("document") ?? "";
  const [docs, setDocs] = useState<Doc[]>([]);
  const [selection, setSelection] = useState<string | null>(null);
  const [role, setRole] = useState<"supplier" | "client">("supplier");
  const [files, setFiles] = useState<ReviewFile[]>([]);
  const [transmission, setTransmission] = useState<Transmission | null>(null);
  const [consent, setConsent] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
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

  function invalidateReview() {
    setTransmission(null);
    setConsent(false);
    setResult(null);
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
    setBusy(action === "preview" ? "전송 내용 준비 중" : "계약 조항 검토 중");
    setError("");
    const body = {
      role,
      document_id: docId ? Number(docId) : null,
      files: files.map(({ name, parts }) => ({ name, parts })),
    };
    try {
      if (action === "preview") {
        setConsent(false);
        setResult(null);
        setTransmission(null);
        setTransmission(await api.post<Transmission>(`${base}/preview`, body));
      } else {
        setResult(null);
        setResult(await api.post<Result>(`${base}/analyze`, { ...body, consent_digest: transmission?.consent_digest }));
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  return <>
    <PageHeader back={{ href: `/contracts/${id}`, label: "계약으로 돌아가기" }} title="AI 계약서 검토"
      desc="체결할 계약서와 별첨에서 확인이 필요한 조건을 찾습니다." />
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
          <Button loading={busy === "계약 조항 검토 중"} disabled={!consent || !!busy} onClick={() => run("analyze")}>AI로 계약서 검토</Button>
        </div>}
        {busy && <p role="status" className="text-sm text-muted">{busy}</p>}
        <div className="whitespace-pre-wrap"><ErrorText>{error}</ErrorText></div>
      </Card>
      <Card className="space-y-4 self-start p-5">
        <h2 className="font-semibold">검토 결과</h2>
        {!result ? <p className="text-sm text-muted">검토를 실행하면 관련 조항의 원문, 우리 쪽 부담, 확인할 질문을 보여줍니다.</p> : <>
          <p className="text-sm">확인할 조항 {result.findings.length}건</p>
          <p className="text-xs text-muted">AI가 읽은 텍스트의 결과입니다. 계약서와 별첨의 최종본을 직접 확인하세요. 이 화면을 닫으면 결과가 사라집니다.</p>
          {result.excluded > 0 && <p role="status" className="text-sm text-amber-800">근거 또는 표시 형식을 확인하지 못한 결과 {result.excluded}건을 제외했습니다.</p>}
          {result.findings.map((finding, index) => <article key={index} className="space-y-3 rounded-lg border border-line p-4">
            <Badge tone="amber">{finding.category}</Badge>
            <h3 className="font-semibold">{finding.title}</h3>
            {finding.evidence.map((evidence, quoteIndex) => <blockquote key={quoteIndex} className="break-words rounded-lg bg-slate-50 p-3 text-sm">
              <p className="mb-1 text-xs font-medium text-muted">{evidence.name}{evidence.page ? ` · ${evidence.page}쪽` : ""}</p>
              {evidence.quote}
            </blockquote>)}
            <p className="text-sm">{finding.impact}</p>
            <p className="text-sm"><strong>확인할 질문</strong> · {finding.question}</p>
          </article>)}
        </>}
      </Card>
    </div>
  </>;
}
