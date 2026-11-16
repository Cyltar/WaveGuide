"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import type { Message } from "@/types/chat";
import ReactMarkdown from "react-markdown";
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
        <span className="header-note">Your personal League coach</span>
      </header>
      <div className="chat-scroll">
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
        <p className="composer-note">WaveGuide can make mistakes. Check important game information.</p>
      </footer>
    </main>
  );
}

