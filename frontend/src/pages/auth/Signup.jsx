import { useNavigate } from "react-router-dom";
import "../../components/ui/ui.css";

function Signup() {
  const navigate = useNavigate();

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
          maxWidth: "460px",
          padding: "40px 32px",
          backgroundColor: "#FFFFFF",
          boxShadow: "0 10px 25px -5px rgba(38, 65, 94, 0.08)",
          textAlign: "center"
        }}
      >
        {/* Brand Header */}
        <div style={{ marginBottom: "28px" }}>
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
            Institutional Access Portal
          </p>
        </div>

        {/* Security Shield Icon */}
        <div
          style={{
            width: "56px",
            height: "56px",
            borderRadius: "50%",
            backgroundColor: "rgba(38, 65, 94, 0.08)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            margin: "0 auto 20px auto",
            color: "#26415E"
          }}
        >
          <span className="material-symbols-outlined" style={{ fontSize: "28px" }}>
            admin_panel_settings
          </span>
        </div>

        {/* Information Notice */}
        <h2
          style={{
            fontSize: "18px",
            fontWeight: 600,
            color: "#0F172A",
            marginBottom: "12px"
          }}
        >
          Public Registration Closed
        </h2>

        <div
          style={{
            padding: "16px",
            backgroundColor: "#F8FAFC",
            border: "1px solid #E2E8F0",
            borderRadius: "8px",
            textAlign: "left",
            fontSize: "13px",
            lineHeight: "1.6",
            color: "#334155",
            marginBottom: "24px"
          }}
        >
          <p style={{ margin: "0 0 10px 0" }}>
            <strong>Institutional Provisioning Policy:</strong>
          </p>
          <p style={{ margin: "0 0 8px 0" }}>
            Public account self-registration is disabled. All student, teacher, and administrator accounts must be provisioned directly by an authorized institution administrator.
          </p>
          <p style={{ margin: 0, color: "#64748B" }}>
            If you need an account or login credentials, please contact your coaching institute or school administration office.
          </p>
        </div>

        {/* Action Button */}
        <button
          type="button"
          onClick={() => navigate("/login")}
          className="edu-btn-primary"
          style={{
            width: "100%",
            padding: "12px",
            fontSize: "13px",
            letterSpacing: "0.03em",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: "8px"
          }}
        >
          <span className="material-symbols-outlined" style={{ fontSize: "16px" }}>
            arrow_back
          </span>
          Return to Sign In
        </button>

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
          Need to recover an existing account?{" "}
          <a
            href="/password-reset"
            style={{ color: "#26415E", textDecoration: "none", fontWeight: 600 }}
          >
            Reset Password →
          </a>
        </div>
      </div>
    </div>
  );
}

export default Signup;
