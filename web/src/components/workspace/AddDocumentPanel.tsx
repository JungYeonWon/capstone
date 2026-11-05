"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import type { Template } from "@/lib/types";
import { Badge, Button, Card, ErrorText, Input, Spinner } from "@/components/ui";
import CustomPlanBuilder from "./CustomPlanBuilder";
import NoticeChecklist from "./NoticeChecklist";
import { PastNoticeBadge } from "@/components/TemplateExtras";

type SearchRes = { results: { template: Template; score: number; ai: boolean; reason: string }[]; ai_enabled: boolean };

const TABS = [
  { id: "search", label: "서류 검색", sub: "CASE 1 · 기본 양식" },
  { id: "upload", label: "자체 양식", sub: "CASE 2 · 업로드" },
  { id: "custom", label: "맞춤 초안", sub: "CASE 3 · 구성 만들기" },
  { id: "notice", label: "안내문 분석", sub: "제출 체크리스트" },
] as const;

function Row({ t, badge, adding, onAdd }: { t: Template; badge?: ReactNode; adding: boolean; onAdd: () => void }) {
  return (
    <li className="flex items-center justify-between gap-2 py-2.5">
      <div className="min-w-0">
        <div className="flex items-center gap-1.5 text-sm font-medium">
          {t.name} {t.kind === "custom" && <Badge tone="amber">맞춤 초안</Badge>} <Badge tone="gray">{t.output_format === "xlsx" ? "Excel" : t.output_format === "hwpx" ? "한글" : t.output_format === "pdf" ? "PDF" : "Word"}</Badge> <PastNoticeBadge template={t} /> {badge}
        </div>
        <div className="truncate text-xs text-muted">{t.description}</div>
      </div>
      <Button size="sm" variant="secondary" loading={adding} onClick={onAdd}>
        추가
      </Button>
    </li>
  );
}

export default function AddDocumentPanel({ contractId, clientName, onAdd, onDocumentsChanged, onChecklistChanged }: { contractId: number; clientName: string; onAdd: (templateId: number, projectCode?: string) => Promise<void>; onDocumentsChanged: () => Promise<void>; onChecklistChanged: () => void }) {
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("search");
  const [q, setQ] = useState("");
  const [projectCode, setProjectCode] = useState("");
  const [error, setError] = useState("");
  const [res, setRes] = useState<SearchRes | null>(null);
  const [searching, setSearching] = useState(false);
  const [mine, setMine] = useState<Template[]>([]);
  const [adding, setAdding] = useState<number | null>(null);

  useEffect(() => {
    let active = true;
    const t = setTimeout(() => {
      setSearching(true);
      api
        .get<SearchRes>(`/templates/search?q=${encodeURIComponent(q)}&contract_id=${contractId}&project_code=${encodeURIComponent(projectCode)}`)
        .then(r => { if (active) { setRes(r); setError(""); } })
        .catch(e => { if (active) setError(e.message); })
        .finally(() => { if (active) setSearching(false); });
    }, 250);
    return () => { active = false; clearTimeout(t); };
  }, [q, contractId, clientName, projectCode]);

  useEffect(() => {
    if (tab === "upload") api.get<Template[]>("/templates").then((t) => setMine(t.filter((x) => x.status === "ready" && x.library.scope === "private"))).catch(e => setError(e.message));
  }, [tab]);

  const add = async (id: number) => {
    setAdding(id);
    try {
      await onAdd(id, projectCode);
    } finally {
      setAdding(null);
    }
  };

  return (
    <Card>
      <div className="grid grid-cols-2 border-b border-line">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-2 py-3 text-center ${tab === t.id ? "border-b-2 border-primary text-primary" : "text-muted hover:text-foreground"}`}
          >
            <div className="text-[13px] font-semibold">{t.label}</div>
            <div className="text-[11px] opacity-80">{t.sub}</div>
          </button>
        ))}
      </div>

      <div className="p-4">
        <ErrorText>{error}</ErrorText>
        {tab === "search" && (
          <>
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="예: 착수신고서 내라고 하네요" />
            <Input className="mt-2" value={projectCode} onChange={e => setProjectCode(e.target.value)} placeholder="공고·사업번호 (해당 시)" />
            <p className="mt-2 text-xs text-muted">발주처: {clientName || "미입력"} · 사업 지정 → 발주처 지정 → 공통 양식 순으로 추천합니다.</p>
            <p className="mt-1.5 text-xs text-muted">요청받은 문장 그대로 입력해도 됩니다. {res && !res.ai_enabled && "(현재 동의어 사전 기반 검색)"}</p>
            {searching && !res ? (
              <div className="py-6 text-center text-muted">
                <Spinner />
              </div>
            ) : (
              <ul className="mt-2 divide-y divide-line">
                {res?.results.map((r) => (
                  <Row
                    key={r.template.id}
                    t={r.template}
                    adding={adding === r.template.id}
                    onAdd={() => add(r.template.id)}
                    badge={
                      <>
                        {r.template.kind === "uploaded" && <Badge tone="blue">자체</Badge>}
                        {q && r.score >= 0.8 && <Badge tone="indigo">추천</Badge>}
                        {r.ai && <Badge tone="green">AI</Badge>}
                        <span className="text-xs text-muted">{r.reason}</span>
                      </>
                    }
                  />
                ))}
                {res && res.results.length === 0 && <li className="py-6 text-center text-sm text-muted">일치하는 양식이 없습니다. 자체 양식을 업로드해 보세요.</li>}
              </ul>
            )}
          </>
        )}

        {tab === "upload" && (
          <>
            <div className="rounded-lg border border-dashed border-line bg-gray-50 p-4 text-center">
              <p className="text-sm">기업이 보내준 한글·Word·PDF 양식을 올리면 입력 항목을 분석해 자동으로 채웁니다.</p>
              <Link
                href={`/templates/upload?contract=${contractId}`}
                className="mt-3 inline-flex h-9 items-center rounded-lg bg-primary px-4 text-sm font-medium text-white hover:bg-indigo-700"
              >
                양식 업로드하기
              </Link>
            </div>
            <div className="mt-4 text-xs font-medium text-muted">내 저장 양식</div>
            <ul className="divide-y divide-line">
              {mine.map((t) => (
                <Row key={t.id} t={t} adding={adding === t.id} onAdd={() => add(t.id)} />
              ))}
              {mine.length === 0 && <li className="py-4 text-center text-sm text-muted">아직 업로드한 양식이 없습니다.</li>}
            </ul>
          </>
        )}

        <div hidden={tab !== "custom"}><CustomPlanBuilder key={`builder-${contractId}`} contractId={contractId} /></div>
        <div hidden={tab !== "notice"}><NoticeChecklist key={`notice-${contractId}`} contractId={contractId} active={tab === "notice"} onDocumentsChanged={onDocumentsChanged} onChecklistChanged={onChecklistChanged} /></div>
      </div>
    </Card>
  );
}
