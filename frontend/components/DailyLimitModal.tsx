"use client";

import { useEffect, useRef } from "react";

type DailyLimitModalProps = { open: boolean; onClose: () => void };

export default function DailyLimitModal({ open, onClose }: DailyLimitModalProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (open && !dialog.current?.open) dialog.current?.showModal();
    if (!open && dialog.current?.open) dialog.current?.close();
  }, [open]);

  return (
    <dialog ref={dialog} className="account-dialog" aria-labelledby="daily-limit-title"
      onKeyDown={event => { if (event.key === "Tab") { event.preventDefault(); event.currentTarget.querySelector("button")?.focus(); } }}
      onCancel={event => { event.preventDefault(); onClose(); }}
      onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="account-surface">
        <h2 id="daily-limit-title" className="text-xl font-semibold">Daily limit reached</h2>
        <p className="dialog-description">WaveGuide has reached today&apos;s AI request limit.
          You can continue chatting when the daily quota resets.</p>
        <p className="dialog-description">Your existing conversations are still available to view.</p>
        <button type="button" onClick={onClose} className="primary-button">Got it</button>
      </section>
    </dialog>
  );
}

