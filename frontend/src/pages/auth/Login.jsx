import { useState } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "../../api/client";
import { TextField } from "../../components/ui";
import "../../components/ui/ui.css";

function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoggingIn, setIsLoggingIn] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setIsLoggingIn(true);

    try {
      const loginResponse = await apiClient.post("/auth/login", { email, password });
      const token = loginResponse.data.access_token;
      localStorage.setItem("access_token", token);

      const meResponse = await apiClient.get("/users/me");
      const role = meResponse.data.role;

      navigate(`/${role}/dashboard`);
    } catch (err) {
      const detail = err.response?.data?.detail || "Login failed. Please check your credentials.";
      setError(detail);
    } finally {
      setIsLoggingIn(false);
    }
  };

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
          maxWidth: "400px",
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
            Decision Intelligence Portal
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

        {/* Login Form */}
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
          <TextField
            label="Email Address"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="admin@eduintel.ai"
            icon="mail"
            required
          />

          <TextField
            label="Password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            icon="lock"
            required
          />

          <button
            type="submit"
            disabled={isLoggingIn}
            className="edu-btn-primary"
            style={{
              width: "100%",
              padding: "12px",
              marginTop: "8px",
              fontSize: "12px",
              letterSpacing: "0.05em",
              opacity: isLoggingIn ? 0.7 : 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "8px"
            }}
          >
            {isLoggingIn ? "Signing In..." : "Sign In to EduIntel"}
            <span className="material-symbols-outlined" style={{ fontSize: "16px" }}>login</span>
          </button>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "6px", marginTop: "4px" }}>
            <button
              type="button"
              onClick={() => {
                setEmail("hishamadmin@gmail.com");
                setPassword("hishamadmin");
              }}
              style={{
                padding: "8px 6px",
                fontSize: "11px",
                fontWeight: 600,
                color: "#059669",
                background: "rgba(16, 185, 129, 0.1)",
                border: "1px solid rgba(16, 185, 129, 0.25)",
                borderRadius: "8px",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "3px"
              }}
            >
              <span className="material-symbols-outlined" style={{ fontSize: "14px" }}>admin_panel_settings</span>
              Admin Fill
            </button>

            <button
              type="button"
              onClick={() => {
                setEmail("hishamteacher@gmail.com");
                setPassword("hishamteacher");
              }}
              style={{
                padding: "8px 6px",
                fontSize: "11px",
                fontWeight: 600,
                color: "#0284C7",
                background: "rgba(14, 165, 233, 0.1)",
                border: "1px solid rgba(14, 165, 233, 0.25)",
                borderRadius: "8px",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "3px"
              }}
            >
              <span className="material-symbols-outlined" style={{ fontSize: "14px" }}>school</span>
              Teacher Fill
            </button>

            <button
              type="button"
              onClick={() => {
                setEmail("synth_student_0@eduintel.demo");
                setPassword("demo_password_123");
              }}
              style={{
                padding: "8px 6px",
                fontSize: "11px",
                fontWeight: 600,
                color: "#8B5CF6",
                background: "rgba(139, 92, 246, 0.1)",
                border: "1px solid rgba(139, 92, 246, 0.25)",
                borderRadius: "8px",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "3px"
              }}
            >
              <span className="material-symbols-outlined" style={{ fontSize: "14px" }}>person</span>
              Student Fill
            </button>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "6px", marginTop: "4px" }}>
            <button
              type="button"
              onClick={() => {
                localStorage.setItem("demo_mode", "true");
                navigate("/admin/dashboard");
              }}
              style={{
                padding: "8px 6px",
                fontSize: "11px",
                fontWeight: 600,
                color: "#1E293B",
                background: "rgba(241, 245, 249, 0.8)",
                border: "1px solid rgba(226, 232, 240, 0.9)",
                borderRadius: "8px",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "3px"
              }}
            >
              <span className="material-symbols-outlined" style={{ fontSize: "14px", color: "#64748B" }}>preview</span>
              Admin Demo
            </button>

            <button
              type="button"
              onClick={() => {
                localStorage.setItem("demo_mode", "true");
                navigate("/teacher/dashboard");
              }}
              style={{
                padding: "8px 6px",
                fontSize: "11px",
                fontWeight: 600,
                color: "#1E293B",
                background: "rgba(241, 245, 249, 0.8)",
                border: "1px solid rgba(226, 232, 240, 0.9)",
                borderRadius: "8px",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "3px"
              }}
            >
              <span className="material-symbols-outlined" style={{ fontSize: "14px", color: "#64748B" }}>preview</span>
              Teacher Demo
            </button>

            <button
              type="button"
              onClick={() => {
                localStorage.setItem("demo_mode", "true");
                navigate("/student/dashboard");
              }}
              style={{
                padding: "8px 6px",
                fontSize: "11px",
                fontWeight: 600,
                color: "#1E293B",
                background: "rgba(241, 245, 249, 0.8)",
                border: "1px solid rgba(226, 232, 240, 0.9)",
                borderRadius: "8px",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "3px"
              }}
            >
              <span className="material-symbols-outlined" style={{ fontSize: "14px", color: "#64748B" }}>preview</span>
              Student Demo
            </button>
          </div>
        </form>

        {/* Navigation Footer Links */}
        <div
          style={{
            marginTop: "24px",
            paddingTop: "20px",
            borderTop: "1px solid #E5E5E1",
            display: "flex",
            justifyContent: "space-between",
            fontSize: "12px",
            color: "#5F6774"
          }}
        >
          <a
            href="/password-reset"
            style={{ color: "#26415E", textDecoration: "none", fontWeight: 600 }}
          >
            Forgot password?
          </a>
          <a
            href="/signup"
            style={{ color: "#C97A2B", textDecoration: "none", fontWeight: 600 }}
          >
            Create an Account →
          </a>
        </div>
      </div>
    </div>
  );
}

export default Login;