import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, DataTable, StatusBadge, FileDropzone } from "../../components/ui";
import { logout } from "../../api/auth";
import apiClient from "../../api/client";
import PortalAssistantWidget from "../../components/PortalAssistantWidget";

function mapSubmission(sub) {
  return {
    id: sub.id,
    title: sub.title,
    subject: sub.subject,
    submittedDate: new Date(sub.created_at).toLocaleDateString("en-IN", {
      day: "2-digit", month: "short", year: "numeric",
    }),
    score: sub.status === "graded" ? `${sub.score} / ${sub.max_score}` : "-- / --",
    statusVariant: sub.status === "graded" ? "on-track" : "needs-attention",
    statusLabel: sub.status.toUpperCase(),
    feedback: sub.status === "graded" ? (sub.feedback || "Graded — no written feedback provided.") : "Awaiting teacher grading.",
    fileName: sub.original_filename,
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
    maxScore: a.max_score,
    instructions: a.instructions || "No additional instructions provided.",
    statusVariant,
    statusLabel,
  };
}

export default function HomeworkUpload() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [pendingAssignments, setPendingAssignments] = useState([]);
  const [selectedAssignment, setSelectedAssignment] = useState(null);
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [submissionHistory, setSubmissionHistory] = useState([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const navigate = useNavigate();

  const fetchSubmissions = async () => {
    try {
      const res = await apiClient.get("/student/homework");
      setSubmissionHistory(res.data.map(mapSubmission));
    } catch (err) {
      console.error("Failed to load homework submissions:", err);
    }
  };

  const fetchAssignments = async () => {
    try {
      const res = await apiClient.get("/student/assignments");
      const mapped = res.data.map(mapAssignment);
      setPendingAssignments(mapped);
      if (mapped.length > 0) {
        setSelectedAssignment(mapped[0]);
      }
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

  const handleDropFiles = (fileList) => {
    const filesArray = Array.from(fileList);
    setUploadedFiles((prev) => [...prev, ...filesArray]);
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
    formData.append("description", "");
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
      console.error("Upload failed:", err);
      alert("Upload failed. Please try again.");
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
          <span style={{ fontWeight: 600, color: "#1B2330", display: "block" }}>{row.title}</span>
          <span style={{ fontSize: "11px", color: "#5F6774" }}>{row.subject} • {row.fileName || "No file"}</span>
        </div>
      )
    },
    { key: "submittedDate", label: "Date Submitted", sortable: true },
    { key: "score", label: "Score", sortable: true },
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
    { key: "feedback", label: "Teacher Feedback", sortable: false }
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
          user={{ name: "Arjun Nair", role: "Student" }}
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
                COURSEWORK SUBMISSIONS
              </span>
              <h2
                className="edu-font-heading"
                style={{ fontSize: "24px", fontWeight: 600, color: "#1B2330", margin: "4px 0 0 0" }}
              >
                Homework Upload
              </h2>
              <p style={{ fontSize: "14px", color: "#5F6774", margin: "4px 0 0 0" }}>
                Submit pending coursework assignments and review submission history.
              </p>
            </div>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))",
              gap: "24px",
              marginBottom: "24px",
              alignItems: "start"
            }}
          >
            <div className="edu-card" style={{ padding: "20px" }}>
              <h4 className="edu-font-heading" style={{ fontSize: "16px", fontWeight: 600, color: "#1B2330", margin: "0 0 12px 0" }}>
                Select Pending Assignment
              </h4>
              {pendingAssignments.length === 0 ? (
                <p style={{ fontSize: "13px", color: "#5F6774" }}>No assignments published yet. Check back later.</p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                  {pendingAssignments.map((hw) => (
                    <div
                      key={hw.id}
                      onClick={() => setSelectedAssignment(hw)}
                      style={{
                        padding: "12px 16px",
                        borderRadius: "4px",
                        border: `1px solid ${selectedAssignment?.id === hw.id ? "#26415E" : "#E5E5E1"}`,
                        backgroundColor: selectedAssignment?.id === hw.id ? "rgba(38, 65, 94, 0.05)" : "#FFFFFF",
                        cursor: "pointer",
                        transition: "all 0.15s ease"
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                        <span style={{ fontSize: "10px", fontWeight: 700, color: "#26415E", textTransform: "uppercase" }}>{hw.subject}</span>
                        <StatusBadge variant={hw.statusVariant} label={hw.statusLabel} />
                      </div>
                      <p style={{ fontSize: "14px", fontWeight: 600, color: "#1B2330", margin: "0 0 4px 0" }}>{hw.title}</p>
                      <p style={{ fontSize: "12px", color: "#5F6774", margin: 0 }}>Due: {hw.dueDate} • Max: {hw.maxScore} pts</p>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <h4 className="edu-font-heading" style={{ fontSize: "16px", fontWeight: 600, color: "#1B2330", margin: "0 0 12px 0" }}>
                Upload Submission{selectedAssignment ? `: ${selectedAssignment.title}` : ""}
              </h4>
              <p style={{ fontSize: "12px", color: "#5F6774", margin: "0 0 16px 0" }}>
                {selectedAssignment ? selectedAssignment.instructions : "Select an assignment on the left to begin."}
              </p>

              <FileDropzone
                onFilesSelected={handleDropFiles}
                accept=".pdf,.docx,.zip,.jpg,.jpeg,.png,.webp"
                acceptText="Drag & drop your solution PDF, DOCX, or a photo of your handwritten work"
                maxSizeText="Maximum file size 25MB"
              />

              {uploadedFiles.length > 0 && (
                <div style={{ marginTop: "16px", padding: "12px", backgroundColor: "#F4F4F1", borderRadius: "4px" }}>
                  <p style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase", margin: "0 0 6px 0" }}>Selected File</p>
                  {uploadedFiles.map((file, idx) => (
                    <p key={idx} style={{ fontSize: "13px", color: "#1B2330", margin: 0, fontWeight: 600, display: "flex", alignItems: "center", gap: "6px" }}>
                      <span className="material-symbols-outlined" style={{ fontSize: "16px", color: "#26415E" }}>description</span>
                      {file.name} ({(file.size / 1024).toFixed(1)} KB)
                    </p>
                  ))}
                </div>
              )}

              <button
                onClick={handleSubmitAssignment}
                disabled={isSubmitting || !selectedAssignment}
                className="edu-btn-primary"
                style={{ width: "100%", marginTop: "16px", padding: "12px", display: "flex", alignItems: "center", justifyContent: "center", gap: "6px", opacity: (isSubmitting || !selectedAssignment) ? 0.6 : 1 }}
              >
                {isSubmitting ? "SUBMITTING..." : "SUBMIT HOMEWORK"}
                <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>send</span>
              </button>
            </div>
          </div>

          <DataTable
            title="Homework Submission History"
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