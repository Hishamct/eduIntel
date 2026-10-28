import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, StatusBadge, ChatBubbles } from "../../components/ui";
import { logout } from "../../api/auth";
import apiClient from "../../api/client";
import PortalAssistantWidget from "../../components/PortalAssistantWidget";

const CURRENT_USER_NAME = "Arjun Nair";

const DEFAULT_THREADS = [
  {
    id: "th-1",
    title: "Clarification on Lenz's Law Negative Sign in Faraday's Equation",
    subject: "PHYSICS",
    askedDate: "27 Sep 2026, 14:30",
    statusVariant: "on-track",
    statusLabel: "RESOLVED",
    messages: [
      {
        id: "m-1",
        senderType: "student",
        senderName: CURRENT_USER_NAME,
        text: "In Faraday's law EMF = -d(Phi)/dt, why is the negative sign explicitly required if we can determine the direction of induced current separately using the right-hand rule?",
        timestamp: "02:30 PM",
      },
      {
        id: "m-2",
        senderType: "institution",
        senderName: "Prof. R. Sen (Physics Faculty)",
        text: "Great question, Arjun. The negative sign is a mathematical expression of Conservation of Energy (Lenz's Law). Without the negative sign, an induced current would create a magnetic field reinforcing the flux change, leading to runaway free energy. The minus sign guarantees that the work done against the opposing force produces the electrical energy.",
        timestamp: "03:15 PM",
      }
    ]
  },
  {
    id: "th-2",
    title: "Choosing between Integration by Parts vs Substitution for x*e^(x^2)",
    subject: "MATHEMATICS",
    askedDate: "26 Sep 2026, 11:20",
    statusVariant: "on-track",
    statusLabel: "RESOLVED",
    messages: [
      {
        id: "m-3",
        senderType: "student",
        senderName: CURRENT_USER_NAME,
        text: "When evaluating integral of x * e^(x^2) dx, I tried integration by parts with u=x and dv=e^(x^2) dx, but got stuck integrating e^(x^2). What is the standard technique here?",
        timestamp: "11:20 AM",
      },
      {
        id: "m-4",
        senderType: "institution",
        senderName: "Dr. A. Sharma (Math Faculty)",
        text: "Notice that the derivative of the exponent x^2 is 2x, which matches the factor x outside. Use u-substitution: let u = x^2, then du = 2x dx => x dx = du/2. The integral becomes (1/2) * integral of e^u du = (1/2)*e^(x^2) + C. Integration by parts is unnecessary!",
        timestamp: "12:05 PM",
      }
    ]
  },
  {
    id: "th-3",
    title: "Time complexity difference between QuickSort and MergeSort on linked lists",
    subject: "COMPUTER SCIENCE",
    askedDate: "25 Sep 2026, 16:45",
    statusVariant: "needs-attention",
    statusLabel: "PENDING FACULTY",
    messages: [
      {
        id: "m-5",
        senderType: "student",
        senderName: CURRENT_USER_NAME,
        text: "Why is MergeSort preferred over QuickSort for sorting singly linked lists, even though QuickSort has lower memory overhead for arrays?",
        timestamp: "04:45 PM",
      }
    ]
  }
];

function mapThread(thread) {
  return {
    id: thread.id,
    title: thread.title,
    subject: thread.subject,
    askedDate: thread.created_at ? new Date(thread.created_at).toLocaleString("en-IN", {
      day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
    }) : thread.askedDate || "Recent",
    statusVariant: thread.status === "resolved" ? "on-track" : "needs-attention",
    statusLabel: thread.status === "resolved" ? "RESOLVED" : "PENDING FACULTY",
    messages: thread.messages ? thread.messages.map((msg) => ({
      id: msg.id,
      senderType: msg.sender_role === "student" ? "student" : "institution",
      senderName: msg.sender_role === "student" ? CURRENT_USER_NAME : (msg.sender_name || "Faculty Advisory"),
      text: msg.body || msg.text,
      timestamp: msg.created_at ? new Date(msg.created_at).toLocaleTimeString("en-IN", {
        hour: "2-digit", minute: "2-digit",
      }) : msg.timestamp || "Just now",
    })) : [],
  };
}

