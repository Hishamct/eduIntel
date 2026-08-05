import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, DataTable, StatusBadge, Modal } from "../../components/ui";
import { studentRecordsData } from "../../data/adminMockData";
import { logout } from "../../api/auth";

export default function StudentRecords() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [selectedClass, setSelectedClass] = useState("All");
  const [selectedStatus, setSelectedStatus] = useState("All");
  const [selectedStudent, setSelectedStudent] = useState(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const navigate = useNavigate();

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const filteredData = useMemo(() => {
    return studentRecordsData.filter((student) => {
      const matchClass = selectedClass === "All" || student.gradeClass === selectedClass;
      const matchStatus =
        selectedStatus === "All" ||
        student.academicStatusVariant === selectedStatus ||
        student.academicStatusLabel.toLowerCase().includes(selectedStatus.toLowerCase());
      return matchClass && matchStatus;
    });
  }, [selectedClass, selectedStatus]);

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
              backgroundColor: "rgba(38, 65, 94, 0.1)",
              color: "#26415E",
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
            <span style={{ fontWeight: 600, color: "#1B2330" }}>{row.name}</span>
          </div>
        </div>
      )
    },
    { key: "id", label: "Student ID", sortable: true },
    { key: "gradeClass", label: "Grade / Class", sortable: true },
    { key: "enrollmentStatus", label: "Enrollment", sortable: true },
    {
      key: "academicStatus",
      label: "Academic Status",
      sortable: true,
      render: (row) => (
        <StatusBadge
          variant={row.academicStatusVariant}
          label={row.academicStatusLabel}
        />
      )
    },
    { key: "joinedDate", label: "Joined Date", sortable: true },
    {
      key: "actions",
      label: "Actions",
      sortable: false,
      render: (row) => (
        <div style={{ textAlign: "right" }}>
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
        activeId="students"
        logoText="EduIntel AI"
        roleText="Administrator Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "students") navigate(`/admin/${itemId}`);
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
                ADMINISTRATOR PORTAL
              </span>
              <h2
                className="edu-font-heading"
                style={{ fontSize: "24px", fontWeight: 600, color: "#1B2330", margin: "4px 0 0 0" }}
              >
                Student Records
              </h2>
            </div>
          </div>

          {/* Filter Controls Strip */}
          <div
            className="edu-card"
            style={{
              padding: "16px 20px",
              marginBottom: "24px",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              flexWrap: "wrap",
              gap: "16px"
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "16px", flexWrap: "wrap" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                <label
                  style={{
                    fontSize: "11px",
                    fontWeight: 700,
                    letterSpacing: "0.05em",
                    textTransform: "uppercase",
                    color: "#5F6774"
                  }}
                >
                  Class Filter
                </label>
                <select
                  value={selectedClass}
                  onChange={(e) => setSelectedClass(e.target.value)}
                  style={{
                    padding: "6px 12px",
                    borderRadius: "4px",
                    border: "1px solid #E5E5E1",
                    backgroundColor: "#F4F4F1",
                    fontSize: "13px",
                    color: "#1B2330",
                    outline: "none"
                  }}
                >
                  <option value="All">All Classes</option>
                  <option value="Grade 10-A">Grade 10-A</option>
                  <option value="Grade 10-B">Grade 10-B</option>
                  <option value="Grade 11-A">Grade 11-A</option>
                  <option value="Grade 11-B">Grade 11-B</option>
                  <option value="Grade 11-C">Grade 11-C</option>
                  <option value="Grade 12-A">Grade 12-A</option>
                  <option value="Grade 12-B">Grade 12-B</option>
                </select>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                <label
                  style={{
                    fontSize: "11px",
                    fontWeight: 700,
                    letterSpacing: "0.05em",
                    textTransform: "uppercase",
                    color: "#5F6774"
                  }}
                >
                  Academic Status
                </label>
                <select
                  value={selectedStatus}
                  onChange={(e) => setSelectedStatus(e.target.value)}
                  style={{
                    padding: "6px 12px",
                    borderRadius: "4px",
                    border: "1px solid #E5E5E1",
                    backgroundColor: "#F4F4F1",
                    fontSize: "13px",
                    color: "#1B2330",
                    outline: "none"
                  }}
                >
                  <option value="All">All Statuses</option>
                  <option value="on-track">On-Track</option>
                  <option value="needs-attention">Needs-Attention</option>
                  <option value="flagged-at-risk">Flagged</option>
                </select>
              </div>
            </div>

            <div style={{ display: "flex", gap: "12px" }}>
              <button className="edu-btn-primary" style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "16px" }}>add</span>
                New Student
              </button>
              <button className="edu-btn-secondary" style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "16px" }}>download</span>
                Export Data
              </button>
            </div>
          </div>

          {/* Master Student Data Table */}
          <DataTable
            title="Student Directory Master List"
            columns={columns}
            data={filteredData}
            pageSize={10}
          />
        </main>
      </div>

      {/* Student Profile Detail Modal */}
      {selectedStudent && (
        <Modal
          isOpen={isModalOpen}
          onClose={() => setIsModalOpen(false)}
          title={`Student Profile: ${selectedStudent.name}`}
          icon="person"
          iconVariant="info"
          primaryLabel="CLOSE PROFILE"
          onPrimary={() => setIsModalOpen(false)}
          secondaryLabel="PRINT RECORD"
          onSecondary={() => window.print()}
          footerNote={`INSTITUTIONAL RECORD ID: ${selectedStudent.id}`}
          description={
            <div style={{ display: "flex", flexDirection: "column", gap: "16px", textAlign: "left" }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "16px",
                  paddingBottom: "16px",
                  borderBottom: "1px solid #E5E5E1"
                }}
              >
                <div
                  style={{
                    width: "52px",
                    height: "52px",
                    borderRadius: "50%",
                    backgroundColor: "#26415E",
                    color: "#FFFFFF",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: "20px",
                    fontWeight: 700,
                    fontFamily: "var(--font-heading)"
                  }}
                >
                  {selectedStudent.avatarInitials}
                </div>
                <div>
                  <h4 style={{ margin: 0, color: "#1B2330", fontSize: "18px" }}>
                    {selectedStudent.name}
                  </h4>
                  <p style={{ margin: "2px 0 0 0", color: "#5F6774", fontSize: "12px", fontFamily: "var(--font-mono)" }}>
                    {selectedStudent.id} • {selectedStudent.gradeClass}
                  </p>
                </div>
                <div style={{ marginLeft: "auto" }}>
                  <StatusBadge
                    variant={selectedStudent.academicStatusVariant}
                    label={selectedStudent.academicStatusLabel}
                  />
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
                <div className="edu-card" style={{ padding: "12px", backgroundColor: "#FAFAF7" }}>
                  <p style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", margin: 0, textTransform: "uppercase" }}>
                    Contact Information
                  </p>
                  <p style={{ fontSize: "12px", color: "#1B2330", margin: "6px 0 2px 0" }}>📧 {selectedStudent.email}</p>
                  <p style={{ fontSize: "12px", color: "#1B2330", margin: "2px 0" }}>📞 {selectedStudent.phone}</p>
                  <p style={{ fontSize: "12px", color: "#5F6774", margin: "2px 0 0 0" }}>📍 {selectedStudent.address}</p>
                </div>

                <div className="edu-card" style={{ padding: "12px", backgroundColor: "#FAFAF7" }}>
                  <p style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", margin: 0, textTransform: "uppercase" }}>
                    Guardian Details
                  </p>
                  <p style={{ fontSize: "12px", fontWeight: 600, color: "#1B2330", margin: "6px 0 2px 0" }}>{selectedStudent.guardianName}</p>
                  <p style={{ fontSize: "12px", color: "#5F6774", margin: "2px 0" }}>Relationship: {selectedStudent.guardianRelationship}</p>
                  <p style={{ fontSize: "12px", color: "#1B2330", margin: "2px 0 0 0" }}>📞 {selectedStudent.guardianPhone}</p>
                </div>
              </div>

              <div className="edu-card" style={{ padding: "12px" }}>
                <p style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", margin: "0 0 8px 0", textTransform: "uppercase" }}>
                  Performance Pulse
                </p>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px", color: "#1B2330" }}>
                  <span>Attendance: <strong>{selectedStudent.attendanceRate}</strong></span>
                  <span>Semester GPA: <strong>{selectedStudent.semesterGpa} / {selectedStudent.targetGpa}</strong></span>
                  <span>Active Days: <strong>{selectedStudent.daysActive} days</strong></span>
                </div>
              </div>
            </div>
          }
        />
      )}
    </div>
  );
}
