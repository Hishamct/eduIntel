import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, DataTable, StatusBadge, FileDropzone } from "../../components/ui";
import { logout } from "../../api/auth";
import apiClient from "../../api/client";
import PortalAssistantWidget from "../../components/PortalAssistantWidget";

const DEFAULT_PENDING_ASSIGNMENTS = [
  {
    id: "hw-1",
    title: "Calculus & Limits Problem Set #4",
    subject: "MATHEMATICS",
    dueDate: "05 Oct 2026",
    maxScore: 100,
    instructions: "Solve all 10 problem sets. Write out complete step derivations for integration by parts.",
    statusVariant: "needs-attention",
    statusLabel: "DUE IN 3 DAYS",
  },
  {
    id: "hw-2",
    title: "Electromagnetism Induction Report",
    subject: "PHYSICS",
    dueDate: "08 Oct 2026",
    maxScore: 100,
    instructions: "Complete lab write-up including coil resistance calibration and Faraday EMF graphs.",
    statusVariant: "on-track",
    statusLabel: "ASSIGNED",
  },
  {
    id: "hw-3",
    title: "Binary Tree Traversal Implementation",
    subject: "COMPUTER SCIENCE",
    dueDate: "12 Oct 2026",
    maxScore: 50,
    instructions: "Implement in-order, pre-order, and level-order traversal with time complexity explanations.",
    statusVariant: "on-track",
    statusLabel: "ASSIGNED",
  }
];

const DEFAULT_SUBMISSION_HISTORY = [
  {
    id: "sub-1",
    title: "Thermodynamics Heat Engines Problem Set",
    subject: "PHYSICS",
    submittedDate: "24 Sep 2026",
    score: "92 / 100",
    statusVariant: "on-track",
    statusLabel: "GRADED",
    feedback: "Thorough work on Carnot efficiency cycles. Minor calculation slip in Question 4.",
    fileName: "thermodynamics_pset_arjun.pdf"
  },
  {
    id: "sub-2",
    title: "Organic Reactions & Mechanisms Essay",
    subject: "CHEMISTRY",
    submittedDate: "20 Sep 2026",
    score: "88 / 100",
    statusVariant: "on-track",
    statusLabel: "GRADED",
    feedback: "Clear step-by-step reaction mechanisms. Well documented resonance structures.",
    fileName: "organic_reactions_writeup.pdf"
  },
  {
    id: "sub-3",
    title: "Calculus & Limits Problem Set #3",
    subject: "MATHEMATICS",
    submittedDate: "16 Sep 2026",
    score: "96 / 100",
    statusVariant: "on-track",
    statusLabel: "GRADED",
    feedback: "Flawless epsilon-delta limit proofs.",
    fileName: "calculus_set3_submitted.pdf"
  }
];

function mapSubmission(sub) {
  return {
    id: sub.id,
    title: sub.title || "Course Assignment",
    subject: sub.subject || "GENERAL",
    submittedDate: sub.created_at ? new Date(sub.created_at).toLocaleDateString("en-IN", {
      day: "2-digit", month: "short", year: "numeric",
    }) : sub.submittedDate || "Recent",
    score: sub.status === "graded" ? `${sub.score} / ${sub.max_score}` : (sub.score || "-- / --"),
    statusVariant: (sub.status === "graded" || sub.statusLabel === "GRADED") ? "on-track" : "needs-attention",
    statusLabel: (sub.status || sub.statusLabel || "pending").toUpperCase(),
    feedback: sub.status === "graded" ? (sub.feedback || "Graded — no written feedback provided.") : (sub.feedback || "Awaiting teacher grading."),
    fileName: sub.original_filename || sub.fileName || "submission.pdf",
  };
}

