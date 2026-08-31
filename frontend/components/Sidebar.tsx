import type { Conversation } from "@/types/chat";


type SidebarProps = {
  conversations: Conversation[];
  activeSessionId: string | null;
  onSelectConversation: (sessionId: string) => void;
  onNewChat: () => void;
  disabled: boolean;
};


export default function Sidebar({
  conversations,
  activeSessionId,
  onSelectConversation,
  onNewChat,
  disabled,
}: SidebarProps) {
  return (
    <aside className="flex h-screen w-72 shrink-0 flex-col border-r border-white/10 bg-[#030816]/80 backdrop-blur-xl">
      <div className="px-5 pt-6">
        <h1 className="text-2xl font-bold tracking-tight text-white">
          Wave
          <span className="text-blue-400">
            Guide
          </span>
        </h1>

        <p className="mt-1 text-xs text-slate-500">
          League coaching assistant
        </p>

        <button
          onClick={onNewChat}
          disabled={disabled}
          className="mt-6 w-full rounded-xl border border-blue-400/20 bg-blue-500/10 px-4 py-3 text-left text-sm font-medium text-blue-100 transition hover:border-blue-400/40 hover:bg-blue-500/15"
        >
          + New Chat
        </button>
      </div>

      <div className="mt-7 flex min-h-0 flex-1 flex-col px-3">
        <h2 className="px-2 pb-3 text-sm font-bold text-slate-200">
          Past Conversations
        </h2>

        <div className="conversation-scroll flex-1 space-y-1 overflow-y-auto pr-1">
          {conversations.length === 0 ? (
            <p className="px-2 py-3 text-sm text-slate-600">
              No conversations yet.
            </p>
          ) : (
            conversations.map((conversation) => {
              const active =
                conversation.sessionId ===
                activeSessionId;

              return (
                <button
                  key={conversation.sessionId}
                  onClick={() =>
                    onSelectConversation(
                      conversation.sessionId
                    )
                  }
                  className={`w-full truncate rounded-xl px-3 py-3 text-left text-sm transition ${
                    active
                      ? "border border-blue-400/20 bg-gradient-to-r from-blue-950/80 to-blue-900/30 text-blue-100 shadow-[0_0_24px_rgba(37,99,235,0.08)]"
                      : "border border-transparent text-slate-400 hover:bg-white/5 hover:text-slate-200"
                  }`}
                >
                  {conversation.title}
                </button>
              );
            })
          )}
        </div>
      </div>

      <div className="border-t border-white/10 px-5 py-4 text-xs text-slate-600">
        WaveGuide
      </div>
    </aside>
  );
}