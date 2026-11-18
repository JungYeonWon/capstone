export type ReviewStatus = "pending" | "asking" | "resolved";
export const REVIEW_STATUS = { pending: "확인 전", asking: "상대방 문의 중", resolved: "수정·확인 완료" };
export type ReviewFinding = { category: string; title: string; impact: string; question: string; status: ReviewStatus; note: string; method?: "ai" | "rule";
  evidence: { source_id?: number; name: string; page: number | null; quote: string }[] };
export type SourceFile = { key: string; name: string };
export type ReviewSummary = { id: number; created_at: string; revision: number; role: "supplier" | "client";
  document_id: number | null; source_files: SourceFile[]; finding_count: number; resolved_count: number };
export type ReviewRecord = ReviewSummary & { findings: ReviewFinding[]; excluded: number; warning: string; review_version?: number; supplement_omitted?: number; document_state?: "current" | "changed" | "deleted" | "uploaded" };
export type ReviewEdit = { status: ReviewStatus; note: string };
export function questionText(record: ReviewRecord, includeResolved: boolean) {
  const questions = record.findings.filter(item => includeResolved || item.status !== "resolved");
  return questions.map((item, index) => `${index + 1}. [${item.category}] ${item.title}${item.method === "rule" ? " (규칙 기반 확인 후보)" : ""}\n${item.question}`).join("\n\n");
}
export function reviewDate(value: string) { return new Date(value.endsWith("Z") ? value : `${value}Z`).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" }); }
