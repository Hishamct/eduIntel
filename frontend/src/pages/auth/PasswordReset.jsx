// import { useState } from "react";

// function PasswordReset() {
//   const [email, setEmail] = useState("");
//   const [token, setToken] = useState("");
//   const [newPassword, setNewPassword] = useState("");

//   const handleRequestReset = (e) => {
//     e.preventDefault();
//     // Dummy behavior for now — real API call comes later
//     console.log("Password reset requested for:", email);
//     alert(`Dummy reset requested for: ${email} (check email in real version)`);
//   };

//   const handleConfirmReset = (e) => {
//     e.preventDefault();
//     // Dummy behavior for now — real API call comes later
//     console.log("Password reset confirm:", { token, newPassword });
//     alert(`Dummy password reset confirmed with token: ${token}`);
//   };

//   return (
//     <div style={{ maxWidth: 360, margin: "80px auto", fontFamily: "sans-serif" }}>
//       <h2>EduIntel AI — Reset Password</h2>

//       <form onSubmit={handleRequestReset} style={{ marginBottom: 32 }}>
//         <h3>Step 1: Request Reset</h3>
//         <div style={{ marginBottom: 12 }}>
//           <label>Email</label><br />
//           <input
//             type="email"
//             value={email}
//             onChange={(e) => setEmail(e.target.value)}
//             required
//             style={{ width: "100%", padding: 8 }}
//           />
//         </div>
//         <button type="submit" style={{ width: "100%", padding: 10 }}>
//           Send Reset Link
//         </button>
//       </form>

//       <form onSubmit={handleConfirmReset}>
//         <h3>Step 2: Confirm New Password</h3>
//         <div style={{ marginBottom: 12 }}>
//           <label>Reset Token</label><br />
//           <input
//             type="text"
//             value={token}
//             onChange={(e) => setToken(e.target.value)}
//             required
//             style={{ width: "100%", padding: 8 }}
//           />
//         </div>
//         <div style={{ marginBottom: 12 }}>
//           <label>New Password</label><br />
//           <input
//             type="password"
//             value={newPassword}
//             onChange={(e) => setNewPassword(e.target.value)}
//             required
//             minLength={8}
//             style={{ width: "100%", padding: 8 }}
//           />
//         </div>
//         <button type="submit" style={{ width: "100%", padding: 10 }}>
//           Reset Password
//         </button>
//       </form>

//       <p style={{ marginTop: 16 }}>
//         <a href="/login">Back to login</a>
//       </p>
//     </div>
//   );
// }

// export default PasswordReset;

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "../../api/client";

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
      // DEV ONLY: backend returns the raw token directly since email-sending isn't built yet.
      // Auto-fill it into Step 2 so you can test the full flow without an inbox.
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
    <div style={{ maxWidth: 360, margin: "80px auto", fontFamily: "sans-serif" }}>
      <h2>EduIntel AI — Reset Password</h2>
      {error && <p style={{ color: "red" }}>{error}</p>}

      <form onSubmit={handleRequestReset} style={{ marginBottom: 32 }}>
        <h3>Step 1: Request Reset</h3>
        {requestMessage && <p style={{ color: "green", fontSize: 14 }}>{requestMessage}</p>}
        <div style={{ marginBottom: 12 }}>
          <label>Email</label><br />
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            style={{ width: "100%", padding: 8 }}
          />
        </div>
        <button type="submit" style={{ width: "100%", padding: 10 }}>
          Send Reset Link
        </button>
      </form>

      <form onSubmit={handleConfirmReset}>
        <h3>Step 2: Confirm New Password</h3>
        <div style={{ marginBottom: 12 }}>
          <label>Reset Token</label><br />
          <input
            type="text"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            required
            style={{ width: "100%", padding: 8 }}
          />
        </div>
        <div style={{ marginBottom: 12 }}>
          <label>New Password</label><br />
          <input
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            required
            minLength={8}
            style={{ width: "100%", padding: 8 }}
          />
        </div>
        <button type="submit" style={{ width: "100%", padding: 10 }}>
          Reset Password
        </button>
      </form>

      <p style={{ marginTop: 16 }}>
        <a href="/login">Back to login</a>
      </p>
    </div>
  );
}

export default PasswordReset;