import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, DataTable, StatusBadge, GradingInput } from "../../components/ui";
import { logout } from "../../api/auth";
import apiClient from "../../api/client";

function initialsFromEmail(email) {
  const namePart = email.split("@")[0];
  return namePart.slice(0, 2).toUpperCase();
}

function mapSubmission(sub) {
  return {
    id: sub.id,
    studentName: sub.student_email,
    studentId: sub.student_id,
    avatarInitials: initialsFromEmail(sub.student_email),
    assignmentTitle: sub.title,
    subject: sub.subject,
    submissionNote: sub.description || "No additional notes",
    submittedDate: new Date(sub.created_at).toLocaleDateString("en-IN", {
      day: "2-digit", month: "short", year: "numeric",
    }),
    maxScore: sub.max_score ?? 100,
    rawScore: sub.score ?? "",
    feedback: sub.feedback || "",
    attachmentName: sub.original_filename,
    statusVariant: sub.status === "graded" ? "on-track" : "needs-attention",
    statusLabel: sub.status.toUpperCase(),
    extractedText: sub.extracted_text || null,
    ocrConfidence: sub.ocr_confidence ?? null,
  };
}

export default function AssignmentsGrading() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [submissions, setSubmissions] = useState([]);
  const [selectedSubmission, setSelectedSubmission] = useState(null);
  const [newTitle, setNewTitle] = useState("");
  const [newSubject, setNewSubject] = useState("MATHEMATICS");
  const [newSection, setNewSection] = useState("Grade 12-A");
  const [newDueDate, setNewDueDate] = useState("");
  const [newMaxScore, setNewMaxScore] = useState(100);
  const [newInstructions, setNewInstructions] = useState("");
  const [publishedAssignments, setPublishedAssignments] = useState([]);

  const navigate = useNavigate();

  const fetchSubmissions = async () => {
    try {
      const res = await apiClient.get("/teacher/homework");
      const mapped = res.data.map(mapSubmission);
      setSubmissions(mapped);
      if (mapped.length > 0 && !selectedSubmission) {
        setSelectedSubmission(mapped[0]);
      }
    } catch (err) {
      console.error("Failed to load submissions:", err);
    }
  };

  const fetchAssignments = async () => {
    try {
      const res = await apiClient.get("/teacher/assignments");
      setPublishedAssignments(res.data);
    } catch (err) {
      console.error("Failed to load assignments:", err);
    }
  };

  useEffect(() => {
    fetchSubmissions();
    fetchAssignments();
  }, []);

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const handlePublishAssignment = async (e) => {
    e.preventDefault();
    if (!newTitle) {
      alert("Please enter an assignment title.");
      return;
    }

    try {
      await apiClient.post("/teacher/assignments", {
        title: newTitle,
        subject: newSubject,
        class_section: newSection,
        due_date: newDueDate || null,
        max_score: Number(newMaxScore),
        instructions: newInstructions || null,
      });
      await fetchAssignments();
      alert(`Assignment "${newTitle}" published for ${newSection}!`);
      setNewTitle("");
      setNewInstructions("");
    } catch (err) {
      console.error("Failed to publish assignment:", err);
      alert("Failed to publish assignment. Please try again.");
    }
  };

  const handleSaveGrade = async ({ score, feedback }) => {
    if (!selectedSubmission) return;

    try {
      await apiClient.patch(`/teacher/homework/${selectedSubmission.id}/grade`, {
        score: Number(score),
        max_score: selectedSubmission.maxScore,
        feedback,
      });
      await fetchSubmissions();
      alert(`Grade saved for ${selectedSubmission.studentName}!`);
    } catch (err) {
      console.error("Failed to save grade:", err);
      alert("Failed to save grade. Please try again.");
    }
  };

  const handleViewOriginalFile = async (submission) => {
    try {
      const res = await apiClient.get(
        `/teacher/homework/${submission.id}/file`,
        { responseType: "blob" }
      );
      const contentType = res.headers["content-type"] || "application/octet-stream";
      const blobUrl = window.URL.createObjectURL(new Blob([res.data], { type: contentType }));
      window.open(blobUrl, "_blank");
      setTimeout(() => window.URL.revokeObjectURL(blobUrl), 10000);
    } catch (err) {
      console.error("Failed to load original file:", err);
      alert("Could not load the original file.");
    }
  };

  const columns = [
    {
      key: "studentName",
      label: "Student Email",
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
            <span style={{ fontSize: "10px", color: "#5F6774" }}>{row.assignmentTitle} • {row.subject}</span>
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
      render: (row) => <strong>{row.rawScore === "" ? "--" : row.rawScore} / {row.maxScore}</strong>
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

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))",
              gap: "24px",
              alignItems: "start"
            }}
          >
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
                    style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "14px", outline: "none", color: "#1B2330" }}
                  />
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Subject</label>
                  <select
                    value={newSubject}
                    onChange={(e) => setNewSubject(e.target.value)}
                    style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "13px", outline: "none", color: "#1B2330" }}
                  >
                    <option value="MATHEMATICS">MATHEMATICS</option>
                    <option value="PHYSICS">PHYSICS</option>
                    <option value="CHEMISTRY">CHEMISTRY</option>
                    <option value="COMPUTER SCIENCE">COMPUTER SCIENCE</option>
                  </select>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                    <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Class Section</label>
                    <select
                      value={newSection}
                      onChange={(e) => setNewSection(e.target.value)}
                      style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "13px", outline: "none", color: "#1B2330" }}
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
                      style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "13px", outline: "none", color: "#1B2330" }}
                    />
                  </div>
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Max Score</label>
                  <input
                    type="number"
                    value={newMaxScore}
                    onChange={(e) => setNewMaxScore(e.target.value)}
                    style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "14px", outline: "none", color: "#1B2330" }}
                  />
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Instructions</label>
                  <textarea
                    rows={4}
                    value={newInstructions}
                    onChange={(e) => setNewInstructions(e.target.value)}
                    placeholder="Define submission guidelines and objectives..."
                    style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "14px", outline: "none", resize: "vertical", color: "#1B2330" }}
                  />
                </div>

                <button className="edu-btn-primary" type="submit" style={{ width: "100%", padding: "12px", display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}>
                  PUBLISH ASSIGNMENT
                  <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>send</span>
                </button>
              </form>

              {publishedAssignments.length > 0 && (
                <div style={{ marginTop: "20px", paddingTop: "16px", borderTop: "1px solid #E5E5E1" }}>
                  <p style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase", margin: "0 0 10px 0" }}>
                    Published Assignments
                  </p>
                  <div style={{ display: "flex", flexDirection: "column", gap: "8px", maxHeight: "180px", overflowY: "auto" }}>
                    {publishedAssignments.map((a) => (
                      <div key={a.id} style={{ fontSize: "12px", color: "#1B2330", padding: "8px 10px", backgroundColor: "#F4F4F1", borderRadius: "4px" }}>
                        <strong>{a.title}</strong> — {a.subject} • {a.class_section}
                        {a.due_date && <span style={{ color: "#5F6774" }}> • Due {a.due_date}</span>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
              <DataTable
                title="Active Submissions Queue"
                columns={columns}
                data={submissions}
                pageSize={5}
              />

              {selectedSubmission && (
                <>
                  {selectedSubmission.extractedText && (
                    <div className="edu-card" style={{ padding: "20px" }}>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "10px" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          <span className="material-symbols-outlined" style={{ color: "#26415E", fontSize: "18px" }}>
                            document_scanner
                          </span>
                          <h4 style={{ margin: 0, fontSize: "13px", fontWeight: 700, color: "#1B2330", textTransform: "uppercase" }}>
                            Extracted Text (OCR)
                          </h4>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                          {selectedSubmission.ocrConfidence !== null && (
                            <span style={{ fontSize: "11px", color: "#5F6774" }}>
                              Confidence: {Math.round(selectedSubmission.ocrConfidence * 100)}%
                            </span>
                          )}
                          <button
                            onClick={() => handleViewOriginalFile(selectedSubmission)}
                            className="edu-btn-secondary"
                            style={{ padding: "3px 8px", fontSize: "11px" }}
                          >
                            View Original
                          </button>
                        </div>
                      </div>
                      <p style={{
                        fontSize: "13px",
                        color: "#1B2330",
                        whiteSpace: "pre-wrap",
                        maxHeight: "160px",
                        overflowY: "auto",
                        margin: 0,
                        lineHeight: 1.5
                      }}>
                        {selectedSubmission.extractedText}
                      </p>
                    </div>
                  )}

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
                </>
              )}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}