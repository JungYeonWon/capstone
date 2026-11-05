"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** Native modal keeps keyboard focus inside and returns it to the opener. */
export default function LayoutReviewDialog({ onClose, busy, children, footer }: {
  onClose: () => void; busy: boolean; children: ReactNode; footer: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const element = dialog.current;
    const overflow = document.body.style.overflow;
    element?.showModal();
    document.body.style.overflow = "hidden";
    return () => { element?.close(); document.body.style.overflow = overflow; };
  }, []);

  if (typeof document === "undefined") return null;
  return createPortal(
    <dialog ref={dialog} aria-labelledby={titleId} onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}
      className="m-auto max-h-[90dvh] w-[calc(100%_-_2rem)] max-w-3xl overflow-hidden rounded-xl border border-line bg-white p-0 text-foreground shadow-xl backdrop:bg-black/30">
      <div className="flex max-h-[90dvh] flex-col">
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-line px-5 py-4">
          <div><h2 id={titleId} className="font-semibold">양식 구성 확인·수정</h2><p className="mt-1 text-xs text-muted">항목과 표 구성을 확인한 뒤 초안 작성을 시작하세요.</p></div>
          <button type="button" aria-label="구성 편집 닫기" disabled={busy} onClick={onClose} className="rounded-lg p-2 text-muted hover:bg-slate-50 hover:text-foreground disabled:opacity-50">✕</button>
        </header>
        <div className="min-h-0 space-y-4 overflow-y-auto overscroll-contain p-5">{children}</div>
        <footer className="shrink-0 space-y-3 border-t border-line bg-white px-5 py-4">{footer}</footer>
      </div>
    </dialog>, document.body,
  );
}
