"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import type { Message } from "@/types/chat";
import ReactMarkdown from "react-markdown";
import Link from "next/link";
import Icon, { type IconName } from "@/components/Icon";

type ChatWindowProps = {
  messages: Message[];
  loading: boolean;
  disabled: boolean;
  guestLabel?: string;
  onSendMessage: (message: string) => void;
  onOpenNavigation: () => void;
  navigationOpen: boolean;
  mobile: boolean;
};

const developerNotice = "WaveGuide isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games, and all associated properties are trademarks or registered trademarks of Riot Games, Inc.";
const fanNotice = `WaveGuide was created under Riot Games' "Legal Jibber Jabber" policy using assets owned by Riot Games. Riot Games does not endorse or sponsor this project.`;

function RiotNotices() {
  return <p className="riot-notices">{developerNotice} {fanNotice}</p>;
}

const prompts: { icon: IconName; label: string; prompt: string }[] = [
  { icon: "chart", label: "Analyze my last 3 games", prompt: "Analyze my last 3 games." },
  { icon: "search", label: "Review my latest deaths", prompt: "Analyze my most recent game and review my deaths." },
  { icon: "team", label: "Review my teamfighting", prompt: "Analyze my most recent game and review my teamfighting." },
  { icon: "build", label: "Help me with my build", prompt: "Help me choose a build for " },
];

export default function ChatWindow({ messages, loading, disabled, guestLabel, onSendMessage,
  onOpenNavigation, navigationOpen, mobile }: ChatWindowProps) {
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const legalDialog = useRef<HTMLDialogElement>(null);
  const legalTrigger = useRef<HTMLButtonElement>(null);
  const busy = loading || disabled;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
      block: "end",
    });
  }, [messages, loading]);

  useEffect(() => {
    if (!textarea.current) return;
    textarea.current.style.height = "auto";
    textarea.current.style.height = `${Math.min(textarea.current.scrollHeight, 144)}px`;
  }, [input, mobile]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || busy) return;
    onSendMessage(trimmed);
    setInput("");
    if (textarea.current) textarea.current.style.height = "auto";
  }

  return (
    <main className="chat-main" id="main-chat">
      <header className="chat-header">
        <button type="button" className="icon-button glass mobile-only" aria-label="Open navigation"
          aria-controls="navigation" aria-expanded={navigationOpen} onClick={onOpenNavigation}><Icon name="menu" /></button>
        <span className="mobile-brand">WaveGuide</span>
      </header>
      <div className={messages.length ? "chat-scroll" : "chat-scroll chat-home"}>
        {messages.length > 0 && <RiotNotices />}
        {messages.length === 0 ? (
          <section className="welcome" aria-labelledby="welcome-title">
            <div className="welcome-inner">
              <span className="eyebrow">A clearer path to your next win</span>
              <h1 id="welcome-title">Your League Journey,<br />Guided by <span>Data</span></h1>
              <p className="welcome-description">Get personalized insights, analyze your games, and improve faster<br className="desktop-break" /> with AI-powered coaching.</p>
              <div className="prompt-grid">
                {prompts.map(prompt => (
                  <button type="button" key={prompt.label} className="prompt-card glass" disabled={busy}
                    onClick={() => { setInput(prompt.prompt); textarea.current?.focus(); }}>
                    <Icon name={prompt.icon} /><span>{prompt.label}</span>
                  </button>
                ))}
              </div>
            </div>
          </section>
        ) : (
          <section className="message-list" aria-label="Conversation">
            {messages.map((message, index) => (
              <article key={message.id ?? `${message.role}-${index}`} className={`message message-${message.role}`}>
                <div className="message-label">{message.role === "assistant" && <Icon name="wave" />}
                  {message.role === "user" ? "You" : "WaveGuide"}</div>
                {message.role === "user" ? <div className="user-content">{message.content}</div> :
                  <div className="assistant-content prose prose-invert prose-blue"><ReactMarkdown>{message.content}</ReactMarkdown></div>}
              </article>
            ))}
            {loading && <div className="thinking" role="status"><span className="thinking-dot" />WaveGuide is thinking…</div>}
            <div ref={bottomRef} />
          </section>
        )}
        {messages.length === 0 && <RiotNotices />}
      </div>
      <footer className="composer-area">
        <span role="status" className="text-xs text-sky-200">{guestLabel}</span>
        <form onSubmit={handleSubmit} className="composer glass">
          <label htmlFor="chat-input" className="sr-only">Message WaveGuide</label>
          <textarea ref={textarea} id="chat-input" value={input} disabled={disabled} rows={1}
            placeholder={disabled ? (guestLabel || "Daily limit reached") : mobile ? "Ask anything…" : "Ask anything about your games…"}
            onChange={event => setInput(event.target.value)}
            onKeyDown={event => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault(); event.currentTarget.form?.requestSubmit();
              }
            }} />
          <button type="submit" className="send-button" aria-label="Send message" disabled={busy || !input.trim()}>
            <Icon name="send" /></button>
        </form>
        <p className="chat-legal">
          <span>WaveGuide can make mistakes.</span>{" "}
          <span className="legal-action"><span aria-hidden="true">&middot; </span><Link className="privacy-link" href="/privacy">Privacy Policy</Link></span>{" "}
          <span className="legal-action"><span aria-hidden="true">&middot; </span><button type="button" className="privacy-link"
            aria-haspopup="dialog" ref={legalTrigger} onClick={() => legalDialog.current?.showModal()}>Independent fan project</button></span>
        </p>
      </footer>
      <dialog ref={legalDialog} className="account-dialog legal-dialog" aria-labelledby="legal-title"
        onClose={() => legalTrigger.current?.focus()}
        onClick={event => { if (event.target === event.currentTarget) event.currentTarget.close(); }}
        onKeyDown={event => {
          if (event.key !== "Tab") return;
          const first = event.currentTarget.querySelector("button");
          const last = event.currentTarget.querySelector("a");
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last?.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first?.focus();
          }
        }}>
        <section className="account-surface">
          <header className="flex items-center justify-between gap-3">
            <h2 id="legal-title" className="text-xl font-semibold">Independent Fan Project</h2>
            <button type="button" className="account-close" aria-label="Close project notices"
              onClick={() => legalDialog.current?.close()}>&times;</button>
          </header>
          <p>WaveGuide is an independent League of Legends coaching project.</p>
          <p>{developerNotice}</p>
          <p>{fanNotice}</p>
          <a className="privacy-link" href="https://www.riotgames.com/en/legal">Riot Games Legal Jibber Jabber policy</a>
        </section>
      </dialog>
    </main>
  );
}

