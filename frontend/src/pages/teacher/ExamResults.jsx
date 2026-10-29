import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, DataTable, StatusBadge, GradingInput } from "../../components/ui";
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
    setSelectedStudent((prev) =>
      prev ? {
        ...prev,
        examScore: numScore,
        gradeLetter,
        statusVariant,
        statusLabel,
        observations: feedback
      } : null
    );
    alert(`Exam result saved for ${selectedStudent.studentName}!`);
  };

  const filteredScores = examScores.filter((row) =>
    selectedSubject === "ALL" || row.subject.toLowerCase() === selectedSubject.toLowerCase()
  );

  const columns = [
    {
      key: "studentName",
      label: "Student",
      sortable: true,
      render: (row) => (
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <div
            style={{
              width: "32px",
              height: "32px",
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
            <div style={{ fontWeight: 600, color: "#0F172A", fontSize: "13px" }}>{row.studentName}</div>
            <div style={{ fontSize: "11px", color: "#64748B" }}>{row.id}</div>
          </div>
        </div>
      )
    },
    { 
      key: "classSection", 
      label: "Class Cohort", 
      sortable: true,
      render: (row) => <span style={{ fontWeight: 600, color: "#334155" }}>{row.classSection}</span>
    },
    { 
      key: "subject", 
      label: "Subject", 
      sortable: true,
      render: (row) => (
        <span style={{ fontSize: "12px", color: "#475569" }}>{row.subject}</span>
      )
    },
    {
      key: "examScore",
      label: "Marks Scored",
      sortable: true,
      render: (row) => (
        <span style={{ fontWeight: 700, color: "#0F172A" }}>
          {row.examScore} <span style={{ color: "#94A3B8", fontWeight: 500 }}>/ {row.maxScore}</span>
        </span>
      )
    },
    {
      key: "gradeLetter",
      label: "Grade",
      sortable: true,
      render: (row) => {
        const isF = row.gradeLetter === "F";
        const isA = row.gradeLetter.includes("A");
        return (
          <span style={{
            display: "inline-block",
            padding: "3px 8px",
            borderRadius: "6px",
            fontSize: "11px",
            fontWeight: 800,
            background: isF ? "rgba(239, 68, 68, 0.12)" : isA ? "rgba(16, 185, 129, 0.12)" : "rgba(245, 158, 11, 0.12)",
            color: isF ? "#DC2626" : isA ? "#065F46" : "#B45309",
            border: `1px solid ${isF ? "rgba(239, 68, 68, 0.25)" : isA ? "rgba(16, 185, 129, 0.25)" : "rgba(245, 158, 11, 0.25)"}`
          }}>
            {row.gradeLetter}
          </span>
        );
      }
    },
    {
      key: "status",
      label: "Result Status",
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
      label: "Action",
      sortable: false,
      render: (row) => (
        <button
          onClick={() => setSelectedStudent(row)}
          style={{
            padding: "5px 12px",
            borderRadius: "8px",
            fontSize: "12px",
            fontWeight: 600,
            background: selectedStudent?.id === row.id ? "#10B981" : "rgba(241, 245, 249, 0.9)",
            color: selectedStudent?.id === row.id ? "#FFFFFF" : "#1E293B",
            border: "none",
            cursor: "pointer",
            transition: "all 0.15s ease",
            boxShadow: selectedStudent?.id === row.id ? "0 2px 8px rgba(16, 185, 129, 0.25)" : "none"
          }}
        >
          {selectedStudent?.id === row.id ? "Editing" : "Modify Mark"}
        </button>
      )
    }
  ];

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="teacher"
        activeId="exams"
        logoText="EduIntel AI"
        roleText="Faculty Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "exams") navigate(`/teacher/${itemId}`);
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
                <span className="material-symbols-outlined" style={{ fontSize: "14px", color: "#059669" }}>grade</span>
                <span style={{ fontSize: "11px", fontWeight: 700, color: "#059669", letterSpacing: "0.06em", textTransform: "uppercase" }}>
                  Assessment Registry
                </span>
              </div>
              <h1
                className="edu-font-heading"
                style={{ fontSize: "28px", fontWeight: 700, color: "#0F172A", margin: "0 0 6px 0", letterSpacing: "-0.02em" }}
              >
                Exam Results & Assessment Registry
              </h1>
              <p style={{ fontSize: "14px", color: "#64748B", margin: 0, maxWidth: "600px" }}>
                Input examination scores, record teacher observations, and review class grade percentiles.
              </p>
            </div>

            <div style={{ display: "flex", gap: "10px" }}>
              <button 
                onClick={() => alert("Mark sheet exported as audit PDF.")}
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
                Export Marksheet
              </button>
            </div>
          </div>

          {/* Top KPI Cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "16px", marginBottom: "28px" }}>
            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Class Average Marks</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#10B981" }}>score</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                74.4 / 100
              </div>
              <div style={{ fontSize: "12px", color: "#059669", display: "flex", alignItems: "center", gap: "4px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "14px" }}>trending_up</span>
                +2.1% vs term benchmark
              </div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Exam Pass Rate</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#0284C7" }}>verified</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                85.0%
              </div>
              <div style={{ fontSize: "12px", color: "#D97706" }}>2 re-tests required</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Top Distinction (A/A+)</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#8B5CF6" }}>workspace_premium</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                12 Students
              </div>
              <div style={{ fontSize: "12px", color: "#059669" }}>Highest recorded: 96/100</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Remedial Priority</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#EF4444" }}>warning</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                3 Students
              </div>
              <div style={{ fontSize: "12px", color: "#DC2626" }}>Scheduled for tutorials</div>
            </div>
          </div>

          {/* Subject Filter Pills */}
          <div style={{ display: "flex", gap: "8px", overflowX: "auto", paddingBottom: "4px", marginBottom: "20px" }}>
            {["Mathematics II", "Physics Lab", "Computer Science", "ALL"].map((subj) => (
              <button
                key={subj}
                onClick={() => setSelectedSubject(subj)}
                style={{
                  padding: "8px 16px",
                  borderRadius: "9999px",
                  fontSize: "12px",
                  fontWeight: 600,
                  border: "none",
                  cursor: "pointer",
                  transition: "all 0.2s ease",
                  backgroundColor: selectedSubject.toLowerCase() === subj.toLowerCase() ? "#10B981" : "rgba(255, 255, 255, 0.75)",
                  color: selectedSubject.toLowerCase() === subj.toLowerCase() ? "#FFFFFF" : "#475569",
                  boxShadow: selectedSubject.toLowerCase() === subj.toLowerCase() ? "0 4px 12px rgba(16, 185, 129, 0.3)" : "0 1px 3px rgba(0,0,0,0.05)",
                }}
              >
                {subj === "ALL" ? "All Subjects" : subj}
              </button>
            ))}
          </div>

          {/* Table & Mark Editor Component */}
          <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
            <DataTable
              title={`Exam Marks Registry: ${selectedSubject} (${filteredScores.length})`}
              columns={columns}
              data={filteredScores}
              pageSize={10}
            />

            {selectedStudent && (
              <div className="edu-card" style={{ padding: "26px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "20px" }}>
                  <div style={{ width: "36px", height: "36px", borderRadius: "10px", background: "rgba(16, 185, 129, 0.12)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#059669" }}>rate_review</span>
                  </div>
                  <div>
                    <h3 className="edu-font-heading" style={{ margin: 0, fontSize: "17px", fontWeight: 700, color: "#0F172A" }}>
                      Update Marks & Pedagogical Feedback
                    </h3>
                    <p style={{ margin: 0, fontSize: "12px", color: "#64748B" }}>
                      Modifying score record for <strong>{selectedStudent.studentName}</strong> ({selectedStudent.id})
                    </p>
                  </div>
                </div>

                <GradingInput
                  studentName={selectedStudent.studentName}
                  studentInitials={selectedStudent.avatarInitials}
                  assignmentTitle={`${selectedStudent.subject} Final Exam`}
                  submissionNote={`Recorded Grade: ${selectedStudent.gradeLetter} • Current Score: ${selectedStudent.examScore}`}
                  maxScore={selectedStudent.maxScore}
                  initialScore={selectedStudent.examScore}
                  initialFeedback={selectedStudent.observations}
                  onSave={handleSaveGrade}
                  onDiscard={() => setSelectedStudent(null)}
                />
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
