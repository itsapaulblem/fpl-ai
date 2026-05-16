import { useEffect, useRef, useState } from "react";
import { Send, X, Loader2, Swords } from "lucide-react";
import { api } from "../api";
import type { ChatMessage } from "../types";

const ROSENIOR_PHOTO = "/rosenior.jpg";

const WELCOME: ChatMessage = {
  role: "assistant",
  content:
    "Hi I am Liam Rosenior. I'm not arrogant. I'm good at what I do. Your FPL players need to make a decision to be around the ball, to respect the ball!",
};

export type ChatContext = {
  /** Short label shown in the header (e.g. "League: The Lads · vs John"). */
  label: string;
  /** Full text appended to the system prompt server-side. */
  text: string;
};

export function RoseniorChat({
  context,
  openSignal,
  autoPrompt,
  autoPromptSignal,
}: {
  context?: ChatContext | null;
  /** Increment this number from a parent to programmatically open the chat. */
  openSignal?: number;
  /** A user message to auto-send the next time `autoPromptSignal` increments. */
  autoPrompt?: string | null;
  autoPromptSignal?: number;
} = {}) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastAutoPromptSignal = useRef<number>(0);
  // Keep the latest context in a ref so the auto-send effect always reads the
  // freshest league/rival context without needing it in the dep array.
  const contextRef = useRef<ChatContext | null | undefined>(context);
  useEffect(() => {
    contextRef.current = context;
  }, [context]);

  // Auto-scroll to bottom on new message
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, loading]);

  // Open programmatically when parent bumps `openSignal`.
  useEffect(() => {
    if (openSignal && openSignal > 0) setOpen(true);
  }, [openSignal]);

  async function sendText(text: string) {
    const trimmed = text.trim();
    if (!trimmed || loading) return;
    const next: ChatMessage[] = [...messages, { role: "user", content: trimmed }];
    setMessages(next);
    setInput("");
    setLoading(true);
    setError(null);
    try {
      const history = next.filter((m) => m !== WELCOME);
      const { reply } = await api.chat(history, contextRef.current?.text);
      setMessages((m) => [...m, { role: "assistant", content: reply }]);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function send() {
    await sendText(input);
  }

  // Auto-send when `autoPromptSignal` increments (e.g. user clicks "Ask Liam").
  useEffect(() => {
    if (
      autoPromptSignal &&
      autoPromptSignal > lastAutoPromptSignal.current &&
      autoPrompt &&
      autoPrompt.trim()
    ) {
      lastAutoPromptSignal.current = autoPromptSignal;
      setOpen(true);
      // Defer one tick so the panel renders before the request fires.
      setTimeout(() => {
        void sendText(autoPrompt);
      }, 50);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoPromptSignal]);

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  return (
    <>
      {/* Floating launcher (bottom-left) */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          aria-label="Chat with Liam Rosenior"
          className="fixed bottom-6 left-6 z-40 flex items-center gap-3 rounded-full bg-panel pl-1 pr-4 py-1 shadow-lg shadow-black/40 ring-2 ring-accent hover:bg-panel2"
        >
          <img
            src={ROSENIOR_PHOTO}
            alt=""
            className="h-12 w-12 rounded-full object-cover ring-2 ring-accent2"
            loading="lazy"
          />
          <div className="text-left">
            <p className="text-[10px] uppercase tracking-wider text-muted leading-none">
              Ask the man-ager
            </p>
            <p className="text-sm font-semibold text-text leading-tight">
              Liam Rosenior
            </p>
          </div>
        </button>
      )}

      {/* Chat panel (slides up from bottom-left) */}
      {open && (
        <div className="fixed bottom-6 left-6 z-40 flex h-[34rem] w-[24rem] flex-col overflow-hidden rounded-2xl bg-panel shadow-2xl shadow-black/60 ring-1 ring-border sm:w-[30rem]">
          {/* Header */}
          <div className="flex items-center gap-3 border-b border-border bg-panel2 px-3 py-2">
            <img
              src={ROSENIOR_PHOTO}
              alt=""
              className="h-10 w-10 rounded-full object-cover ring-2 ring-accent"
            />
            <div className="flex-1 leading-tight">
              <p className="text-base font-semibold text-text">Liam Rosenior</p>
              <p className="text-[11px] text-accent">
                <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-accent" />
                Online · talking tactics and respecting the ball
              </p>
              {context?.label && (
                <p className="mt-0.5 flex items-center gap-1 text-[10px] text-accent2">
                  <Swords className="h-3 w-3" />
                  <span className="truncate">{context.label}</span>
                </p>
              )}
            </div>
            <button
              onClick={() => setOpen(false)}
              aria-label="Close chat"
              className="flex h-8 w-8 items-center justify-center rounded-lg text-muted hover:bg-bg/40 hover:text-text"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* Messages */}
          <div
            ref={scrollRef}
            className="flex-1 space-y-3 overflow-y-auto px-3 py-4"
          >
            {messages.map((m, i) => (
              <Bubble key={i} message={m} />
            ))}
            {loading && (
              <div className="flex items-center gap-2 text-xs text-muted">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Liam is thinking…
              </div>
            )}
            {error && (
              <p className="rounded-md bg-danger/15 px-2 py-1 text-xs text-danger ring-1 ring-danger/40">
                {error}
              </p>
            )}
          </div>

          {/* Composer */}
          <div className="border-t border-border bg-panel2 p-2">
            <div className="flex items-end gap-2">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                rows={1}
                placeholder="Ask the man-ager about FPL!"
                className="max-h-32 min-h-[2.5rem] flex-1 resize-none rounded-lg bg-bg px-3 py-2 text-base text-text outline-none ring-1 ring-border focus:ring-2 focus:ring-accent"
              />
              <button
                onClick={send}
                disabled={!input.trim() || loading}
                aria-label="Send"
                className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent text-bg hover:bg-accent/80 disabled:opacity-50"
              >
                <Send className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 text-base leading-snug ring-1 ${
          isUser
            ? "bg-accent text-bg ring-accent/40"
            : "bg-bg/60 text-text ring-border"
        }`}
      >
        {message.content}
      </div>
    </div>
  );
}
