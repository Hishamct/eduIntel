import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, KpiCard, DataTable, StatusBadge } from "../../components/ui";
import { academicAnalysisKpis, departmentBreakdownData } from "../../data/adminMockData";
import { logout } from "../../api/auth";

export default function AcademicAnalysis() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const navigate = useNavigate();

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const columns = [
    { key: "department", label: "Department / School", sortable: true },
    { key: "studentCount", label: "Enrolled Students", sortable: true },
    {
      key: "avgGpa",
      label: "Average GPA",
      sortable: true,
      render: (row) => <strong>{row.avgGpa.toFixed(2)}</strong>
    },
    { key: "passRate", label: "Pass Rate", sortable: true },
    {
      key: "status",
      label: "Performance Status",
      sortable: true,
      render: (row) => (
        <StatusBadge
          variant={row.statusVariant}
          label={row.statusLabel}
        />
      )
    }
  ];

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="admin"
        activeId="analysis"
        logoText="EduIntel AI"
        roleText="Administrator Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "analysis") navigate(`/admin/${itemId}`);
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: "Dr. Aria Vance", role: "Super Admin" }}
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
                INSTITUTIONAL METRICS
              </span>
              <h2
                className="edu-font-heading"
                style={{ fontSize: "24px", fontWeight: 600, color: "#1B2330", margin: "4px 0 0 0" }}
              >
                Academic Analysis
              </h2>
              <p style={{ fontSize: "14px", color: "#5F6774", margin: "4px 0 0 0" }}>
                Cross-departmental performance metrics and student status monitoring.
              </p>
            </div>

            <div style={{ display: "flex", gap: "12px" }}>
              <button className="edu-btn-secondary" style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "16px" }}>file_download</span>
                EXPORT PDF
              </button>
              <button className="edu-btn-primary" style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "16px" }}>filter_list</span>
                FILTER DATA
              </button>
            </div>
          </div>

          {/* Top KPI Metrics Row */}
          <div className="edu-kpi-grid" style={{ marginBottom: "24px" }}>
            <KpiCard
              title="Average GPA"
              value={academicAnalysisKpis.averageGpa}
              trend={academicAnalysisKpis.gpaTrend}
              trendDirection="up"
              progressPercent={95}
              progressColor="#26415E"
            />
            <KpiCard
              title="Pass Rate"
              value={academicAnalysisKpis.passRate}
              trend={academicAnalysisKpis.passRateTrend}
              trendDirection="up"
              progressPercent={94}
              progressColor="#3C8C5D"
            />
            <KpiCard
              title="Improvement Rate"
              value={academicAnalysisKpis.improvementRate}
              trend={academicAnalysisKpis.improvementTrend}
              trendDirection="up"
              progressPercent={60}
              progressColor="#C97A2B"
            />
          </div>

          {/* Charts & Visual Summary Section */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 480px), 1fr))",
              gap: "20px",
              marginBottom: "24px"
            }}
          >
            {/* Score Trend Visual Card */}
            <div className="edu-card" style={{ padding: "20px", display: "flex", flexDirection: "column" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
                <h4 className="edu-font-heading" style={{ margin: 0, fontSize: "16px", color: "#1B2330" }}>
                  Average Score Trend
                </h4>
                <span style={{ fontSize: "11px", color: "#5F6774", fontWeight: 700, textTransform: "uppercase" }}>
                  OVERALL MEAN
                </span>
              </div>
              <div style={{ height: "180px", display: "flex", alignItems: "flex-end", gap: "16px", padding: "12px 0" }}>
                <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", height: "100%", justifyContent: "flex-end" }}>
                  <div style={{ width: "100%", backgroundColor: "rgba(38, 65, 94, 0.2)", height: "65%", borderRadius: "2px" }} />
                  <span style={{ fontSize: "11px", color: "#5F6774", marginTop: "6px" }}>Sem 1</span>
                </div>
                <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", height: "100%", justifyContent: "flex-end" }}>
                  <div style={{ width: "100%", backgroundColor: "rgba(38, 65, 94, 0.3)", height: "70%", borderRadius: "2px" }} />
                  <span style={{ fontSize: "11px", color: "#5F6774", marginTop: "6px" }}>Sem 2</span>
                </div>
                <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", height: "100%", justifyContent: "flex-end" }}>
                  <div style={{ width: "100%", backgroundColor: "rgba(38, 65, 94, 0.5)", height: "78%", borderRadius: "2px" }} />
                  <span style={{ fontSize: "11px", color: "#5F6774", marginTop: "6px" }}>Sem 3</span>
                </div>
                <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", height: "100%", justifyContent: "flex-end" }}>
                  <div style={{ width: "100%", backgroundColor: "#26415E", height: "92%", borderRadius: "2px" }} />
                  <span style={{ fontSize: "11px", color: "#26415E", fontWeight: 700, marginTop: "6px" }}>Sem 4</span>
                </div>
              </div>
            </div>

            {/* Department Comparison Card */}
            <div className="edu-card" style={{ padding: "20px", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
              <div>
                <h4 className="edu-font-heading" style={{ margin: "0 0 12px 0", fontSize: "16px", color: "#1B2330" }}>
                  Cohort Distribution Summary
                </h4>
                <p style={{ fontSize: "13px", color: "#5F6774", margin: 0 }}>
                  STEM fields show high engagement with 95.1% pass rates. Humanities and Computer Applications maintain consistent grade point averages above 3.80.
                </p>
              </div>

              <div style={{ marginTop: "20px", paddingTop: "16px", borderTop: "1px solid #E5E5E1", display: "flex", justifyContent: "space-around" }}>
                <div style={{ textAlign: "center" }}>
                  <span style={{ fontSize: "20px", fontWeight: 700, color: "#26415E" }}>1,435</span>
                  <p style={{ fontSize: "11px", color: "#5F6774", margin: "2px 0 0 0", textTransform: "uppercase" }}>Total Evaluated</p>
                </div>
                <div style={{ textAlign: "center" }}>
                  <span style={{ fontSize: "20px", fontWeight: 700, color: "#3C8C5D" }}>5</span>
                  <p style={{ fontSize: "11px", color: "#5F6774", margin: "2px 0 0 0", textTransform: "uppercase" }}>Active Schools</p>
                </div>
              </div>
            </div>
          </div>

          {/* Department Breakdown Table */}
          <DataTable
            title="Departmental Performance Registry"
            columns={columns}
            data={departmentBreakdownData}
            pageSize={5}
          />
        </main>
      </div>
    </div>
  );
}
