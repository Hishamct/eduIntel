import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "../../api/client";
import { logout } from "../../api/auth";
import { Sidebar, TopBar, KpiCard, StatusBadge } from "../../components/ui";
import "../../components/ui/ui.css";
import PortalAssistantWidget from "../../components/PortalAssistantWidget";

function timeAgo(timestamp) {
  const diffMs = Date.now() - new Date(timestamp).getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

function PreviewCard({ icon, title, children }) {
  return (
    <div
      className="edu-card"
      style={{
        padding: "20px",
        border: "1px dashed #C9C9C3",
        backgroundColor: "#FAFAF8",
        position: "relative",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "12px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#92ADCF" }}>
            {icon}
          </span>
          <p style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.05em", textTransform: "uppercase", color: "#5F6774", margin: 0 }}>
            {title}
          </p>
        </div>
        <span
          style={{
            fontSize: "9px",
            fontWeight: 700,
            letterSpacing: "0.05em",
            color: "#92ADCF",
            border: "1px solid #92ADCF",
            borderRadius: "3px",
            padding: "2px 6px",
          }}
        >
          PREVIEW
        </span>
      </div>
      {children}
    </div>
  );
}

function StudentDashboard() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    apiClient
      .get("/student/dashboard")
      .then((response) => setData(response.data))
      .catch((err) => {
        const detail = err.response?.data?.detail || "Failed to load dashboard.";
        setError(detail);
      });
  }, []);

  const handleProfileSelect = (itemId) => {
    if (itemId === 'logout') {
      logout(navigate);
    }
  };

  if (error) {
    return (
      <div style={{ minHeight: "100vh", backgroundColor: "#FAFAF7", padding: "60px 24px", textAlign: "center" }}>
        <div className="edu-card" style={{ maxWidth: "440px", margin: "0 auto", padding: "32px" }}>
          <span className="material-symbols-outlined" style={{ fontSize: "48px", color: "#B23A2E", marginBottom: "12px" }}>
            error
          </span>
          <h3 className="edu-font-heading" style={{ color: "#1B2330", margin: "0 0 8px 0" }}>
            Dashboard Error
          </h3>
          <p style={{ color: "#5F6774", fontSize: "14px", marginBottom: "20px" }}>{error}</p>
          <button onClick={() => logout(navigate)} className="edu-btn-secondary">
            Log out
          </button>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div style={{ minHeight: "100vh", backgroundColor: "#FAFAF7", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{ textAlign: "center" }}>
          <span className="material-symbols-outlined" style={{ fontSize: "36px", color: "#26415E", animation: "spin 1s infinite linear" }}>
            sync
          </span>
          <p style={{ color: "#5F6774", marginTop: "12px", fontFamily: "'IBM Plex Sans', sans-serif" }}>
            Loading Student Dashboard...
          </p>
        </div>
      </div>
    );
  }

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
          user={{ name: "Student Portal", role: "Student" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: "24px", flexWrap: "wrap", gap: "12px" }}>
            <div>
              <span style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.05em", color: "#5F6774", textTransform: "uppercase" }}>
                STUDENT DASHBOARD
              </span>
              <h2 className="edu-font-heading" style={{ fontSize: "24px", fontWeight: 600, color: "#1B2330", margin: "4px 0 0 0" }}>
                Overview & Academic Status
              </h2>
            </div>
            <div style={{ display: "flex", gap: "10px" }}>
              <button
                onClick={() => navigate("/student/homework")}
                className="edu-btn-secondary"
                style={{ display: "flex", alignItems: "center", gap: "6px", padding: "8px 16px" }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: "16px" }}>upload_file</span>
                UPLOAD HOMEWORK
              </button>
              <button
                onClick={() => navigate("/student/doubts")}
                className="edu-btn-primary"
                style={{ display: "flex", alignItems: "center", gap: "6px", padding: "8px 16px" }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: "16px" }}>forum</span>
                ASK A DOUBT
              </button>
            </div>
          </div>

          <div
            className="edu-card"
            style={{
              padding: "16px 20px",
              marginBottom: "24px",
              backgroundColor: "#FFFFFF",
              borderLeft: "4px solid #26415E"
            }}
          >
            <p style={{ fontSize: "14px", color: "#1B2330", margin: 0, fontWeight: 500 }}>
              {data.message}
            </p>
          </div>

          <div className="edu-kpi-grid">
            <KpiCard
              title="Pending Homework"
              value={data.homework_count}
              trend={data.homework_count > 0 ? "Action Needed" : "Up to date"}
              trendDirection={data.homework_count > 0 ? "down" : "up"}
              progressPercent={data.homework_count > 0 ? 60 : 100}
              progressColor={data.homework_count > 0 ? "#D9922E" : "#3C8C5D"}
            />

            <KpiCard
              title="Unresolved Doubts"
              value={data.unresolved_doubts}
              trend={data.unresolved_doubts > 0 ? "Pending Tutor" : "All Resolved"}
              trendDirection={data.unresolved_doubts > 0 ? "down" : "up"}
              progressPercent={data.unresolved_doubts > 0 ? 40 : 100}
              progressColor={data.unresolved_doubts > 0 ? "#D9922E" : "#3C8C5D"}
            />

            <div className="edu-card" style={{ padding: "20px", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
              <p style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.05em", textTransform: "uppercase", color: "#5F6774", margin: 0 }}>
                Study Plan Status
              </p>
              <div style={{ margin: "16px 0" }}>
                <StatusBadge
                  variant={data.study_plan_ready ? "on-track" : "needs-attention"}
                  label={data.study_plan_ready ? "READY" : "NOT READY"}
                />
              </div>
              <p style={{ fontSize: "12px", color: "#5F6774", margin: 0 }}>
                {data.study_plan_ready ? "Curriculum path is synchronized." : "Awaiting faculty assignment."}
              </p>
            </div>
          </div>

          {/* Recent Activity + Preview Cards Grid */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))",
              gap: "20px",
              marginTop: "24px",
            }}
          >
            {/* Recent Activity — real data */}
            <div className="edu-card" style={{ padding: "20px" }}>
              <h4 className="edu-font-heading" style={{ fontSize: "16px", fontWeight: 600, color: "#1B2330", margin: "0 0 14px 0" }}>
                Recent Activity
              </h4>
              {data.recent_activity && data.recent_activity.length > 0 ? (
                <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                  {data.recent_activity.map((item, idx) => (
                    <div key={idx} style={{ display: "flex", alignItems: "flex-start", gap: "10px" }}>
                      <span
                        className="material-symbols-outlined"
                        style={{
                          fontSize: "16px",
                          color: item.type === "homework" ? "#26415E" : "#D9922E",
                          marginTop: "2px",
                        }}
                      >
                        {item.type === "homework" ? "description" : "help"}
                      </span>
                      <div>
                        <p style={{ fontSize: "13px", color: "#1B2330", margin: 0 }}>{item.text}</p>
                        <p style={{ fontSize: "11px", color: "#5F6774", margin: "2px 0 0 0" }}>{timeAgo(item.timestamp)}</p>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p style={{ fontSize: "13px", color: "#5F6774" }}>No recent activity yet.</p>
              )}
            </div>

            {/* Mock preview cards */}
            <PreviewCard icon="event_available" title="Attendance">
              <p style={{ fontSize: "22px", fontWeight: 700, color: "#B7BEC7", margin: "0 0 4px 0" }}>--.-%</p>
              <p style={{ fontSize: "12px", color: "#92ADCF", margin: 0 }}>
                Live attendance tracking unlocks once the admin portal is connected.
              </p>
            </PreviewCard>

            <PreviewCard icon="event" title="Upcoming Exams">
              <p style={{ fontSize: "13px", color: "#B7BEC7", margin: "0 0 4px 0" }}>No exam data yet</p>
              <p style={{ fontSize: "12px", color: "#92ADCF", margin: 0 }}>
                Exam scheduling unlocks once the teacher portal is connected.
              </p>
            </PreviewCard>

            <PreviewCard icon="auto_awesome" title="Recommended For You">
              <p style={{ fontSize: "13px", color: "#B7BEC7", margin: "0 0 4px 0" }}>No recommendations yet</p>
              <p style={{ fontSize: "12px", color: "#92ADCF", margin: 0 }}>
                Personalized recommendations unlock once the AI learning agent is live.
              </p>
            </PreviewCard>
          </div>
        </main>
      </div>

      <PortalAssistantWidget />
    </div>
  );
}

export default StudentDashboard;