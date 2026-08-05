import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, KpiCard, DataTable, StatusBadge, Modal } from "../../components/ui";
import { riskAlertsKpis, riskAlertsQueueData } from "../../data/adminMockData";
import { logout } from "../../api/auth";

export default function RiskAlerts() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [selectedStudent, setSelectedStudent] = useState(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const navigate = useNavigate();

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const handleViewProfile = (student) => {
    setSelectedStudent(student);
    setIsModalOpen(true);
  };

  const columns = [
    {
      key: "name",
      label: "Student Name",
      sortable: true,
      render: (row) => (
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <div
            style={{
              width: "32px",
              height: "32px",
              borderRadius: "50%",
              backgroundColor: row.statusVariant === "flagged-at-risk" ? "rgba(178, 58, 46, 0.1)" : "rgba(217, 146, 46, 0.1)",
              color: row.statusVariant === "flagged-at-risk" ? "#B23A2E" : "#D9922E",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontWeight: 700,
              fontSize: "12px",
              fontFamily: "var(--font-heading)"
            }}
          >
            {row.avatarInitials}
          </div>
          <div>
            <span style={{ fontWeight: 600, color: "#1B2330", display: "block" }}>{row.name}</span>
            <span style={{ fontSize: "11px", color: "#5F6774" }}>{row.department}</span>
          </div>
        </div>
      )
    },
    { key: "id", label: "ID", sortable: true },
    {
      key: "status",
      label: "Status Badge",
      sortable: true,
      render: (row) => (
        <StatusBadge
          variant={row.statusVariant}
          label={row.statusLabel}
        />
      )
    },
    { key: "reason", label: "Reason / Trigger", sortable: false },
    {
      key: "daysFlagged",
      label: "Days Since Flagged",
      sortable: true,
      render: (row) => (
        <span style={{ color: row.statusVariant === "flagged-at-risk" ? "#B23A2E" : "#D9922E", fontWeight: 600 }}>
          {row.daysFlagged}
        </span>
      )
    },
    {
      key: "actions",
      label: "Actions",
      sortable: false,
      render: (row) => (
        <div style={{ textAlign: "center" }}>
          <button
            onClick={() => handleViewProfile(row)}
            className="edu-btn-secondary"
            style={{ padding: "4px 10px", fontSize: "11px" }}
          >
            View Profile
          </button>
        </div>
      )
    }
  ];

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="admin"
        activeId="alerts"
        logoText="EduIntel AI"
        roleText="Administrator Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "alerts") navigate(`/admin/${itemId}`);
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: "Dr. Aria Vance", role: "Super Admin" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content">
          {/* Page Header */}
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
                EARLY INTERVENTION SYSTEM
              </span>
              <h2
                className="edu-font-heading"
                style={{ fontSize: "24px", fontWeight: 600, color: "#1B2330", margin: "4px 0 0 0" }}
              >
                Risk Alerts
              </h2>
              <p style={{ fontSize: "14px", color: "#5F6774", margin: "4px 0 0 0" }}>
                Identify and manage students requiring immediate academic or attendance intervention.
              </p>
            </div>

            <div style={{ display: "flex", gap: "12px" }}>
              <button className="edu-btn-secondary" style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "16px" }}>filter_list</span>
                Filter Controls
              </button>
              <button className="edu-btn-accent" style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "16px" }}>add</span>
                New Intervention
              </button>
            </div>
          </div>

          {/* KPI Stat Cards Row */}
          <div className="edu-kpi-grid" style={{ marginBottom: "24px" }}>
            <KpiCard
              title="At-Risk Students"
              value={riskAlertsKpis.atRiskCount}
              trend={riskAlertsKpis.atRiskTrend}
              trendDirection="down"
              progressPercent={75}
              progressColor="#B23A2E"
            />
            <KpiCard
              title="Needs Attention"
              value={riskAlertsKpis.needsAttentionCount}
              trend={riskAlertsKpis.needsAttentionTrend}
              trendDirection="up"
              progressPercent={45}
              progressColor="#D9922E"
            />
            <KpiCard
              title="Resolution Rate"
              value={riskAlertsKpis.resolutionRate}
              trend={riskAlertsKpis.resolutionAvgDays}
              trendDirection="up"
              progressPercent={88}
              progressColor="#3C8C5D"
            />
            <KpiCard
              title="Pending Actions"
              value={riskAlertsKpis.pendingActionsCount}
              trend="Counselor Assigned"
              trendDirection="up"
              progressPercent={60}
              progressColor="#26415E"
            />
          </div>

          {/* Intervention Queue Table */}
          <DataTable
            title="Intervention Queue"
            columns={columns}
            data={riskAlertsQueueData}
            pageSize={10}
            actions={
              <button className="edu-btn-secondary" style={{ padding: "6px 12px", fontSize: "12px", display: "flex", alignItems: "center", gap: "4px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "16px" }}>download</span>
                Export Priority List
              </button>
            }
          />
        </main>
      </div>

      {/* Intervention Detail Modal */}
      {selectedStudent && (
        <Modal
          isOpen={isModalOpen}
          onClose={() => setIsModalOpen(false)}
          title={`Intervention Brief: ${selectedStudent.name}`}
          icon="warning"
          iconVariant={selectedStudent.statusVariant === "flagged-at-risk" ? "danger" : "warning"}
          primaryLabel="ASSIGN ADVISOR"
          onPrimary={() => {
            alert(`Counselor assigned for ${selectedStudent.name}`);
            setIsModalOpen(false);
          }}
          secondaryLabel="CLOSE"
          onSecondary={() => setIsModalOpen(false)}
          footerNote={`INTERVENTION ID: ${selectedStudent.id}`}
          description={
            <div style={{ textAlign: "left" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
                <div>
                  <h4 style={{ margin: 0, color: "#1B2330", fontSize: "16px" }}>{selectedStudent.name}</h4>
                  <p style={{ margin: 0, fontSize: "12px", color: "#5F6774" }}>{selectedStudent.department}</p>
                </div>
                <StatusBadge variant={selectedStudent.statusVariant} label={selectedStudent.statusLabel} />
              </div>
              <div className="edu-card" style={{ padding: "16px", backgroundColor: "#FAFAF7", marginBottom: "16px" }}>
                <p style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase", margin: "0 0 6px 0" }}>Trigger Reason</p>
                <p style={{ fontSize: "13px", color: "#B23A2E", margin: 0, fontWeight: 500 }}>{selectedStudent.reason}</p>
              </div>
              <p style={{ fontSize: "12px", color: "#5F6774", margin: 0 }}>
                Flagged: <strong>{selectedStudent.daysFlagged}</strong>. Requires academic advisor consultation and parent notification.
              </p>
            </div>
          }
        />
      )}
    </div>
  );
}
