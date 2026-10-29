import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, DataTable, StatusBadge } from "../../components/ui";
import { progressMonitoringStudents } from "../../data/teacherMockData";
import { logout } from "../../api/auth";

export default function ProgressMonitoring() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [selectedClass, setSelectedClass] = useState("All");
  const [searchQuery, setSearchQuery] = useState("");
  const navigate = useNavigate();

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const filteredData = useMemo(() => {
    return progressMonitoringStudents.filter((item) => {
      const matchesClass = selectedClass === "All" || item.classSection === selectedClass;
      const matchesSearch = !searchQuery || 
        item.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        item.id.toLowerCase().includes(searchQuery.toLowerCase());
      return matchesClass && matchesSearch;
    });
  }, [selectedClass, searchQuery]);

  const columns = [
    {
      key: "name",
      label: "Student Name",
      sortable: true,
      render: (row) => (
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <div
            style={{
              width: "34px",
              height: "34px",
              borderRadius: "50%",
              background: "linear-gradient(135deg, rgba(16, 185, 129, 0.15), rgba(14, 165, 233, 0.15))",
              color: "#059669",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontWeight: 700,
              fontSize: "12px",
              border: "1px solid rgba(16, 185, 129, 0.3)"
            }}
          >
            {row.avatarInitials}
          </div>
          <div>
            <div style={{ fontWeight: 600, color: "#0F172A", fontSize: "13px" }}>{row.name}</div>
            <div style={{ fontSize: "11px", color: "#64748B" }}>{row.id}</div>
          </div>
        </div>
      )
    },
    { 
      key: "classSection", 
      label: "Class Cohort", 
      sortable: true,
      render: (row) => (
        <span style={{ fontWeight: 600, color: "#334155" }}>{row.classSection}</span>
      )
    },
    {
      key: "attendanceRate",
      label: "Attendance Rate",
      sortable: true,
      render: (row) => {
        const rate = parseFloat(row.attendanceRate);
        const isLow = rate < 75;
        const isModerate = rate >= 75 && rate < 85;
        return (
          <span style={{
            display: "inline-block",
            padding: "4px 10px",
            borderRadius: "6px",
            fontSize: "11px",
            fontWeight: 700,
            background: isLow ? "rgba(239, 68, 68, 0.1)" : isModerate ? "rgba(245, 158, 11, 0.1)" : "rgba(16, 185, 129, 0.1)",
            color: isLow ? "#DC2626" : isModerate ? "#B45309" : "#059669",
            border: isLow ? "1px solid rgba(239, 68, 68, 0.25)" : isModerate ? "1px solid rgba(245, 158, 11, 0.25)" : "1px solid rgba(16, 185, 129, 0.25)"
          }}>
            {row.attendanceRate}
          </span>
        );
      }
    },
    { 
      key: "assignmentCompletion", 
      label: "Homework Completion", 
      sortable: true,
      render: (row) => (
        <span style={{ fontWeight: 600, color: "#0F172A" }}>{row.assignmentCompletion}</span>
      )
    },
    { 
      key: "gpaTrend", 
      label: "GPA Trajectory", 
      sortable: true,
      render: (row) => (
        <div style={{ display: "flex", alignItems: "center", gap: "4px", color: row.gpaTrend.includes("+") ? "#059669" : "#64748B", fontWeight: 600 }}>
          <span className="material-symbols-outlined" style={{ fontSize: "16px" }}>
            {row.gpaTrend.includes("+") ? "trending_up" : "trending_flat"}
          </span>
          {row.gpaTrend}
        </div>
      )
    },
    {
      key: "status",
      label: "Academic Standing",
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
        roleText="Faculty Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "progress") navigate(`/teacher/${itemId}`);
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: "Dr. Sarah Jenkins", role: "Faculty Head" }}
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
              <div style={{ display: "inline-flex", alignItems: "center", gap: "6px", padding: "4px 10px", borderRadius: "9999px", background: "rgba(16, 185, 129, 0.1)", border: "1px solid rgba(16, 185, 129, 0.2)", marginBottom: "8px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "14px", color: "#059669" }}>monitoring</span>
                <span style={{ fontSize: "11px", fontWeight: 700, color: "#059669", letterSpacing: "0.06em", textTransform: "uppercase" }}>
                  Classroom Analytics
                </span>
              </div>
              <h1
                className="edu-font-heading"
                style={{ fontSize: "28px", fontWeight: 700, color: "#0F172A", margin: "0 0 6px 0", letterSpacing: "-0.02em" }}
              >
                Progress Monitoring
              </h1>
              <p style={{ fontSize: "14px", color: "#64748B", margin: 0, maxWidth: "600px" }}>
                Track student academic trajectories, attendance consistency, and automated assignment completion rates.
              </p>
            </div>

            <div style={{ display: "flex", gap: "10px" }}>
              <button 
                onClick={() => alert("Classroom academic progress ledger exported as CSV.")}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "6px",
                  padding: "9px 16px",
                  borderRadius: "10px",
                  fontSize: "13px",
                  fontWeight: 600,
                  background: "rgba(255, 255, 255, 0.8)",
                  border: "1px solid rgba(226, 232, 240, 0.9)",
                  color: "#1E293B",
                  cursor: "pointer",
                  backdropFilter: "blur(12px)"
                }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: "18px", color: "#64748B" }}>download</span>
                Export Report
              </button>
              <button 
                className="edu-btn-primary" 
                onClick={() => navigate("/teacher/flagged")}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "6px",
                  padding: "9px 18px",
                  borderRadius: "10px",
                  fontSize: "13px",
                  fontWeight: 600,
                  boxShadow: "0 4px 12px rgba(16, 185, 129, 0.25)"
                }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>flag</span>
                View At-Risk Students
              </button>
            </div>
          </div>

          {/* Top KPI Cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "16px", marginBottom: "28px" }}>
            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Cohort Attendance</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#10B981" }}>event_available</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                94.2%
              </div>
              <div style={{ fontSize: "12px", color: "#059669", display: "flex", alignItems: "center", gap: "4px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "14px" }}>trending_up</span>
                Consistent benchmark
              </div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Submissions On-Time</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#0284C7" }}>assignment_turned_in</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                88.0%
              </div>
              <div style={{ fontSize: "12px", color: "#0284C7" }}>+3.4% MoM improvement</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Pass Trajectory</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#10B981" }}>school</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                92.5%
              </div>
              <div style={{ fontSize: "12px", color: "#059669" }}>Above department target</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Interventions Needed</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#F59E0B" }}>help_center</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                4 Students
              </div>
              <div style={{ fontSize: "12px", color: "#D97706" }}>Attendance &lt; 75%</div>
            </div>
          </div>

          {/* Section Filter Pills and Search */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px", flexWrap: "wrap", gap: "12px" }}>
            <div style={{ display: "flex", gap: "8px", overflowX: "auto", paddingBottom: "4px" }}>
              {["All", "Grade 10-A", "Grade 10-B", "Grade 11-A", "Grade 11-B", "Grade 12-A"].map((sec) => (
                <button
                  key={sec}
                  onClick={() => setSelectedClass(sec)}
                  style={{
                    padding: "8px 16px",
                    borderRadius: "9999px",
                    fontSize: "12px",
                    fontWeight: 600,
                    border: "none",
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                    backgroundColor: selectedClass === sec ? "#10B981" : "rgba(255, 255, 255, 0.75)",
                    color: selectedClass === sec ? "#FFFFFF" : "#475569",
                    boxShadow: selectedClass === sec ? "0 4px 12px rgba(16, 185, 129, 0.3)" : "0 1px 3px rgba(0,0,0,0.05)",
                  }}
                >
                  {sec === "All" ? "All Class Cohorts" : sec}
                </button>
              ))}
            </div>

            <div style={{ position: "relative", minWidth: "240px" }}>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search student or ID..."
                style={{
                  width: "100%",
                  padding: "9px 14px 9px 36px",
                  borderRadius: "10px",
                  border: "1px solid rgba(226, 232, 240, 0.9)",
                  backgroundColor: "rgba(255, 255, 255, 0.85)",
                  fontSize: "13px",
                  color: "#1E293B",
                  outline: "none",
                  boxSizing: "border-box"
                }}
              />
              <span className="material-symbols-outlined" style={{ position: "absolute", left: "10px", top: "9px", fontSize: "18px", color: "#94A3B8" }}>
                search
              </span>
            </div>
          </div>

          {/* Progress Trajectory Data Table */}
          <DataTable
            title={`Student Trajectory Registry (${filteredData.length})`}
            columns={columns}
            data={filteredData}
            pageSize={10}
          />
        </main>
      </div>
    </div>
  );
}
