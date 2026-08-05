import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, KpiCard, DataTable, StatusBadge, Modal } from "../../components/ui";
import { flaggedStudentsData } from "../../data/teacherMockData";
import { logout } from "../../api/auth";

export default function FlaggedStudents() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [selectedStudent, setSelectedStudent] = useState(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedAction, setSelectedAction] = useState("");
  const navigate = useNavigate();

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const handleOpenActionModal = (student) => {
    setSelectedStudent(student);
    setSelectedAction(student.teacherActions[0] || "Schedule 1:1 Meeting");
    setIsModalOpen(true);
  };

  const handleExecuteAction = () => {
    if (!selectedStudent || !selectedAction) return;
    alert(`Action "${selectedAction}" initiated for ${selectedStudent.name}.`);
    setIsModalOpen(false);
  };

  const columns = [
    {
      key: "name",
      label: "Student Name",
      sortable: true,
      render: (row) => (
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <div
            style={{
              width: "32px",
              height: "32px",
              borderRadius: "50%",
              backgroundColor: "rgba(178, 58, 46, 0.1)",
              color: "#B23A2E",
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
            <span style={{ fontSize: "11px", color: "#5F6774" }}>{row.id} • {row.locality}</span>
          </div>
        </div>
      )
    },
    { key: "classSection", label: "Class / Section", sortable: true },
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
    {
      key: "flagReason",
      label: "Academic / Attendance Reason",
      sortable: false,
      render: (row) => (
        <span style={{ color: "#B23A2E", fontWeight: 500, fontSize: "13px" }}>
          {row.flagReason}
        </span>
      )
    },
    { key: "daysFlagged", label: "Flagged Date", sortable: true },
    {
      key: "actions",
      label: "Teacher Action",
      sortable: false,
      render: (row) => (
        <div style={{ textAlign: "right" }}>
          <button
            onClick={() => handleOpenActionModal(row)}
            className="edu-btn-accent"
            style={{ padding: "6px 12px", fontSize: "11px" }}
          >
            Take Action
          </button>
        </div>
      )
    }
  ];

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="teacher"
        activeId="flagged"
        logoText="EduIntel AI"
        roleText="Teacher Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "flagged") navigate(`/teacher/${itemId}`);
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: "Faculty Portal", role: "Educator" }}
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
                CLASSROOM ALERTS
              </span>
              <h2
                className="edu-font-heading"
                style={{ fontSize: "24px", fontWeight: 600, color: "#1B2330", margin: "4px 0 0 0" }}
              >
                Flagged Students
              </h2>
              <p style={{ fontSize: "14px", color: "#5F6774", margin: "4px 0 0 0" }}>
                Review students with active academic or attendance alerts requiring teacher intervention.
              </p>
            </div>
          </div>

          {/* KPI Stat Cards Row */}
          <div className="edu-kpi-grid" style={{ marginBottom: "24px" }}>
            <KpiCard
              title="Total Flagged Students"
              value={flaggedStudentsData.length}
              trend="Action Required"
              trendDirection="down"
              progressPercent={100}
              progressColor="#B23A2E"
            />
            <KpiCard
              title="Attendance Alerts (<75%)"
              value="2"
              trend="Requires Notice"
              trendDirection="down"
              progressPercent={66}
              progressColor="#B23A2E"
            />
            <KpiCard
              title="Academic Score Drops"
              value="2"
              trend="Grade Drop > 15%"
              trendDirection="down"
              progressPercent={66}
              progressColor="#D9922E"
            />
          </div>

          {/* Flagged Students Data Table */}
          <DataTable
            title="Active Academic & Attendance Risk Registry"
            columns={columns}
            data={flaggedStudentsData}
            pageSize={5}
          />
        </main>
      </div>

      {/* Action Selection Modal (Manual Options Menu) */}
      {selectedStudent && (
        <Modal
          isOpen={isModalOpen}
          onClose={() => setIsModalOpen(false)}
          title={`Initiate Intervention: ${selectedStudent.name}`}
          icon="warning"
          iconVariant="danger"
          primaryLabel="EXECUTE ACTION"
          onPrimary={handleExecuteAction}
          secondaryLabel="CANCEL"
          onSecondary={() => setIsModalOpen(false)}
          footerNote={`STUDENT ID: ${selectedStudent.id}`}
          description={
            <div style={{ textAlign: "left" }}>
              <div style={{ padding: "12px", backgroundColor: "#FAFAF7", borderLeft: "4px solid #B23A2E", marginBottom: "16px" }}>
                <p style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase", margin: "0 0 4px 0" }}>
                  Academic Trigger Reason
                </p>
                <p style={{ fontSize: "13px", fontWeight: 600, color: "#B23A2E", margin: 0 }}>
                  {selectedStudent.flagReason}
                </p>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginBottom: "16px" }}>
                <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>
                  Select Manual Teacher Action:
                </label>
                {selectedStudent.teacherActions.map((actionText) => (
                  <label
                    key={actionText}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "10px",
                      padding: "10px 14px",
                      borderRadius: "4px",
                      border: `1px solid ${selectedAction === actionText ? "#26415E" : "#E5E5E1"}`,
                      backgroundColor: selectedAction === actionText ? "rgba(38, 65, 94, 0.05)" : "#FFFFFF",
                      cursor: "pointer",
                      fontSize: "13px",
                      fontWeight: selectedAction === actionText ? 600 : 400,
                      color: "#1B2330"
                    }}
                  >
                    <input
                      type="radio"
                      name="teacherActionChoice"
                      value={actionText}
                      checked={selectedAction === actionText}
                      onChange={(e) => setSelectedAction(e.target.value)}
                      style={{ accentColor: "#26415E" }}
                    />
                    {actionText}
                  </label>
                ))}
              </div>

              <p style={{ fontSize: "12px", color: "#5F6774", margin: 0 }}>
                Guardian: <strong>{selectedStudent.guardianName}</strong> ({selectedStudent.guardianPhone})
              </p>
            </div>
          }
        />
      )}
    </div>
  );
}
