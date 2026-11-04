import { Navigate } from "react-router-dom";

function ProtectedRoute({ children, requirePlatformAdmin = false }) {
  const isAuthenticated = sessionStorage.getItem("is_authenticated") === "true";
  const isPlatformAdmin = sessionStorage.getItem("is_platform_admin") === "true";

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  if (requirePlatformAdmin && !isPlatformAdmin) {
    const role = sessionStorage.getItem("user_role") || "student";
    return <Navigate to={`/${role}/dashboard`} replace />;
  }

  return children;
}

export default ProtectedRoute;
