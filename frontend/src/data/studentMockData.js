// Student Portal Mock Data

export const studentProfileData = {
  id: "#EDU-9821",
  name: "Arjun Nair",
  avatarInitials: "AN",
  gradeClass: "Grade 12-A",
  email: "arjun.nair@edu-example.com",
  phone: "+91 98470 12345",
  locality: "Panampilly Nagar, Ernakulam, Kochi",
  guardianName: "Sunil Nair",
  guardianRelationship: "Father",
  guardianPhone: "+91 98470 12346",
  studyPlanReady: true,
  studyPlanMessage: "Curriculum path is synchronized with Grade 12-A syllabus.",
};

export const studentDashboardKpis = {
  homeworkCount: 2,
  homeworkStatusText: "2 Pending Submissions",
  unresolvedDoubts: 1,
  unresolvedStatusText: "1 Awaiting Faculty Reply",
  studyPlanReady: true,
  studyPlanStatusText: "READY",
  overallAttendance: "98.4%",
  currentGpa: "3.92",
};

export const pendingHomeworkList = [
  {
    id: "HW-101",
    title: "Advanced Calculus Integration Methods",
    subject: "MATHEMATICS",
    dueDate: "Tomorrow, 5:00 PM",
    maxScore: 100,
    instructions: "Solve problem set 4.3 (questions 1-15). Show all intermediate integration steps clearly.",
    statusVariant: "needs-attention",
    statusLabel: "DUE TOMORROW",
  },
  {
    id: "HW-102",
    title: "Electromagnetic Induction Lab Analysis",
    subject: "PHYSICS",
    dueDate: "Oct 28, 2026",
    maxScore: 50,
    instructions: "Complete graph plots for magnetic flux variation and derive Faraday's law constants.",
    statusVariant: "on-track",
    statusLabel: "ASSIGNED",
  }
];

export const homeworkSubmissionsHistory = [
  {
    id: "SUB-881",
    title: "Differential Equations Worksheet",
    subject: "MATHEMATICS",
    submittedDate: "Oct 22, 2026",
    score: "94 / 100",
    statusVariant: "on-track",
    statusLabel: "GRADED",
    feedback: "Excellent precision on second-order linear differential equations.",
    fileName: "arjun_diff_equations.pdf",
  },
  {
    id: "SUB-882",
    title: "Organic Reaction Mechanisms Summary",
    subject: "CHEMISTRY",
    submittedDate: "Oct 18, 2026",
    score: "88 / 100",
    statusVariant: "on-track",
    statusLabel: "GRADED",
    feedback: "Well structured synthesis paths for aromatic compounds.",
    fileName: "arjun_organic_reactions.pdf",
  },
  {
    id: "SUB-883",
    title: "Data Structures Binary Tree Implementation",
    subject: "COMPUTER SCIENCE",
    submittedDate: "Oct 14, 2026 (1h late)",
    score: "85 / 100",
    statusVariant: "needs-attention",
    statusLabel: "LATE (1H)",
    feedback: "Good recursion logic. Minor penalty applied for late submission.",
    fileName: "arjun_binary_tree.cpp",
  },
  {
    id: "SUB-884",
    title: "Thermodynamics Laws Practice Quiz",
    subject: "PHYSICS",
    submittedDate: "--",
    score: "0 / 100",
    statusVariant: "flagged-at-risk",
    statusLabel: "MISSING",
    feedback: "Non-submission recorded. Please contact Dr. Vance for retake options.",
    fileName: "",
  }
];

export const doubtThreadsData = [
  {
    id: "DOUBT-01",
    title: "Clarification on Integration by Parts substitution rule",
    subject: "MATHEMATICS",
    askedDate: "Oct 24, 10:42 AM",
    statusVariant: "on-track",
    statusLabel: "RESOLVED",
    messages: [
      {
        id: "m1",
        senderType: "student",
        senderName: "Arjun Nair",
        text: "In question 8 of calculus sheet 4, should we choose u = ln(x) or u = x^2 first?",
        timestamp: "10:42 AM",
      },
      {
        id: "m2",
        senderType: "institution",
        senderName: "Faculty Advisory (Dr. Vance)",
        text: "Hi Arjun! Always follow the LIATE rule (Logarithmic before Algebraic). So set u = ln(x) and dv = x^2 dx.",
        timestamp: "10:50 AM",
      }
    ]
  },
  {
    id: "DOUBT-02",
    title: "Lenz's Law direction in magnetic loop experiment",
    subject: "PHYSICS",
    askedDate: "Oct 25, 02:15 PM",
    statusVariant: "needs-attention",
    statusLabel: "PENDING FACULTY",
    messages: [
      {
        id: "m3",
        senderType: "student",
        senderName: "Arjun Nair",
        text: "When the north pole approaches the coil, does the induced current oppose the flux increase?",
        timestamp: "02:15 PM",
      }
    ]
  }
];