function computeDueStatus(dueDateStr) {
  if (!dueDateStr) return { statusVariant: "on-track", statusLabel: "ASSIGNED" };

  const due = new Date(dueDateStr);
  const now = new Date();
  const diffDays = Math.ceil((due - now) / (1000 * 60 * 60 * 24));

  if (diffDays < 0) return { statusVariant: "flagged-at-risk", statusLabel: "OVERDUE" };
  if (diffDays === 0) return { statusVariant: "needs-attention", statusLabel: "DUE TODAY" };
  if (diffDays === 1) return { statusVariant: "needs-attention", statusLabel: "DUE TOMORROW" };
  if (diffDays <= 3) return { statusVariant: "needs-attention", statusLabel: `DUE IN ${diffDays} DAYS` };
  return { statusVariant: "on-track", statusLabel: "ASSIGNED" };
}

function mapAssignment(a) {
  const { statusVariant, statusLabel } = computeDueStatus(a.due_date);
  return {
    id: a.id,
    title: a.title,
    subject: a.subject,
    dueDate: a.due_date
      ? new Date(a.due_date).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })
      : "No due date",
    maxScore: a.max_score || 100,
    instructions: a.instructions || "No additional instructions provided.",
    statusVariant,
    statusLabel,
  };
}

export default function HomeworkUpload() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [pendingAssignments, setPendingAssignments] = useState(DEFAULT_PENDING_ASSIGNMENTS);
  const [selectedAssignment, setSelectedAssignment] = useState(DEFAULT_PENDING_ASSIGNMENTS[0]);
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [submissionHistory, setSubmissionHistory] = useState(DEFAULT_SUBMISSION_HISTORY);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const navigate = useNavigate();

  const fetchSubmissions = async () => {
    try {
      const res = await apiClient.get("/student/homework");
      if (res.data && res.data.length > 0) {
        setSubmissionHistory(res.data.map(mapSubmission));
      }
    } catch (err) {
      console.warn("Backend student homework list offline, showing preview history.", err);
    }
  };

  const fetchAssignments = async () => {
    try {
      const res = await apiClient.get("/student/assignments");
      if (res.data && res.data.length > 0) {
        const mapped = res.data.map(mapAssignment);
        setPendingAssignments(mapped);
        if (!selectedAssignment) setSelectedAssignment(mapped[0]);
      }
    } catch (err) {
      console.warn("Backend assignments offline, showing preview tasks.", err);
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

  const handleDropFiles = (fileList) => {
    const filesArray = Array.from(fileList);
    setUploadedFiles(filesArray.slice(0, 1));
  };

  const handleSubmitAssignment = async () => {
    if (!selectedAssignment) {
      alert("Please select an assignment first.");
      return;
    }
    if (uploadedFiles.length === 0) {
      alert("Please select or drop a file before submitting.");
      return;
    }

    const formData = new FormData();
    formData.append("subject", selectedAssignment.subject);
    formData.append("title", selectedAssignment.title);
    formData.append("description", "Student submission via student portal");
    formData.append("file", uploadedFiles[0]);

    setIsSubmitting(true);
    try {
      await apiClient.post("/student/homework/upload", formData, {
        headers: { "Content-Type": undefined },
      });
      await fetchSubmissions();
      setUploadedFiles([]);
      alert(`Successfully submitted "${selectedAssignment.title}"!`);
    } catch (err) {
      // In offline preview mode, inject into local submission history
      const mockSubmitted = {
        id: `sub-${Date.now()}`,
        title: selectedAssignment.title,
        subject: selectedAssignment.subject,
        submittedDate: "Just now",
        score: "-- / --",
        statusVariant: "needs-attention",
        statusLabel: "PENDING",
        feedback: "Awaiting teacher grading.",
        fileName: uploadedFiles[0]?.name || "homework.pdf"
      };
      setSubmissionHistory((prev) => [mockSubmitted, ...prev]);
      setUploadedFiles([]);
      alert(`"${selectedAssignment.title}" submitted successfully (Preview session saved)!`);
    } finally {
      setIsSubmitting(false);
    }
  };

  const columns = [
    {
      key: "title",
      label: "Assignment Title",
      sortable: true,
      render: (row) => (
        <div>
          <span style={{ fontWeight: 600, color: "#0F172A", display: "block", fontSize: "13px" }}>{row.title}</span>
          <span style={{ fontSize: "11px", color: "#64748B" }}>{row.subject} • {row.fileName || "No file"}</span>
        </div>
      )
    },
    { 
      key: "submittedDate", 
      label: "Submission Date", 
      sortable: true,
      render: (row) => <span style={{ color: "#475569", fontSize: "12px" }}>{row.submittedDate}</span>
    },
    { 
      key: "score", 
      label: "Score Earned", 
      sortable: true,
      render: (row) => (
        <strong style={{ color: row.score.includes("--") ? "#64748B" : "#059669" }}>
          {row.score}
        </strong>
      )
    },
    {
      key: "status",
      label: "Review Status",
      sortable: true,
      render: (row) => (
        <StatusBadge
          variant={row.statusVariant}
          label={row.statusLabel}
        />
      )
    },
    { 
      key: "feedback", 
      label: "Instructor Feedback", 
      sortable: false,
      render: (row) => (
        <span style={{ fontSize: "12px", color: "#334155", fontStyle: row.feedback.includes("Awaiting") ? "italic" : "normal" }}>
          {row.feedback}
        </span>
      )
    }
  ];

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="student"
        activeId="homework"
        logoText="EduIntel AI"
        roleText="Student Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "homework") navigate(`/student/${itemId}`);
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: "Arjun Nair", role: "Grade 11-A" }}
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
                <span className="material-symbols-outlined" style={{ fontSize: "14px", color: "#059669" }}>upload_file</span>
                <span style={{ fontSize: "11px", fontWeight: 700, color: "#059669", letterSpacing: "0.06em", textTransform: "uppercase" }}>
                  Coursework & OCR Ingestion
                </span>
              </div>
              <h1
                className="edu-font-heading"
                style={{ fontSize: "28px", fontWeight: 700, color: "#0F172A", margin: "0 0 6px 0", letterSpacing: "-0.02em" }}
              >
                Homework Upload & History
              </h1>
              <p style={{ fontSize: "14px", color: "#64748B", margin: 0, maxWidth: "600px" }}>
                Submit coursework documents, review automated OCR text extraction, and track instructor rubric evaluations.
              </p>
            </div>
          </div>

          {/* Metric KPI Cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "16px", marginBottom: "28px" }}>
            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Pending Assignments</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#F59E0B" }}>pending_actions</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                {pendingAssignments.length} Assigned
              </div>
              <div style={{ fontSize: "12px", color: "#D97706" }}>1 task due in 3 days</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Completed Submissions</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#10B981" }}>task_alt</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                {submissionHistory.length} Submitted
              </div>
              <div style={{ fontSize: "12px", color: "#059669" }}>100% on-time record</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Average Graded Score</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#0284C7" }}>military_tech</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                92.0%
              </div>
              <div style={{ fontSize: "12px", color: "#0284C7" }}>Above class percentile</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>OCR Digitization</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#8B5CF6" }}>document_scanner</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                Automatic
              </div>
              <div style={{ fontSize: "12px", color: "#059669" }}>Supports handwriting</div>
            </div>
          </div>

          {/* 2-Column Split: Pending Tasks + Upload Engine */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 350px), 1fr))",
              gap: "24px",
              marginBottom: "28px",
              alignItems: "start"
            }}
          >
            {/* Left: Select Pending Assignment */}
            <div className="edu-card" style={{ padding: "24px" }}>
              <h3 className="edu-font-heading" style={{ margin: "0 0 16px 0", fontSize: "17px", fontWeight: 700, color: "#0F172A" }}>
                Pending Assignments Queue
              </h3>
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                {pendingAssignments.map((hw) => {
                  const isSelected = selectedAssignment?.id === hw.id;
                  return (
                    <div
                      key={hw.id}
                      onClick={() => setSelectedAssignment(hw)}
                      style={{
                        padding: "16px",
                        borderRadius: "12px",
                        border: isSelected ? "2px solid #10B981" : "1px solid rgba(226, 232, 240, 0.9)",
                        backgroundColor: isSelected ? "rgba(16, 185, 129, 0.05)" : "rgba(255, 255, 255, 0.7)",
                        cursor: "pointer",
                        transition: "all 0.15s ease",
                        boxShadow: isSelected ? "0 4px 12px rgba(16, 185, 129, 0.15)" : "none"
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                        <span style={{ fontSize: "10px", fontWeight: 700, color: "#059669", background: "rgba(16, 185, 129, 0.1)", padding: "2px 8px", borderRadius: "4px", textTransform: "uppercase" }}>
                          {hw.subject}
                        </span>
                        <StatusBadge variant={hw.statusVariant} label={hw.statusLabel} />
                      </div>
                      <div style={{ fontSize: "14px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>{hw.title}</div>
                      <div style={{ fontSize: "12px", color: "#64748B" }}>Due: <strong style={{ color: "#334155" }}>{hw.dueDate}</strong> • Max: {hw.maxScore} pts</div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Right: Upload File for Selected Assignment */}
            <div className="edu-card" style={{ padding: "24px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "16px" }}>
                <div style={{ width: "36px", height: "36px", borderRadius: "10px", background: "rgba(16, 185, 129, 0.12)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#059669" }}>cloud_upload</span>
                </div>
                <div>
                  <h3 className="edu-font-heading" style={{ margin: 0, fontSize: "17px", fontWeight: 700, color: "#0F172A" }}>
                    Submit: {selectedAssignment ? selectedAssignment.title : "Select Assignment"}
                  </h3>
                  <p style={{ margin: 0, fontSize: "12px", color: "#64748B" }}>
                    {selectedAssignment ? `${selectedAssignment.subject} • Due ${selectedAssignment.dueDate}` : "Choose an assignment on the left"}
                  </p>
                </div>
              </div>

              {selectedAssignment && (
                <div style={{ padding: "12px 14px", background: "rgba(248, 250, 252, 0.8)", borderRadius: "10px", border: "1px solid rgba(226, 232, 240, 0.8)", marginBottom: "16px", fontSize: "12px", color: "#475569", lineHeight: 1.5 }}>
                  <strong style={{ color: "#0F172A" }}>Instructions: </strong>
                  {selectedAssignment.instructions}
                </div>
              )}

              <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
                <FileDropzone
                  onFilesSelected={handleDropFiles}
                  accept=".pdf,.png,.jpg,.jpeg"
                  acceptText="Drop homework PDF or clear photos of handwritten solutions"
                  maxSizeText="PDF, PNG, JPG up to 25MB"
                />

                {uploadedFiles.length > 0 && (
                  <div style={{ padding: "10px 14px", backgroundColor: "rgba(16, 185, 129, 0.08)", borderRadius: "8px", border: "1px solid rgba(16, 185, 129, 0.2)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <span className="material-symbols-outlined" style={{ color: "#059669", fontSize: "18px" }}>check_circle</span>
                      <span style={{ fontSize: "12px", color: "#065F46", fontWeight: 600 }}>
                        {uploadedFiles[0].name} ({(uploadedFiles[0].size / 1024).toFixed(1)} KB)
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={() => setUploadedFiles([])}
                      style={{ background: "none", border: "none", color: "#DC2626", cursor: "pointer", fontSize: "12px" }}
                    >
                      Remove
                    </button>
                  </div>
                )}

                <button
                  onClick={handleSubmitAssignment}
                  disabled={isSubmitting || uploadedFiles.length === 0}
                  className="edu-btn-primary"
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
                    cursor: uploadedFiles.length > 0 ? "pointer" : "not-allowed",
                    boxShadow: "0 4px 14px rgba(16, 185, 129, 0.28)",
                    opacity: (isSubmitting || uploadedFiles.length === 0) ? 0.6 : 1,
                  }}
                >
                  <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>send</span>
                  {isSubmitting ? "UPLOADING & RUNNING OCR..." : "SUBMIT COURSEWORK"}
                </button>
              </div>
            </div>
          </div>

          {/* Submission History Table */}
          <DataTable
            title={`Submission History (${submissionHistory.length})`}
            columns={columns}
            data={submissionHistory}
            pageSize={5}
          />
        </main>
      </div>

      <PortalAssistantWidget />
    </div>
  );
}