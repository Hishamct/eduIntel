import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "../../api/client";
import { logout } from "../../api/auth";
import { Sidebar, TopBar } from "../../components/ui";
import "../../components/ui/ui.css";

const DEFAULT_ADMIN_DATA = {
  name: "Dr. Sarah Evans",
  role: "Super Admin",
  total_students: 12842,
  total_teachers: 418,
  message: "Institutional AI guardrails and student performance models running in optimal condition."
};

export default function AdminDashboard() {
  const [data, setData] = useState(DEFAULT_ADMIN_DATA);
  const [error, setError] = useState("");
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [selectedPeriod, setSelectedPeriod] = useState("This Semester");
  const navigate = useNavigate();

  useEffect(() => {
    apiClient
      .get("/admin/dashboard")
      .then((response) => {
        if (response.data) setData(response.data);
      })
      .catch((err) => {
        // Keep default demo data active so design is fully previewable
        console.warn("Backend not available, running in UI preview mode.");
      });
  }, []);

  const handleProfileSelect = (itemId) => {
    if (itemId === 'logout') {
      logout(navigate);
    }
  };

  if (error) {
    return (
      <div style={{ minHeight: "100vh", backgroundColor: "#F8FAFC", padding: "60px 24px", textAlign: "center", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div className="edu-card" style={{ maxWidth: "440px", width: "100%", padding: "36px", textAlign: "center" }}>
          <div style={{ width: "54px", height: "54px", borderRadius: "50%", backgroundColor: "#FEE2E2", color: "#EF4444", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 16px" }}>
            <span className="material-symbols-outlined" style={{ fontSize: "28px" }}>
              error
            </span>
          </div>
          <h3 className="edu-font-heading" style={{ color: "#0F172A", margin: "0 0 8px 0", fontSize: "20px" }}>
            Dashboard Error
          </h3>
          <p style={{ color: "#64748B", fontSize: "14px", marginBottom: "24px" }}>{error}</p>
          <button onClick={() => logout(navigate)} className="edu-btn-secondary" style={{ width: "100%" }}>
            Sign Out
          </button>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div style={{ minHeight: "100vh", backgroundColor: "#F8FAFC", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ width: "48px", height: "48px", borderRadius: "50%", background: "linear-gradient(135deg, #10B981, #059669)", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 16px", boxShadow: "0 4px 12px rgba(16, 185, 129, 0.3)" }}>
            <span className="material-symbols-outlined" style={{ fontSize: "26px", color: "#FFFFFF", animation: "spin 1s infinite linear" }}>
              sync
            </span>
          </div>
          <p style={{ color: "#64748B", fontSize: "14px", fontWeight: 500, fontFamily: "var(--font-body)" }}>
            Loading Institutional Intelligence Summary...
          </p>
        </div>
      </div>
    );
  }

  const userName = data.name || "Sarah";

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="admin"
        activeId="dashboard"
        logoText="eduIntel"
        roleText="Administrator Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== 'dashboard') {
            navigate(`/admin/${itemId}`);
          }
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: userName, role: data.role || "Super Admin" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content">
          {/* Header Section */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "28px", flexWrap: "wrap", gap: "16px" }}>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" }}>
                <span style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", color: "#059669", textTransform: "uppercase", backgroundColor: "#DCFCE7", padding: "3px 10px", borderRadius: "9999px" }}>
                  ADMINISTRATOR INTELLIGENCE
                </span>
                <span style={{ fontSize: "12px", color: "#64748B" }}>• Live Overview</span>
              </div>
              <h2 className="edu-font-heading" style={{ fontSize: "28px", fontWeight: 700, color: "#0F172A", margin: 0, letterSpacing: "-0.02em" }}>
                Welcome {userName}! 👋
              </h2>
              <p style={{ fontSize: "14px", color: "#64748B", margin: "4px 0 0 0" }}>
                Here is your educational performance & AI anti-cheating summary for this semester.
              </p>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
              <select
                value={selectedPeriod}
                onChange={(e) => setSelectedPeriod(e.target.value)}
                style={{
                  padding: "9px 16px",
                  borderRadius: "10px",
                  backgroundColor: "rgba(255, 255, 255, 0.85)",
                  border: "1px solid rgba(226, 232, 240, 0.9)",
                  fontSize: "13px",
                  fontWeight: 600,
                  color: "#1E293B",
                  cursor: "pointer",
                  outline: "none"
                }}
              >
                <option>This Semester</option>
                <option>Last 30 Days</option>
                <option>Academic Year 2024</option>
              </select>

              <button
                className="edu-btn-accent"
                onClick={() => navigate('/admin/analysis')}
                style={{ display: "flex", alignItems: "center", gap: "6px" }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>
                  analytics
                </span>
                Generate Report
              </button>
            </div>
          </div>

          {/* Top Gauge & Metrics Grid (Reference Layout Cards) */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "20px", marginBottom: "28px" }}>
            
            {/* Card 1: Score Gauge (17%) */}
            <div className="edu-card edu-card-hover" style={{ padding: "22px", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <p style={{ fontSize: "12px", fontWeight: 700, letterSpacing: "0.05em", color: "#64748B", textTransform: "uppercase", margin: 0 }}>
                  Student Performance
                </p>
                <span style={{ fontSize: "11px", fontWeight: 600, color: "#EF4444", backgroundColor: "#FEE2E2", padding: "2px 8px", borderRadius: "9999px" }}>
                  Below Target
                </span>
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: "20px", marginTop: "16px" }}>
                <div style={{ position: "relative", width: "70px", height: "70px", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <svg width="70" height="70" viewBox="0 0 36 36">
                    <path
                      d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                      fill="none"
                      stroke="#E2E8F0"
                      strokeWidth="3.5"
                    />
                    <path
                      d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                      fill="none"
                      stroke="#8B5CF6"
                      strokeWidth="3.5"
                      strokeDasharray="17, 100"
                      strokeLinecap="round"
                    />
                  </svg>
                  <span style={{ position: "absolute", fontSize: "16px", fontWeight: 700, color: "#0F172A" }}>
                    17%
                  </span>
                </div>
                <div>
                  <h4 style={{ fontSize: "22px", fontWeight: 700, color: "#0F172A", margin: 0 }}>Score 17/100</h4>
                  <p style={{ fontSize: "12px", color: "#64748B", margin: "2px 0 0 0" }}>Average Score Across Tests</p>
                </div>
              </div>
            </div>

            {/* Card 2: Percentile Rank (91st Percentile) */}
            <div className="edu-card edu-card-hover" style={{ padding: "22px", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <p style={{ fontSize: "12px", fontWeight: 700, letterSpacing: "0.05em", color: "#64748B", textTransform: "uppercase", margin: 0 }}>
                  National Percentile
                </p>
                <span style={{ fontSize: "11px", fontWeight: 600, color: "#15803D", backgroundColor: "#DCFCE7", padding: "2px 8px", borderRadius: "9999px" }}>
                  Top 10%
                </span>
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: "20px", marginTop: "16px" }}>
                <div style={{ position: "relative", width: "70px", height: "70px", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <svg width="70" height="70" viewBox="0 0 36 36">
                    <path
                      d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                      fill="none"
                      stroke="#E2E8F0"
                      strokeWidth="3.5"
                    />
                    <path
                      d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                      fill="none"
                      stroke="#10B981"
                      strokeWidth="3.5"
                      strokeDasharray="91, 100"
                      strokeLinecap="round"
                    />
                  </svg>
                  <span style={{ position: "absolute", fontSize: "15px", fontWeight: 700, color: "#10B981" }}>
                    91st
                  </span>
                </div>
                <div>
                  <h4 style={{ fontSize: "22px", fontWeight: 700, color: "#0F172A", margin: 0 }}>91st Percentile</h4>
                  <p style={{ fontSize: "12px", color: "#64748B", margin: "2px 0 0 0" }}>Higher than 91% of users</p>
                </div>
              </div>
            </div>

            {/* Card 3: Total Enrolled Students */}
            <div className="edu-card edu-card-hover" style={{ padding: "22px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <p style={{ fontSize: "12px", fontWeight: 700, letterSpacing: "0.05em", color: "#64748B", textTransform: "uppercase", margin: 0 }}>
                  Active Students
                </p>
                <div style={{ width: "36px", height: "36px", borderRadius: "10px", backgroundColor: "#E0F2FE", color: "#0284C7", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <span className="material-symbols-outlined" style={{ fontSize: "20px" }}>
                    group
                  </span>
                </div>
              </div>
              <h3 style={{ fontSize: "32px", fontWeight: 700, color: "#0F172A", margin: "0 0 8px 0" }}>
                {data.total_students || "12,842"}
              </h3>
              <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#166534", backgroundColor: "#DCFCE7", padding: "2px 8px", borderRadius: "6px" }}>
                  +5.2%
                </span>
                <span style={{ fontSize: "12px", color: "#64748B" }}>enrolled this month</span>
              </div>
            </div>

            {/* Card 4: Active Faculty & Teachers */}
            <div className="edu-card edu-card-hover" style={{ padding: "22px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <p style={{ fontSize: "12px", fontWeight: 700, letterSpacing: "0.05em", color: "#64748B", textTransform: "uppercase", margin: 0 }}>
                  Faculty Members
                </p>
                <div style={{ width: "36px", height: "36px", borderRadius: "10px", backgroundColor: "#F3E8FF", color: "#7E22CE", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <span className="material-symbols-outlined" style={{ fontSize: "20px" }}>
                    badge
                  </span>
                </div>
              </div>
              <h3 style={{ fontSize: "32px", fontWeight: 700, color: "#0F172A", margin: "0 0 8px 0" }}>
                {data.total_teachers || "418"}
              </h3>
              <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#15803D", backgroundColor: "#DCFCE7", padding: "2px 8px", borderRadius: "6px" }}>
                  98% Active
                </span>
                <span style={{ fontSize: "12px", color: "#64748B" }}>faculty response rate</span>
              </div>
            </div>

          </div>

          {/* Main Dashboard Two-Column Section */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: "24px" }}>
            
            {/* Left Column: Progress Table & Schedule Timetable */}
            <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
              
              {/* Module Progress Table (Reference Component) */}
              <div className="edu-card" style={{ padding: "24px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
                  <div>
                    <h3 className="edu-font-heading" style={{ fontSize: "18px", fontWeight: 700, color: "#0F172A", margin: 0 }}>
                      Institutional Module Overview
                    </h3>
                    <p style={{ fontSize: "13px", color: "#64748B", margin: "2px 0 0 0" }}>
                      Curriculum completion & student progress distribution
                    </p>
                  </div>
                  <button onClick={() => navigate('/admin/students')} className="edu-btn-secondary" style={{ fontSize: "12px", padding: "6px 12px" }}>
                    View All Students
                  </button>
                </div>

                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left" }}>
                    <thead>
                      <tr style={{ borderBottom: "1px solid #E2E8F0" }}>
                        <th style={{ padding: "12px 8px", fontSize: "11px", fontWeight: 700, color: "#64748B", textTransform: "uppercase", letterSpacing: "0.05em" }}>Module Name</th>
                        <th style={{ padding: "12px 8px", fontSize: "11px", fontWeight: 700, color: "#64748B", textTransform: "uppercase", letterSpacing: "0.05em" }}>Completion (%)</th>
                        <th style={{ padding: "12px 8px", fontSize: "11px", fontWeight: 700, color: "#64748B", textTransform: "uppercase", letterSpacing: "0.05em" }}>Grade Target</th>
                        <th style={{ padding: "12px 8px", fontSize: "11px", fontWeight: 700, color: "#64748B", textTransform: "uppercase", letterSpacing: "0.05em" }}>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[
                        { name: "Computer Science & AI", percent: 98, target: "70%", status: "ON TRACK", color: "#10B981", badgeBg: "#DCFCE7", badgeText: "#15803D" },
                        { name: "Data Science & RAG", percent: 95, target: "20%", status: "NEEDS ATTENTION", color: "#F59E0B", badgeBg: "#FEF3C7", badgeText: "#B45309" },
                        { name: "Behavioral & Ethics AI", percent: 90, target: "68%", status: "ON TRACK", color: "#10B981", badgeBg: "#DCFCE7", badgeText: "#15803D" },
                        { name: "Applied Machine Learning", percent: 92, target: "72%", status: "ON TRACK", color: "#10B981", badgeBg: "#DCFCE7", badgeText: "#15803D" },
                        { name: "Autonomous Agent Traces", percent: 95, target: "32%", status: "FLAGGED AT RISK", color: "#EF4444", badgeBg: "#FEE2E2", badgeText: "#B91C1C" },
                      ].map((item, idx) => (
                        <tr key={idx} style={{ borderBottom: idx === 4 ? "none" : "1px solid #F1F5F9" }}>
                          <td style={{ padding: "14px 8px", fontSize: "13.5px", fontWeight: 600, color: "#0F172A" }}>
                            {item.name}
                          </td>
                          <td style={{ padding: "14px 8px", width: "220px" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                              <span style={{ fontSize: "12.5px", fontWeight: 600, color: "#64748B", minWidth: "35px" }}>{item.percent}%</span>
                              <div className="edu-progress-bar-track">
                                <div className="edu-progress-bar-fill" style={{ width: `${item.percent}%`, backgroundColor: item.color }} />
                              </div>
                            </div>
                          </td>
                          <td style={{ padding: "14px 8px", fontSize: "13px", fontWeight: 600, color: "#64748B" }}>
                            {item.target}
                          </td>
                          <td style={{ padding: "14px 8px" }}>
                            <span style={{ fontSize: "10.5px", fontWeight: 700, padding: "4px 10px", borderRadius: "9999px", backgroundColor: item.badgeBg, color: item.badgeText, letterSpacing: "0.04em" }}>
                              {item.status}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Study Schedule & Timetable Calendar Plan (Reference Component) */}
              <div className="edu-card" style={{ padding: "24px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
                  <div>
                    <h3 className="edu-font-heading" style={{ fontSize: "18px", fontWeight: 700, color: "#0F172A", margin: 0 }}>
                      Study Schedule & Timetable Plan
                    </h3>
                    <p style={{ fontSize: "13px", color: "#64748B", margin: "2px 0 0 0" }}>
                      Upcoming lectures, exams, and scheduled AI tutorials
                    </p>
                  </div>
                  <button onClick={() => navigate('/admin/timetable')} className="edu-btn-accent" style={{ fontSize: "12px", padding: "6px 14px" }}>
                    + Add Schedule
                  </button>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: "12px" }}>
                  {[
                    { day: "MON", date: "23", title: "C Programming", time: "2 hr 35 min", status: "In Progress", bg: "#FEF3C7", text: "#92400E" },
                    { day: "TUE", date: "24", title: "Data Structures", time: "1 hr 45 min", status: "Incomplete", bg: "#FEE2E2", text: "#991B1B" },
                    { day: "WED", date: "25", title: "AI Guardrails", time: "2 hr 10 min", status: "Completed", bg: "#DCFCE7", text: "#166534" },
                    { day: "THU", date: "26", title: "Machine Learning", time: "3 hr 00 min", status: "Completed", bg: "#DCFCE7", text: "#166534" },
                    { day: "FRI", date: "27", title: "Thesis Review", time: "1 hr 30 min", status: "Upcoming", bg: "#E0F2FE", text: "#0369A1" },
                  ].map((col, idx) => (
                    <div key={idx} style={{ padding: "14px", borderRadius: "12px", backgroundColor: "rgba(248, 250, 252, 0.8)", border: "1px solid #E2E8F0", textAlign: "center" }}>
                      <p style={{ fontSize: "11px", fontWeight: 700, color: "#64748B", margin: 0 }}>{col.day}</p>
                      <p style={{ fontSize: "20px", fontWeight: 700, color: "#0F172A", margin: "2px 0 10px 0" }}>{col.date}</p>
                      <div style={{ padding: "10px", borderRadius: "10px", backgroundColor: col.bg, color: col.text, textAlign: "left" }}>
                        <p style={{ fontSize: "12px", fontWeight: 700, margin: 0 }}>{col.title}</p>
                        <p style={{ fontSize: "10px", margin: "2px 0 6px 0", opacity: 0.8 }}>{col.time}</p>
                        <span style={{ fontSize: "9.5px", fontWeight: 700, textTransform: "uppercase" }}>{col.status}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

            </div>

            {/* Right Column: AI Risk Feed & Readiness Indicator */}
            <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
              
              {/* Exam Date Reminder & Readiness Indicator */}
              <div className="edu-card" style={{ padding: "22px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
                  <h4 className="edu-font-heading" style={{ fontSize: "16px", fontWeight: 700, color: "#0F172A", margin: 0 }}>
                    Exam Date Reminder
                  </h4>
                  <span style={{ fontSize: "11px", fontWeight: 700, color: "#EF4444", backgroundColor: "#FEE2E2", padding: "2px 8px", borderRadius: "6px" }}>
                    Left 30d
                  </span>
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                  <div style={{ padding: "12px", borderRadius: "12px", backgroundColor: "rgba(239, 68, 68, 0.05)", border: "1px solid rgba(239, 68, 68, 0.15)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <div>
                      <span style={{ fontSize: "11px", fontWeight: 700, color: "#EF4444" }}>&lt; 50%</span>
                      <p style={{ fontSize: "13px", fontWeight: 700, color: "#0F172A", margin: "2px 0 0 0" }}>Not Ready</p>
                      <p style={{ fontSize: "11px", color: "#64748B", margin: 0 }}>Major gaps in pacing</p>
                    </div>
                    <span className="material-symbols-outlined" style={{ color: "#EF4444", fontSize: "22px" }}>warning</span>
                  </div>

                  <div style={{ padding: "12px", borderRadius: "12px", backgroundColor: "rgba(245, 158, 11, 0.05)", border: "1px solid rgba(245, 158, 11, 0.15)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <div>
                      <span style={{ fontSize: "11px", fontWeight: 700, color: "#D97706" }}>50 - 69%</span>
                      <p style={{ fontSize: "13px", fontWeight: 700, color: "#0F172A", margin: "2px 0 0 0" }}>Needs Improvement</p>
                      <p style={{ fontSize: "11px", color: "#64748B", margin: 0 }}>Study plan needs rebalancing</p>
                    </div>
                    <span className="material-symbols-outlined" style={{ color: "#D97706", fontSize: "22px" }}>auto_awesome</span>
                  </div>

                  <div style={{ padding: "12px", borderRadius: "12px", backgroundColor: "rgba(16, 185, 129, 0.05)", border: "1px solid rgba(16, 185, 129, 0.15)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <div>
                      <span style={{ fontSize: "11px", fontWeight: 700, color: "#059669" }}>70 - 84%</span>
                      <p style={{ fontSize: "13px", fontWeight: 700, color: "#0F172A", margin: "2px 0 0 0" }}>Approaching Readiness</p>
                      <p style={{ fontSize: "11px", color: "#64748B", margin: 0 }}>Continue building mastery</p>
                    </div>
                    <span className="material-symbols-outlined" style={{ color: "#059669", fontSize: "22px" }}>verified</span>
                  </div>
                </div>
              </div>

              {/* Anti-Cheating Telemetry Alerts */}
              <div className="edu-card" style={{ padding: "22px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
                  <h4 className="edu-font-heading" style={{ fontSize: "16px", fontWeight: 700, color: "#0F172A", margin: 0 }}>
                    Anti-Cheating Telemetry
                  </h4>
                  <button onClick={() => navigate('/admin/alerts')} style={{ background: "none", border: "none", color: "#059669", fontSize: "12px", fontWeight: 600, cursor: "pointer" }}>
                    View All
                  </button>
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                  {[
                    { user: "Maya Lin", issue: "Tab Switching Detected", time: "10 mins ago", level: "HIGH", color: "#EF4444", bg: "#FEE2E2" },
                    { user: "Alex Carter", issue: "AI Output Match 94%", time: "34 mins ago", level: "CRITICAL", color: "#EF4444", bg: "#FEE2E2" },
                    { user: "Liam Davies", issue: "Grade Sudden Drop", time: "1 hour ago", level: "MEDIUM", color: "#D97706", bg: "#FEF3C7" },
                  ].map((alert, idx) => (
                    <div key={idx} style={{ padding: "12px", borderRadius: "10px", backgroundColor: "#F8FAFC", border: "1px solid #E2E8F0" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                        <span style={{ fontSize: "13px", fontWeight: 700, color: "#0F172A" }}>{alert.user}</span>
                        <span style={{ fontSize: "9.5px", fontWeight: 700, color: alert.color, backgroundColor: alert.bg, padding: "2px 6px", borderRadius: "4px" }}>
                          {alert.level}
                        </span>
                      </div>
                      <p style={{ fontSize: "12px", color: "#64748B", margin: 0 }}>{alert.issue}</p>
                      <span style={{ fontSize: "10.5px", color: "#94A3B8", marginTop: "4px", display: "block" }}>{alert.time}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Active AI Agent Status */}
              <div className="edu-card" style={{ padding: "22px", background: "linear-gradient(135deg, rgba(16, 185, 129, 0.08) 0%, rgba(6, 182, 212, 0.05) 100%)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "12px" }}>
                  <div style={{ width: "32px", height: "32px", borderRadius: "50%", backgroundColor: "#10B981", color: "#FFFFFF", display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>smart_toy</span>
                  </div>
                  <div>
                    <p style={{ fontSize: "13px", fontWeight: 700, color: "#0F172A", margin: 0 }}>AI System Integrity</p>
                    <p style={{ fontSize: "11px", color: "#059669", margin: 0, fontWeight: 600 }}>99.4% Active Protection</p>
                  </div>
                </div>
                <p style={{ fontSize: "12px", color: "#64748B", margin: "0 0 12px 0", lineHeight: 1.4 }}>
                  All guardrails, LLM telemetry traces, and plagiarism sensors running normally.
                </p>
                <button onClick={() => navigate('/admin/llm-usage')} className="edu-btn-secondary" style={{ width: "100%", fontSize: "12px", padding: "8px" }}>
                  Inspect Agent Traces
                </button>
              </div>

            </div>

          </div>
        </main>
      </div>
    </div>
  );
}