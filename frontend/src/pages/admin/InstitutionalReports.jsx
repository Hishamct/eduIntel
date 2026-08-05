import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, KpiCard, DataTable, StatusBadge } from "../../components/ui";
import { institutionalReportsStats, institutionalReportsList } from "../../data/adminMockData";
import { logout } from "../../api/auth";

export default function InstitutionalReports() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const navigate = useNavigate();

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const handleDownloadReport = (report) => {
    alert(`Downloading ${report.name} (${report.fileSize})`);
  };

  const columns = [
    {
      key: "name",
      label: "Report Name",
      sortable: true,
      render: (row) => (
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <span className="material-symbols-outlined" style={{ color: "#26415E", fontSize: "20px" }}>
            description
          </span>
          <span style={{ fontWeight: 600, color: "#1B2330" }}>{row.name}</span>
        </div>
      )
    },
    { key: "type", label: "Format", sortable: true },
    { key: "dateGenerated", label: "Date Generated", sortable: true },
    {
      key: "status",
      label: "Status",
      sortable: true,
      render: (row) => (
        <StatusBadge
          variant={row.statusVariant}
          label={row.statusLabel}
        />
      )
    },
    { key: "fileSize", label: "Size", sortable: true },
    {
      key: "actions",
      label: "Actions",
      sortable: false,
      render: (row) => (
        <div style={{ textAlign: "right" }}>
          <button
            onClick={() => handleDownloadReport(row)}
            className="edu-btn-secondary"
            style={{ padding: "4px 10px", fontSize: "11px", display: "inline-flex", alignItems: "center", gap: "4px" }}
          >
            <span className="material-symbols-outlined" style={{ fontSize: "14px" }}>download</span>
            Download
          </button>
        </div>
      )
    }
  ];

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="admin"
        activeId="reports"
        logoText="EduIntel AI"
        roleText="Administrator Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "reports") navigate(`/admin/${itemId}`);
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
                GOVERNANCE & COMPLIANCE
              </span>
              <h2
                className="edu-font-heading"
                style={{ fontSize: "24px", fontWeight: 600, color: "#1B2330", margin: "4px 0 0 0" }}
              >
                Institutional Reports
              </h2>
              <p style={{ fontSize: "14px", color: "#5F6774", margin: "4px 0 0 0" }}>
                Manage, download, and schedule automated performance summaries.
              </p>
            </div>

            <button
              className="edu-btn-accent"
              style={{ display: "flex", alignItems: "center", gap: "6px", padding: "12px 18px" }}
              onClick={() => alert("Report Generator Wizard started.")}
            >
              <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>add</span>
              Generate New Report
            </button>
          </div>

          {/* Bento Summary Statistics */}
          <div className="edu-kpi-grid" style={{ marginBottom: "24px" }}>
            <KpiCard
              title="Total Reports"
              value={institutionalReportsStats.totalReports}
              trend={institutionalReportsStats.totalReportsTrend}
              trendDirection="up"
              progressPercent={85}
              progressColor="#26415E"
            />
            <KpiCard
              title="Scheduled Tasks"
              value={institutionalReportsStats.scheduledTasks}
              trend="Active Automations"
              trendDirection="up"
              progressPercent={40}
              progressColor="#26415E"
            />
            <KpiCard
              title="Storage Used"
              value={institutionalReportsStats.storageUsed}
              trend="40% Capacity"
              trendDirection="up"
              progressPercent={40}
              progressColor="#C97A2B"
            />
            <div className="edu-card" style={{ padding: "20px", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
              <p style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.05em", textTransform: "uppercase", color: "#5F6774", margin: 0 }}>
                Last Audit Status
              </p>
              <div style={{ margin: "12px 0" }}>
                <h3 className="edu-font-heading" style={{ fontSize: "22px", fontWeight: 600, color: "#1B2330", margin: 0 }}>
                  {institutionalReportsStats.lastAudit}
                </h3>
              </div>
              <p style={{ fontSize: "12px", color: "#3C8C5D", margin: 0, fontWeight: 600, display: "flex", alignItems: "center", gap: "4px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "16px" }}>verified</span>
                Fully Verified & Compliant
              </p>
            </div>
          </div>

          {/* Recent Documents Table */}
          <DataTable
            title="Recent Documents Repository"
            columns={columns}
            data={institutionalReportsList}
            pageSize={5}
            actions={
              <button
                className="edu-btn-secondary"
                style={{ padding: "6px 12px", fontSize: "12px", display: "flex", alignItems: "center", gap: "4px" }}
                onClick={() => alert("Refreshed document list.")}
              >
                <span className="material-symbols-outlined" style={{ fontSize: "16px" }}>refresh</span>
                Refresh
              </button>
            }
          />
        </main>
      </div>
    </div>
  );
}
