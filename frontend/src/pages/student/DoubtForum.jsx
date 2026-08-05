import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, StatusBadge, ChatBubbles } from "../../components/ui";
import { doubtThreadsData } from "../../data/studentMockData";
import { logout } from "../../api/auth";

export default function DoubtForum() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [threads, setThreads] = useState(doubtThreadsData);
  const [newTitle, setNewTitle] = useState("");
  const [newSubject, setNewSubject] = useState("MATHEMATICS");
  const [newQuestionText, setNewQuestionText] = useState("");
  const navigate = useNavigate();

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const handlePostDoubt = (e) => {
    e.preventDefault();
    if (!newTitle || !newQuestionText) {
      alert("Please enter both a title and question details.");
      return;
    }

    const newThread = {
      id: `DOUBT-${Math.floor(10 + Math.random() * 90)}`,
      title: newTitle,
      subject: newSubject,
      askedDate: "Just Now",
      statusVariant: "needs-attention",
      statusLabel: "PENDING FACULTY",
      messages: [
        {
          id: `msg-${Date.now()}`,
          senderType: "student",
          senderName: "Arjun Nair",
          text: newQuestionText,
          timestamp: "Just Now"
        }
      ]
    };

    setThreads([newThread, ...threads]);
    setNewTitle("");
    setNewQuestionText("");
    alert("Doubt posted successfully! Faculty has been notified.");
  };

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="student"
        activeId="doubts"
        logoText="EduIntel AI"
        roleText="Student Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "doubts") navigate(`/student/${itemId}`);
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: "Arjun Nair", role: "Student" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content">
          {/* Header Bar */}
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-end",
              marginBottom: "24px",
              flexWrap: "wrap",
              gap: "12px"
            }}
          >
            <div>
              <span
                style={{
                  fontSize: "11px",
                  fontWeight: 700,
                  letterSpacing: "0.05em",
                  color: "#5F6774",
                  textTransform: "uppercase"
                }}
              >
                ACADEMIC HELP DESK
              </span>
              <h2
                className="edu-font-heading"
                style={{ fontSize: "24px", fontWeight: 600, color: "#1B2330", margin: "4px 0 0 0" }}
              >
                Doubt Forum
              </h2>
              <p style={{ fontSize: "14px", color: "#5F6774", margin: "4px 0 0 0" }}>
                Ask subject queries, engage in academic discussions, and view faculty clarifications.
              </p>
            </div>
          </div>

          {/* Ask New Doubt Card */}
          <div className="edu-card" style={{ padding: "20px", marginBottom: "24px" }}>
            <h4 className="edu-font-heading" style={{ fontSize: "16px", fontWeight: 600, color: "#1B2330", margin: "0 0 12px 0" }}>
              Ask a New Question / Doubt
            </h4>

            <form onSubmit={handlePostDoubt} style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 200px), 1fr))", gap: "12px" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Question Title</label>
                  <input
                    type="text"
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                    placeholder="e.g. Derivation of Lenz's Law induced EMF formula"
                    style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "14px", outline: "none" }}
                  />
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Subject</label>
                  <select
                    value={newSubject}
                    onChange={(e) => setNewSubject(e.target.value)}
                    style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "13px", outline: "none" }}
                  >
                    <option value="MATHEMATICS">MATHEMATICS</option>
                    <option value="PHYSICS">PHYSICS</option>
                    <option value="CHEMISTRY">CHEMISTRY</option>
                    <option value="COMPUTER SCIENCE">COMPUTER SCIENCE</option>
                  </select>
                </div>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Question Details & Context</label>
                <textarea
                  rows={3}
                  value={newQuestionText}
                  onChange={(e) => setNewQuestionText(e.target.value)}
                  placeholder="Describe your doubt in detail..."
                  style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "14px", outline: "none", resize: "vertical" }}
                />
              </div>

              <button className="edu-btn-primary" type="submit" style={{ width: "fit-content", padding: "10px 24px", display: "flex", alignItems: "center", gap: "6px" }}>
                POST QUESTION
                <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>send</span>
              </button>
            </form>
          </div>

          {/* Discussion Threads List */}
          <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
            {threads.map((thread) => (
              <div key={thread.id} style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "0 4px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                    <span style={{ fontSize: "10px", fontWeight: 700, color: "#26415E", backgroundColor: "#F0F4F8", padding: "3px 8px", borderRadius: "2px" }}>
                      {thread.subject}
                    </span>
                    <span style={{ fontSize: "12px", color: "#5F6774" }}>Asked: {thread.askedDate}</span>
                  </div>
                  <StatusBadge variant={thread.statusVariant} label={thread.statusLabel} />
                </div>
                <ChatBubbles
                  title={thread.title}
                  messages={thread.messages}
                />
              </div>
            ))}
          </div>
        </main>
      </div>
    </div>
  );
}
