import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "../../api/client";
import { logout } from "../../api/auth";
import { Sidebar, TopBar, StatusBadge } from "../../components/ui";
import "../../components/ui/ui.css";

const DEFAULT_DASHBOARD_DATA = {
  message: "Welcome back, Professor! 14 student homework submissions await evaluation.",
  students_assigned: 68,
  pending_grading: 14,
  avg_attendance: 93.8,
  flagged_count: 3
};

const RECENT_SUBMISSIONS = [
  { id: "sub-1", student: "Aarav Sharma", email: "aarav.sharma@eduintel.ac.in", assignment: "Calculus Problem Set #4", subject: "MATHEMATICS", submitted: "10 mins ago", status: "PENDING" },
  { id: "sub-2", student: "Diya Patel", email: "diya.patel@eduintel.ac.in", assignment: "Electromagnetism Lab Report", subject: "PHYSICS", submitted: "45 mins ago", status: "PENDING" },
  { id: "sub-3", student: "Rohan Varma", email: "rohan.varma@eduintel.ac.in", assignment: "Organic Chemistry Synthesis", subject: "CHEMISTRY", submitted: "2 hrs ago", status: "GRADED", score: "92/100" },
  { id: "sub-4", student: "Ananya Iyer", email: "ananya.iyer@eduintel.ac.in", assignment: "Data Structures Binary Tree", subject: "COMPUTER SCIENCE", submitted: "3 hrs ago", status: "PENDING" },
];

const TODAY_SCHEDULE = [
  { period: "Period 1", time: "08:30 - 09:20", subject: "MATHEMATICS", section: "Grade 12-A", room: "Hall B-102", status: "Completed" },
  { period: "Period 2", time: "09:30 - 10:20", subject: "PHYSICS", section: "Grade 11-A", room: "Lab 3", status: "In Progress" },
  { period: "Period 4", time: "11:30 - 12:20", subject: "MATHEMATICS", section: "Grade 10-A", room: "Hall A-204", status: "Upcoming" },
  { period: "Period 6", time: "13:30 - 14:20", subject: "TUTORIAL", section: "At-Risk Cohort", room: "Seminar 1", status: "Upcoming" },
];

const SUBJECT_COLORS = {
  "MATHEMATICS": { bg: "rgba(16, 185, 129, 0.12)", text: "#065F46", border: "rgba(16, 185, 129, 0.25)" },
  "PHYSICS": { bg: "rgba(14, 165, 233, 0.12)", text: "#0369A1", border: "rgba(14, 165, 233, 0.25)" },
  "CHEMISTRY": { bg: "rgba(245, 158, 11, 0.12)", text: "#92400E", border: "rgba(245, 158, 11, 0.25)" },
  "COMPUTER SCIENCE": { bg: "rgba(99, 102, 241, 0.12)", text: "#4338CA", border: "rgba(99, 102, 241, 0.25)" },
  "TUTORIAL": { bg: "rgba(236, 72, 153, 0.12)", text: "#9D174D", border: "rgba(236, 72, 153, 0.25)" }
};

