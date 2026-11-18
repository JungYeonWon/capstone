"use client";
import { useParams } from "next/navigation";
import Link from "next/link";
import WorkflowWorkspace from "@/components/workspace/WorkflowWorkspace";
import { WORKFLOW_MODES, type WorkflowMode } from "@/lib/ai-workflows";

export default function WorkflowPage() {
  const { id, mode } = useParams<{ id: string; mode: string }>();
  if (!Object.prototype.hasOwnProperty.call(WORKFLOW_MODES, mode)) return <p>지원하지 않는 기능입니다. <Link href={`/contracts/${id}`}>계약 상세로 돌아가기</Link></p>;
  return <WorkflowWorkspace key={`${id}:${mode}`} contractId={Number(id)} mode={mode as WorkflowMode} />;
}
