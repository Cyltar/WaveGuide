type DailyLimitModalProps = {
  open: boolean;
  onClose: () => void;
};


export default function DailyLimitModal({
  open,
  onClose,
}: DailyLimitModalProps) {
  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl bg-white p-7 shadow-2xl">
        <h2 className="text-xl font-bold text-slate-900">
          Daily limit reached
        </h2>

        <p className="mt-3 text-sm leading-6 text-slate-600">
          LoLGPT has reached today&apos;s AI
          request limit. You can continue using
          the chatbot when the daily quota resets.
        </p>

        <p className="mt-3 text-sm text-slate-500">
          Existing conversations can still be
          viewed, but new messages and chats are
          temporarily disabled.
        </p>

        <div className="mt-6 flex justify-end">
          <button
            onClick={onClose}
            className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-600"
          >
            OK
          </button>
        </div>
      </div>
    </div>
  );
}