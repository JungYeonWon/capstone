"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";

/** Private encrypted server draft. Serial writes + optimistic revisions protect other tabs. */
export function useWorkspaceDraft<T extends object>(contractId: number, slot: string, initial: T) {
  const path = `/contracts/${contractId}/workspace/${slot}`;
  const [value, setValue] = useState<T>(initial);
  const [ready, setReady] = useState(false);
  const [loadedValue, setLoadedValue] = useState<T | null>(null);
  const [status, setStatus] = useState("임시 저장 불러오는 중");
  const [error, setError] = useState("");
  const [savedValue, setSavedValue] = useState("");
  const revision = useRef(0);
  const saved = useRef("");
  const current = useRef(value);
  const blocked = useRef(false);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const fallback = useRef(initial);
  useEffect(() => {
    let active = true;
    api.get<{ payload: T; revision: number }>(path).then(result => {
      if (!active) return;
      const restored = Object.keys(result.payload).length ? result.payload : fallback.current;
      revision.current = result.revision; saved.current = JSON.stringify(restored);
      setSavedValue(saved.current);
      current.current = restored; setValue(restored); setLoadedValue(restored); setReady(true);
      setStatus(Object.keys(result.payload).length ? "서버 임시 저장 복원됨" : "새 초안");
    }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [path]);
  useEffect(() => { current.current = value; }, [value]);
  const persist = useCallback((payload: T) => {
    const run = queue.current.then(async () => {
      if (blocked.current) throw new Error("다른 창의 변경을 확인하세요. 입력한 내용을 복사한 뒤 새로고침하세요.");
      const serialized = JSON.stringify(payload);
      if (serialized === saved.current) return;
      setStatus("서버에 임시 저장 중");
      try {
        const result = await api.put<{ revision: number }>(path, { payload, revision: revision.current });
        revision.current = result.revision; saved.current = serialized;
        setSavedValue(serialized);
        setStatus("서버에 임시 저장됨"); setError("");
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) blocked.current = true;
        setStatus("임시 저장 실패"); setError((e as Error).message); throw e;
      }
    });
    queue.current = run.catch(() => {});
    return run;
  }, [path]);
  const serialized = JSON.stringify(value);
  useEffect(() => {
    if (!ready || serialized === saved.current || blocked.current) return;
    const timer = setTimeout(() => { void persist(current.current).catch(() => {}); }, 900);
    return () => clearTimeout(timer);
  }, [serialized, ready, persist]);
  const saveNow = useCallback(() => persist(current.current), [persist]);
  const replace = useCallback(async (next: T) => {
    current.current = next; setValue(next); await persist(next);
  }, [persist]);
  return { value, setValue, loadedValue, ready, status, error, saveNow, replace, pending: ready && serialized !== savedValue };
}
