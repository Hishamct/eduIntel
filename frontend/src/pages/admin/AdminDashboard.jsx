import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "../../api/client";
import { logout } from "../../api/auth";

function AdminDashboard() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    apiClient
      .get("/admin/dashboard")
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
        <h2>Admin Dashboard</h2>
        <button onClick={() => logout(navigate)} style={{ padding: "6px 12px" }}>
          Log out
        </button>
      </div>
      <p>{data.message}</p>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginTop: 24 }}>
        <div style={cardStyle}>
          <h3>{data.total_students}</h3>
          <p>Total students</p>
        </div>
        <div style={cardStyle}>
          <h3>{data.total_teachers}</h3>
          <p>Total teachers</p>
        </div>
        <div style={cardStyle}>
          <h3>₹{data.revenue_this_month.toLocaleString()}</h3>
          <p>Revenue this month</p>
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

export default AdminDashboard;