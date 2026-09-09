import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "../../api/client";
import { logout } from "../../api/auth";
import { Sidebar, TopBar, KpiCard } from "../../components/ui";
import "../../components/ui/ui.css";

function PreviewCard({ icon, title, children }) {
  return (
    <div
      className="edu-card"
      style={{
        padding: "20px",
        border: "1px dashed #C9C9C3",
        backgroundColor: "#FAFAF8",
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

function AdminDashboard() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    apiClient
      .get("/admin/dashboard")
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
            Loading Administrator Dashboard...
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="admin"
        activeId="dashboard"
        logoText="EduIntel AI"
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
          user={{ name: "Dr. Aria Vance", role: "Super Admin" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: "24px", flexWrap: "wrap", gap: "12px" }}>
            <div>
              <span style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.05em", color: "#5F6774", textTransform: "uppercase" }}>
                ADMINISTRATOR DASHBOARD
              </span>
              <h2 className="edu-font-heading" style={{ fontSize: "24px", fontWeight: 600, color: "#1B2330", margin: "4px 0 0 0" }}>
                Institutional Intelligence Summary
              </h2>
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
              title="Total Students"
              value={data.total_students}
              trend="Enrolled"
              trendDirection="up"
              progressPercent={75}
              progressColor="#26415E"
            />

            <KpiCard
              title="Total Teachers"
              value={data.total_teachers}
              trend="Faculty Active"
              trendDirection="up"
              progressPercent={90}
              progressColor="#26415E"
            />

            <PreviewCard icon="payments" title="Revenue This Month">
              <p style={{ fontSize: "22px", fontWeight: 700, color: "#B7BEC7", margin: "0 0 4px 0" }}>₹--,---</p>
              <p style={{ fontSize: "12px", color: "#92ADCF", margin: 0 }}>
                Fee & payment tracking is not yet built — no revenue data source exists.
              </p>
            </PreviewCard>
          </div>
        </main>
      </div>
    </div>
  );
}

export default AdminDashboard;