"use client";

import { Button } from "@/components/ui";

export function RecoveryComparison({ local, remote, busy, onLocal, onRemote }: {
  local: object; remote: object; busy: boolean; onLocal: () => void; onRemote: () => void;
}) {
  return <section className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
    <p className="text-sm font-medium">다른 창의 저장본과 현재 작업이 다릅니다. 비교한 뒤 사용할 내용을 선택하세요.</p>
    <div className="grid gap-3 md:grid-cols-2">
      {[["현재 작업", local], ["서버 저장본", remote]].map(([title, data]) => <div key={String(title)} className="min-w-0">
        <h3 className="mb-1 text-xs font-semibold">{String(title)}</h3>
        <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded bg-white p-2 text-xs">{JSON.stringify(data, null, 2)}</pre>
      </div>)}
    </div>
    <div className="flex flex-wrap gap-2">
      <Button size="sm" disabled={busy} onClick={onLocal}>현재 작업으로 저장</Button>
      <Button size="sm" variant="secondary" disabled={busy} onClick={onRemote}>서버 저장본 사용</Button>
    </div>
  </section>;
}

export default function DraftRecovery<T extends object>({ draft, onUseServer }: {
  draft: {
    value: T; error: string; ready: boolean; lastSavedAt: string | null; conflicted: boolean;
    remote: { payload: T; revision: number } | null; recovering: boolean;
    retryLoad: () => Promise<void>; saveNow: () => Promise<void>; compare: () => Promise<void>;
    resolve: (useServer: boolean) => Promise<void>;
  };
  onUseServer?: (value: T) => void;
}) {
  const run = (action: () => Promise<void>) => { void action().catch(() => {}); };
  return <div className="space-y-2">
    {draft.lastSavedAt && <p className="text-xs text-muted">마지막 임시 저장 {new Date(/Z$|[+-]\d\d:\d\d$/.test(draft.lastSavedAt) ? draft.lastSavedAt : draft.lastSavedAt + "Z").toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })}</p>}
    {draft.error && !draft.conflicted && <Button size="sm" variant="secondary" disabled={draft.recovering}
      onClick={() => run(draft.ready ? draft.saveNow : draft.retryLoad)}>{draft.ready ? "임시 저장 다시 시도" : "임시 저장 다시 불러오기"}</Button>}
    {draft.conflicted && <Button size="sm" variant="secondary" disabled={draft.recovering}
      onClick={() => run(draft.compare)}>서버 저장본과 비교</Button>}
    {draft.remote && <RecoveryComparison local={draft.value} remote={draft.remote.payload} busy={draft.recovering}
      onLocal={() => run(() => draft.resolve(false))}
      onRemote={() => run(async () => { const payload = draft.remote!.payload; await draft.resolve(true); onUseServer?.(payload); })} />}
  </div>;
}
