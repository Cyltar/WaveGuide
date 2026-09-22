"use client";



import { useEffect, useRef, useState } from "react";

import { deleteAccount } from "@/lib/api";

import { createClient } from "@/lib/supabase/client";

import LogoutButton from "@/components/LogoutButton";



type AccountPanelProps = {

  email: string;

  disabled: boolean;

  onDeleted: () => void;

};



export default function AccountPanel({ email, disabled, onDeleted }: AccountPanelProps) {

  const dialog = useRef<HTMLDialogElement>(null);

  const trigger = useRef<HTMLButtonElement>(null);

  const cancelButton = useRef<HTMLButtonElement>(null);

  const closeButton = useRef<HTMLButtonElement>(null);

  const requestPending = useRef(false);

  const [confirming, setConfirming] = useState(false);

  const [deleting, setDeleting] = useState(false);

  const [error, setError] = useState("");



  useEffect(() => {

    if (dialog.current?.open) {

      (confirming ? cancelButton : closeButton).current?.focus();

    }

  }, [confirming]);



  function closePanel() {

    if (requestPending.current) return;

    dialog.current?.close();

    trigger.current?.focus();

  }



  function openPanel() {

    setConfirming(false);

    setError("");

    dialog.current?.showModal();

    closeButton.current?.focus();

  }



  async function confirmDeletion() {

    if (requestPending.current) return;

    requestPending.current = true;

    setDeleting(true);

    setError("");

    try {

      await deleteAccount();

    } catch {

      setError("Unable to delete your account. Please try again.");

      requestPending.current = false;

      setDeleting(false);

      return;

    }



    // Only sign out after the backend confirms permanent deletion.

    // The installed Supabase client removes local storage even if revocation fails.

    try {

      await createClient().auth.signOut({ scope: "local" });

    } catch {

      // The account is already deleted; still clear the visible app state and leave this page.

    }

    onDeleted();

  }



  return (

    <>

      <button ref={trigger} type="button" className="account-trigger" onClick={openPanel}

        disabled={disabled} aria-haspopup="dialog" aria-label={`Open account for ${email || "your account"}`}>

        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"

          aria-hidden="true"><circle cx="12" cy="8" r="4" /><path d="M4 22v-3a8 8 0 0 1 16 0v3" /></svg>

        <span className="min-w-0 flex-1 truncate text-left" title={email}>{email || "Account"}</span>

        <span aria-hidden="true">›</span>

      </button>

      <dialog ref={dialog} className={`account-dialog ${confirming ? "account-confirmation" : ""}`}

        aria-labelledby="account-title" aria-describedby={confirming ? "deletion-warning" : undefined}

        aria-busy={deleting} tabIndex={-1}
        onKeyDown={event => {
          if (event.key !== "Tab") return;
          const controls = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)"));
          const first = controls[0];
          const last = controls[controls.length - 1];
          if (!first) { event.preventDefault(); event.currentTarget.focus(); }
          else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
          else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        }}

        onCancel={(event) => { event.preventDefault(); closePanel(); }}

        onClick={(event) => { if (event.target === event.currentTarget) closePanel(); }}>

        <section className="account-surface">

          <header className="flex items-center justify-between gap-4">

            <h2 id="account-title" className="text-xl font-semibold">{confirming ? "Delete Account" : "Account"}</h2>

            <button ref={closeButton} type="button" className="account-close" aria-label="Close account panel"

              disabled={deleting} onClick={closePanel}>×</button>

          </header>

          {confirming ? (

            <>

              <p id="deletion-warning" className="account-warning">

                <strong>This action cannot be undone.</strong><br />

                Your account, chat history, and associated WaveGuide data will be permanently deleted.

              </p>

              {error && <p role="alert" className="account-error">{error}</p>}

              <div className="account-actions">

                <button ref={cancelButton} type="button" className="account-cancel" disabled={deleting}

                  onClick={() => { setConfirming(false); setError(""); }}>Cancel</button>

                <button type="button" className="account-delete-final" disabled={deleting}

                  onClick={confirmDeletion}>{deleting ? "Deleting..." : "Delete Account"}</button>

              </div>

              <span role="status" className="sr-only">{deleting ? "Deleting your account. Please wait." : ""}</span>

            </>

          ) : (

            <>

              <p className="my-6 break-all text-sm text-blue-100">{email}</p>

              <button type="button" className="account-delete" onClick={() => setConfirming(true)}>

                Delete Account

              </button>

              <div className="mt-4"><LogoutButton /></div>

            </>

          )}

        </section>

      </dialog>

    </>

  );

}

