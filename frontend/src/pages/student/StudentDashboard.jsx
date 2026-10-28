import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "../../api/client";
import { logout } from "../../api/auth";
import { Sidebar, TopBar, StatusBadge } from "../../components/ui";
import "../../components/ui/ui.css";
import PortalAssistantWidget from "../../components/PortalAssistantWidget";

const DEFAULT_STUDENT_DASHBOARD = {
  message: "Welcome back, Arjun! You have 2 assignments due this week and 1 resolved doubt to review.",
  homework_count: 2,
  unresolved_doubts: 1,
  attendance_rate: 94.6,
  cumulative_gpa: "3.85 / 4.0",
  study_plan_ready: true,
  recent_activity: [
    { type: "homework", text: "Submitted 'Calculus Problem Set #4'", time: "2 hours ago" },
    { type: "doubt", text: "Dr. Sharma answered your question on 'Faraday's Induction'", time: "Yesterday" },
    { type: "grade", text: "Received 94/100 on 'Organic Synthesis Lab Report'", time: "2 days ago" },
    { type: "study", text: "Ingested new study note: 'Maxwell's Equations Summary'", time: "3 days ago" },
  ]
};

const COURSE_PROGRESS = [
  { subject: "MATHEMATICS", code: "MATH-301", name: "Advanced Calculus & Analysis", progress: 78, color: "#10B981", nextDue: "5 Oct 2026" },
  { subject: "PHYSICS", code: "PHYS-202", name: "Electromagnetism & Wave Mechanics", progress: 85, color: "#0EA5E9", nextDue: "8 Oct 2026" },
  { subject: "CHEMISTRY", code: "CHEM-104", name: "Organic Synthesis & Mechanisms", progress: 92, color: "#F59E0B", nextDue: "12 Oct 2026" },
  { subject: "COMPUTER SCIENCE", code: "CS-210", name: "Data Structures & Algorithms", progress: 88, color: "#8B5CF6", nextDue: "15 Oct 2026" },
];

const UPCOMING_TESTS = [
  { title: "Calculus Mid-Term Exam", subject: "MATHEMATICS", date: "10 Oct 2026", time: "09:30 AM", room: "Hall B-102" },
  { title: "Electromagnetism Lab Quiz", subject: "PHYSICS", date: "14 Oct 2026", time: "11:00 AM", room: "Physics Lab 2" },
  { title: "Organic Reactions Unit Test", subject: "CHEMISTRY", date: "18 Oct 2026", time: "02:00 PM", room: "Hall A-204" },
];

