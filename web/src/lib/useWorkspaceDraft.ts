"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";

/** Private encrypted server draft. Serial writes + optimistic revisions protect other tabs. */
export function useWorkspaceDraft<T extends object>(contractId: number, slot: string, initial: T) {
  const path = `/contracts/${contractId}/workspace/${slot}`;
  const [value, setValue] = useState<T>(initial);
  const [ready, setReady] = useState(false);
  const [readyPath, setReadyPath] = useState("");
  const [loadedValue, setLoadedValue] = useState<T | null>(null);
  const [status, setStatus] = useState("임시 저장 불러오는 중");
  const [error, setError] = useState("");
  const [savedValue, setSavedValue] = useState("");
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);
  const [conflicted, setConflicted] = useState(false);
  const [remote, setRemote] = useState<{ payload: T; revision: number; updated_at?: string } | null>(null);
  const [recovering, setRecovering] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const revision = useRef(0);
  const saved = useRef("");
  const current = useRef(value);
  const blocked = useRef(false);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const fallback = useRef(initial);
  const epoch = useRef(0);
  const loadedPath = useRef("");
  useEffect(() => {
    let active = true;
    const generation = ++epoch.current;
    loadedPath.current = "";
    api.get<{ payload: T; revision: number; updated_at?: string }>(path).then(result => {
      if (!active) return;
      if (generation !== epoch.current) return;
      const restored = Object.keys(result.payload).length ? result.payload : fallback.current;
      revision.current = result.revision; saved.current = JSON.stringify(restored);
      setSavedValue(saved.current);
      setRemote(null);
      setError("");
      setLastSavedAt(result.updated_at ?? null);
      blocked.current = false;
      setConflicted(false);
      current.current = restored; setValue(restored); setLoadedValue(restored); setReady(true);
      setReadyPath(path);
      setStatus(Object.keys(result.payload).length ? "서버 임시 저장 복원됨" : "새 초안");
      loadedPath.current = path;
    }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; epoch.current += 1; loadedPath.current = ""; };
  }, [path, loadAttempt]);
  useEffect(() => { current.current = value; }, [value]);
  const persist = useCallback((payload: T) => {
    const generation = epoch.current;
    const run = queue.current.then(async () => {
      if (generation !== epoch.current || loadedPath.current !== path) return;
      if (blocked.current) throw new Error("다른 창의 저장본과 현재 작업을 비교한 뒤 선택하세요.");
      const serialized = JSON.stringify(payload);
      if (serialized === saved.current) { setSavedValue(serialized); setError(""); return; }
      setStatus("서버에 임시 저장 중");
      try {
        const result = await api.put<{ revision: number }>(path, { payload, revision: revision.current });
        if (generation !== epoch.current) return;
        revision.current = result.revision; saved.current = serialized;
        setSavedValue(serialized);
        setLastSavedAt(new Date().toISOString());
        setStatus("서버에 임시 저장됨"); setError("");
      } catch (e) {
        if (generation !== epoch.current) return;
        if (e instanceof ApiError && e.status === 409) { blocked.current = true; setConflicted(true); }
        setStatus("임시 저장 실패 · 현재 입력 유지"); setError((e as Error).message); throw e;
      }
    });
    queue.current = run.catch(() => {});
    return run;
  }, [path]);
  const serialized = JSON.stringify(value);
  useEffect(() => {
    if (!ready || loadedPath.current !== path || serialized === saved.current || blocked.current) return;
    const timer = setTimeout(() => { void persist(current.current).catch(() => {}); }, 900);
    return () => clearTimeout(timer);
  }, [serialized, ready, persist, path]);
  const saveNow = useCallback(() => persist(current.current), [persist]);
  const replace = useCallback(async (next: T) => {
    current.current = next; setValue(next); await persist(next);
  }, [persist]);
  const compare = useCallback(async () => {
    setRecovering(true);
    try {
      await queue.current;
      setRemote(await api.get<{ payload: T; revision: number; updated_at?: string }>(path));
      setError("");
    } catch (e) { setError((e as Error).message); }
    finally { setRecovering(false); }
  }, [path]);
  const resolve = useCallback(async (useServer: boolean) => {
    if (!remote || recovering) return;
    setRecovering(true);
    revision.current = remote.revision;
    blocked.current = false;
    setConflicted(false);
    setRemote(null);
    try {
      if (useServer) {
        const restored = Object.keys(remote.payload).length ? remote.payload : fallback.current;
        saved.current = JSON.stringify(restored);
        current.current = restored;
        setValue(restored);
        setLoadedValue(restored);
        setSavedValue(saved.current);
        setLastSavedAt(remote.updated_at ?? null);
        setStatus("서버 저장본을 선택했습니다.");
        setError("");
      } else {
        saved.current = JSON.stringify(remote.payload);
        await persist(current.current);
      }
    } finally { setRecovering(false); }
  }, [remote, recovering, persist]);
  const retryLoad = useCallback(async () => { setLoadAttempt(attempt => attempt + 1); }, []);
  const currentPathReady = ready && readyPath === path;
  return { value, setValue, loadedValue: currentPathReady ? loadedValue : null, ready: currentPathReady, status, error, saveNow, replace, lastSavedAt,
    pending: currentPathReady && serialized !== savedValue, conflicted, remote, recovering, compare, resolve, retryLoad };
}
