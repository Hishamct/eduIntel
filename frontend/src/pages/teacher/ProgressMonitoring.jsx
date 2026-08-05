import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, KpiCard, DataTable, StatusBadge } from "../../components/ui";
import { progressMonitoringStudents } from "../../data/teacherMockData";
import { logout } from "../../api/auth";

export default function ProgressMonitoring() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [selectedClass, setSelectedClass] = useState("All");
  const navigate = useNavigate();

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const filteredData = useMemo(() => {
    return progressMonitoringStudents.filter((item) => {
      return selectedClass === "All" || item.classSection === selectedClass;
    });
  }, [selectedClass]);

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
            <span style={{ fontSize: "11px", color: "#5F6774", display: "block" }}>{row.id}</span>
          </div>
        </div>
      )
    },
    { key: "classSection", label: "Class / Section", sortable: true },
    {
      key: "attendanceRate",
      label: "Attendance Rate",
      sortable: true,
      render: (row) => (
        <span style={{ fontWeight: 600, color: parseFloat(row.attendanceRate) < 75 ? "#B23A2E" : "#1B2330" }}>
          {row.attendanceRate}
        </span>
      )
    },
    { key: "assignmentCompletion", label: "Assignment Completion", sortable: true },
    { key: "gpaTrend", label: "GPA Trajectory", sortable: true },
    {
      key: "status",
      label: "Progress Status",
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
        userRole="teacher"
        activeId="progress"
        logoText="EduIntel AI"
        roleText="Teacher Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "progress") navigate(`/teacher/${itemId}`);
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
                CLASSROOM ANALYTICS
              </span>
              <h2
                className="edu-font-heading"
                style={{ fontSize: "24px", fontWeight: 600, color: "#1B2330", margin: "4px 0 0 0" }}
              >
                Progress Monitoring
              </h2>
              <p style={{ fontSize: "14px", color: "#5F6774", margin: "4px 0 0 0" }}>
                Track student academic trajectories, attendance consistency, and submission completion rates.
              </p>
            </div>

            <div style={{ display: "flex", gap: "12px" }}>
              <button className="edu-btn-secondary" style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "16px" }}>download</span>
                EXPORT REPORT
              </button>
            </div>
          </div>

          {/* Top KPI Cards */}
          <div className="edu-kpi-grid" style={{ marginBottom: "24px" }}>
            <KpiCard
              title="Class Average Attendance"
              value="94.2%"
              trend="STABLE"
              trendDirection="up"
              progressPercent={94}
              progressColor="#3C8C5D"
            />
            <KpiCard
              title="Submissions On-Time"
              value="88.0%"
              trend="+3.4%"
              trendDirection="up"
              progressPercent={88}
              progressColor="#26415E"
            />
            <KpiCard
              title="Cohort Pass Rate"
              value="92.5%"
              trend="ABOVE TARGET"
              trendDirection="up"
              progressPercent={92}
              progressColor="#3C8C5D"
            />
          </div>

          {/* Filter Bar */}
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
            <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
              <label style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.05em", color: "#5F6774", textTransform: "uppercase" }}>
                Select Class Section
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
                <option value="All">All Sections</option>
                <option value="Grade 10-A">Grade 10-A</option>
                <option value="Grade 10-B">Grade 10-B</option>
                <option value="Grade 11-A">Grade 11-A</option>
                <option value="Grade 11-B">Grade 11-B</option>
                <option value="Grade 11-C">Grade 11-C</option>
                <option value="Grade 12-A">Grade 12-A</option>
                <option value="Grade 12-B">Grade 12-B</option>
              </select>
            </div>
          </div>

          {/* Progress Trajectory Data Table */}
          <DataTable
            title="Student Trajectory Registry"
            columns={columns}
            data={filteredData}
            pageSize={10}
          />
        </main>
      </div>
    </div>
  );
}
