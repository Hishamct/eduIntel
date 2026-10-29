import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, DataTable, StatusBadge, GradingInput } from "../../components/ui";
import { logout } from "../../api/auth";
import apiClient from "../../api/client";

function initialsFromEmail(email) {
  if (!email) return "ST";
  const namePart = email.split("@")[0];
  return namePart.slice(0, 2).toUpperCase();
}

const DEFAULT_SUBMISSIONS = [
  {
    id: "sub-101",
    studentName: "aarav.sharma@eduintel.ac.in",
    studentId: "STU-2026-001",
    avatarInitials: "AS",
    assignmentTitle: "Calculus & Limits Problem Set #4",
    subject: "MATHEMATICS",
    submissionNote: "Completed all 10 problems, step-by-step proofs included.",
    submittedDate: "27 Sep 2026",
    maxScore: 100,
    rawScore: "",
    feedback: "",
    attachmentName: "calculus_set4_asharma.pdf",
    statusVariant: "needs-attention",
    statusLabel: "PENDING",
    extractedText: "Problem 1: Evaluate limit as x -> 0 of sin(3x)/x. Applying L'Hopital's rule: d/dx[sin(3x)] / d/dx[x] = 3*cos(3x)/1. As x -> 0, 3*cos(0) = 3. Problem 2: Continuous function proof over closed interval [a, b] satisfies intermediate value theorem...",
    ocrConfidence: 0.96,
  },
  {
    id: "sub-102",
    studentName: "diya.patel@eduintel.ac.in",
    studentId: "STU-2026-002",
    avatarInitials: "DP",
    assignmentTitle: "Electromagnetism Induction Report",
    subject: "PHYSICS",
    submissionNote: "Lab experiment 4 observations and Faraday's law calculations.",
    submittedDate: "27 Sep 2026",
    maxScore: 100,
    rawScore: 94,
    feedback: "Exceptional error analysis and clear diagrams of flux density.",
    attachmentName: "faraday_induction_lab.pdf",
    statusVariant: "on-track",
    statusLabel: "GRADED",
    extractedText: "Faraday's Law of Electromagnetic Induction: EMF = -d(Phi)/dt. Measured coil resistance: 4.2 Ohms. Peak induced voltage observed: 1.24 V at frequency f = 50 Hz.",
    ocrConfidence: 0.98,
  },
  {
    id: "sub-103",
    studentName: "rohan.varma@eduintel.ac.in",
    studentId: "STU-2026-003",
    avatarInitials: "RV",
    assignmentTitle: "Data Structures Binary Tree Traversal",
    subject: "COMPUTER SCIENCE",
    submissionNote: "C++ implementation of AVL balance rotations.",
    submittedDate: "26 Sep 2026",
    maxScore: 50,
    rawScore: "",
    feedback: "",
    attachmentName: "avl_tree_impl.cpp",
    statusVariant: "needs-attention",
    statusLabel: "PENDING",
    extractedText: "Node* rightRotate(Node* y) { Node* x = y->left; Node* T2 = x->right; x->right = y; y->left = T2; y->height = max(height(y->left), height(y->right)) + 1; return x; }",
    ocrConfidence: 0.99,
  }
];

function mapSubmission(sub) {
  return {
    id: sub.id,
    studentName: sub.student_email || sub.studentName,
    studentId: sub.student_id || sub.studentId,
    avatarInitials: initialsFromEmail(sub.student_email || sub.studentName),
    assignmentTitle: sub.title || sub.assignmentTitle,
    subject: sub.subject || "GENERAL",
    submissionNote: sub.description || sub.submissionNote || "No additional notes",
    submittedDate: sub.created_at ? new Date(sub.created_at).toLocaleDateString("en-IN", {
      day: "2-digit", month: "short", year: "numeric",
    }) : sub.submittedDate || "Recent",
    maxScore: sub.max_score ?? sub.maxScore ?? 100,
    rawScore: sub.score ?? sub.rawScore ?? "",
    feedback: sub.feedback || "",
    attachmentName: sub.original_filename || sub.attachmentName || "submission.pdf",
    statusVariant: (sub.status === "graded" || sub.statusLabel === "GRADED") ? "on-track" : "needs-attention",
    statusLabel: (sub.status || sub.statusLabel || "pending").toUpperCase(),
    extractedText: sub.extracted_text || sub.extractedText || null,
    ocrConfidence: sub.ocr_confidence ?? sub.ocrConfidence ?? null,
  };
}

