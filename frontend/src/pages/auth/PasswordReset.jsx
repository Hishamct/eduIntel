import { useState } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "../../api/client";
import { TextField } from "../../components/ui";
import "../../components/ui/ui.css";

function PasswordReset() {
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [requestMessage, setRequestMessage] = useState("");
  const [error, setError] = useState("");
  const navigate = useNavigate();

  const handleRequestReset = async (e) => {
    e.preventDefault();
    setError("");
    setRequestMessage("");

    try {
      const response = await apiClient.post("/auth/password-reset/request", { email });
      setRequestMessage(response.data.message);

      if (response.data.dev_reset_token) {
        setToken(response.data.dev_reset_token);
      }
    } catch (err) {
      const detail = err.response?.data?.detail || "Request failed. Please try again.";
      setError(detail);
    }
  };

  const handleConfirmReset = async (e) => {
    e.preventDefault();
    setError("");

    try {
      await apiClient.post("/auth/password-reset/confirm", { token, new_password: newPassword });
      navigate("/login");
    } catch (err) {
      const detail = err.response?.data?.detail || "Reset failed. Please try again.";
      setError(detail);
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
          maxWidth: "440px",
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
            Password Recovery
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

        {/* Step 1: Request Reset Form */}
        <form onSubmit={handleRequestReset} style={{ marginBottom: "28px" }}>
          <h3
            className="edu-font-heading"
            style={{
              fontSize: "14px",
              fontWeight: 600,
              color: "#26415E",
              marginBottom: "12px",
              textTransform: "uppercase",
              letterSpacing: "0.05em"
            }}
          >
            Step 1: Request Reset Link
          </h3>

          {requestMessage && (
            <div
              style={{
                padding: "8px 12px",
                backgroundColor: "rgba(60, 140, 93, 0.1)",
                border: "1px solid #3C8C5D",
                borderRadius: "4px",
                color: "#3C8C5D",
                fontSize: "12px",
                marginBottom: "12px"
              }}
            >
              {requestMessage}
            </div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            <TextField
              label="Registered Email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="user@eduintel.ai"
              icon="mail"
              required
            />
            <button
              type="submit"
              className="edu-btn-secondary"
              style={{ width: "100%", padding: "10px", fontSize: "11px" }}
            >
              Send Reset Link
            </button>
          </div>
        </form>

        <div style={{ height: "1px", backgroundColor: "#E5E5E1", margin: "20px 0" }} />

        {/* Step 2: Confirm Reset Form */}
        <form onSubmit={handleConfirmReset}>
          <h3
            className="edu-font-heading"
            style={{
              fontSize: "14px",
              fontWeight: 600,
              color: "#26415E",
              marginBottom: "12px",
              textTransform: "uppercase",
              letterSpacing: "0.05em"
            }}
          >
            Step 2: Set New Password
          </h3>

          <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
            <TextField
              label="Reset Token"
              type="text"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="Enter received reset token"
              icon="key"
              required
            />

            <TextField
              label="New Password"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="••••••••"
              icon="lock"
              required
            />

            <button
              type="submit"
              className="edu-btn-primary"
              style={{
                width: "100%",
                padding: "12px",
                marginTop: "4px",
                fontSize: "12px"
              }}
            >
              Reset Password
            </button>
          </div>
        </form>

        {/* Navigation Footer */}
        <div
          style={{
            marginTop: "24px",
            paddingTop: "16px",
            borderTop: "1px solid #E5E5E1",
            textAlign: "center",
            fontSize: "12px"
          }}
        >
          <a
            href="/login"
            style={{ color: "#26415E", textDecoration: "none", fontWeight: 600 }}
          >
            ← Back to Login
          </a>
        </div>
      </div>
    </div>
  );
}

export default PasswordReset;