export default function TeacherDashboard() {
  const [data, setData] = useState(DEFAULT_DASHBOARD_DATA);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    apiClient
      .get("/teacher/dashboard")
      .then((response) => {
        if (response.data) {
          setData({
            ...DEFAULT_DASHBOARD_DATA,
            ...response.data
          });
        }
      })
      .catch((err) => {
        console.warn("Backend teacher dashboard offline, using default preview data.", err);
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
        userRole="teacher"
        activeId="dashboard"
        logoText="EduIntel AI"
        roleText="Faculty Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== 'dashboard') {
            navigate(`/teacher/${itemId}`);
          }
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: "Dr. Sarah Jenkins", role: "Faculty Head" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content">
          {/* Header */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "28px", flexWrap: "wrap", gap: "16px" }}>
            <div>
              <div style={{ display: "inline-flex", alignItems: "center", gap: "6px", padding: "4px 10px", borderRadius: "9999px", background: "rgba(16, 185, 129, 0.1)", border: "1px solid rgba(16, 185, 129, 0.2)", marginBottom: "8px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "14px", color: "#059669" }}>school</span>
                <span style={{ fontSize: "11px", fontWeight: 700, color: "#059669", letterSpacing: "0.06em", textTransform: "uppercase" }}>
                  Faculty Intelligence
                </span>
              </div>
              <h1 className="edu-font-heading" style={{ fontSize: "28px", fontWeight: 700, color: "#0F172A", margin: "0 0 6px 0", letterSpacing: "-0.02em" }}>
                Classroom Overview & Student Metrics
              </h1>
              <p style={{ fontSize: "14px", color: "#64748B", margin: 0, maxWidth: "600px" }}>
                Monitor assignment submissions, instructional timetables, and ML at-risk diagnostic predictions.
              </p>
            </div>

            <div style={{ display: "flex", gap: "10px" }}>
              <button 
                onClick={() => navigate("/teacher/materials")}
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
                Upload Material
              </button>
              <button 
                className="edu-btn-primary" 
                onClick={() => navigate("/teacher/grading")}
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
                <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>grading</span>
                Grade Submissions ({data.pending_grading})
              </button>
            </div>
          </div>

          {/* KPI Cards Grid */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "16px", marginBottom: "28px" }}>
            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Students Assigned</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#10B981" }}>groups</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                {data.students_assigned} Students
              </div>
              <div style={{ fontSize: "12px", color: "#059669", display: "flex", alignItems: "center", gap: "4px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "14px" }}>check_circle</span>
                Across 3 grade sections
              </div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Pending Grading</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#F59E0B" }}>pending_actions</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                {data.pending_grading} Items
              </div>
              <div style={{ fontSize: "12px", color: "#D97706" }}>
                4 require OCR text review
              </div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Average Attendance</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#0284C7" }}>event_available</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                {data.avg_attendance}%
              </div>
              <div style={{ fontSize: "12px", color: "#0284C7" }}>
                +1.4% above term average
              </div>
            </div>

            <div className="edu-card" style={{ padding: "20px", borderLeft: "4px solid #EF4444" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>At-Risk Flagged</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#EF4444" }}>flag</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                {data.flagged_count} Flagged
              </div>
              <div style={{ fontSize: "12px", color: "#DC2626", cursor: "pointer", fontWeight: 600 }} onClick={() => navigate("/teacher/flagged")}>
                View ML diagnostic report →
              </div>
            </div>
          </div>

          {/* Main Grid: Submissions & Timetable */}
          <div style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr", gap: "24px", alignItems: "start" }}>
            {/* Left: Pending Submissions Queue */}
            <div className="edu-card" style={{ padding: "24px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "18px" }}>
                <div>
                  <h3 className="edu-font-heading" style={{ margin: 0, fontSize: "17px", fontWeight: 700, color: "#0F172A" }}>
                    Recent Homework Submissions
                  </h3>
                  <p style={{ margin: "2px 0 0 0", fontSize: "12px", color: "#64748B" }}>Latest student submissions awaiting grading</p>
                </div>
                <button
                  onClick={() => navigate("/teacher/grading")}
                  style={{
                    background: "none",
                    border: "none",
                    color: "#059669",
                    fontSize: "12px",
                    fontWeight: 700,
                    cursor: "pointer"
                  }}
                >
                  View All ({data.pending_grading}) →
                </button>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                {RECENT_SUBMISSIONS.map((sub) => {
                  const style = SUBJECT_COLORS[sub.subject] || { bg: "#F1F5F9", text: "#475569", border: "#E2E8F0" };
                  const isGraded = sub.status === "GRADED";

                  return (
                    <div
                      key={sub.id}
                      style={{
                        padding: "14px 16px",
                        borderRadius: "12px",
                        background: "rgba(255, 255, 255, 0.7)",
                        border: "1px solid rgba(226, 232, 240, 0.9)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: "12px",
                        transition: "all 0.15s ease",
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                        <div style={{
                          width: "36px",
                          height: "36px",
                          borderRadius: "50%",
                          background: "linear-gradient(135deg, rgba(16, 185, 129, 0.15), rgba(14, 165, 233, 0.15))",
                          color: "#059669",
                          fontWeight: 700,
                          fontSize: "13px",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center"
                        }}>
                          {sub.student.charAt(0)}
                        </div>
                        <div>
                          <div style={{ fontSize: "13px", fontWeight: 700, color: "#0F172A" }}>{sub.student}</div>
                          <div style={{ fontSize: "12px", color: "#64748B" }}>{sub.assignment}</div>
                        </div>
                      </div>

                      <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                        <span style={{
                          padding: "3px 8px",
                          borderRadius: "6px",
                          fontSize: "10px",
                          fontWeight: 700,
                          background: style.bg,
                          color: style.text,
                          border: `1px solid ${style.border}`
                        }}>
                          {sub.subject}
                        </span>

                        <span style={{ fontSize: "11px", color: "#94A3B8" }}>{sub.submitted}</span>

                        <button
                          onClick={() => navigate("/teacher/grading")}
                          style={{
                            padding: "6px 12px",
                            borderRadius: "8px",
                            fontSize: "12px",
                            fontWeight: 600,
                            background: isGraded ? "rgba(241, 245, 249, 0.8)" : "#10B981",
                            color: isGraded ? "#475569" : "#FFFFFF",
                            border: "none",
                            cursor: "pointer",
                            boxShadow: isGraded ? "none" : "0 2px 8px rgba(16, 185, 129, 0.25)"
                          }}
                        >
                          {isGraded ? sub.score : "Grade Now"}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Right Column: Schedule & AI Diagnostic Card */}
            <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
              {/* Today's Timetable */}
              <div className="edu-card" style={{ padding: "22px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
                  <h3 className="edu-font-heading" style={{ margin: 0, fontSize: "16px", fontWeight: 700, color: "#0F172A" }}>
                    Today's Schedule
                  </h3>
                  <span style={{ fontSize: "11px", fontWeight: 600, color: "#059669", background: "rgba(16, 185, 129, 0.1)", padding: "3px 8px", borderRadius: "9999px" }}>
                    4 Periods
                  </span>
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                  {TODAY_SCHEDULE.map((item, idx) => {
                    const isNow = item.status === "In Progress";
                    return (
                      <div
                        key={idx}
                        style={{
                          padding: "10px 14px",
                          borderRadius: "10px",
                          background: isNow ? "rgba(16, 185, 129, 0.08)" : "rgba(248, 250, 252, 0.8)",
                          border: isNow ? "1px solid rgba(16, 185, 129, 0.3)" : "1px solid rgba(226, 232, 240, 0.7)",
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center"
                        }}
                      >
                        <div>
                          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                            <span style={{ fontSize: "12px", fontWeight: 700, color: "#0F172A" }}>{item.period}</span>
                            <span style={{ fontSize: "11px", color: "#64748B" }}>({item.time})</span>
                          </div>
                          <div style={{ fontSize: "11px", color: "#059669", fontWeight: 600, marginTop: "2px" }}>
                            {item.section} • {item.room}
                          </div>
                        </div>

                        <span style={{
                          fontSize: "11px",
                          fontWeight: 700,
                          color: isNow ? "#059669" : item.status === "Completed" ? "#94A3B8" : "#3B82F6"
                        }}>
                          {item.status}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* At-Risk AI Assistant Alert */}
              <div
                className="edu-card"
                style={{
                  padding: "20px",
                  background: "linear-gradient(135deg, rgba(254, 242, 242, 0.8), rgba(255, 255, 255, 0.9))",
                  border: "1px solid rgba(254, 202, 202, 0.8)"
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
                  <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#EF4444" }}>warning</span>
                  <span style={{ fontSize: "12px", fontWeight: 700, color: "#DC2626", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    ML At-Risk Detection
                  </span>
                </div>
                <p style={{ fontSize: "13px", color: "#1E293B", margin: "0 0 12px 0", lineHeight: "1.5" }}>
                  3 students in Grade 11-A show high struggle probability in <strong>Thermodynamics & Polynomials</strong>.
                </p>
                <button
                  onClick={() => navigate("/teacher/flagged")}
                  style={{
                    width: "100%",
                    padding: "9px",
                    borderRadius: "8px",
                    fontSize: "12px",
                    fontWeight: 700,
                    background: "#EF4444",
                    color: "#FFFFFF",
                    border: "none",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: "6px",
                    boxShadow: "0 2px 10px rgba(239, 68, 68, 0.25)"
                  }}
                >
                  <span className="material-symbols-outlined" style={{ fontSize: "16px" }}>insights</span>
                  Review Diagnostic Explanations
                </button>
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}