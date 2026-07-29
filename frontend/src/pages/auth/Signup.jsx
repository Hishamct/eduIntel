// import { useState } from "react";

// function Signup() {
//   const [email, setEmail] = useState("");
//   const [password, setPassword] = useState("");
//   const [role, setRole] = useState("student");

//   const handleSubmit = (e) => {
//     e.preventDefault();
//     // Dummy behavior for now — real API call comes later
//     console.log("Signup attempt:", { email, password, role });
//     alert(`Dummy signup submitted for: ${email} as ${role}`);
//   };

//   return (
//     <div style={{ maxWidth: 360, margin: "80px auto", fontFamily: "sans-serif" }}>
//       <h2>EduIntel AI — Sign Up</h2>
//       <form onSubmit={handleSubmit}>
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
//         <div style={{ marginBottom: 12 }}>
//           <label>Password</label><br />
//           <input
//             type="password"
//             value={password}
//             onChange={(e) => setPassword(e.target.value)}
//             required
//             minLength={8}
//             style={{ width: "100%", padding: 8 }}
//           />
//         </div>
//         <div style={{ marginBottom: 12 }}>
//           <label>Role</label><br />
//           <select
//             value={role}
//             onChange={(e) => setRole(e.target.value)}
//             style={{ width: "100%", padding: 8 }}
//           >
//             <option value="student">Student</option>
//             <option value="teacher">Teacher</option>
//             <option value="admin">Admin</option>
//           </select>
//         </div>
//         <button type="submit" style={{ width: "100%", padding: 10 }}>
//           Sign Up
//         </button>
//       </form>
//       <p style={{ marginTop: 16 }}>
//         Already have an account? <a href="/login">Log in</a>
//       </p>
//     </div>
//   );
// }

// export default Signup;

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "../../api/client";

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
      // Signup doesn't log the user in automatically — send them to login
      navigate("/login");
    } catch (err) {
      const detail = err.response?.data?.detail || "Signup failed. Please try again.";
      setError(detail);
    }
  };

  return (
    <div style={{ maxWidth: 360, margin: "80px auto", fontFamily: "sans-serif" }}>
      <h2>EduIntel AI — Sign Up</h2>
      {error && <p style={{ color: "red" }}>{error}</p>}
      <form onSubmit={handleSubmit}>
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
        <div style={{ marginBottom: 12 }}>
          <label>Password</label><br />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            style={{ width: "100%", padding: 8 }}
          />
        </div>
        <div style={{ marginBottom: 12 }}>
          <label>Role</label><br />
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            style={{ width: "100%", padding: 8 }}
          >
            <option value="student">Student</option>
            <option value="teacher">Teacher</option>
            <option value="admin">Admin</option>
          </select>
        </div>
        <button type="submit" style={{ width: "100%", padding: 10 }}>
          Sign Up
        </button>
      </form>
      <p style={{ marginTop: 16 }}>
        Already have an account? <a href="/login">Log in</a>
      </p>
    </div>
  );
}

export default Signup;