export default function DoubtForum() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [threads, setThreads] = useState(DEFAULT_THREADS);
  const [selectedSubject, setSelectedSubject] = useState("ALL");
  const [newTitle, setNewTitle] = useState("");
  const [newSubject, setNewSubject] = useState("MATHEMATICS");
  const [newQuestionText, setNewQuestionText] = useState("");
  const [isPosting, setIsPosting] = useState(false);
  const navigate = useNavigate();

  const fetchThreads = async () => {
    try {
      const res = await apiClient.get("/student/doubts");
      if (res.data && res.data.length > 0) {
        setThreads(res.data.map(mapThread));
      }
    } catch (err) {
      console.warn("Backend doubts endpoint offline, displaying demo discussion threads.", err);
    }
  };

  useEffect(() => {
    fetchThreads();
  }, []);

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const handlePostDoubt = async (e) => {
    e.preventDefault();
    if (!newTitle || !newQuestionText) {
      alert("Please enter both a title and question details.");
      return;
    }

    setIsPosting(true);
    try {
      await apiClient.post("/student/doubts", {
        subject: newSubject,
        title: newTitle,
        body: newQuestionText,
      });
      await fetchThreads();
      alert("Doubt posted successfully! Faculty has been notified.");
    } catch (err) {
      // In offline preview mode, inject locally
      const mockThread = {
        id: `th-${Date.now()}`,
        title: newTitle,
        subject: newSubject,
        askedDate: "Just now",
        statusVariant: "needs-attention",
        statusLabel: "PENDING FACULTY",
        messages: [
          {
            id: `m-${Date.now()}`,
            senderType: "student",
            senderName: CURRENT_USER_NAME,
            text: newQuestionText,
            timestamp: "Just now",
          }
        ]
      };
      setThreads((prev) => [mockThread, ...prev]);
      alert("Question posted (Preview session saved)!");
    } finally {
      setNewTitle("");
      setNewQuestionText("");
      setIsPosting(false);
    }
  };

  const filteredThreads = threads.filter((t) =>
    selectedSubject === "ALL" || t.subject.toUpperCase() === selectedSubject.toUpperCase()
  );

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
          user={{ name: "Arjun Nair", role: "Grade 11-A" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content">
          {/* Header */}
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-start",
              marginBottom: "28px",
              flexWrap: "wrap",
              gap: "16px"
            }}
          >
            <div>
              <div style={{ display: "inline-flex", alignItems: "center", gap: "6px", padding: "4px 10px", borderRadius: "9999px", background: "rgba(16, 185, 129, 0.1)", border: "1px solid rgba(16, 185, 129, 0.2)", marginBottom: "8px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "14px", color: "#059669" }}>forum</span>
                <span style={{ fontSize: "11px", fontWeight: 700, color: "#059669", letterSpacing: "0.06em", textTransform: "uppercase" }}>
                  Peer & AI Collaboration
                </span>
              </div>
              <h1
                className="edu-font-heading"
                style={{ fontSize: "28px", fontWeight: 700, color: "#0F172A", margin: "0 0 6px 0", letterSpacing: "-0.02em" }}
              >
                Doubt Resolution & Inquiry Forum
              </h1>
              <p style={{ fontSize: "14px", color: "#64748B", margin: 0, maxWidth: "600px" }}>
                Post conceptual questions, receive verified explanations from course professors, and search resolved peer solutions.
              </p>
            </div>
          </div>

          {/* Metric KPI Cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "16px", marginBottom: "28px" }}>
            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Total Inquiries</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#10B981" }}>question_answer</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                {threads.length} Threads
              </div>
              <div style={{ fontSize: "12px", color: "#059669" }}>Active academic dialogues</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Resolved by Faculty</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#0284C7" }}>check_circle</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                {threads.filter(t => t.statusLabel === "RESOLVED").length} Clarified
              </div>
              <div style={{ fontSize: "12px", color: "#0284C7" }}>Instructor verified answers</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Pending Faculty Review</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#F59E0B" }}>schedule</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                {threads.filter(t => t.statusLabel.includes("PENDING")).length} Pending
              </div>
              <div style={{ fontSize: "12px", color: "#D97706" }}>Expected reply &lt; 4 hours</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Avg Response Time</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#8B5CF6" }}>bolt</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                2.4 Hours
              </div>
              <div style={{ fontSize: "12px", color: "#059669" }}>Priority faculty queue</div>
            </div>
          </div>

          {/* Ask New Doubt Card */}
          <div className="edu-card" style={{ padding: "26px", marginBottom: "28px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "18px" }}>
              <div style={{ width: "36px", height: "36px", borderRadius: "10px", background: "rgba(16, 185, 129, 0.12)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#059669" }}>add_comment</span>
              </div>
              <div>
                <h3 className="edu-font-heading" style={{ margin: 0, fontSize: "17px", fontWeight: 700, color: "#0F172A" }}>
                  Ask a New Subject Question
                </h3>
                <p style={{ margin: 0, fontSize: "12px", color: "#64748B" }}>Notify professors and get peer assistance</p>
              </div>
            </div>

            <form onSubmit={handlePostDoubt} style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 260px), 1fr))", gap: "14px" }}>
                <div>
                  <label style={{ display: "block", fontSize: "11px", fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "6px" }}>
                    Question Title
                  </label>
                  <input
                    type="text"
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                    placeholder="e.g. Derivation of Lenz's Law induced EMF formula"
                    style={{
                      width: "100%",
                      padding: "11px 14px",
                      borderRadius: "10px",
                      border: "1px solid rgba(226, 232, 240, 0.9)",
                      backgroundColor: "rgba(255, 255, 255, 0.9)",
                      fontSize: "13px",
                      color: "#1E293B",
                      outline: "none",
                      boxSizing: "border-box"
                    }}
                  />
                </div>

                <div>
                  <label style={{ display: "block", fontSize: "11px", fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "6px" }}>
                    Subject Discipline
                  </label>
                  <select
                    value={newSubject}
                    onChange={(e) => setNewSubject(e.target.value)}
                    style={{
                      width: "100%",
                      padding: "11px 14px",
                      borderRadius: "10px",
                      border: "1px solid rgba(226, 232, 240, 0.9)",
                      backgroundColor: "rgba(255, 255, 255, 0.9)",
                      fontSize: "13px",
                      color: "#1E293B",
                      outline: "none"
                    }}
                  >
                    <option value="MATHEMATICS">MATHEMATICS</option>
                    <option value="PHYSICS">PHYSICS</option>
                    <option value="CHEMISTRY">CHEMISTRY</option>
                    <option value="COMPUTER SCIENCE">COMPUTER SCIENCE</option>
                  </select>
                </div>
              </div>

              <div>
                <label style={{ display: "block", fontSize: "11px", fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "6px" }}>
                  Detailed Formulation & Problem Context
                </label>
                <textarea
                  rows={3}
                  value={newQuestionText}
                  onChange={(e) => setNewQuestionText(e.target.value)}
                  placeholder="Explain what step you got stuck on, include formulas or equation references..."
                  style={{
                    width: "100%",
                    padding: "11px 14px",
                    borderRadius: "10px",
                    border: "1px solid rgba(226, 232, 240, 0.9)",
                    backgroundColor: "rgba(255, 255, 255, 0.9)",
                    fontSize: "13px",
                    color: "#1E293B",
                    outline: "none",
                    resize: "vertical",
                    boxSizing: "border-box"
                  }}
                />
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <button
                  className="edu-btn-primary"
                  type="submit"
                  disabled={isPosting}
                  style={{
                    padding: "11px 24px",
                    borderRadius: "10px",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "8px",
                    fontSize: "13px",
                    fontWeight: 700,
                    cursor: "pointer",
                    boxShadow: "0 4px 14px rgba(16, 185, 129, 0.28)",
                    opacity: isPosting ? 0.6 : 1
                  }}
                >
                  <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>send</span>
                  {isPosting ? "TRANSMITTING..." : "POST QUESTION TO FORUM"}
                </button>
              </div>
            </form>
          </div>

          {/* Subject Filter Pills */}
          <div style={{ display: "flex", gap: "8px", overflowX: "auto", paddingBottom: "4px", marginBottom: "20px" }}>
            {["ALL", "MATHEMATICS", "PHYSICS", "CHEMISTRY", "COMPUTER SCIENCE"].map((sub) => (
              <button
                key={sub}
                onClick={() => setSelectedSubject(sub)}
                style={{
                  padding: "8px 16px",
                  borderRadius: "9999px",
                  fontSize: "12px",
                  fontWeight: 600,
                  border: "none",
                  cursor: "pointer",
                  transition: "all 0.2s ease",
                  backgroundColor: selectedSubject === sub ? "#10B981" : "rgba(255, 255, 255, 0.75)",
                  color: selectedSubject === sub ? "#FFFFFF" : "#475569",
                  boxShadow: selectedSubject === sub ? "0 4px 12px rgba(16, 185, 129, 0.3)" : "0 1px 3px rgba(0,0,0,0.05)",
                }}
              >
                {sub === "ALL" ? "All Subjects" : sub}
              </button>
            ))}
          </div>

          {/* Thread List */}
          <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
            {filteredThreads.map((thread) => (
              <div
                key={thread.id}
                className="edu-card"
                style={{
                  padding: "20px",
                  display: "flex",
                  flexDirection: "column",
                  gap: "12px"
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "8px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                    <span style={{
                      fontSize: "11px",
                      fontWeight: 700,
                      color: "#059669",
                      background: "rgba(16, 185, 129, 0.12)",
                      padding: "3px 10px",
                      borderRadius: "6px",
                      border: "1px solid rgba(16, 185, 129, 0.25)"
                    }}>
                      {thread.subject}
                    </span>
                    <span style={{ fontSize: "12px", color: "#64748B" }}>Asked: {thread.askedDate}</span>
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

      <PortalAssistantWidget />
    </div>
  );
}