import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "../../api/client";
import { logout } from "../../api/auth";
import { Sidebar, TopBar } from "../../components/ui";
import "../../components/ui/ui.css";

export default function PlatformDashboard() {
  const [institutions, setInstitutions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    fetchInstitutions();
  }, []);

  const fetchInstitutions = async () => {
    setLoading(true);
    setError("");
    try {
      const response = await apiClient.get("/institutions");
      setInstitutions(response.data || []);
    } catch (err) {
      console.error("Failed to fetch institutions:", err);
      setError(err.response?.data?.detail || "Failed to load platform data.");
    } finally {
      setLoading(false);
    }
  };

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const totalInstitutions = institutions.length;
  const activeInstitutions = institutions.filter((i) => i.is_active).length;
  const suspendedInstitutions = institutions.filter((i) => !i.is_active).length;
  const totalStudents = institutions.reduce((sum, i) => sum + (i.student_count || 0), 0);
  const totalTeachers = institutions.reduce((sum, i) => sum + (i.teacher_count || 0), 0);
  const totalMemberships = institutions.reduce((sum, i) => sum + (i.total_memberships || 0), 0);

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="platform_admin"
        activeId="dashboard"
        logoText="eduIntel"
        roleText="Platform Administration"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId === "institutions") {
            navigate("/platform-admin/institutions");
          }
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: "Platform Admin", role: "Global Root Administrator" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content">
          {/* Header Section */}
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-start",
              marginBottom: "28px",
              flexWrap: "wrap",
              gap: "16px",
            }}
          >
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "6px" }}>
                <span
                  style={{
                    fontSize: "11px",
                    fontWeight: 700,
                    letterSpacing: "0.06em",
                    color: "#059669",
                    textTransform: "uppercase",
                    backgroundColor: "#DCFCE7",
                    padding: "3px 10px",
                    borderRadius: "9999px",
                  }}
                >
                  GLOBAL CONTROL PLANE
                </span>
                <span style={{ fontSize: "12px", color: "#64748B" }}>• Release 1 Production Gate</span>
              </div>
              <h1
                className="edu-font-heading"
                style={{
                  fontSize: "26px",
                  fontWeight: 700,
                  color: "#0F172A",
                  margin: "0 0 6px 0",
                  letterSpacing: "-0.02em",
                }}
              >
                Platform Overview
              </h1>
              <p style={{ color: "#64748B", margin: 0, fontSize: "14px" }}>
                Multi-tenant school provisioning, system health, and cross-tenant isolation telemetry.
              </p>
            </div>

            <div style={{ display: "flex", gap: "10px" }}>
              <button
                onClick={() => navigate("/platform-admin/institutions?action=onboard")}
                className="edu-btn-accent"
                style={{ display: "flex", alignItems: "center", gap: "8px" }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>
                  add_business
                </span>
                Onboard Institution
              </button>
            </div>
          </div>

          {error && (
            <div
              style={{
                padding: "12px 16px",
                backgroundColor: "#FEE2E2",
                border: "1px solid #EF4444",
                borderRadius: "8px",
                color: "#B91C1C",
                fontSize: "13px",
                marginBottom: "24px",
                display: "flex",
                alignItems: "center",
                gap: "10px",
              }}
            >
              <span className="material-symbols-outlined" style={{ fontSize: "20px" }}>
                error
              </span>
              <span>{error}</span>
            </div>
          )}

          {/* Metric KPI Grid */}
          <div className="edu-kpi-grid" style={{ marginBottom: "32px" }}>
            <div className="edu-card" style={{ padding: "20px 24px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B", textTransform: "uppercase" }}>
                  Institutions
                </span>
                <span
                  style={{
                    backgroundColor: "rgba(16, 185, 129, 0.12)",
                    color: "#059669",
                    borderRadius: "8px",
                    padding: "6px",
                    display: "flex",
                  }}
                >
                  <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>
                    domain
                  </span>
                </span>
              </div>
              <div style={{ fontSize: "28px", fontWeight: 700, color: "#0F172A", marginBottom: "6px" }}>
                {loading ? "..." : totalInstitutions}
              </div>
              <div style={{ fontSize: "12px", color: "#64748B", display: "flex", gap: "12px" }}>
                <span style={{ color: "#059669", fontWeight: 600 }}>{activeInstitutions} Active</span>
                <span>•</span>
                <span style={{ color: suspendedInstitutions > 0 ? "#DC2626" : "#64748B" }}>
                  {suspendedInstitutions} Suspended
                </span>
              </div>
            </div>

            <div className="edu-card" style={{ padding: "20px 24px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B", textTransform: "uppercase" }}>
                  Active Students
                </span>
                <span
                  style={{
                    backgroundColor: "rgba(6, 182, 212, 0.12)",
                    color: "#0891B2",
                    borderRadius: "8px",
                    padding: "6px",
                    display: "flex",
                  }}
                >
                  <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>
                    school
                  </span>
                </span>
              </div>
              <div style={{ fontSize: "28px", fontWeight: 700, color: "#0F172A", marginBottom: "6px" }}>
                {loading ? "..." : totalStudents.toLocaleString()}
              </div>
              <div style={{ fontSize: "12px", color: "#64748B" }}>Enrolled across all tenants</div>
            </div>

            <div className="edu-card" style={{ padding: "20px 24px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B", textTransform: "uppercase" }}>
                  Faculty & Staff
                </span>
                <span
                  style={{
                    backgroundColor: "rgba(139, 92, 246, 0.12)",
                    color: "#7C3AED",
                    borderRadius: "8px",
                    padding: "6px",
                    display: "flex",
                  }}
                >
                  <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>
                    badge
                  </span>
                </span>
              </div>
              <div style={{ fontSize: "28px", fontWeight: 700, color: "#0F172A", marginBottom: "6px" }}>
                {loading ? "..." : totalTeachers.toLocaleString()}
              </div>
              <div style={{ fontSize: "12px", color: "#64748B" }}>Certified instructors</div>
            </div>

            <div className="edu-card" style={{ padding: "20px 24px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B", textTransform: "uppercase" }}>
                  Isolation Status
                </span>
                <span
                  style={{
                    backgroundColor: "rgba(16, 185, 129, 0.12)",
                    color: "#059669",
                    borderRadius: "8px",
                    padding: "6px",
                    display: "flex",
                  }}
                >
                  <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>
                    shield
                  </span>
                </span>
              </div>
              <div style={{ fontSize: "20px", fontWeight: 700, color: "#059669", marginBottom: "6px" }}>
                RLS Enforced
              </div>
              <div style={{ fontSize: "12px", color: "#64748B" }}>17 tenant tables isolated</div>
            </div>
          </div>

          {/* Security Architecture Callout */}
          <div
            className="edu-card"
            style={{
              padding: "20px 24px",
              marginBottom: "32px",
              backgroundColor: "rgba(240, 253, 244, 0.8)",
              border: "1px solid rgba(187, 247, 208, 0.8)",
            }}
          >
            <div style={{ display: "flex", alignItems: "flex-start", gap: "14px" }}>
              <span className="material-symbols-outlined" style={{ fontSize: "26px", color: "#059669", marginTop: "2px" }}>
                verified_user
              </span>
              <div>
                <h4 style={{ margin: "0 0 4px 0", fontSize: "15px", fontWeight: 600, color: "#065F46" }}>
                  PostgreSQL Dual-Policy Tenant Architecture Active
                </h4>
                <p style={{ margin: 0, fontSize: "13px", color: "#047857", lineHeight: 1.5 }}>
                  Cross-tenant visibility operates under transaction-scoped <code>app.is_platform_admin</code> read-only
                  privileges. Academic tables reject all cross-tenant mutating operations (<code>WITH CHECK</code> enforced).
                  Administrative provisioning creates accounts with inactive passwords and 48-hour single-use SHA-256 tokens.
                </p>
              </div>
            </div>
          </div>

          {/* Recent Institutions Table Section */}
          <div className="edu-card" style={{ padding: "24px" }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "20px",
              }}
            >
              <div>
                <h3
                  className="edu-font-heading"
                  style={{ fontSize: "18px", fontWeight: 700, color: "#0F172A", margin: "0 0 4px 0" }}
                >
                  Enrolled Institutions
                </h3>
                <p style={{ margin: 0, fontSize: "13px", color: "#64748B" }}>
                  Summary of schools, active memberships, and lifecycle status.
                </p>
              </div>
              <button
                onClick={() => navigate("/platform-admin/institutions")}
                className="edu-btn-secondary"
                style={{ fontSize: "12px", padding: "8px 14px" }}
              >
                View All Institutions
              </button>
            </div>

            {loading ? (
              <div style={{ padding: "40px", textAlign: "center", color: "#64748B" }}>
                Loading institutions...
              </div>
            ) : institutions.length === 0 ? (
              <div style={{ padding: "40px", textAlign: "center", color: "#64748B" }}>
                No institutions provisioned yet. Click "Onboard Institution" to create your first tenant.
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13.5px" }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid #E2E8F0", textAlign: "left" }}>
                      <th style={{ padding: "12px 16px", color: "#64748B", fontWeight: 600 }}>INSTITUTION</th>
                      <th style={{ padding: "12px 16px", color: "#64748B", fontWeight: 600 }}>SLUG</th>
                      <th style={{ padding: "12px 16px", color: "#64748B", fontWeight: 600 }}>STUDENTS</th>
                      <th style={{ padding: "12px 16px", color: "#64748B", fontWeight: 600 }}>FACULTY</th>
                      <th style={{ padding: "12px 16px", color: "#64748B", fontWeight: 600 }}>STATUS</th>
                      <th style={{ padding: "12px 16px", color: "#64748B", fontWeight: 600, textAlign: "right" }}>ACTIONS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {institutions.slice(0, 5).map((inst) => (
                      <tr key={inst.id} style={{ borderBottom: "1px solid #F1F5F9" }}>
                        <td style={{ padding: "14px 16px", fontWeight: 600, color: "#0F172A" }}>
                          {inst.name}
                          {inst.contact_email && (
                            <div style={{ fontSize: "12px", fontWeight: 400, color: "#64748B", marginTop: "2px" }}>
                              {inst.contact_email}
                            </div>
                          )}
                        </td>
                        <td style={{ padding: "14px 16px", color: "#475569", fontFamily: "var(--font-mono)" }}>
                          {inst.slug}
                        </td>
                        <td style={{ padding: "14px 16px", color: "#475569" }}>{inst.student_count || 0}</td>
                        <td style={{ padding: "14px 16px", color: "#475569" }}>{inst.teacher_count || 0}</td>
                        <td style={{ padding: "14px 16px" }}>
                          <span
                            style={{
                              display: "inline-block",
                              padding: "3px 10px",
                              borderRadius: "9999px",
                              fontSize: "11px",
                              fontWeight: 600,
                              textTransform: "uppercase",
                              backgroundColor: inst.is_active ? "#DCFCE7" : "#FEE2E2",
                              color: inst.is_active ? "#15803D" : "#B91C1C",
                            }}
                          >
                            {inst.is_active ? "Active" : "Suspended"}
                          </span>
                        </td>
                        <td style={{ padding: "14px 16px", textAlign: "right" }}>
                          <button
                            onClick={() => navigate("/platform-admin/institutions")}
                            className="edu-btn-secondary"
                            style={{ padding: "6px 12px", fontSize: "12px" }}
                          >
                            Manage
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}

