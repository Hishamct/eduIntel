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
      render: (row) => <strong style={{ color: "#0F172A", fontSize: "14px" }}>{row.avgGpa.toFixed(2)}</strong>
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
        logoText="eduIntel"
        roleText="Administrator Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "analysis") navigate(`/admin/${itemId}`);
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: "Dr. Sarah Evans", role: "Super Admin" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content">
          {/* Header Bar */}
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
              <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" }}>
                <span style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", color: "#059669", textTransform: "uppercase", backgroundColor: "#DCFCE7", padding: "3px 10px", borderRadius: "9999px" }}>
                  INSTITUTIONAL METRICS
                </span>
                <span style={{ fontSize: "12px", color: "#64748B" }}>• Academic Year 2024</span>
              </div>
              <h2
                className="edu-font-heading"
                style={{ fontSize: "28px", fontWeight: 700, color: "#0F172A", margin: "4px 0 0 0", letterSpacing: "-0.02em" }}
              >
                Academic Analysis & Cohort Trends
              </h2>
              <p style={{ fontSize: "14px", color: "#64748B", margin: "4px 0 0 0" }}>
                Cross-departmental performance metrics, GPA distributions, and cohort pass rates.
              </p>
            </div>

            <div style={{ display: "flex", gap: "12px" }}>
              <button className="edu-btn-secondary" style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>file_download</span>
                Export Report
              </button>
              <button className="edu-btn-accent" style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>filter_list</span>
                Filter Cohorts
              </button>
            </div>
          </div>

          {/* Top KPI Metrics Row */}
          <div className="edu-kpi-grid" style={{ marginBottom: "28px" }}>
            <KpiCard
              title="Average GPA"
              value={academicAnalysisKpis.averageGpa}
              trend={academicAnalysisKpis.gpaTrend}
              trendDirection="up"
              progressPercent={95}
              progressColor="#10B981"
            />
            <KpiCard
              title="Pass Rate"
              value={academicAnalysisKpis.passRate}
              trend={academicAnalysisKpis.passRateTrend}
              trendDirection="up"
              progressPercent={94}
              progressColor="#06B6D4"
            />
            <KpiCard
              title="Improvement Rate"
              value={academicAnalysisKpis.improvementRate}
              trend={academicAnalysisKpis.improvementTrend}
              trendDirection="up"
              progressPercent={60}
              progressColor="#8B5CF6"
            />
          </div>

          {/* Charts & Visual Summary Section */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 480px), 1fr))",
              gap: "24px",
              marginBottom: "28px"
            }}
          >
            {/* Score Trend Visual Card */}
            <div className="edu-card" style={{ padding: "24px", display: "flex", flexDirection: "column" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
                <h4 className="edu-font-heading" style={{ margin: 0, fontSize: "17px", fontWeight: 700, color: "#0F172A" }}>
                  Semester Score Progression Trend
                </h4>
                <span style={{ fontSize: "11px", color: "#15803D", backgroundColor: "#DCFCE7", padding: "2px 8px", borderRadius: "9999px", fontWeight: 700, textTransform: "uppercase" }}>
                  +8.4% OVERALL
                </span>
              </div>
              <div style={{ height: "180px", display: "flex", alignItems: "flex-end", gap: "20px", padding: "12px 12px 0" }}>
                {[
                  { sem: "Sem 1", height: "65%", val: "68%", color: "rgba(16, 185, 129, 0.3)" },
                  { sem: "Sem 2", height: "72%", val: "72%", color: "rgba(16, 185, 129, 0.5)" },
                  { sem: "Sem 3", height: "82%", val: "81%", color: "rgba(16, 185, 129, 0.75)" },
                  { sem: "Sem 4", height: "94%", val: "89%", color: "#10B981" },
                ].map((item, idx) => (
                  <div key={idx} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", height: "100%", justifyContent: "flex-end" }}>
                    <span style={{ fontSize: "11px", fontWeight: 700, color: "#0F172A", marginBottom: "6px" }}>{item.val}</span>
                    <div style={{ width: "100%", backgroundColor: item.color, height: item.height, borderRadius: "8px 8px 0 0", transition: "height 0.4s ease" }} />
                    <span style={{ fontSize: "12px", color: "#64748B", marginTop: "8px", fontWeight: 500 }}>{item.sem}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Department Comparison Card */}
            <div className="edu-card" style={{ padding: "24px", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
              <div>
                <h4 className="edu-font-heading" style={{ margin: "0 0 8px 0", fontSize: "17px", fontWeight: 700, color: "#0F172A" }}>
                  Cohort Distribution Summary
                </h4>
                <p style={{ fontSize: "13.5px", color: "#64748B", margin: 0, lineHeight: 1.5 }}>
                  Computer Science & AI lead student engagement with a <strong>95.1% pass rate</strong>. Behavioral Science and Mathematics maintain consistent GPA averages above 3.80.
                </p>
              </div>

              <div style={{ marginTop: "24px", paddingTop: "18px", borderTop: "1px solid #E2E8F0", display: "flex", justifyContent: "space-around" }}>
                <div style={{ textAlign: "center" }}>
                  <span style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A" }}>1,435</span>
                  <p style={{ fontSize: "11px", color: "#64748B", margin: "2px 0 0 0", textTransform: "uppercase", fontWeight: 600 }}>Total Evaluated</p>
                </div>
                <div style={{ textAlign: "center" }}>
                  <span style={{ fontSize: "24px", fontWeight: 700, color: "#10B981" }}>5</span>
                  <p style={{ fontSize: "11px", color: "#64748B", margin: "2px 0 0 0", textTransform: "uppercase", fontWeight: 600 }}>Active Schools</p>
                </div>
                <div style={{ textAlign: "center" }}>
                  <span style={{ fontSize: "24px", fontWeight: 700, color: "#0284C7" }}>98.2%</span>
                  <p style={{ fontSize: "11px", color: "#64748B", margin: "2px 0 0 0", textTransform: "uppercase", fontWeight: 600 }}>Data Accuracy</p>
                </div>
              </div>
            </div>
          </div>

          {/* Department Breakdown Table */}
          <DataTable
            title="Departmental Academic Performance Registry"
            columns={columns}
            data={departmentBreakdownData}
            pageSize={5}
          />
        </main>
      </div>
    </div>
  );
}

