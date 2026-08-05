import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, DataTable, StatusBadge, FileDropzone } from "../../components/ui";
import { pendingHomeworkList, homeworkSubmissionsHistory } from "../../data/studentMockData";
import { logout } from "../../api/auth";

export default function HomeworkUpload() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [selectedAssignment, setSelectedAssignment] = useState(pendingHomeworkList[0]);
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [submissionHistory, setSubmissionHistory] = useState(homeworkSubmissionsHistory);
  const navigate = useNavigate();

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const handleDropFiles = (files) => {
    setUploadedFiles((prev) => [...prev, ...files]);
  };

  const handleSubmitAssignment = () => {
    if (uploadedFiles.length === 0) {
      alert("Please select or drop a file before submitting.");
      return;
    }

    const newSub = {
      id: `SUB-${Math.floor(100 + Math.random() * 900)}`,
      title: selectedAssignment.title,
      subject: selectedAssignment.subject,
      submittedDate: "Just Now",
      score: `-- / ${selectedAssignment.maxScore}`,
      statusVariant: "on-track",
      statusLabel: "SUBMITTED",
      feedback: "Awaiting teacher grading.",
      fileName: uploadedFiles[0].name,
    };

    setSubmissionHistory([newSub, ...submissionHistory]);
    setUploadedFiles([]);
    alert(`Successfully submitted "${selectedAssignment.title}"!`);
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

          {/* Upload Section Card */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))",
              gap: "24px",
              marginBottom: "24px",
              alignItems: "start"
            }}
          >
            {/* Left: Pending Homework Selector */}
            <div className="edu-card" style={{ padding: "20px" }}>
              <h4 className="edu-font-heading" style={{ fontSize: "16px", fontWeight: 600, color: "#1B2330", margin: "0 0 12px 0" }}>
                Select Pending Assignment
              </h4>
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                {pendingHomeworkList.map((hw) => (
                  <div
                    key={hw.id}
                    onClick={() => setSelectedAssignment(hw)}
                    style={{
                      padding: "12px 16px",
                      borderRadius: "4px",
                      border: `1px solid ${selectedAssignment.id === hw.id ? "#26415E" : "#E5E5E1"}`,
                      backgroundColor: selectedAssignment.id === hw.id ? "rgba(38, 65, 94, 0.05)" : "#FFFFFF",
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
            </div>

            {/* Right: File Dropzone & Submit */}
            <div className="edu-card" style={{ padding: "20px" }}>
              <h4 className="edu-font-heading" style={{ fontSize: "16px", fontWeight: 600, color: "#1B2330", margin: "0 0 12px 0" }}>
                Upload Submission: {selectedAssignment.title}
              </h4>
              <p style={{ fontSize: "12px", color: "#5F6774", margin: "0 0 16px 0" }}>
                {selectedAssignment.instructions}
              </p>

              <FileDropzone
                onDropFiles={handleDropFiles}
                accept=".pdf,.docx,.zip"
                maxSizeMb={25}
                helperText="Drag & drop your solution PDF or DOCX file here (Max 25MB)"
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
                className="edu-btn-primary"
                style={{ width: "100%", marginTop: "16px", padding: "12px", display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}
              >
                SUBMIT HOMEWORK
                <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>send</span>
              </button>
            </div>
          </div>

          {/* Submission History Table */}
          <DataTable
            title="Homework Submission History"
            columns={columns}
            data={submissionHistory}
            pageSize={5}
          />
        </main>
      </div>
    </div>
  );
}
