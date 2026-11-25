import type { DraftChange, WorkflowDraft, WorkflowSection } from "./ai-workflows";

const labelKey = (label: string) => label.normalize("NFKC").replace(/[\s·ㆍ:：()\[\]]/g, "").toLowerCase();
const equalSection = (a?: WorkflowSection | null, b?: WorkflowSection | null) => !!a && !!b && a.label === b.label && a.text === b.text;
const clone = (drafts: WorkflowDraft[]) => drafts.map(draft => ({ ...draft, sections: draft.sections.map(section => ({ ...section })) }));
function hash(value: string) { let result = 0; for (const char of value) result = (result * 31 + char.charCodeAt(0)) >>> 0; return result.toString(36); }

export function identifyDrafts(drafts: WorkflowDraft[], previous: WorkflowDraft[] = []): WorkflowDraft[] {
  return drafts.map(draft => {
    const old = previous.find(d => d.kind === draft.kind);
    const used = new Set<string>();
    return { ...draft, sections: draft.sections.map((section, index) => {
      const matches = old?.sections.filter(s => labelKey(s.label) === labelKey(section.label)) ?? [];
      let id = matches.length === 1 ? matches[0].id : undefined;
      id ||= previous.length ? `${draft.kind}_new_${index}_${hash(section.label)}` : section.id || `${draft.kind}_section_${index}`;
      if (used.has(id)) id = `${id}_${index}`;
      used.add(id);
      return { ...section, id };
    }) };
  });
}

export function compareDrafts(current: WorkflowDraft[], baseline: WorkflowDraft[], incoming: WorkflowDraft[]): DraftChange[] {
  const changes: DraftChange[] = [];
  for (const old of current) {
    const next = incoming.find(d => d.kind === old.kind), base = baseline.find(d => d.kind === old.kind);
    const change = (type: DraftChange["type"], extra: Partial<DraftChange>): DraftChange => ({ id: `${old.kind}_${type}_${extra.section_id || "document"}`,
      kind: old.kind, type, section_id: "", before: null, after: null, before_title: "", after_title: "", document: null, protected: true, ...extra });
    if (!next) {
      changes.push(change("remove_document", { document: old })); continue;
    }
    if (old.title !== next.title) changes.push(change("title", { before_title: old.title, after_title: next.title, protected: !base || base.title !== old.title }));
    for (const section of old.sections) {
      const replacement = next.sections.find(s => s.id === section.id);
      const original = base?.sections.find(s => s.id === section.id);
      if (equalSection(section, replacement)) continue;
      changes.push(change(replacement ? "section" : "remove_section", { section_id: section.id!, before: section, after: replacement || null,
        protected: !equalSection(section, original) }));
    }
    for (const section of next.sections) {
      if (!old.sections.some(s => s.id === section.id)) changes.push(change("add_section", { section_id: section.id!, after: section, protected: false }));
    }
  }
  for (const draft of incoming) if (!current.some(d => d.kind === draft.kind)) changes.push({
    id: `${draft.kind}_add_document`, kind: draft.kind, type: "add_document", section_id: "", before: null, after: null,
    before_title: "", after_title: "", document: draft, protected: false,
  });
  return changes;
}

export function applyDraftChange(drafts: WorkflowDraft[], change: DraftChange): WorkflowDraft[] {
  const next = clone(drafts), index = next.findIndex(draft => draft.kind === change.kind);
  const stale = () => { throw new Error("비교 이후 기존 내용이 달라졌습니다. 기존 내용을 유지한 뒤 다시 분석하세요."); };
  if (change.type === "add_document") {
    if (index >= 0 || !change.document) stale();
    next.push({ ...change.document!, sections: change.document!.sections.map(s => ({ ...s })) });
  } else {
    if (index < 0) stale();
    const draft = next[index];
    if (change.type === "title") {
      if (draft.title !== change.before_title) stale();
      draft.title = change.after_title;
    } else if (change.type === "remove_document") {
      if (JSON.stringify(draft) !== JSON.stringify(change.document)) stale();
      next.splice(index, 1);
    } else if (change.type === "add_section") {
      if (!change.after || draft.sections.some(s => s.id === change.section_id)) stale();
      draft.sections.push({ ...change.after! });
    } else {
      const sectionIndex = draft.sections.findIndex(s => s.id === change.section_id);
      if (sectionIndex < 0 || !equalSection(draft.sections[sectionIndex], change.before)) stale();
      if (change.type === "remove_section") draft.sections.splice(sectionIndex, 1);
      else { if (!change.after) stale(); draft.sections[sectionIndex] = { ...change.after! }; }
    }
  }
  if (next.length < 1 || next.length > 3 || next.some(d => d.sections.length < 1 || d.sections.length > 10)) {
    throw new Error("서류는 1~3개, 서류별 항목은 1~10개여야 합니다. 다른 제안을 먼저 검토하거나 기존 내용을 유지하세요.");
  }
  return next;
}
