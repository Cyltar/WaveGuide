"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";

export default function GuestSignupModal({open,onClose}:{open:boolean;onClose:()=>void}) {
  const ref=useRef<HTMLDialogElement>(null);
  useEffect(()=>{
    if(open && !ref.current?.open) ref.current?.showModal();
    if(!open && ref.current?.open) ref.current.close();
  },[open]);
  return <dialog ref={ref} className="account-dialog" aria-labelledby="guest-signup-title"
    onCancel={e=>{e.preventDefault();onClose();}}>
    <section className="account-surface">
      <h2 id="guest-signup-title" className="text-xl font-semibold">You’ve used your 5 free messages</h2>
      <p className="dialog-description">Create a free WaveGuide account to keep chatting and save this conversation.</p>
      <Link className="primary-button" href="/signup">Create a free account</Link>
      <p className="dialog-description">Already have an account? <Link href="/login">Log in</Link></p>
      <button type="button" onClick={onClose} className="secondary-button">Back to conversation</button>
      <p className="auth-privacy"><Link className="privacy-link" href="/privacy">Privacy Policy</Link></p>
    </section>
  </dialog>;
}
