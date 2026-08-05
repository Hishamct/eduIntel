import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "../../api/client";
import { logout } from "../../api/auth";
import { Sidebar, TopBar, KpiCard, StatusBadge } from "../../components/ui";
import "../../components/ui/ui.css";

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
      {/* Sidebar Navigation */}
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

      {/* Main Content Shell */}
      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: "Student Portal", role: "Student" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content">
          {/* Header Bar */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: "24px", flexWrap: "wrap", gap: "12px" }}>
            <div>
              <span style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.05em", color: "#5F6774", textTransform: "uppercase" }}>
                STUDENT DASHBOARD
              </span>
              <h2 className="edu-font-heading" style={{ fontSize: "24px", fontWeight: 600, color: "#1B2330", margin: "4px 0 0 0" }}>
                Overview & Academic Status
              </h2>
            </div>
          </div>

          {/* Welcome Banner */}
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

          {/* KPI Stat Cards Grid */}
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
        </main>
      </div>
    </div>
  );
}

export default StudentDashboard;