export default function AssignmentsGrading() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [submissions, setSubmissions] = useState(DEFAULT_SUBMISSIONS);
  const [selectedSubmission, setSelectedSubmission] = useState(DEFAULT_SUBMISSIONS[0]);
  const [newTitle, setNewTitle] = useState("");
  const [newSubject, setNewSubject] = useState("MATHEMATICS");
  const [newSection, setNewSection] = useState("Grade 12-A");
  const [newDueDate, setNewDueDate] = useState("");
  const [newMaxScore, setNewMaxScore] = useState(100);
  const [newInstructions, setNewInstructions] = useState("");
  const [publishedAssignments, setPublishedAssignments] = useState([
    { id: "a1", title: "Calculus & Limits Problem Set #4", subject: "MATHEMATICS", class_section: "Grade 12-A", due_date: "2026-10-05" },
    { id: "a2", title: "Electromagnetism Induction Report", subject: "PHYSICS", class_section: "Grade 11-A", due_date: "2026-10-08" },
  ]);

  const navigate = useNavigate();

  const fetchSubmissions = async () => {
    try {
      const res = await apiClient.get("/teacher/homework");
      if (res.data && res.data.length > 0) {
        const mapped = res.data.map(mapSubmission);
        setSubmissions(mapped);
        if (!selectedSubmission) {
          setSelectedSubmission(mapped[0]);
        }
      }
    } catch (err) {
      console.warn("Backend submissions endpoint offline, showing demo queue.", err);
    }
  };

  const fetchAssignments = async () => {
    try {
      const res = await apiClient.get("/teacher/assignments");
      if (res.data && res.data.length > 0) {
        setPublishedAssignments(res.data);
      }
    } catch (err) {
      console.warn("Backend assignments endpoint offline, showing preview list.", err);
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
    } catch (err) {
      // In offline preview mode, append locally
      const mockAssignment = {
        id: `a-${Date.now()}`,
        title: newTitle,
        subject: newSubject,
        class_section: newSection,
        due_date: newDueDate,
      };
      setPublishedAssignments((prev) => [mockAssignment, ...prev]);
      alert(`Assignment "${newTitle}" published for ${newSection} (Preview)!`);
    } finally {
      setNewTitle("");
      setNewInstructions("");
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
      // Save locally in state
      setSubmissions((prev) =>
        prev.map((s) =>
          s.id === selectedSubmission.id
            ? { ...s, rawScore: Number(score), feedback, statusVariant: "on-track", statusLabel: "GRADED" }
            : s
        )
      );
      setSelectedSubmission((prev) =>
        prev ? { ...prev, rawScore: Number(score), feedback, statusVariant: "on-track", statusLabel: "GRADED" } : null
      );
      alert(`Grade saved for ${selectedSubmission.studentName} (Session saved)!`);
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
      alert("Simulated preview: Original submission PDF opened.");
    }
  };

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
              fontSize: "12px",
              fontWeight: 700,
              border: "1px solid rgba(16, 185, 129, 0.3)"
            }}
          >
            {row.avatarInitials}
          </div>
          <div>
            <span style={{ fontWeight: 600, color: "#0F172A", display: "block", fontSize: "13px" }}>{row.studentName}</span>
            <span style={{ fontSize: "11px", color: "#64748B" }}>{row.assignmentTitle} • {row.subject}</span>
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
    { 
      key: "submittedDate", 
      label: "Submitted", 
      sortable: true,
      render: (row) => <span style={{ color: "#475569", fontSize: "12px" }}>{row.submittedDate}</span>
    },
    {
      key: "rawScore",
      label: "Evaluation",
      sortable: true,
      render: (row) => (
        <strong style={{ color: row.rawScore !== "" ? "#059669" : "#64748B" }}>
          {row.rawScore === "" ? "Ungraded" : `${row.rawScore} / ${row.maxScore}`}
        </strong>
      )
    },
    {
      key: "actions",
      label: "Action",
      sortable: false,
      render: (row) => (
        <button
          onClick={() => setSelectedSubmission(row)}
          style={{
            padding: "5px 12px",
            borderRadius: "8px",
            fontSize: "12px",
            fontWeight: 600,
            background: selectedSubmission?.id === row.id ? "#10B981" : "rgba(241, 245, 249, 0.9)",
            color: selectedSubmission?.id === row.id ? "#FFFFFF" : "#1E293B",
            border: "none",
            cursor: "pointer",
            transition: "all 0.15s ease",
            boxShadow: selectedSubmission?.id === row.id ? "0 2px 8px rgba(16, 185, 129, 0.25)" : "none"
          }}
        >
          {selectedSubmission?.id === row.id ? "Inspecting" : "Evaluate"}
        </button>
      )
    }
  ];

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="teacher"
        activeId="grading"
        logoText="EduIntel AI"
        roleText="Faculty Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "grading") navigate(`/teacher/${itemId}`);
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: "Dr. Sarah Jenkins", role: "Faculty Head" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content">
          {/* Header */}
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
                <span className="material-symbols-outlined" style={{ fontSize: "14px", color: "#059669" }}>assignment_turned_in</span>
                <span style={{ fontSize: "11px", fontWeight: 700, color: "#059669", letterSpacing: "0.06em", textTransform: "uppercase" }}>
                  Academic Evaluation
                </span>
              </div>
              <h1
                className="edu-font-heading"
                style={{ fontSize: "28px", fontWeight: 700, color: "#0F172A", margin: "0 0 6px 0", letterSpacing: "-0.02em" }}
              >
                Assignments & Grading Workbench
              </h1>
              <p style={{ fontSize: "14px", color: "#64748B", margin: 0, maxWidth: "600px" }}>
                Publish course tasks, review student OCR transcriptions, and evaluate rubric scores with automated feedback.
              </p>
            </div>

            <div style={{ display: "flex", gap: "10px" }}>
              <button 
                onClick={() => alert("Grading batch exported to administrative records.")}
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
                Export Gradebook
              </button>
            </div>
          </div>

          {/* KPI Summary Cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "16px", marginBottom: "28px" }}>
            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Submissions in Queue</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#F59E0B" }}>hourglass_top</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                {submissions.filter(s => s.statusLabel === "PENDING").length} Pending
              </div>
              <div style={{ fontSize: "12px", color: "#D97706" }}>Awaiting grading</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Evaluated Submissions</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#10B981" }}>task_alt</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                {submissions.filter(s => s.statusLabel === "GRADED").length} Graded
              </div>
              <div style={{ fontSize: "12px", color: "#059669" }}>Feedback delivered</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Active Assignments</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#0284C7" }}>assignment</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                {publishedAssignments.length} Live Tasks
              </div>
              <div style={{ fontSize: "12px", color: "#0284C7" }}>Published across classes</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>OCR Engine Quality</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#8B5CF6" }}>document_scanner</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                97.6%
              </div>
              <div style={{ fontSize: "12px", color: "#059669" }}>Handwriting recognition</div>
            </div>
          </div>

          {/* Main 2-Column Split */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 350px), 1fr))",
              gap: "24px",
              alignItems: "start"
            }}
          >
            {/* Left: Create Assignment Form */}
            <div className="edu-card" style={{ padding: "26px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "20px" }}>
                <div style={{ width: "36px", height: "36px", borderRadius: "10px", background: "rgba(16, 185, 129, 0.12)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#059669" }}>post_add</span>
                </div>
                <div>
                  <h3 className="edu-font-heading" style={{ margin: 0, fontSize: "17px", fontWeight: 700, color: "#0F172A" }}>
                    Publish Assignment
                  </h3>
                  <p style={{ margin: 0, fontSize: "12px", color: "#64748B" }}>Create coursework for student submission</p>
                </div>
              </div>

              <form onSubmit={handlePublishAssignment} style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                <div>
                  <label style={{ display: "block", fontSize: "11px", fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "6px" }}>
                    Assignment Title
                  </label>
                  <input
                    type="text"
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                    placeholder="e.g. Mid-Term Analytical Calculus Essay"
                    style={{
                      width: "100%",
                      padding: "11px 14px",
                      borderRadius: "10px",
                      border: "1px solid rgba(226, 232, 240, 0.9)",
                      backgroundColor: "rgba(255, 255, 255, 0.9)",
                      fontSize: "13px",
                      color: "#1E293B",
                      outline: "none",
                      boxSizing: "border-box"
                    }}
                  />
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                  <div>
                    <label style={{ display: "block", fontSize: "11px", fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "6px" }}>
                      Subject
                    </label>
                    <select
                      value={newSubject}
                      onChange={(e) => setNewSubject(e.target.value)}
                      style={{
                        width: "100%",
                        padding: "11px 14px",
                        borderRadius: "10px",
                        border: "1px solid rgba(226, 232, 240, 0.9)",
                        backgroundColor: "rgba(255, 255, 255, 0.9)",
                        fontSize: "13px",
                        color: "#1E293B",
                        outline: "none"
                      }}
                    >
                      <option value="MATHEMATICS">MATHEMATICS</option>
                      <option value="PHYSICS">PHYSICS</option>
                      <option value="CHEMISTRY">CHEMISTRY</option>
                      <option value="COMPUTER SCIENCE">COMPUTER SCIENCE</option>
                    </select>
                  </div>

                  <div>
                    <label style={{ display: "block", fontSize: "11px", fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "6px" }}>
                      Class Cohort
                    </label>
                    <select
                      value={newSection}
                      onChange={(e) => setNewSection(e.target.value)}
                      style={{
                        width: "100%",
                        padding: "11px 14px",
                        borderRadius: "10px",
                        border: "1px solid rgba(226, 232, 240, 0.9)",
                        backgroundColor: "rgba(255, 255, 255, 0.9)",
                        fontSize: "13px",
                        color: "#1E293B",
                        outline: "none"
                      }}
                    >
                      <option value="Grade 10-A">Grade 10-A</option>
                      <option value="Grade 10-B">Grade 10-B</option>
                      <option value="Grade 11-A">Grade 11-A</option>
                      <option value="Grade 11-B">Grade 11-B</option>
                      <option value="Grade 12-A">Grade 12-A</option>
                    </select>
                  </div>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: "12px" }}>
                  <div>
                    <label style={{ display: "block", fontSize: "11px", fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "6px" }}>
                      Due Date
                    </label>
                    <input
                      type="date"
                      value={newDueDate}
                      onChange={(e) => setNewDueDate(e.target.value)}
                      style={{
                        width: "100%",
                        padding: "11px 14px",
                        borderRadius: "10px",
                        border: "1px solid rgba(226, 232, 240, 0.9)",
                        backgroundColor: "rgba(255, 255, 255, 0.9)",
                        fontSize: "13px",
                        color: "#1E293B",
                        outline: "none",
                        boxSizing: "border-box"
                      }}
                    />
                  </div>
                  <div>
                    <label style={{ display: "block", fontSize: "11px", fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "6px" }}>
                      Max Score
                    </label>
                    <input
                      type="number"
                      value={newMaxScore}
                      onChange={(e) => setNewMaxScore(e.target.value)}
                      style={{
                        width: "100%",
                        padding: "11px 14px",
                        borderRadius: "10px",
                        border: "1px solid rgba(226, 232, 240, 0.9)",
                        backgroundColor: "rgba(255, 255, 255, 0.9)",
                        fontSize: "13px",
                        color: "#1E293B",
                        outline: "none",
                        boxSizing: "border-box"
                      }}
                    />
                  </div>
                </div>

                <div>
                  <label style={{ display: "block", fontSize: "11px", fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "6px" }}>
                    Guidelines & Rubric Instructions
                  </label>
                  <textarea
                    rows={4}
                    value={newInstructions}
                    onChange={(e) => setNewInstructions(e.target.value)}
                    placeholder="Specify problem numbers, proof structure, or formatting requirements..."
                    style={{
                      width: "100%",
                      padding: "11px 14px",
                      borderRadius: "10px",
                      border: "1px solid rgba(226, 232, 240, 0.9)",
                      backgroundColor: "rgba(255, 255, 255, 0.9)",
                      fontSize: "13px",
                      color: "#1E293B",
                      outline: "none",
                      resize: "vertical",
                      boxSizing: "border-box"
                    }}
                  />
                </div>

                <button
                  className="edu-btn-primary"
                  type="submit"
                  style={{
                    width: "100%",
                    padding: "13px",
                    borderRadius: "10px",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: "8px",
                    fontSize: "13px",
                    fontWeight: 700,
                    cursor: "pointer",
                    boxShadow: "0 4px 14px rgba(16, 185, 129, 0.28)",
                    marginTop: "6px"
                  }}
                >
                  <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>send</span>
                  PUBLISH ASSIGNMENT
                </button>
              </form>

              {publishedAssignments.length > 0 && (
                <div style={{ marginTop: "24px", paddingTop: "18px", borderTop: "1px solid rgba(226, 232, 240, 0.8)" }}>
                  <p style={{ fontSize: "11px", fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: "0.05em", margin: "0 0 12px 0" }}>
                    Active Published Tasks ({publishedAssignments.length})
                  </p>
                  <div style={{ display: "flex", flexDirection: "column", gap: "8px", maxHeight: "190px", overflowY: "auto" }}>
                    {publishedAssignments.map((a) => (
                      <div key={a.id} style={{ fontSize: "12px", color: "#1E293B", padding: "10px 12px", backgroundColor: "rgba(248, 250, 252, 0.8)", borderRadius: "8px", border: "1px solid rgba(226, 232, 240, 0.7)" }}>
                        <div style={{ fontWeight: 600 }}>{a.title}</div>
                        <div style={{ fontSize: "11px", color: "#64748B", marginTop: "2px" }}>
                          {a.subject} • {a.class_section} {a.due_date ? `• Due ${a.due_date}` : ""}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Right: Submissions Table + Evaluation Drawer */}
            <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
              <DataTable
                title={`Active Submissions Queue (${submissions.length})`}
                columns={columns}
                data={submissions}
                pageSize={5}
              />

              {selectedSubmission && (
                <>
                  {selectedSubmission.extractedText && (
                    <div className="edu-card" style={{ padding: "22px" }}>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "12px" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          <span className="material-symbols-outlined" style={{ color: "#059669", fontSize: "20px" }}>
                            document_scanner
                          </span>
                          <h4 style={{ margin: 0, fontSize: "14px", fontWeight: 700, color: "#0F172A", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                            Extracted Text (OCR Telemetry)
                          </h4>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                          {selectedSubmission.ocrConfidence !== null && (
                            <span style={{
                              fontSize: "11px",
                              fontWeight: 700,
                              color: "#059669",
                              background: "rgba(16, 185, 129, 0.1)",
                              padding: "3px 8px",
                              borderRadius: "6px"
                            }}>
                              OCR Confidence: {Math.round(selectedSubmission.ocrConfidence * 100)}%
                            </span>
                          )}
                          <button
                            onClick={() => handleViewOriginalFile(selectedSubmission)}
                            style={{
                              padding: "4px 10px",
                              borderRadius: "6px",
                              fontSize: "11px",
                              fontWeight: 600,
                              background: "rgba(241, 245, 249, 0.9)",
                              border: "1px solid rgba(226, 232, 240, 0.9)",
                              color: "#334155",
                              cursor: "pointer"
                            }}
                          >
                            View Original File
                          </button>
                        </div>
                      </div>
                      <div style={{
                        fontSize: "13px",
                        color: "#334155",
                        whiteSpace: "pre-wrap",
                        maxHeight: "160px",
                        overflowY: "auto",
                        lineHeight: 1.6,
                        padding: "12px 14px",
                        background: "rgba(248, 250, 252, 0.7)",
                        borderRadius: "10px",
                        border: "1px solid rgba(226, 232, 240, 0.8)",
                        fontFamily: "monospace"
                      }}>
                        {selectedSubmission.extractedText}
                      </div>
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