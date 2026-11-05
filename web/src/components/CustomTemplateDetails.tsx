"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useUnsavedChanges } from "@/lib/useUnsavedChanges";
import type { Template } from "@/lib/types";
import { Badge, Button, Card, ErrorText, Input, PageHeader } from "./ui";
import TemplateVersionEditor from "./TemplateVersionEditor";

export default function CustomTemplateDetails({ template }: { template: Template }) {
  const router = useRouter();
  const [current, setCurrent] = useState(template);
  const [name, setName] = useState(template.name);
  const [pages, setPages] = useState<{ data: string; width: number; height: number }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [versions, setVersions] = useState<Template[]>([]);
  const [editing, setEditing] = useState(false);
  useEffect(() => {
    let active = true;
    api.get<Template[]>(`/templates/${template.id}/versions`).then(rows => { if (active) setVersions(rows); }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [template.id]);
  useUnsavedChanges(name !== current.name);
  const act = async (fn: () => Promise<void>) => {
    setBusy(true); setError("");
    try { await fn(); } catch(e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return <>
    <PageHeader back={{ href: "/templates", label: "내 양식" }} title={current.name} desc="본인만 사용할 수 있는 맞춤 서류 구성입니다." />
    <ErrorText>{error}</ErrorText>
    <Card className="space-y-4 p-5">
      <div className="flex gap-2"><Badge>내 맞춤 양식 · v{current.custom_plan?.version ?? 1}</Badge><Badge tone="amber">검토용 초안 · 지정 서식 아님</Badge></div>
      {current.custom_plan?.version_note && <p className="text-sm">변경 메모: {current.custom_plan.version_note}</p>}
      <label htmlFor="custom-template-name" className="block text-sm font-medium">라이브러리 표시 이름</label>
      <div className="flex flex-wrap gap-2"><Input id="custom-template-name" maxLength={100} value={name} onChange={e => setName(e.target.value)} disabled={busy} className="max-w-md" /><Button disabled={busy || !name.trim() || name.trim() === current.name} onClick={() => act(async () => {
        const result = await api.put<Template>(`/templates/${current.id}/name`, { name }); setCurrent(result); setName(result.name);
      })}>이름 변경</Button></div>
      <p className="text-xs text-muted">표시 이름 변경은 기존 서류와 출력 제목을 바꾸지 않습니다.</p>
      <h2 className="font-semibold">저장된 구성</h2>
      <ol className="list-inside list-decimal space-y-2 text-sm">{current.custom_plan?.layout.sections.map(section => <li key={section.key}>{section.label} · {section.kind === "table" ? `표 (${section.columns.join(" / ")})` : "본문"}{section.required ? " · 필수 입력" : ""}</li>)}</ol>
      <p className="text-xs text-muted">{current.custom_plan?.reference}</p>
      <p className="text-sm">계약의 서류 검색 또는 자체 양식 목록에서 이 양식을 추가하면, 해당 계약의 정보로 새 초안을 작성합니다. 이전 계약의 입력 내용은 복사하지 않습니다.</p>
      <div className="flex flex-wrap gap-2"><Link href="/dashboard" className="text-sm text-primary underline">계약에서 이 양식 사용하기 →</Link>
        <Button variant="secondary" size="sm" disabled={busy} onClick={() => act(async () => { const result = await api.get<{ pages: typeof pages }>(`/templates/${current.id}/review-preview-pages`); setPages(result.pages); })}>샘플 미리보기</Button>
        <Button variant="secondary" size="sm" disabled={busy} onClick={() => act(() => api.download(`/templates/${current.id}/sample-file`, "맞춤양식_샘플.hwpx"))}>샘플 HWPX</Button>
        <Button variant="danger" size="sm" disabled={busy} onClick={() => { if (confirm("저장된 맞춤 양식을 삭제할까요? 이 양식을 쓰는 서류가 있으면 먼저 서류를 삭제해야 합니다.")) void act(async () => { await api.del(`/templates/${current.id}`); router.replace("/templates"); }); }}>양식 삭제</Button>
      </div>
    </Card>
    <Card className="mt-5 space-y-3 p-5"><h2 className="font-semibold">버전 이력</h2><ul className="space-y-2 text-sm">{versions.map(version => <li key={version.id}><Link className="text-primary underline" href={`/templates/${version.id}`}>v{version.custom_plan?.version ?? 1} · {version.name}</Link>{version.id === current.id && " · 현재 버전"}</li>)}</ul><Button variant="secondary" disabled={busy} onClick={() => setEditing(previous => !previous)}>{editing ? "구성 편집 닫기" : "복제·새 버전 구성 편집"}</Button></Card>
    {editing && <TemplateVersionEditor key={current.id} template={current} />}
    {pages.length > 0 && <div className="mt-5 space-y-4"><p className="text-sm text-muted">가상 샘플 정보의 출력입니다. 실제 서류는 계약에서 추가하여 작성하세요.</p>{pages.map((page,index) => <figure key={index} className="mx-auto max-w-[720px]">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={page.data} alt={`맞춤 양식 샘플 ${index+1}페이지`} width={page.width} height={page.height} className="h-auto w-full bg-white shadow-sm" />
    </figure>)}</div>}
  </>;
}
