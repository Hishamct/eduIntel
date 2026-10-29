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
              width: "36px",
              height: "36px",
              borderRadius: "10px",
              backgroundColor: row.statusVariant === "flagged-at-risk" ? "#FEE2E2" : "#FEF3C7",
              color: row.statusVariant === "flagged-at-risk" ? "#B91C1C" : "#B45309",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontWeight: 700,
              fontSize: "12.5px",
              fontFamily: "var(--font-heading)"
            }}
          >
            {row.avatarInitials}
          </div>
          <div>
            <span style={{ fontWeight: 600, color: "#0F172A", display: "block" }}>{row.name}</span>
            <span style={{ fontSize: "11.5px", color: "#64748B" }}>{row.department}</span>
          </div>
        </div>
      )
    },
    { key: "id", label: "ID", sortable: true },
    {
      key: "status",
      label: "Risk Level",
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
        <span style={{ color: row.statusVariant === "flagged-at-risk" ? "#EF4444" : "#D97706", fontWeight: 700 }}>
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
            style={{ padding: "6px 12px", fontSize: "12px", borderRadius: "8px" }}
          >
            Inspect Alert
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
        logoText="eduIntel"
        roleText="Administrator Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "alerts") navigate(`/admin/${itemId}`);
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: "Dr. Sarah Evans", role: "Super Admin" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content">
          {/* Page Header */}
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
                <span style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", color: "#B91C1C", textTransform: "uppercase", backgroundColor: "#FEE2E2", padding: "3px 10px", borderRadius: "9999px" }}>
                  EARLY INTERVENTION SYSTEM
                </span>
                <span style={{ fontSize: "12px", color: "#64748B" }}>• Real-time Anomaly Tracking</span>
              </div>
              <h2
                className="edu-font-heading"
                style={{ fontSize: "28px", fontWeight: 700, color: "#0F172A", margin: "4px 0 0 0", letterSpacing: "-0.02em" }}
              >
                Risk Alerts & Violations
              </h2>
              <p style={{ fontSize: "14px", color: "#64748B", margin: "4px 0 0 0" }}>
                Identify and manage students requiring immediate academic intervention, exam review, or attendance support.
              </p>
            </div>

            <div style={{ display: "flex", gap: "12px" }}>
              <button className="edu-btn-secondary" style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>filter_list</span>
                Filter Controls
              </button>
              <button className="edu-btn-accent" style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>add</span>
                New Intervention
              </button>
            </div>
          </div>

          {/* KPI Stat Cards Row */}
          <div className="edu-kpi-grid" style={{ marginBottom: "28px" }}>
            <KpiCard
              title="At-Risk Students"
              value={riskAlertsKpis.atRiskCount}
              trend={riskAlertsKpis.atRiskTrend}
              trendDirection="down"
              progressPercent={75}
              progressColor="#EF4444"
            />
            <KpiCard
              title="Needs Attention"
              value={riskAlertsKpis.needsAttentionCount}
              trend={riskAlertsKpis.needsAttentionTrend}
              trendDirection="up"
              progressPercent={45}
              progressColor="#F59E0B"
            />
            <KpiCard
              title="Resolution Rate"
              value={riskAlertsKpis.resolutionRate}
              trend={riskAlertsKpis.resolutionAvgDays}
              trendDirection="up"
              progressPercent={88}
              progressColor="#10B981"
            />
            <KpiCard
              title="Pending Actions"
              value={riskAlertsKpis.pendingActionsCount}
              trend="Counselor Assigned"
              trendDirection="up"
              progressPercent={60}
              progressColor="#06B6D4"
            />
          </div>

          {/* Intervention Queue Table */}
          <DataTable
            title="Active Intervention Queue"
            columns={columns}
            data={riskAlertsQueueData}
            pageSize={10}
            actions={
              <button className="edu-btn-secondary" style={{ padding: "8px 14px", fontSize: "12px", display: "flex", alignItems: "center", gap: "6px" }}>
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
                  <h4 style={{ margin: 0, color: "#0F172A", fontSize: "16px", fontWeight: 700 }}>{selectedStudent.name}</h4>
                  <p style={{ margin: 0, fontSize: "12px", color: "#64748B" }}>{selectedStudent.department}</p>
                </div>
                <StatusBadge variant={selectedStudent.statusVariant} label={selectedStudent.statusLabel} />
              </div>
              <div className="edu-card" style={{ padding: "16px", backgroundColor: "#F8FAFC", marginBottom: "16px", border: "1px solid #E2E8F0" }}>
                <p style={{ fontSize: "11px", fontWeight: 700, color: "#64748B", textTransform: "uppercase", margin: "0 0 6px 0" }}>Trigger Reason</p>
                <p style={{ fontSize: "13px", color: "#B91C1C", margin: 0, fontWeight: 600 }}>{selectedStudent.reason}</p>
              </div>
              <p style={{ fontSize: "12.5px", color: "#64748B", margin: 0, lineHeight: 1.5 }}>
                Flagged: <strong>{selectedStudent.daysFlagged}</strong>. Requires academic advisor consultation and parent notification.
              </p>
            </div>
          }
        />
      )}
    </div>
  );
}

