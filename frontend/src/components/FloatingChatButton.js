import React, { useState, useCallback, useRef, useEffect } from "react";
import "./FloatingChatButton.css";

const API = "http://localhost:8000";

const SUGGESTIONS = [
  "Which segment should I focus on first?",
  "Who are my most valuable customers?",
  "What are my top selling products?",
  "Which segment is most at risk of churning?",
  "What's my best sales day of the week?",
  "What % of revenue do my top segment drive?",
];

export default function FloatingChatButton({ context }) {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef(null);
  const panelRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages]);

  // Close panel when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target) && !e.target.closest(".floating-chat-btn")) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [isOpen]);

  const send = useCallback(async (text) => {
    const msg = (text || input).trim();
    if (!msg || streaming || !context) return;
    setInput("");
    const userMsg = { role: "user", content: msg };
    setMessages(prev => [...prev, userMsg]);
    setStreaming(true);
    setMessages(prev => [...prev, { role: "assistant", content: "" }]);
    try {
      const res = await fetch(`${API}/ai/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, history: messages, context }),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "failed");
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let full = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        full += dec.decode(value, { stream: true });
        setMessages(prev => [...prev.slice(0, -1), { role: "assistant", content: full }]);
      }
    } catch (e) {
      setMessages(prev => [...prev.slice(0, -1), { role: "assistant", content: `⚠️ ${e.message}` }]);
    } finally {
      setStreaming(false);
    }
  }, [input, streaming, messages, context]);

  if (!context) return null;

  return (
    <>
      {/* Floating Button */}
      <button
        className="floating-chat-btn"
        onClick={() => setIsOpen(!isOpen)}
        title="Ask AI about your data"
      >
        <span className="floating-chat-icon">🧠</span>
      </button>

      {/* Floating Panel */}
      {isOpen && (
        <div className="floating-chat-panel" ref={panelRef}>
          <div className="floating-chat-header">
            <div className="floating-chat-title">
              <span>🧠</span> Ask Your Data
            </div>
            <button
              className="floating-chat-close"
              onClick={() => setIsOpen(false)}
            >
              ✕
            </button>
          </div>

          {messages.length === 0 && (
            <div className="floating-chat-suggestions">
              {SUGGESTIONS.map((s, i) => (
                <button
                  key={i}
                  className="floating-suggestion-chip"
                  onClick={() => send(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          )}

          <div className="floating-chat-messages">
            {messages.length === 0 ? (
              <div className="floating-chat-empty">
                <span className="floating-chat-empty-icon">💬</span>
                <p className="floating-chat-empty-text">Ask anything about your segments</p>
              </div>
            ) : (
              messages.map((m, i) => (
                <div key={i} className={`floating-chat-msg floating-chat-msg-${m.role === "user" ? "user" : "ai"}`}>
                  <div className="floating-chat-msg-avatar">{m.role === "user" ? "👤" : "🧠"}</div>
                  <div className="floating-chat-msg-bubble">
                    {m.role === "assistant" && m.content === "" ? (
                      <div className="floating-chat-typing">
                        <span className="floating-chat-typing-dot" />
                        <span className="floating-chat-typing-dot" />
                        <span className="floating-chat-typing-dot" />
                      </div>
                    ) : (
                      m.content
                    )}
                  </div>
                </div>
              ))
            )}
            <div ref={bottomRef} />
          </div>

          <div className="floating-chat-input-row">
            <textarea
              className="floating-chat-input"
              placeholder="Ask a question…"
              value={input}
              rows={1}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              disabled={streaming}
            />
            <button
              className="floating-chat-send"
              onClick={() => send()}
              disabled={!input.trim() || streaming}
            >
              ↑
            </button>
          </div>

          {messages.length > 0 && (
            <button className="floating-chat-clear" onClick={() => setMessages([])}>
              Clear conversation
            </button>
          )}
        </div>
      )}
    </>
  );
}
