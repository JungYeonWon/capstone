"use client";

import { useEffect, useState } from "react";
import { useWorkspaceDraft } from "@/lib/useWorkspaceDraft";
import type { Doc } from "@/lib/types";
import { Button, ErrorText } from "@/components/ui";

type Buffer = { values?: Record<string, string>; base_updated_at?: string };

export default function DocumentDraftBuffer({ doc, values, onRestore }: { doc: Doc; values: Record<string, string>; onRestore: (values: Record<string, string>) => void }) {
  const draft = useWorkspaceDraft<Buffer>(doc.contract_id, `document_${doc.id}`, {});
  const [accepted, setAccepted] = useState(false);
  const dirty = JSON.stringify(values) !== JSON.stringify(doc.values);
  const stored = draft.loadedValue?.values;
  const offer = draft.ready && !accepted && stored && JSON.stringify(stored) !== JSON.stringify(doc.values);
  const serialized = JSON.stringify(values);
  const { ready, value: buffered, setValue: setBuffered } = draft;
  useEffect(() => {
    if (!ready || offer) return;
    const next: Buffer = dirty ? { values: JSON.parse(serialized), base_updated_at: doc.updated_at } : {};
    if (JSON.stringify(buffered) !== JSON.stringify(next)) setBuffered(next);
  }, [serialized, dirty, doc.updated_at, offer, ready, buffered, setBuffered]);
  return <div className="mb-4 space-y-2 rounded-lg border border-line bg-slate-50 p-3 text-xs">
    <p role="status">{draft.status} · 출력·미리보기에는 ‘저장하고 미리보기’를 누른 내용이 반영됩니다.</p>
    <ErrorText>{draft.error}</ErrorText>
    {offer && <><p>복원 가능한 임시 저장 내용이 있습니다.{draft.loadedValue?.base_updated_at !== doc.updated_at ? " 저장 문서가 변경된 뒤의 복원이므로 내용을 비교하세요." : ""}</p>
      <Button size="sm" variant="secondary" onClick={() => { onRestore(stored); setAccepted(true); }}>임시 저장 내용 복원</Button>
      <Button size="sm" variant="ghost" onClick={() => { setAccepted(true); void draft.replace({}).catch(() => {}); }}>현재 저장 문서에서 시작</Button>
    </>}
    {dirty && !offer && <Button size="sm" variant="ghost" disabled={!draft.ready} onClick={() => void draft.saveNow().catch(() => {})}>지금 임시 저장</Button>}
  </div>;
}
