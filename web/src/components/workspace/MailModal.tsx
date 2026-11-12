"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { Doc } from "@/lib/types";
import { Button, ErrorText, Field, Input, Modal, Textarea } from "@/components/ui";

const FORMATS = [
  { id: "native", label: "원본(한글/Excel)" },
  { id: "pdf", label: "PDF" },
  { id: "both", label: "원본+PDF" },
];

export default function MailModal({ onClose, contractId, docs }: { onClose: () => void; contractId: number; docs: Doc[] }) {
  const [to, setTo] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [format, setFormat] = useState("native");
  const [selected, setSelected] = useState<number[]>(docs.map((d) => d.id));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");

  const send = async () => {
    setLoading(true);
    setError("");
    try {
      const r = await api.post<{ mock: boolean; count: number }>(`/contracts/${contractId}/mail`, { to, subject, body, format, document_ids: selected });
      setDone(r.mock ? `MOCK 모드: 실제 발송 없이 ${r.count}건 처리했습니다. (SMTP 설정 시 실제 발송)` : `${to}로 ${r.count}건을 보냈습니다.`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal open onClose={onClose} title="메일로 제출">
      {done ? (
        <div className="space-y-4">
          <p className="rounded-lg bg-emerald-50 px-3 py-3 text-sm text-emerald-700">{done}</p>
          <div className="flex justify-end">
            <Button onClick={onClose}>닫기</Button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <Field label="받는 사람" required>
            <Input type="email" value={to} onChange={(e) => setTo(e.target.value)} placeholder="manager@client.go.kr" />
          </Field>
          <Field label="제목" hint="비워두면 “[회사명] 계약명 관련 서류 제출”">
            <Input value={subject} onChange={(e) => setSubject(e.target.value)} />
          </Field>
          <Field label="본문">
            <Textarea rows={3} value={body} onChange={(e) => setBody(e.target.value)} placeholder="비워두면 기본 문구가 들어갑니다." />
          </Field>
          <div>
            <div className="mb-1.5 text-[13px] font-medium text-gray-700">첨부 서류</div>
            <div className="flex flex-wrap gap-2">
              {docs.map((d) => (
                <label key={d.id} className="flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5 text-sm">
                  <input
                    type="checkbox"
                    checked={selected.includes(d.id)}
                    onChange={(e) => setSelected(e.target.checked ? [...selected, d.id] : selected.filter((x) => x !== d.id))}
                  />
                  {d.title}
                </label>
              ))}
            </div>
            {docs.some(doc => selected.includes(doc.id) && doc.requires_seal_approval) && <p className="mt-2 text-xs text-muted">선택한 AI 자유 양식은 인감 없는 파일로 첨부됩니다.</p>}
          </div>
          <div className="flex gap-3 text-sm">
            {FORMATS.map((f) => (
              <label key={f.id} className="flex items-center gap-1">
                <input type="radio" checked={format === f.id} onChange={() => setFormat(f.id)} /> {f.label}
              </label>
            ))}
          </div>
          <ErrorText>{error}</ErrorText>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={onClose}>
              취소
            </Button>
            <Button onClick={send} loading={loading} disabled={!to || selected.length === 0}>
              보내기
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
