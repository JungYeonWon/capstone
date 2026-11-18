export const WORKFLOW_MODES = {
  change: { title: "추가 요청 영향 분석", description: "기존 계약과 고객 요청을 비교하고 변경 합의서·협의 메일을 만듭니다.",
    input: "고객의 추가 요청", placeholder: "예: 관리자 통계 화면에 월별 엑셀 다운로드도 추가해 주세요.", action: "변경 영향 분석" },
  requirements: { title: "요구사항 구체화", description: "AI 질문에 답하며 기능·산출물·검수 기준을 정하고 과업지시서·견적을 만듭니다.",
    input: "만들고 싶은 서비스와 요구사항", placeholder: "예: 소규모 병원의 예약 관리 사이트를 만들고 싶어요. 환자 예약과 관리자 일정 관리가 필요합니다.", action: "요구사항 구체화" },
  meeting: { title: "회의록 후속 업무", description: "합의 후보·논의·미결 사항과 담당 업무를 정리하고 회의 확인서·메일을 만듭니다.",
    input: "회의록·대화 내용", placeholder: "예: 고객: 교육은 온라인으로 진행하는 데 동의합니다. 수행사: 네, 온라인 교육으로 진행하겠습니다. 추가 통계 기능의 비용은 다음 회의에서 결정하기로 했습니다.", action: "회의록 정리" },
} as const;
export type WorkflowMode = keyof typeof WORKFLOW_MODES;
export const ITEM_LABELS: Record<string, string> = { scope_included: "기존 범위 포함 후보", scope_additional: "추가 업무 후보", scope_unclear: "범위 판단 보류",
  schedule: "일정 영향·계획", cost: "비용 영향", feature: "기능", deliverable: "산출물", acceptance: "검수 기준", exclusion: "제외 범위",
  agreed: "합의 후보 · 확인 필요", discussion: "논의·제안", open: "미결·확인 필요", task: "후속 업무" };
export const DRAFT_LABELS: Record<string, string> = { change_agreement: "과업변경 합의서", scope: "과업지시서", estimate: "견적 구성", followup_email: "확인·협의 메일", meeting_minutes: "회의 확인서" };
export type WorkflowFile = { name: string; kind: "input" | "reference"; parts: { page: number | null; text: string }[]; warning: string };
export type WorkflowAnswer = { question: string; text: string };
export type WorkflowInput = { text: string; role: "supplier" | "client"; include_contract: boolean; document_id: number | null; files: WorkflowFile[]; answers: WorkflowAnswer[]; consent_digest?: string };
export type WorkflowSource = { source_id: number; name: string; page: number | null; kind: "input" | "reference" | "answer"; text: string };
export type WorkflowItem = { category: string; title: string; detail: string; basis: "source" | "proposal"; owner: string; due: string; evidence: { source_id: number; quote: string }[] };
export type WorkflowDraft = { kind: string; title: string; sections: { label: string; text: string }[] };
export type WorkflowOutput = { result: { summary: string; items: WorkflowItem[]; questions: { question: string; reason: string }[]; drafts: WorkflowDraft[] };
  sources: WorkflowSource[]; warning: string; consent_digest: string };
export type EstimateLine = { label: string; quantity: string; unit: string; unit_price: string };
export type WorkflowSession = { input: WorkflowInput; output: WorkflowOutput | null; estimate_lines: EstimateLine[]; output_stale: boolean };
export type WorkflowPreview = { payload_preview: string; consent_digest: string; ai_available: boolean; warning: string };
export function emptyWorkflow(): WorkflowSession {
  return { input: { text: "", role: "supplier", include_contract: false, document_id: null, files: [], answers: [] }, output: null, estimate_lines: [], output_stale: false };
}

// Integer hundredths keep the displayed quotation identical to server Decimal rounding.
function hundredths(value: string, max: bigint): bigint | null {
  if (!/^\d{1,9}(\.\d{1,2})?$/.test(value)) return null;
  const [whole, fraction = ""] = value.split(".");
  const parsed = BigInt(whole) * BigInt(100) + BigInt(fraction.padEnd(2, "0"));
  return parsed <= max * BigInt(100) ? parsed : null;
}
export function estimateAmounts(lines: EstimateLine[]) {
  const amounts = lines.map(line => {
    const q = hundredths(line.quantity, BigInt(10000)), rate = hundredths(line.unit_price, BigInt(100000000));
    if (!line.label.trim() || !line.unit.trim() || q === null || q <= BigInt(0) || rate === null) return null;
    return (q * rate + BigInt(50)) / BigInt(100);
  });
  return { amounts, total: amounts.some(amount => amount === null) ? null : amounts.reduce<bigint>((sum, amount) => sum + (amount ?? BigInt(0)), BigInt(0)) };
}
export function money(cents: bigint) { return `${(cents / BigInt(100)).toLocaleString("ko-KR")}.${(cents % BigInt(100)).toString().padStart(2, "0")}원`; }
export function draftText(draft: WorkflowDraft) { return `[검토용 초안] ${draft.title}\n\n${draft.sections.map(section => `${section.label}\n${section.text}`).join("\n\n")}`; }
