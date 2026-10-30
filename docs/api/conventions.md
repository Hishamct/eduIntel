# EduIntel AI — API Conventions & Protocols

This document establishes the official REST API design standards, error formats, response envelopes, and authentication protocols used across all endpoints in EduIntel AI.

---

## 1. Protocol & Architectural Principles

- **Transport**: All production API communications are encrypted via HTTPS (TLS 1.3). In local development, HTTP on port 8000 is used.
- **Base URL**: All application endpoints are mounted under the `/api` prefix.
- **Resource Naming**:
  - URLs use kebab-case and lowercase nouns.
  - Endpoints follow portal or domain scopes: `/api/auth/*`, `/api/student/*`, `/api/teacher/*`, `/api/admin/*`, `/api/ml/*`, `/api/rag/*`, etc.
  - Resource collections use plural nouns (e.g., `/api/student/homework`, `/api/admin/fees`).
- **Idempotency**: `GET`, `PUT`, and `DELETE` requests are idempotent. `POST` requests create new resources or invoke actions.

---

## 2. Authentication & Authorization Headers

All endpoints requiring authentication must receive a signed JSON Web Token (JWT) formatted as a Bearer token in the standard HTTP `Authorization` header:

```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Role-Based Access Control (RBAC) Enforcement
When a client requests a protected endpoint:
1. The `get_current_user` FastAPI dependency decodes the token using `JWT_SECRET_KEY` and verifies the expiration timestamp (`exp`).
2. The user record is retrieved from PostgreSQL to verify `is_active == True`.
3. The `require_role(["role1", ...])` dependency compares the user's role claim against the permitted roles for that endpoint.
4. If the token is invalid, missing, or expired: HTTP **401 Unauthorized** is returned.
5. If the token is valid but the user's role is not permitted: HTTP **403 Forbidden** is returned.

---

## 3. Standard HTTP Status Codes

| Code | Status | Usage in EduIntel |
|---|---|---|
| **200** | OK | Successful `GET` query, or `POST`/`PUT` mutation returning updated payload. |
| **201** | Created | Successful resource creation (e.g., user signup, assignment creation, homework submission). |
| **204** | No Content | Successful deletion or state change returning no body. |
| **400** | Bad Request | Business rule validation failed (e.g., invalid payment status, missing dependency). |
| **401** | Unauthorized | Missing, invalid, or expired Bearer JWT token. |
| **403** | Forbidden | User authenticated successfully, but role lacks permission to access endpoint. |
| **404** | Not Found | Requested entity ID does not exist in the database. |
| **422** | Unprocessable Entity | Pydantic schema validation failure (e.g., malformed email, missing required field). |
| **429** | Too Many Requests | Rate limit exceeded on AI endpoints or auth attempts. |
| **500** | Internal Server Error | Unhandled backend exception or unexpected upstream failure. |

---

## 4. Response Payload & Envelope Formats

### 4.1. Single Resource Response
Single resource endpoints return the serialized Pydantic model directly:

```json
{
  "id": "c1f7a6b2-84e1-482a-9fbc-302381283921",
  "title": "Kinematics Problem Set 3",
  "subject": "Physics",
  "due_date": "2026-11-15T23:59:59Z",
  "max_marks": 50,
  "created_at": "2026-10-25T14:30:00Z",
  "updated_at": "2026-10-25T14:30:00Z"
}
```

### 4.2. Collection List Response
Collections return a direct JSON array of serialized items:

```json
[
  {
    "id": "e83712b1-1234-4567-89ab-cdef01234567",
    "day_of_week": "Monday",
    "subject": "Mathematics",
    "start_time": "09:00:00",
    "end_time": "10:30:00",
    "room_number": "Room 204",
    "teacher_name": "Prof. Sharma"
  }
]
```

### 4.3. Standard Error Response
FastAPI error responses follow the standard `detail` schema:

```json
{
  "detail": "Assignment submission deadline has passed."
}
```

For Pydantic schema validation failures (HTTP 422):
```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "password"],
      "msg": "String should have at least 8 characters",
      "input": "short"
    }
  ]
}
```

---

## 5. Date & Time Representations

- All timestamps are stored and transmitted in **ISO 8601 UTC format**:
  `YYYY-MM-DDTHH:MM:SSZ` (e.g., `2026-10-30T16:00:00Z`).
- Date-only fields (e.g., `attendance_date`, `due_date`) follow the `YYYY-MM-DD` standard.
- Time-only fields (e.g., `start_time`, `end_time` in timetables) follow the `HH:MM:SS` format.

---

## 6. Multipart Form Data (File Uploads)

Endpoints accepting document or image uploads (e.g. `/api/student/homework`, `/api/teacher/materials`, `/api/ocr/extract`) use `multipart/form-data`:
- Header: `Content-Type: multipart/form-data`
- Supported File Extensions: `.jpg`, `.jpeg`, `.png`, `.pdf`
- Maximum Upload Size: 10 MB per file.

