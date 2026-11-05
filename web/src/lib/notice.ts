export type NoticeItem = { id: string; title: string; evidence: string; condition?: string; required: boolean; done: boolean; document_id: number | null; note: string };
export type NoticeFact = { kind: "deadline" | "method" | "place" | "contact" | "caution"; value: string; evidence: string };
export type NoticeState = { text: string; analyzed_text?: string; items: NoticeItem[]; facts?: NoticeFact[] };
export type NoticeAnalysis = { items: NoticeItem[]; facts: NoticeFact[]; mode: "rule" | "ai" | "rule_fallback"; warning: string; notice: string };
export const FACT_LABELS = { deadline: "제출기한", method: "제출방법", place: "제출처", contact: "문의처", caution: "유의사항" };

/** Keep manual work, but ask again when the source or requirements changed. */
export function applyNoticeAnalysis(previous: NoticeState, analysis: NoticeAnalysis): NoticeState {
  const items = analysis.items.map(item => {
    const old = previous.items.find(old => old.id === item.id || old.title.replaceAll(" ", "") === item.title.replaceAll(" ", ""));
    const unchanged = old && old.evidence === item.evidence && (old.condition || "") === (item.condition || "");
    return old ? { ...item, title: old.title, note: old.note, document_id: old.document_id,
      required: unchanged ? old.required : item.required, done: Boolean(unchanged && old.done) } : item;
  });
  for (const item of previous.items) if (!item.evidence && !items.some(next => next.id === item.id)) items.push(item);
  if (items.length > 30) throw new Error("직접 추가한 항목과 합쳐 30개를 초과합니다. 불필요한 항목을 먼저 제외하세요.");
  return { text: previous.text, analyzed_text: previous.text, items, facts: analysis.facts };
}
