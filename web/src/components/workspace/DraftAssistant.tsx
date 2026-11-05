"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useWorkspaceDraft } from "@/lib/useWorkspaceDraft";
import type { Doc, Template } from "@/lib/types";
import { Button, Card, ErrorText, Textarea } from "@/components/ui";
import TableFieldEditor from "@/components/TableFieldEditor";

type Question = { key: string; label: string; question: string; kind: "table" | "text"; columns: string[] };
type Transfer = { payload_preview: string; consent_digest: string; ai_available: boolean; questions: Question[] };
type Suggestion = { values: Record<string, string>; mode: string; warning: string; notice: string; questions: Question[] };

export default function DraftAssistant({ doc, template, values, onApply }: { doc: Doc; template: Template; values: Record<string, string>; onApply: (key: string, text: string) => void }) {
  const answers = useWorkspaceDraft<{ answers: Record<string, string> }>(doc.contract_id, `answers_${doc.id}`, { answers: {} });
  const [useAi, setUseAi] = useState(false);
  const [consent, setConsent] = useState(false);
  const [transfer, setTransfer] = useState<Transfer | null>(null);
  const [confirmed, setConfirmed] = useState("");
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pendingApply, setPendingApply] = useState<{ key: string; text: string } | null>(null);
  const snapshot = JSON.stringify({ values, answers: answers.value.answers });
  const current = confirmed === snapshot;
  const sections = template.custom_plan?.layout.sections ?? [];
  const act = async (fn: () => Promise<void>) => {
    setBusy(true); setError("");
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return <Card className="mb-5 space-y-4 p-5">
    <h2 className="font-semibold">항목별 본문 작성 도우미</h2>
    <p className="text-sm text-muted">부족한 정보를 답변하면 확인된 내용으로 초안을 제안합니다. 모르는 사실은 빈칸으로 두세요. 제안은 선택한 항목에만 반영되며 저장 전 검토할 수 있습니다.</p>
    <ErrorText>{error || answers.error}</ErrorText>
    <p role="status" className="text-xs text-muted">답변: {answers.status}</p>
    <Button variant="secondary" disabled={busy || !answers.ready} onClick={() => act(async () => {
      setTransfer(await api.post<Transfer>(`/documents/${doc.id}/draft/preview`, { values, answers: answers.value.answers })); setConfirmed(snapshot); setConsent(false); setSuggestion(null);
    })}>부족한 정보 질문 확인</Button>
    {transfer && <div className="space-y-3">
      {transfer.questions.length === 0 && <p className="text-sm">필수 항목이 채워져 있습니다. 필요한 항목을 제안받아 비교할 수 있습니다.</p>}
      {transfer.questions.map(question => <div key={question.key} className="space-y-2"><p className="text-sm">{question.question}</p>
        {question.kind === "table" ? <TableFieldEditor id={`answer-${question.key}`} columns={question.columns} value={answers.value.answers[question.key] ?? ""} disabled={busy} onChange={text => answers.setValue(previous => ({ answers: { ...previous.answers, [question.key]: text } }))} /> : <Textarea aria-label={`${question.label} 확인된 답변`} maxLength={10000} rows={2} value={answers.value.answers[question.key] ?? ""} disabled={busy} onChange={e => answers.setValue(previous => ({ answers: { ...previous.answers, [question.key]: e.target.value } }))} />}
      </div>)}
    </div>}
    {transfer && !current && <p className="text-xs text-amber-800">답변 또는 문서 내용이 바뀌었습니다. 질문·전송 내용을 다시 확인하세요.</p>}
    <label className="flex gap-2 text-sm"><input type="checkbox" checked={useAi} disabled={busy} onChange={e => { setUseAi(e.target.checked); setConsent(false); }} />외부 AI로 본문 제안 받기</label>
    {useAi && transfer && current && <div className="space-y-2 rounded-lg border border-line p-3">
      <p className="text-xs text-muted">회사·계약의 일부 정보, 원래 요청과 아래 답변이 OpenAI로 전송됩니다. 영업기밀이 남아 있는지 확인하세요. 계좌·인감은 자동 첨부하지 않습니다.</p>
      <Textarea aria-label="본문 작성 AI 전송 내용" readOnly rows={7} value={transfer.payload_preview} />
      {!transfer.ai_available && <p className="text-sm text-amber-800">외부 AI가 연결되어 있지 않습니다. 로컬 제안은 사용할 수 있습니다.</p>}
      <label className="flex gap-2 text-sm"><input type="checkbox" checked={consent} disabled={busy || !transfer.ai_available} onChange={e => setConsent(e.target.checked)} />위 내용을 이번 요청에 전송하는 데 동의합니다.</label>
    </div>}
    <Button loading={busy} disabled={!answers.ready || (useAi && (!current || !transfer?.ai_available || !consent))} onClick={() => act(async () => {
      await answers.saveNow();
      setSuggestion(await api.post<Suggestion>(`/documents/${doc.id}/draft/suggest`, { values, answers: answers.value.answers, use_ai: useAi, consent_digest: useAi ? transfer?.consent_digest : "" }));
    })}>{useAi ? "AI 본문 제안" : "답변으로 로컬 초안 제안"}</Button>
    {suggestion && <div className="space-y-3 border-t border-line pt-4">
      <p className="text-sm">{suggestion.mode === "ai" ? "AI 작성 제안" : "확인된 답변·로컬 문장 제안"} · {suggestion.notice}</p>
      {suggestion.warning && <p role="status" className="text-sm text-amber-800">{suggestion.warning}</p>}
      {Object.entries(suggestion.values).map(([key, text]) => <div key={key} className="space-y-2 rounded border border-line p-3"><h3 className="text-sm font-medium">{sections.find(s => s.key === key)?.label ?? key}</h3><pre className="whitespace-pre-wrap break-words text-xs">{text}</pre><Button size="sm" variant="secondary" disabled={busy} onClick={() => { if (values[key]?.trim()) setPendingApply({ key, text }); else onApply(key, text); }}>이 항목에 반영</Button>
        {pendingApply?.key === key && <div role="alert" className="space-y-2 rounded bg-amber-50 p-3 text-sm"><p>이 항목의 기존 입력을 제안으로 바꿀까요?</p><Button size="sm" onClick={() => { onApply(pendingApply.key, pendingApply.text); setPendingApply(null); }}>기존 입력을 제안으로 교체</Button><Button size="sm" variant="ghost" onClick={() => setPendingApply(null)}>취소</Button></div>}
      </div>)}
      {Object.keys(suggestion.values).length === 0 && <p className="text-sm">작성할 근거가 부족합니다. 질문에 확인된 내용을 입력하세요.</p>}
    </div>}
  </Card>;
}
