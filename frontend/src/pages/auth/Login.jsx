// import { useState } from "react";

// function Login() {
//     const [email, setEmail] = useState("");
//     const [password, setPassword] = useState("");

//     const handleSubmit = (e) => {
//         e.preventDefault();
//         // Dummy behavior for now — real API call comes later
//         console.log("Login attempt:", { email, password });
//         alert(`Dummy login submitted for: ${email}`);
//     };

//     return (
//         <div style={{ maxWidth: 360, margin: "80px auto", fontFamily: "sans-serif" }}>
//             <h2>EduIntel AI — Login</h2>
//             <form onSubmit={handleSubmit}>
//                 <div style={{ marginBottom: 12 }}>
//                     <label>Email</label><br />
//                     <input
//                         type="email"
//                         value={email}
//                         onChange={(e) => setEmail(e.target.value)}
//                         required
//                         style={{ width: "100%", padding: 8 }}
//                     />
//                 </div>
//                 <div style={{ marginBottom: 12 }}>
//                     <label>Password</label><br />
//                     <input
//                         type="password"
//                         value={password}
//                         onChange={(e) => setPassword(e.target.value)}
//                         required
//                         style={{ width: "100%", padding: 8 }}
//                     />
//                 </div>
//                 <button type="submit" style={{ width: "100%", padding: 10 }}>
//                     Log In
//                 </button>
//             </form>
//             <p style={{ marginTop: 16 }}>
//                 <a href="/password-reset">Forgot password?</a> · <a href="/signup">Sign up</a>
//             </p>
//         </div>
//     );
// }

// export default Login;


import { useState } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "../../api/client";

function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");

    try {
      // Step 1: log in and get the token
      const loginResponse = await apiClient.post("/auth/login", { email, password });
      const token = loginResponse.data.access_token;
      localStorage.setItem("access_token", token);

      // Step 2: fetch the logged-in user's role, now that the token is stored
      // (the apiClient interceptor automatically attaches it to this request)
      const meResponse = await apiClient.get("/users/me");
      const role = meResponse.data.role;

      // Step 3: redirect to the correct dashboard based on role
      navigate(`/${role}/dashboard`);
    } catch (err) {
      const detail = err.response?.data?.detail || "Login failed. Please try again.";
      setError(detail);
    }
  };

  return (
    <div style={{ maxWidth: 360, margin: "80px auto", fontFamily: "sans-serif" }}>
      <h2>EduIntel AI — Login</h2>
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
            style={{ width: "100%", padding: 8 }}
          />
        </div>
        <button type="submit" style={{ width: "100%", padding: 10 }}>
          Log In
        </button>
      </form>
      <p style={{ marginTop: 16 }}>
        <a href="/password-reset">Forgot password?</a> · <a href="/signup">Sign up</a>
      </p>
    </div>
  );
}

export default Login;