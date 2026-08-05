import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, DataTable, StatusBadge, GradingInput } from "../../components/ui";
import { activeAssignmentsList, assignmentSubmissionsQueue } from "../../data/teacherMockData";
import { logout } from "../../api/auth";

export default function AssignmentsGrading() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [submissions, setSubmissions] = useState(assignmentSubmissionsQueue);
  const [selectedSubmission, setSelectedSubmission] = useState(assignmentSubmissionsQueue[0]);
  const [newTitle, setNewTitle] = useState("");
  const [newSection, setNewSection] = useState("Grade 12-A");
  const [newDueDate, setNewDueDate] = useState("");
  const [newMaxScore, setNewMaxScore] = useState(100);
  const [newInstructions, setNewInstructions] = useState("");

  const navigate = useNavigate();

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const handlePublishAssignment = (e) => {
    e.preventDefault();
    if (!newTitle) {
      alert("Please enter an assignment title.");
      return;
    }
    alert(`Assignment "${newTitle}" published for ${newSection}!`);
    setNewTitle("");
    setNewInstructions("");
  };

  const handleSaveGrade = ({ score, feedback }) => {
    if (!selectedSubmission) return;

    setSubmissions((prev) =>
      prev.map((item) =>
        item.id === selectedSubmission.id
          ? {
              ...item,
              rawScore: score,
              feedback,
              statusVariant: "on-track",
              statusLabel: "GRADED"
            }
          : item
      )
    );
    alert(`Grade saved for ${selectedSubmission.studentName}!`);
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
              width: "28px",
              height: "28px",
              borderRadius: "50%",
              backgroundColor: "rgba(38, 65, 94, 0.1)",
              color: "#26415E",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: "11px",
              fontWeight: 700
            }}
          >
            {row.avatarInitials}
          </div>
          <div>
            <span style={{ fontWeight: 600, color: "#1B2330", display: "block" }}>{row.studentName}</span>
            <span style={{ fontSize: "10px", color: "#5F6774" }}>{row.studentId}</span>
          </div>
        </div>
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
    { key: "submittedDate", label: "Date", sortable: true },
    {
      key: "rawScore",
      label: "Raw Score",
      sortable: true,
      render: (row) => <strong>{row.rawScore} / {row.maxScore}</strong>
    },
    {
      key: "actions",
      label: "Actions",
      sortable: false,
      render: (row) => (
        <div style={{ textAlign: "right" }}>
          <button
            onClick={() => setSelectedSubmission(row)}
            className="edu-btn-secondary"
            style={{ padding: "4px 10px", fontSize: "11px" }}
          >
            Grade
          </button>
        </div>
      )
    }
  ];

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="teacher"
        activeId="grading"
        logoText="EduIntel AI"
        roleText="Teacher Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "grading") navigate(`/teacher/${itemId}`);
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
                ACADEMIC MANAGEMENT
              </span>
              <h2
                className="edu-font-heading"
                style={{ fontSize: "24px", fontWeight: 600, color: "#1B2330", margin: "4px 0 0 0" }}
              >
                Assignments & Grading
              </h2>
              <p style={{ fontSize: "14px", color: "#5F6774", margin: "4px 0 0 0" }}>
                Publish new coursework, evaluate submissions, and record rubric feedback.
              </p>
            </div>
          </div>

          {/* 2-Column Section */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))",
              gap: "24px",
              alignItems: "start"
            }}
          >
            {/* Left Column: Create Assignment Form */}
            <div className="edu-card" style={{ padding: "24px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "16px", paddingBottom: "12px", borderBottom: "1px solid #E5E5E1" }}>
                <span className="material-symbols-outlined" style={{ color: "#26415E" }}>edit_note</span>
                <h3 className="edu-font-heading" style={{ margin: 0, fontSize: "16px", fontWeight: 600, color: "#1B2330", textTransform: "uppercase" }}>
                  Create Assignment
                </h3>
              </div>

              <form onSubmit={handlePublishAssignment} style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Assignment Title</label>
                  <input
                    type="text"
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                    placeholder="e.g. Mid-Term Analytical Essay"
                    style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "14px", outline: "none" }}
                  />
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                    <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Class Section</label>
                    <select
                      value={newSection}
                      onChange={(e) => setNewSection(e.target.value)}
                      style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "13px", outline: "none" }}
                    >
                      <option value="Grade 10-A">Grade 10-A</option>
                      <option value="Grade 10-B">Grade 10-B</option>
                      <option value="Grade 11-A">Grade 11-A</option>
                      <option value="Grade 11-B">Grade 11-B</option>
                      <option value="Grade 12-A">Grade 12-A</option>
                    </select>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                    <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Due Date</label>
                    <input
                      type="date"
                      value={newDueDate}
                      onChange={(e) => setNewDueDate(e.target.value)}
                      style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "13px", outline: "none" }}
                    />
                  </div>
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Max Score</label>
                  <input
                    type="number"
                    value={newMaxScore}
                    onChange={(e) => setNewMaxScore(e.target.value)}
                    style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "14px", outline: "none" }}
                  />
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Instructions</label>
                  <textarea
                    rows={4}
                    value={newInstructions}
                    onChange={(e) => setNewInstructions(e.target.value)}
                    placeholder="Define submission guidelines and objectives..."
                    style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "14px", outline: "none", resize: "vertical" }}
                  />
                </div>

                <button className="edu-btn-primary" type="submit" style={{ width: "100%", padding: "12px", display: "flex", alignItems: "center", justifyCenter: "center", gap: "6px" }}>
                  PUBLISH ASSIGNMENT
                  <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>send</span>
                </button>
              </form>
            </div>

            {/* Right Column: Submissions Table & Grading Input */}
            <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
              <DataTable
                title="Active Submissions Queue"
                columns={columns}
                data={submissions}
                pageSize={5}
              />

              {/* Grading Input Component */}
              {selectedSubmission && (
                <GradingInput
                  studentName={selectedSubmission.studentName}
                  studentInitials={selectedSubmission.avatarInitials}
                  assignmentTitle={selectedSubmission.assignmentTitle}
                  submissionNote={selectedSubmission.submissionNote}
                  maxScore={selectedSubmission.maxScore}
                  initialScore={selectedSubmission.rawScore}
                  initialFeedback={selectedSubmission.feedback}
                  attachmentName={selectedSubmission.attachmentName}
                  onSave={handleSaveGrade}
                  onDiscard={() => setSelectedSubmission(null)}
                />
              )}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
