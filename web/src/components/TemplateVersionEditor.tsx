"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useUnsavedChanges } from "@/lib/useUnsavedChanges";
import type { CustomPlanLayout, CustomPlanSection, Template } from "@/lib/types";
import { Button, Card, ErrorText, Input } from "./ui";

export default function TemplateVersionEditor({ template }: { template: Template }) {
  const router = useRouter();
  const original = template.custom_plan!.layout;
  const [layout, setLayout] = useState<CustomPlanLayout>(original);
  const [note, setNote] = useState("");
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const markSaved = useUnsavedChanges(JSON.stringify(layout) !== JSON.stringify(original) || Boolean(note));
  const edit = (next: CustomPlanLayout) => { setLayout(next); setAck(false); };
  const sectionEdit = (index: number, changes: Partial<CustomPlanSection>) => edit({ ...layout, sections: layout.sections.map((section, i) => i === index ? { ...section, ...changes } : section) });
  return <Card className="mt-5 space-y-4 p-5">
    <h2 className="font-semibold">양식 복제·새 버전 만들기</h2>
    <p className="text-sm text-muted">수정한 구성은 새 개인 양식으로 저장합니다. 이미 작성한 문서는 원래 버전의 구성·제목·출력을 유지합니다. 문서 입력 내용은 복사하지 않습니다.</p>
    <ErrorText>{error}</ErrorText>
    <label className="block text-sm">새 버전 제목<Input value={layout.title} maxLength={100} disabled={busy} onChange={e => edit({ ...layout, title: e.target.value })} /></label>
    <ol className="space-y-3">{layout.sections.map((section, index) => <li key={section.key} className="space-y-2 rounded border border-line p-3">
      <label className="block text-sm">{index + 1}. 항목명<Input disabled={busy} value={section.label} maxLength={60} onChange={e => sectionEdit(index, { label: e.target.value })} /></label>
      <div className="flex flex-wrap items-center gap-2 text-xs"><label>입력 형식<select aria-label={`${section.label} 새 버전 형식`} value={section.kind} disabled={busy} onChange={e => sectionEdit(index, e.target.value === "table" ? { kind: "table", columns: ["항목", "내용"] } : { kind: "text", columns: [] })}><option value="text">본문</option><option value="table">표</option></select></label>
        <label><input type="checkbox" checked={section.required} disabled={busy} onChange={e => sectionEdit(index, { required: e.target.checked })} /> 필수</label>
        <Button size="sm" variant="ghost" disabled={busy || index === 0} aria-label={`${section.label} 위로 이동`} onClick={() => { const sections = [...layout.sections]; [sections[index - 1], sections[index]] = [sections[index], sections[index - 1]]; edit({ ...layout, sections }); }}>↑</Button>
        <Button size="sm" variant="ghost" disabled={busy || index === layout.sections.length - 1} aria-label={`${section.label} 아래로 이동`} onClick={() => { const sections = [...layout.sections]; [sections[index + 1], sections[index]] = [sections[index], sections[index + 1]]; edit({ ...layout, sections }); }}>↓</Button>
        <Button size="sm" variant="ghost" disabled={busy || layout.sections.length <= 1 || (layout.document_type !== "free" && ["work_summary", "description"].includes(section.key))} onClick={() => edit({ ...layout, sections: layout.sections.filter(s => s.key !== section.key) })}>제외</Button>
      </div>
      {section.kind === "table" && <div className="space-y-2">{section.columns.map((column, i) => <label key={i} className="block text-xs">{i + 1}열 이름<Input value={column} maxLength={30} disabled={busy} onChange={e => sectionEdit(index, { columns: section.columns.map((c, n) => n === i ? e.target.value : c) })} /></label>)}
        <Button variant="ghost" size="sm" disabled={busy || section.columns.length >= 6} onClick={() => sectionEdit(index, { columns: [...section.columns, "추가 열"] })}>열 추가</Button>
        <Button variant="ghost" size="sm" disabled={busy || section.columns.length <= 2} onClick={() => sectionEdit(index, { columns: section.columns.slice(0, -1) })}>마지막 열 제외</Button>
      </div>}
    </li>)}</ol>
    <Button variant="secondary" size="sm" disabled={busy || layout.sections.length >= 12} onClick={() => {
      const key = Array.from({ length: 99 }, (_, i) => `custom_${i + 1}`).find(key => !layout.sections.some(s => s.key === key));
      if (key) edit({ ...layout, sections: [...layout.sections, { key, label: "추가 항목", kind: "text", columns: [], required: true }] });
    }}>항목 추가</Button>
    <label className="block text-sm">변경 메모<Input maxLength={300} value={note} disabled={busy} onChange={e => setNote(e.target.value)} /></label>
    <label className="flex gap-2 text-sm"><input type="checkbox" checked={ack} disabled={busy} onChange={e => setAck(e.target.checked)} />새 버전의 구성과 필수 항목을 확인했습니다.</label>
    <Button loading={busy} disabled={!ack || !layout.title.trim() || layout.sections.some(s => !s.label.trim())} onClick={async () => {
      setBusy(true); setError("");
      try { const result = await api.post<Template>(`/templates/${template.id}/versions`, { layout, note }); markSaved(); router.push(`/templates/${result.id}`); }
      catch (e) { setError((e as Error).message); } finally { setBusy(false); }
    }}>복제하여 새 버전 저장</Button>
  </Card>;
}
