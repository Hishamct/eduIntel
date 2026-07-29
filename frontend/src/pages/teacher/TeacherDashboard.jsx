import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "../../api/client";
import { logout } from "../../api/auth";

function TeacherDashboard() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    apiClient
      .get("/teacher/dashboard")
      .then((response) => setData(response.data))
      .catch((err) => {
        const detail = err.response?.data?.detail || "Failed to load dashboard.";
        setError(detail);
      });
  }, []);

  if (error) return <p style={{ color: "red", textAlign: "center", marginTop: 80 }}>{error}</p>;
  if (!data) return <p style={{ textAlign: "center", marginTop: 80 }}>Loading...</p>;

  return (
    <div style={{ maxWidth: 500, margin: "60px auto", fontFamily: "sans-serif" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2>Teacher Dashboard</h2>
        <button onClick={() => logout(navigate)} style={{ padding: "6px 12px" }}>
          Log out
        </button>
      </div>
      <p>{data.message}</p>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginTop: 24 }}>
        <div style={cardStyle}>
          <h3>{data.students_assigned}</h3>
          <p>Students assigned</p>
        </div>
        <div style={cardStyle}>
          <h3>{data.pending_grading}</h3>
          <p>Pending grading</p>
        </div>
        <div style={cardStyle}>
          <h3>{data.flagged_students}</h3>
          <p>Flagged students</p>
        </div>
      </div>
    </div>
  );
}

const cardStyle = {
  border: "1px solid #ccc",
  borderRadius: 8,
  padding: 16,
  textAlign: "center",
};

export default TeacherDashboard;