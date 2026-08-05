import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, KpiCard, DataTable, StatusBadge, GradingInput } from "../../components/ui";
import { examEntryData } from "../../data/teacherMockData";
import { logout } from "../../api/auth";

export default function ExamResults() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [examScores, setExamScores] = useState(examEntryData);
  const [selectedStudent, setSelectedStudent] = useState(examEntryData[0]);
  const [selectedSubject, setSelectedSubject] = useState("Mathematics II");
  const navigate = useNavigate();

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const handleSaveGrade = ({ score, feedback }) => {
    if (!selectedStudent) return;
    const numScore = Number(score);
    let gradeLetter = "A+";
    let statusVariant = "on-track";
    let statusLabel = "PASSED";

    if (numScore < 50) {
      gradeLetter = "F";
      statusVariant = "flagged-at-risk";
      statusLabel = "FAILED";
    } else if (numScore < 70) {
      gradeLetter = "C";
      statusVariant = "needs-attention";
      statusLabel = "PASSED";
    } else if (numScore < 85) {
      gradeLetter = "B";
    }

    setExamScores((prev) =>
      prev.map((item) =>
        item.id === selectedStudent.id
          ? {
              ...item,
              examScore: numScore,
              gradeLetter,
              statusVariant,
              statusLabel,
              observations: feedback
            }
          : item
      )
    );
    alert(`Exam result saved for ${selectedStudent.studentName}!`);
  };

  const columns = [
    {
      key: "studentName",
      label: "Student Name",
      sortable: true,
      render: (row) => (
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <div
            style={{
              width: "30px",
              height: "30px",
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
            <span style={{ fontWeight: 600, color: "#1B2330" }}>{row.studentName}</span>
            <span style={{ fontSize: "11px", color: "#5F6774", display: "block" }}>{row.id}</span>
          </div>
        </div>
      )
    },
    { key: "classSection", label: "Class", sortable: true },
    { key: "subject", label: "Subject", sortable: true },
    {
      key: "examScore",
      label: "Score",
      sortable: true,
      render: (row) => <strong>{row.examScore} / {row.maxScore}</strong>
    },
    {
      key: "gradeLetter",
      label: "Grade",
      sortable: true,
      render: (row) => (
        <span style={{ fontWeight: 700, color: row.statusVariant === "flagged-at-risk" ? "#B23A2E" : "#26415E" }}>
          {row.gradeLetter}
        </span>
      )
    },
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
    {
      key: "actions",
      label: "Actions",
      sortable: false,
      render: (row) => (
        <div style={{ textAlign: "right" }}>
          <button
            onClick={() => setSelectedStudent(row)}
            className="edu-btn-secondary"
            style={{ padding: "4px 10px", fontSize: "11px" }}
          >
            Edit Score
          </button>
        </div>
      )
    }
  ];

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="teacher"
        activeId="exams"
        logoText="EduIntel AI"
        roleText="Teacher Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "exams") navigate(`/teacher/${itemId}`);
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
                ASSESSMENT REGISTRY
              </span>
              <h2
                className="edu-font-heading"
                style={{ fontSize: "24px", fontWeight: 600, color: "#1B2330", margin: "4px 0 0 0" }}
              >
                Exam Result Entry & Analysis
              </h2>
              <p style={{ fontSize: "14px", color: "#5F6774", margin: "4px 0 0 0" }}>
                Input subject scores, record teacher observations, and review class grade distributions.
              </p>
            </div>

            <div style={{ display: "flex", gap: "12px" }}>
              <button className="edu-btn-secondary" style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "16px" }}>download</span>
                EXPORT MARKSHEET
              </button>
            </div>
          </div>

          {/* Top KPI Cards */}
          <div className="edu-kpi-grid" style={{ marginBottom: "24px" }}>
            <KpiCard
              title="Class Average Marks"
              value="74.4 / 100"
              trend="+2.1%"
              trendDirection="up"
              progressPercent={74}
              progressColor="#26415E"
            />
            <KpiCard
              title="Exam Pass Rate"
              value="85.0%"
              trend="2 Re-tests Required"
              trendDirection="down"
              progressPercent={85}
              progressColor="#3C8C5D"
            />
            <KpiCard
              title="Top Grade (A/A+)"
              value="12 Students"
              trend="Highest Score: 96"
              trendDirection="up"
              progressPercent={60}
              progressColor="#C97A2B"
            />
          </div>

          {/* Filter Strip */}
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
                Subject
              </label>
              <select
                value={selectedSubject}
                onChange={(e) => setSelectedSubject(e.target.value)}
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
                <option value="Mathematics II">Mathematics II</option>
                <option value="Physics Lab">Physics Lab</option>
                <option value="Computer Science">Computer Science</option>
              </select>
            </div>
          </div>

          {/* Table & Grading Component */}
          <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
            <DataTable
              title={`Exam Marks Registry: ${selectedSubject}`}
              columns={columns}
              data={examScores}
              pageSize={10}
            />

            {selectedStudent && (
              <GradingInput
                studentName={selectedStudent.studentName}
                studentInitials={selectedStudent.avatarInitials}
                assignmentTitle={`${selectedStudent.subject} Final Exam`}
                submissionNote={`Grade Assigned: ${selectedStudent.gradeLetter}`}
                maxScore={selectedStudent.maxScore}
                initialScore={selectedStudent.examScore}
                initialFeedback={selectedStudent.observations}
                onSave={handleSaveGrade}
                onDiscard={() => setSelectedStudent(null)}
              />
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
