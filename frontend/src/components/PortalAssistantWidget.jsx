import { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";
import { ChatBubbles } from "./ui";
import apiClient from "../api/client";
import "./PortalAssistantWidget.css";

function getOrCreateSessionId() {
  const key = "portal_assistant_session_id";
  let sessionId = sessionStorage.getItem(key);
  if (!sessionId) {
    sessionId = `session-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    sessionStorage.setItem(key, sessionId);
  }
  return sessionId;
}

function nowTimestamp() {
  return new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
}

function toChatBubbleMessage(msg, idx) {
  const isAssistant = msg.role === "assistant";
  return {
    id: `${idx}-${msg.role}`,
    senderType: isAssistant ? "institution" : "student",
    senderName: isAssistant ? "Portal Assistant" : "You",
    text: msg.content,
    timestamp: msg.timestamp || "",
  };
}

function PortalAssistantWidgetInner() {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content:
        "Hi! I can help you with using the platform — homework upload, the doubt forum, study materials, your dashboard. What do you need?",
      timestamp: nowTimestamp(),
    },
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const sessionIdRef = useRef(getOrCreateSessionId());
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isOpen]);

  async function handleSend() {
    const query = input.trim();
    if (!query || isLoading) return;

    setMessages((prev) => [...prev, { role: "user", content: query, timestamp: nowTimestamp() }]);
    setInput("");
    setIsLoading(true);

    try {
      const { data } = await apiClient.post("/agents/portal-assistant/chat", {
        session_id: sessionIdRef.current,
        query,
      });
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: data.answer, timestamp: nowTimestamp() },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Sorry, something went wrong reaching the assistant. Please try again.",
          timestamp: nowTimestamp(),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  const chatBubbleMessages = messages.map(toChatBubbleMessage);

  return (
    <div className="edu-portal-assistant-widget">
      {isOpen && (
        <div className="edu-portal-assistant-panel">
          <div className="edu-portal-assistant-body" ref={scrollRef}>
            <ChatBubbles title="Portal Assistant" messages={chatBubbleMessages} />
            {isLoading && <div className="edu-portal-assistant-typing">Thinking…</div>}
          </div>

          <div className="edu-portal-assistant-input-row">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about the platform..."
              disabled={isLoading}
              className="edu-portal-assistant-input"
            />
            <button
              onClick={handleSend}
              disabled={isLoading || !input.trim()}
              className="edu-portal-assistant-send"
            >
              <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>send</span>
            </button>
          </div>
        </div>
      )}

      <button
        className="edu-portal-assistant-toggle"
        onClick={() => setIsOpen((v) => !v)}
        aria-label={isOpen ? "Close help assistant" : "Open help assistant"}
      >
        <span className="material-symbols-outlined" style={{ fontSize: "26px" }}>
          {isOpen ? "close" : "chat"}
        </span>
      </button>
    </div>
  );
}

export default function PortalAssistantWidget() {
  return createPortal(<PortalAssistantWidgetInner />, document.body);
}