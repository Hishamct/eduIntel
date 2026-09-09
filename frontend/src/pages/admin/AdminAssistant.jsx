import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "../../api/client";
import { logout } from "../../api/auth";
import { Sidebar, TopBar, ChatBubbles } from "../../components/ui";
import "../../components/ui/ui.css";

function getOrCreateSessionId() {
  const key = "admin_assistant_session_id";
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
    senderType: isAssistant ? "institution" : "admin",
    senderName: isAssistant ? "AI Assistant" : "You",
    text: msg.content,
    timestamp: msg.timestamp || "",
  };
}

const SUGGESTED_QUESTIONS = [
  "How many students and teachers do we have?",
  "What's our salary payout status this month?",
  "What's the attendance rate across all classes?",
  "Which teachers have the fastest grading turnaround?",
  "What's our revenue collection status?",
  "Are there any timetable gaps in our sections?",
];

export default function AdminAssistant() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content:
        "Hi! I can answer questions about student/teacher counts, salary status, timetable coverage, teacher grading performance, revenue, and attendance — no need to dig through the dashboards yourself. What would you like to know?",
      timestamp: nowTimestamp(),
    },
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const sessionIdRef = useRef(getOrCreateSessionId());
  const scrollRef = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  async function sendQuery(query) {
    if (!query.trim() || isLoading) return;

    setMessages((prev) => [...prev, { role: "user", content: query, timestamp: nowTimestamp() }]);
    setInput("");
    setIsLoading(true);

    try {
      const { data } = await apiClient.post("/agents/admin-assistant/chat", {
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

  function handleSend() {
    sendQuery(input);
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  const chatBubbleMessages = messages.map(toChatBubbleMessage);
  const showSuggestions = messages.length === 1; // only show before the first real question

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="admin"
        activeId="ai-assistant"
        logoText="EduIntel AI"
        roleText="Administrator Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "ai-assistant") {
            navigate(`/admin/${itemId}`);
          }
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: "Dr. Aria Vance", role: "Super Admin" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content">
          <div style={{ marginBottom: "24px" }}>
            <span
              style={{
                fontSize: "11px",
                fontWeight: 700,
                letterSpacing: "0.05em",
                color: "#5F6774",
                textTransform: "uppercase",
              }}
            >
              INSTITUTIONAL INTELLIGENCE
            </span>
            <h2
              className="edu-font-heading"
              style={{ fontSize: "24px", fontWeight: 600, color: "#1B2330", margin: "4px 0 0 0" }}
            >
              AI Assistant
            </h2>
            <p style={{ fontSize: "14px", color: "#5F6774", margin: "4px 0 0 0" }}>
              Ask about students, teachers, salary, timetable, revenue, or attendance — answered from live platform data.
            </p>
          </div>

          <div
            className="edu-card"
            style={{
              display: "flex",
              flexDirection: "column",
              height: "calc(100vh - 260px)",
              minHeight: "400px",
              padding: 0,
              overflow: "hidden",
            }}
          >
            <div style={{ flex: 1, overflowY: "auto", padding: "20px" }} ref={scrollRef}>
              <ChatBubbles title="" messages={chatBubbleMessages} />

              {isLoading && (
                <p style={{ fontSize: "13px", color: "#5F6774", fontStyle: "italic", padding: "8px 4px" }}>
                  Thinking…
                </p>
              )}

              {showSuggestions && !isLoading && (
                <div style={{ marginTop: "16px", display: "flex", flexDirection: "column", gap: "8px" }}>
                  <p style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase", margin: "0 0 4px 0" }}>
                    Try asking
                  </p>
                  {SUGGESTED_QUESTIONS.map((q) => (
                    <button
                      key={q}
                      onClick={() => sendQuery(q)}
                      style={{
                        textAlign: "left",
                        padding: "10px 14px",
                        borderRadius: "6px",
                        border: "1px solid #E5E5E1",
                        backgroundColor: "#F4F4F1",
                        color: "#1B2330",
                        fontSize: "13px",
                        cursor: "pointer",
                        transition: "all 0.15s ease",
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "#EAEAE6")}
                      onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "#F4F4F1")}
                    >
                      {q}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div
              style={{
                display: "flex",
                gap: "8px",
                padding: "12px 16px",
                borderTop: "1px solid #E5E5E1",
                backgroundColor: "#FFFFFF",
              }}
            >
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about students, salary, attendance, revenue..."
                disabled={isLoading}
                style={{
                  flex: 1,
                  padding: "10px 14px",
                  borderRadius: "6px",
                  border: "1px solid #E5E5E1",
                  fontSize: "14px",
                  outline: "none",
                  fontFamily: "var(--font-body)",
                }}
              />
              <button
                onClick={handleSend}
                disabled={isLoading || !input.trim()}
                className="edu-btn-primary"
                style={{
                  padding: "10px 20px",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                  opacity: isLoading || !input.trim() ? 0.6 : 1,
                }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>send</span>
              </button>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}