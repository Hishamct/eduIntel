import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Login from "./pages/auth/Login";
import Signup from "./pages/auth/Signup";
import PasswordReset from "./pages/auth/PasswordReset";
import StudentDashboard from "./pages/student/StudentDashboard";
import HomeworkUpload from "./pages/student/HomeworkUpload";
import DoubtForum from "./pages/student/DoubtForum";
import StudyMaterials from "./pages/student/StudyMaterials";
import SelfEvaluation from "./pages/student/SelfEvaluation";
import TeacherDashboard from "./pages/teacher/TeacherDashboard";
import ProgressMonitoring from "./pages/teacher/ProgressMonitoring";
import AssignmentsGrading from "./pages/teacher/AssignmentsGrading";
import ExamResults from "./pages/teacher/ExamResults";
import FlaggedStudents from "./pages/teacher/FlaggedStudents";
import AdminDashboard from "./pages/admin/AdminDashboard";
import StudentRecords from "./pages/admin/StudentRecords";
import RiskAlerts from "./pages/admin/RiskAlerts";
import AcademicAnalysis from "./pages/admin/AcademicAnalysis";
import InstitutionalReports from "./pages/admin/InstitutionalReports";
import ProtectedRoute from "./components/ProtectedRoute";


function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/login" replace />} />
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="/password-reset" element={<PasswordReset />} />
        <Route
          path="/student/dashboard"
          element={
            <ProtectedRoute>
              <StudentDashboard />
            </ProtectedRoute>
          }
        />
        <Route
          path="/student/homework"
          element={
            <ProtectedRoute>
              <HomeworkUpload />
            </ProtectedRoute>
          }
        />
        <Route
          path="/student/doubts"
          element={
            <ProtectedRoute>
              <DoubtForum />
            </ProtectedRoute>
          }
        />
        <Route
          path="/student/materials"
          element={
            <ProtectedRoute>
              <StudyMaterials />
            </ProtectedRoute>
          }
        />
        <Route
          path="/student/self-eval"
          element={
            <ProtectedRoute>
              <SelfEvaluation />
            </ProtectedRoute>
          }
        />
        <Route
          path="/teacher/dashboard"
          element={
            <ProtectedRoute>
              <TeacherDashboard />
            </ProtectedRoute>
          }
        />
        <Route
          path="/teacher/progress"
          element={
            <ProtectedRoute>
              <ProgressMonitoring />
            </ProtectedRoute>
          }
        />
        <Route
          path="/teacher/grading"
          element={
            <ProtectedRoute>
              <AssignmentsGrading />
            </ProtectedRoute>
          }
        />
        <Route
          path="/teacher/exams"
          element={
            <ProtectedRoute>
              <ExamResults />
            </ProtectedRoute>
          }
        />
        <Route
          path="/teacher/flagged"
          element={
            <ProtectedRoute>
              <FlaggedStudents />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/dashboard"
          element={
            <ProtectedRoute>
              <AdminDashboard />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/students"
          element={
            <ProtectedRoute>
              <StudentRecords />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/alerts"
          element={
            <ProtectedRoute>
              <RiskAlerts />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/analysis"
          element={
            <ProtectedRoute>
              <AcademicAnalysis />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/reports"
          element={
            <ProtectedRoute>
              <InstitutionalReports />
            </ProtectedRoute>
          }
        />
      </Routes>
    </BrowserRouter>
  );
}

export default App;