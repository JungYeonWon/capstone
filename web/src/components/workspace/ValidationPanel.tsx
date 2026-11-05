"use client";

import Link from "next/link";
import type { ValidationResult } from "@/lib/types";
import { Badge, Card, CardHeader } from "@/components/ui";

export default function ValidationPanel({ result, contractId }: { result: ValidationResult; contractId: number }) {
  const { summary, issues, ai_comments } = result;
  return (
    <Card>
      <CardHeader
        title="제출 전 통합 점검"
        desc={`서류 ${summary.documents}건 · 오류 ${summary.errors} · 주의 ${summary.warnings}`}
        action={summary.ready_for_submission ? <Badge tone="green">자동 점검 통과 · 제출 조건 별도 확인</Badge> : <Badge tone="amber">확인·수정 필요</Badge>}
      />
      <p className="px-5 py-3 text-xs text-muted">필수값·금액·기간·서류 간 불일치·미확정 문구·표 빈칸·체크리스트와 임시 저장을 함께 확인합니다. 발주처 승인이나 실제 제출 완료를 의미하지 않습니다.</p>
      {issues.length === 0 && ai_comments.length === 0 ? (
        <div className="px-5 py-8 text-center text-sm text-emerald-700">누락·오류·서류 간 불일치가 없습니다 ✓</div>
      ) : (
        <ul className="divide-y divide-line">
          {issues.map((i, idx) => (
            <li key={idx} className="flex gap-3 px-5 py-3">
              <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${i.severity === "error" ? "bg-red-500" : "bg-amber-400"}`} />
              <div className="min-w-0 text-sm">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge tone={i.severity === "error" ? "red" : "amber"}>{i.type}</Badge>
                  {i.field_label && <span className="text-xs text-muted">{i.field_label}</span>}
                </div>
                <p className="mt-1">{i.message}</p>
                <div className="mt-1 flex flex-wrap gap-2 text-xs">
                  {i.document_ids.map((id, k) => (
                    <Link
                      key={`${id}-${k}`}
                      href={`/contracts/${contractId}/documents/${id}${i.field_key ? `?focus=${i.field_key}` : ""}`}
                      className="text-primary hover:underline"
                    >
                      {i.document_titles[k]} 수정 →
                    </Link>
                  ))}
                </div>
              </div>
            </li>
          ))}
          {ai_comments.map((c) => (
            <li key={c.document_id} className="px-5 py-3 text-sm">
              <div className="flex items-center gap-1.5">
                <Badge tone="indigo">AI 문장 검토</Badge> <span className="font-medium">{c.title}</span>
              </div>
              <ul className="mt-1 list-disc pl-5 text-gray-700">
                {c.comments.map((m, k) => (
                  <li key={k}>{m}</li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
