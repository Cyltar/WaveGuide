"use client";

import { useEffect, useRef } from "react";
import { developerNotice, fanNotice } from "@/components/riotNotices";
import AccountPanel from "@/components/AccountPanel";
import Icon from "@/components/Icon";
import type { Conversation } from "@/types/chat";

type SidebarProps = {
  conversations: Conversation[];
  activeSessionId: string | null;
  onSelectConversation: (sessionId: string) => void;
  onNewChat: () => void;
  disabled: boolean;
  userEmail: string;
  guest?: boolean;
  accountDisabled: boolean;
  onAccountDeleted: () => void;
  mobile: boolean;
  open: boolean;
  onClose: () => void;
};

export default function Sidebar({ conversations, activeSessionId, onSelectConversation, onNewChat,
  disabled, userEmail, guest, accountDisabled, onAccountDeleted, mobile, open, onClose }: SidebarProps) {
  const panel = useRef<HTMLElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!mobile || !open) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    closeButton.current?.focus();
    function handleKey(event: KeyboardEvent) {
      // Native account dialogs manage their own focus and Escape handling above this drawer.
      if (document.querySelector("dialog[open]")) return;
      if (event.key === "Escape") { event.preventDefault(); onClose(); }
      if (event.key !== "Tab") return;
      const controls = Array.from(panel.current?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), a[href], [tabindex="0"]') ?? []).filter(node => node.getClientRects().length);
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("keydown", handleKey);
      if (previousFocus?.getClientRects().length) previousFocus.focus();
    };
  }, [mobile, open, onClose]);

  return (
    <>
      <button type="button" className={`navigation-backdrop ${open ? "is-open" : ""}`} tabIndex={-1}
        aria-label="Close navigation" aria-hidden={!mobile || !open} onClick={onClose} />
      <aside ref={panel} id="navigation" className={`sidebar glass ${open ? "is-open" : ""}`}
        inert={mobile && !open} role={mobile ? "dialog" : undefined} aria-modal={mobile && open ? true : undefined}
        aria-label="Navigation">
        <div className="sidebar-top">
          <div className="sidebar-brand-row">
            <div className="brand"><Icon name="wave" className="brand-mark" /><span>WaveGuide</span></div>
            <button ref={closeButton} type="button" className="icon-button mobile-only" onClick={onClose}
              aria-label="Close navigation"><Icon name="close" /></button>
          </div>
          <button type="button" onClick={onNewChat} disabled={disabled} className="new-chat glass">
            <Icon name="chat" /><span>New Chat</span><span className="new-chat-plus" aria-hidden="true">+</span>
          </button>
        </div>
        <nav className="history" aria-label="Chat history">
          <h2><Icon name="history" />Chat History</h2>
          <div className="conversation-scroll">
            {conversations.length === 0 ? (
              <div className="history-empty"><p>A fresh start.</p><span>Your conversations will appear here.</span></div>
            ) : conversations.map(conversation => (
              <button type="button" key={conversation.sessionId} onClick={() => onSelectConversation(conversation.sessionId)}
                disabled={accountDisabled} className={`conversation ${conversation.sessionId === activeSessionId ? "active" : ""}`}
                aria-current={conversation.sessionId === activeSessionId ? "page" : undefined} title={conversation.title}>
                <Icon name="chat" /><span>{conversation.title}</span>
              </button>
            ))}
          </div>
        </nav>
        <div className="sidebar-bottom">
          <p className="sidebar-notices">{developerNotice} {fanNotice}</p>
          {guest ? (
            <div className="guest-auth">
              <a className="new-chat glass" href="/signup">Create a free account</a>
              <a className="new-chat glass" href="/login">Log in</a>
            </div>
          ) : <AccountPanel email={userEmail} disabled={accountDisabled} onDeleted={onAccountDeleted} />}
        </div>
      </aside>
    </>
  );
}