export const studyMaterialsListData = [
  {
    id: "MAT-1",
    title: "Advanced Calculus & Integration Methods Notes",
    subject: "MATHEMATICS",
    fileType: "pdf",
    date: "Oct 20, 2026",
    fileSize: "4.2 MB",
    downloadUrl: "#",
  },
  {
    id: "MAT-2",
    title: "Electromagnetism & Faraday's Law Lecture Slides",
    subject: "PHYSICS",
    fileType: "slide",
    date: "Oct 18, 2026",
    fileSize: "12.8 MB",
    downloadUrl: "#",
  },
  {
    id: "MAT-3",
    title: "Organic Chemistry Reaction Schemes Reference",
    subject: "CHEMISTRY",
    fileType: "pdf",
    date: "Oct 15, 2026",
    fileSize: "6.1 MB",
    downloadUrl: "#",
  },
  {
    id: "MAT-4",
    title: "Data Structures & Algorithm Complexity Guide",
    subject: "COMPUTER SCIENCE",
    fileType: "docx",
    date: "Oct 12, 2026",
    fileSize: "2.4 MB",
    downloadUrl: "#",
  },
  {
    id: "MAT-5",
    title: "Linear Algebra Vectors & Matrix Operators Video",
    subject: "MATHEMATICS",
    fileType: "video",
    date: "Oct 08, 2026",
    fileSize: "45.0 MB",
    downloadUrl: "#",
  },
  {
    id: "MAT-6",
    title: "Quantum Physics Wave Function Foundations",
    subject: "PHYSICS",
    fileType: "pdf",
    date: "Oct 05, 2026",
    fileSize: "3.8 MB",
    downloadUrl: "#",
  }
];

// Self-Evaluation Encouraging Reflective Mock Data
export const selfEvaluationData = {
  encouragementBanner: {
    headline: "You're Making Great Academic Progress, Arjun!",
    subtext: "Your dedication to Mathematics and Computer Science is paying off. Keep building your daily study routine to reach your target GPA.",
  },
  subjectStrengths: [
    { subject: "Mathematics II", score: "94%", statusVariant: "on-track", statusLabel: "STRONG HOLD", reflection: "Consistent practice on calculus problem sets has built excellent speed." },
    { subject: "Computer Science", score: "90%", statusVariant: "on-track", statusLabel: "EXCELLENT", reflection: "Strong problem solving in binary trees and algorithm design." },
    { subject: "Physics", score: "84%", statusVariant: "on-track", statusLabel: "STEADY", reflection: "Good grasp of concepts. Focus slightly more on experimental lab derivations." },
    { subject: "Chemistry", score: "78%", statusVariant: "needs-attention", statusLabel: "FOCUS AREA", reflection: "Organic reaction mechanisms are improving. Weekly revision will help solidify formulas." }
  ],
  studyHabitsChecklist: [
    { id: "h1", task: "Review daily lecture notes within 24 hours", completed: true },
    { id: "h2", task: "Complete practice problem set for Mathematics", completed: true },
    { id: "h3", task: "Post unresolved doubts on Doubt Forum prompt", completed: true },
    { id: "h4", task: "Conduct weekend revision for Chemistry reaction schemes", completed: false }
  ],
  personalGoals: [
    { goal: "Maintain 95%+ Attendance across all subjects", current: "98.4%", progressPercent: 98 },
    { goal: "Achieve Target GPA of 4.0 in Final Semester", current: "3.92 / 4.0", progressPercent: 98 },
    { goal: "Complete all homework assignments at least 1 day before due date", current: "88% On-Time", progressPercent: 88 }
  ]
};