export default function StudentDashboard() {
  const [data, setData] = useState(DEFAULT_STUDENT_DASHBOARD);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    apiClient
      .get("/student/dashboard")
      .then((response) => {
        if (response.data) {
          setData((prev) => ({
            ...prev,
            ...response.data,
            recent_activity: response.data.recent_activity || prev.recent_activity,
          }));
        }
      })
      .catch((err) => {
        console.warn("Backend student dashboard offline, displaying demo preview.", err);
      });
  }, []);

  const handleProfileSelect = (itemId) => {
    if (itemId === 'logout') {
      logout(navigate);
    }
  };

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="student"
        activeId="dashboard"
        logoText="EduIntel AI"
        roleText="Student Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== 'dashboard') {
            navigate(`/student/${itemId}`);
          }
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: "Arjun Nair", role: "Grade 11-A" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content">
          {/* Header */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "28px", flexWrap: "wrap", gap: "16px" }}>
            <div>
              <div style={{ display: "inline-flex", alignItems: "center", gap: "6px", padding: "4px 10px", borderRadius: "9999px", background: "rgba(16, 185, 129, 0.1)", border: "1px solid rgba(16, 185, 129, 0.2)", marginBottom: "8px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "14px", color: "#059669" }}>school</span>
                <span style={{ fontSize: "11px", fontWeight: 700, color: "#059669", letterSpacing: "0.06em", textTransform: "uppercase" }}>
                  Student Academic Portal
                </span>
              </div>
              <h1 className="edu-font-heading" style={{ fontSize: "28px", fontWeight: 700, color: "#0F172A", margin: "0 0 6px 0", letterSpacing: "-0.02em" }}>
                Academic Overview & Learning Trajectory
              </h1>
              <p style={{ fontSize: "14px", color: "#64748B", margin: 0, maxWidth: "600px" }}>
                Review active course modules, track pending assignments, query the AI Doubt Assistant, and examine personal learning goals.
              </p>
            </div>

            <div style={{ display: "flex", gap: "10px" }}>
              <button 
                onClick={() => navigate("/student/homework")}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "6px",
                  padding: "9px 16px",
                  borderRadius: "10px",
                  fontSize: "13px",
                  fontWeight: 600,
                  background: "rgba(255, 255, 255, 0.8)",
                  border: "1px solid rgba(226, 232, 240, 0.9)",
                  color: "#1E293B",
                  cursor: "pointer",
                  backdropFilter: "blur(12px)"
                }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: "18px", color: "#64748B" }}>upload_file</span>
                Submit Homework
              </button>
              <button 
                className="edu-btn-primary" 
                onClick={() => navigate("/student/doubts")}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "6px",
                  padding: "9px 18px",
                  borderRadius: "10px",
                  fontSize: "13px",
                  fontWeight: 600,
                  boxShadow: "0 4px 12px rgba(16, 185, 129, 0.25)"
                }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>forum</span>
                Ask AI Doubt
              </button>
            </div>
          </div>

          {/* Metric KPI Cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "16px", marginBottom: "28px" }}>
            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Pending Assignments</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#F59E0B" }}>assignment_late</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                {data.homework_count} Tasks Due
              </div>
              <div style={{ fontSize: "12px", color: "#D97706" }}>Next submission in 3 days</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Doubt Inquiries</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#0284C7" }}>help</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                {data.unresolved_doubts} Unresolved
              </div>
              <div style={{ fontSize: "12px", color: "#0284C7" }}>Faculty reviewing response</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Semester Attendance</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#10B981" }}>event_available</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                {data.attendance_rate}%
              </div>
              <div style={{ fontSize: "12px", color: "#059669", display: "flex", alignItems: "center", gap: "4px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "14px" }}>verified</span>
                On track for honors
              </div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Cumulative Standing</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#8B5CF6" }}>workspace_premium</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                {data.cumulative_gpa}
              </div>
              <div style={{ fontSize: "12px", color: "#059669" }}>Rank #4 in Grade 11-A</div>
            </div>
          </div>

          {/* Main 2-Column Grid */}
          <div style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr", gap: "24px", alignItems: "start" }}>
            {/* Left Column: Course Modules & Feed */}
            <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
              {/* Active Courses Progress */}
              <div className="edu-card" style={{ padding: "24px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "18px" }}>
                  <div>
                    <h3 className="edu-font-heading" style={{ margin: 0, fontSize: "17px", fontWeight: 700, color: "#0F172A" }}>
                      Active Course Modules & Syllabus Completion
                    </h3>
                    <p style={{ margin: "2px 0 0 0", fontSize: "12px", color: "#64748B" }}>Semester curriculum progress tracking</p>
                  </div>
                  <button
                    onClick={() => navigate("/student/materials")}
                    style={{ background: "none", border: "none", color: "#059669", fontSize: "12px", fontWeight: 700, cursor: "pointer" }}
                  >
                    View Materials →
                  </button>
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                  {COURSE_PROGRESS.map((course) => (
                    <div
                      key={course.code}
                      style={{
                        padding: "16px",
                        borderRadius: "12px",
                        background: "rgba(255, 255, 255, 0.7)",
                        border: "1px solid rgba(226, 232, 240, 0.8)",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                        <div>
                          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                            <span style={{ fontSize: "11px", fontWeight: 700, color: course.color, background: `${course.color}15`, padding: "2px 6px", borderRadius: "4px" }}>
                              {course.code}
                            </span>
                            <span style={{ fontSize: "13px", fontWeight: 700, color: "#0F172A" }}>{course.name}</span>
                          </div>
                          <div style={{ fontSize: "11px", color: "#64748B", marginTop: "4px" }}>
                            Next Submission: <strong style={{ color: "#334155" }}>{course.nextDue}</strong>
                          </div>
                        </div>
                        <span style={{ fontSize: "14px", fontWeight: 800, color: "#0F172A" }}>
                          {course.progress}%
                        </span>
                      </div>

                      {/* Progress Track */}
                      <div style={{ width: "100%", height: "6px", backgroundColor: "rgba(226, 232, 240, 0.8)", borderRadius: "9999px", overflow: "hidden" }}>
                        <div style={{ width: `${course.progress}%`, height: "100%", backgroundColor: course.color, borderRadius: "9999px", transition: "width 0.6s ease" }} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Recent Activity Feed */}
              <div className="edu-card" style={{ padding: "24px" }}>
                <h3 className="edu-font-heading" style={{ margin: "0 0 16px 0", fontSize: "17px", fontWeight: 700, color: "#0F172A" }}>
                  Recent Academic Activity
                </h3>
                <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                  {data.recent_activity.map((item, idx) => (
                    <div
                      key={idx}
                      style={{
                        padding: "12px 14px",
                        borderRadius: "10px",
                        background: "rgba(248, 250, 252, 0.7)",
                        border: "1px solid rgba(226, 232, 240, 0.7)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between"
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                        <span className="material-symbols-outlined" style={{ fontSize: "18px", color: item.type === "grade" ? "#059669" : item.type === "doubt" ? "#0284C7" : "#10B981" }}>
                          {item.type === "grade" ? "grade" : item.type === "doubt" ? "help" : "description"}
                        </span>
                        <span style={{ fontSize: "13px", color: "#1E293B", fontWeight: 500 }}>{item.text}</span>
                      </div>
                      <span style={{ fontSize: "11px", color: "#94A3B8", whiteSpace: "nowrap" }}>{item.time}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Right Column: AI Tutor Suggestions & Test Schedule */}
            <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
              {/* AI Study Plan Banner */}
              <div
                className="edu-card"
                style={{
                  padding: "22px",
                  background: "linear-gradient(135deg, rgba(16, 185, 129, 0.08), rgba(255, 255, 255, 0.95))",
                  border: "1px solid rgba(16, 185, 129, 0.25)"
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "10px" }}>
                  <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#059669" }}>auto_awesome</span>
                  <span style={{ fontSize: "12px", fontWeight: 700, color: "#059669", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    AI Adaptive Study Plan
                  </span>
                </div>
                <p style={{ fontSize: "13px", color: "#1E293B", margin: "0 0 14px 0", lineHeight: "1.5" }}>
                  Based on recent assessment signals, we recommend spending <strong>30 minutes reviewing Definite Integrals</strong> before the upcoming mid-term exam.
                </p>
                <div style={{ display: "flex", gap: "8px" }}>
                  <button
                    onClick={() => navigate("/student/materials")}
                    style={{
                      flex: 1,
                      padding: "8px 12px",
                      borderRadius: "8px",
                      fontSize: "12px",
                      fontWeight: 600,
                      background: "#10B981",
                      color: "#FFFFFF",
                      border: "none",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: "4px",
                      boxShadow: "0 2px 8px rgba(16, 185, 129, 0.25)"
                    }}
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: "16px" }}>menu_book</span>
                    Open Review Notes
                  </button>
                  <button
                    onClick={() => navigate("/student/self-eval")}
                    style={{
                      padding: "8px 12px",
                      borderRadius: "8px",
                      fontSize: "12px",
                      fontWeight: 600,
                      background: "rgba(255, 255, 255, 0.9)",
                      border: "1px solid rgba(226, 232, 240, 0.9)",
                      color: "#1E293B",
                      cursor: "pointer"
                    }}
                  >
                    Self-Eval
                  </button>
                </div>
              </div>

              {/* Upcoming Examination Schedule */}
              <div className="edu-card" style={{ padding: "22px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
                  <h3 className="edu-font-heading" style={{ margin: 0, fontSize: "16px", fontWeight: 700, color: "#0F172A" }}>
                    Upcoming Examinations
                  </h3>
                  <span style={{ fontSize: "11px", fontWeight: 600, color: "#059669", background: "rgba(16, 185, 129, 0.1)", padding: "3px 8px", borderRadius: "9999px" }}>
                    Term 2
                  </span>
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                  {UPCOMING_TESTS.map((test, idx) => (
                    <div
                      key={idx}
                      style={{
                        padding: "12px 14px",
                        borderRadius: "10px",
                        background: "rgba(248, 250, 252, 0.8)",
                        border: "1px solid rgba(226, 232, 240, 0.7)",
                      }}
                    >
                      <div style={{ fontSize: "13px", fontWeight: 700, color: "#0F172A" }}>{test.title}</div>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "4px" }}>
                        <span style={{ fontSize: "11px", color: "#059669", fontWeight: 600 }}>{test.room}</span>
                        <span style={{ fontSize: "11px", color: "#64748B" }}>{test.date} • {test.time}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </main>
      </div>

      <PortalAssistantWidget />
    </div>
  );
}