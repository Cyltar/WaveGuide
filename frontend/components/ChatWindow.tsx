"use client";

import {
  FormEvent,
  useEffect,
  useRef,
  useState,
} from "react";

import type { Message } from "@/types/chat";
import ReactMarkdown from "react-markdown";

type ChatWindowProps = {
  messages: Message[];
  loading: boolean;
  disabled: boolean;
  onSendMessage: (message: string) => void;
};


export default function ChatWindow({
  messages,
  loading,
  disabled,
  onSendMessage,
}: ChatWindowProps) {
  const [input, setInput] = useState("");

  const bottomRef =
    useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({
      behavior: "smooth",
    });
  }, [messages, loading]);


  function handleSubmit(
    event: FormEvent<HTMLFormElement>
  ) {
    event.preventDefault();

    const trimmed = input.trim();

    if (!trimmed || loading || disabled) {
      return;
    }

    onSendMessage(trimmed);

    setInput("");
  }


  return (
    <main className="relative flex min-w-0 flex-1 flex-col">
      <header className="flex h-[72px] items-center justify-end border-b border-white/5 px-7">
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col px-6 pb-40 pt-10">
          {messages.length === 0 ? (
            <div className="flex flex-1 items-center justify-center">
              <div className="text-center">
                <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl border border-blue-400/20 bg-gradient-to-br from-blue-950 to-blue-800/30 shadow-[0_0_45px_rgba(37,99,235,0.12)]">
                  <span className="text-xl font-bold text-blue-300">
                    L
                  </span>
                </div>

                <h2 className="text-2xl font-semibold text-slate-100">
                  What can I help you with?
                </h2>

                <p className="mt-2 text-sm text-slate-500">
                  Ask about champions, matchups,
                  laning, macro, or the current meta.
                </p>
              </div>
            </div>
          ) : (
            <div className="space-y-8">
              {messages.map((message, index) => (
                <div
                  key={`${message.role}-${index}`}
                  className={`flex ${
                    message.role === "user"
                      ? "justify-end"
                      : "justify-start"
                  }`}
                >
                  {message.role === "user" ? (
                    <div className="max-w-[75%] rounded-2xl border border-blue-400/15 bg-blue-950/50 px-4 py-3 text-sm leading-6 text-slate-100">
                      {message.content}
                    </div>
                  ) : (
                    <div className="prose prose-invert prose-blue max-w-[90%] text-[15px]">
                      <ReactMarkdown>
                          {message.content}
                      </ReactMarkdown>
                    </div>
                  )}
                </div>
              ))}

              {loading && (
                <div className="text-sm text-slate-500">
                  WaveGuide is thinking...
                </div>
              )}

              <div ref={bottomRef} />
            </div>
          )}
        </div>
      </div>

      <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-[#050c1d] via-[#050c1d]/95 to-transparent px-5 pb-6 pt-12">
        <form
          onSubmit={handleSubmit}
          className="mx-auto flex w-full max-w-3xl items-end gap-3 rounded-2xl border border-blue-300/15 bg-[#0a1428]/90 p-3 shadow-[0_15px_50px_rgba(0,0,0,0.45)] backdrop-blur-xl focus-within:border-blue-400/40"
        >
          <textarea
            value={input}
            onChange={(event) =>
              setInput(event.target.value)
            }
            disabled={disabled}
            placeholder= {disabled? "Daily limit reached" : "Ask WaveGuide..."}
            rows={1}
            className="max-h-36 min-h-11 flex-1 resize-none bg-transparent px-2 py-2.5 text-sm text-slate-100 outline-none placeholder:text-slate-600"
            onKeyDown={(event) => {
              if (
                event.key === "Enter" &&
                !event.shiftKey
              ) {
                event.preventDefault();

                event.currentTarget.form?.requestSubmit();
              }
            }}
          />

          <button
            type="submit"
            disabled={loading || disabled || !input.trim()}
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-lg text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-slate-800 disabled:text-slate-600"
          >
            ↑
          </button>
        </form>

        <p className="mx-auto mt-2 max-w-3xl text-center text-[11px] text-slate-600">
          WaveGuide can make mistakes. Check important
          game information.
        </p>
      </div>
    </main>
  );
}