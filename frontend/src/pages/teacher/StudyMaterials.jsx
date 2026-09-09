import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, DataTable, FileDropzone } from "../../components/ui";
import { logout } from "../../api/auth";
import apiClient from "../../api/client";

function mapMaterial(m) {
  return {
    id: m.id,
    title: m.title,
    subject: m.subject,
    description: m.description || "No description",
    fileName: m.original_filename,
    extractionMethod: m.extraction_method,
    hasText: !!m.extracted_text,
    extractedText: m.extracted_text,
    uploadedDate: new Date(m.created_at).toLocaleDateString("en-IN", {
      day: "2-digit", month: "short", year: "numeric",
    }),
  };
}

export default function StudyMaterials() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [materials, setMaterials] = useState([]);
  const [selectedMaterial, setSelectedMaterial] = useState(null);
  const [newSubject, setNewSubject] = useState("MATHEMATICS");
  const [newTitle, setNewTitle] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const navigate = useNavigate();

  const fetchMaterials = async () => {
    try {
      const res = await apiClient.get("/teacher/study-materials");
      setMaterials(res.data.map(mapMaterial));
    } catch (err) {
      console.error("Failed to load study materials:", err);
    }
  };

  useEffect(() => {
    fetchMaterials();
  }, []);

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const handleDropFiles = (fileList) => {
    const filesArray = Array.from(fileList);
    setUploadedFiles(filesArray.slice(0, 1)); // one file at a time
  };

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!newTitle) {
      alert("Please enter a title.");
      return;
    }
    if (uploadedFiles.length === 0) {
      alert("Please select or drop a file first.");
      return;
    }

    const formData = new FormData();
    formData.append("subject", newSubject);
    formData.append("title", newTitle);
    formData.append("description", newDescription);
    formData.append("file", uploadedFiles[0]);

    setIsSubmitting(true);
    try {
      await apiClient.post("/teacher/study-materials/upload", formData, {
        headers: { "Content-Type": undefined },
      });
      await fetchMaterials();
      setNewTitle("");
      setNewDescription("");
      setUploadedFiles([]);
      alert(`"${newTitle}" uploaded successfully!`);
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
      label: "Title",
      sortable: true,
      render: (row) => (
        <div>
          <span style={{ fontWeight: 600, color: "#1B2330", display: "block" }}>{row.title}</span>
          <span style={{ fontSize: "11px", color: "#5F6774" }}>{row.subject} • {row.fileName}</span>
        </div>
      )
    },
    { key: "uploadedDate", label: "Uploaded", sortable: true },
    {
      key: "extractionMethod",
      label: "Text Extracted",
      sortable: true,
      render: (row) => (
        <span style={{ fontSize: "12px", color: row.hasText ? "#3C8C5D" : "#5F6774" }}>
          {row.hasText ? (row.extractionMethod === "ocr" ? "OCR" : "PDF Text") : "Not extracted"}
        </span>
      )
    },
    {
      key: "actions",
      label: "Actions",
      sortable: false,
      render: (row) => (
        <div style={{ textAlign: "right" }}>
          <button
            onClick={() => setSelectedMaterial(row)}
            className="edu-btn-secondary"
            style={{ padding: "4px 10px", fontSize: "11px" }}
          >
            View Text
          </button>
        </div>
      )
    }
  ];

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="teacher"
        activeId="materials"
        logoText="EduIntel AI"
        roleText="Teacher Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "materials") navigate(`/teacher/${itemId}`);
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: "Faculty Portal", role: "Educator" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content">
          <div style={{ marginBottom: "24px" }}>
            <span style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.05em", color: "#5F6774", textTransform: "uppercase" }}>
              KNOWLEDGE BASE
            </span>
            <h2 className="edu-font-heading" style={{ fontSize: "24px", fontWeight: 600, color: "#1B2330", margin: "4px 0 0 0" }}>
              Study Materials
            </h2>
            <p style={{ fontSize: "14px", color: "#5F6774", margin: "4px 0 0 0" }}>
              Upload notes and question papers — text is extracted automatically for search and AI features.
            </p>
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
                <span className="material-symbols-outlined" style={{ color: "#26415E" }}>upload_file</span>
                <h3 className="edu-font-heading" style={{ margin: 0, fontSize: "16px", fontWeight: 600, color: "#1B2330", textTransform: "uppercase" }}>
                  Upload Material
                </h3>
              </div>

              <form onSubmit={handleUpload} style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Title</label>
                  <input
                    type="text"
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                    placeholder="e.g. Trigonometry Previous Year Questions"
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

                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Description</label>
                  <textarea
                    rows={3}
                    value={newDescription}
                    onChange={(e) => setNewDescription(e.target.value)}
                    placeholder="Optional notes about this material..."
                    style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "14px", outline: "none", resize: "vertical", color: "#1B2330" }}
                  />
                </div>

                <FileDropzone
                  onFilesSelected={handleDropFiles}
                  accept=".pdf,.jpg,.jpeg,.png,.webp"
                  acceptText="Drag & drop a scanned note, question paper, or PDF here"
                  maxSizeText="Maximum file size 25MB"
                />

                {uploadedFiles.length > 0 && (
                  <div style={{ padding: "12px", backgroundColor: "#F4F4F1", borderRadius: "4px" }}>
                    <p style={{ fontSize: "13px", color: "#1B2330", margin: 0, fontWeight: 600 }}>
                      {uploadedFiles[0].name} ({(uploadedFiles[0].size / 1024).toFixed(1)} KB)
                    </p>
                  </div>
                )}

                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="edu-btn-primary"
                  style={{ width: "100%", padding: "12px", display: "flex", alignItems: "center", justifyContent: "center", gap: "6px", opacity: isSubmitting ? 0.6 : 1 }}
                >
                  {isSubmitting ? "UPLOADING..." : "UPLOAD MATERIAL"}
                  <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>send</span>
                </button>
              </form>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
              <DataTable
                title="Uploaded Materials"
                columns={columns}
                data={materials}
                pageSize={5}
              />

              {selectedMaterial && (
                <div className="edu-card" style={{ padding: "20px" }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "10px" }}>
                    <h4 style={{ margin: 0, fontSize: "13px", fontWeight: 700, color: "#1B2330", textTransform: "uppercase" }}>
                      {selectedMaterial.title}
                    </h4>
                    <button onClick={() => setSelectedMaterial(null)} className="edu-btn-secondary" style={{ padding: "4px 10px", fontSize: "11px" }}>
                      Close
                    </button>
                  </div>
                  {selectedMaterial.hasText ? (
                    <p style={{ fontSize: "13px", color: "#1B2330", whiteSpace: "pre-wrap", maxHeight: "240px", overflowY: "auto", margin: 0, lineHeight: 1.5 }}>
                      {selectedMaterial.extractedText}
                    </p>
                  ) : (
                    <p style={{ fontSize: "13px", color: "#5F6774" }}>No text was extracted from this file.</p>
                  )}
                </div>
              )}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}