import { useState } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "../../api/client";
import { TextField, SelectInput } from "../../components/ui";
import "../../components/ui/ui.css";

function Signup() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("student");
  const [error, setError] = useState("");
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");

    try {
      await apiClient.post("/auth/signup", { email, password, role });
      navigate("/login");
    } catch (err) {
      const detail = err.response?.data?.detail || "Signup failed. Please try again.";
      setError(detail);
    }
  };

  const roleOptions = [
    { value: "student", label: "Student" },
    { value: "teacher", label: "Teacher / Educator" },
    { value: "admin", label: "Administrator" }
  ];

  return (
    <div
      style={{
        minHeight: "100vh",
        backgroundColor: "#FAFAF7",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px",
        fontFamily: "'IBM Plex Sans', sans-serif"
      }}
    >
      <div
        className="edu-card"
        style={{
          width: "100%",
          maxWidth: "420px",
          padding: "36px 32px",
          backgroundColor: "#FFFFFF",
          boxShadow: "0 10px 25px -5px rgba(38, 65, 94, 0.08)"
        }}
      >
        {/* Brand Header */}
        <div style={{ textAlign: "center", marginBottom: "28px" }}>
          <h1
            className="edu-font-heading"
            style={{
              fontSize: "26px",
              fontWeight: 700,
              color: "#26415E",
              margin: 0,
              letterSpacing: "-0.02em"
            }}
          >
            EduIntel AI
          </h1>
          <p
            style={{
              fontSize: "11px",
              fontWeight: 700,
              letterSpacing: "0.05em",
              textTransform: "uppercase",
              color: "#5F6774",
              marginTop: "4px"
            }}
          >
            Create Your Account
          </p>
        </div>

        {/* Error Notification Banner */}
        {error && (
          <div
            style={{
              padding: "10px 14px",
              backgroundColor: "rgba(178, 58, 46, 0.1)",
              border: "1px solid #B23A2E",
              borderRadius: "4px",
              color: "#B23A2E",
              fontSize: "13px",
              marginBottom: "20px",
              display: "flex",
              alignItems: "center",
              gap: "8px"
            }}
          >
            <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>
              error
            </span>
            <span>{error}</span>
          </div>
        )}

        {/* Signup Form */}
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
          <TextField
            label="Email Address"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="user@eduintel.ai"
            icon="mail"
            required
          />

          <TextField
            label="Password (min. 8 characters)"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            icon="lock"
            required
          />

          <SelectInput
            label="Institutional Role"
            value={role}
            onChange={(e) => setRole(e.target.value)}
            options={roleOptions}
            placeholder=""
          />

          <button
            type="submit"
            className="edu-btn-accent"
            style={{
              width: "100%",
              padding: "12px",
              marginTop: "8px",
              fontSize: "12px",
              letterSpacing: "0.05em"
            }}
          >
            Register Account
          </button>
        </form>

        {/* Navigation Footer */}
        <div
          style={{
            marginTop: "24px",
            paddingTop: "20px",
            borderTop: "1px solid #E5E5E1",
            textAlign: "center",
            fontSize: "12px",
            color: "#5F6774"
          }}
        >
          Already registered?{" "}
          <a
            href="/login"
            style={{ color: "#26415E", textDecoration: "none", fontWeight: 600 }}
          >
            Sign in here →
          </a>
        </div>
      </div>
    </div>
  );
}

export default Signup;