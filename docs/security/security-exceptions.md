# EduIntel AI — Security Findings & Exception Register

**Document Status:** 🟢 **Active / Enforced**  
**Classification:** Enterprise Security & Compliance Register  
**Lead Security Architect:** DevSecOps & Application Security Engineering  
**Governing Standard:** ISO/IEC 27001 / OWASP ASVS Level 2  
**Last Audit:** November 5, 2026  
**Review Cycle:** Bi-monthly or on major dependency upgrades  

---

## 1. Governance & Exemption Policy

This document provides formal tracking and architectural justification for accepted security findings, static analysis exclusions, and software composition analysis (SCA) advisories across the EduIntel codebase.

### Mandatory Exemption Lifecycle Invariants:
1. **No Silent Suppressions:** Every `# nosec` annotation in backend Python code or lint ignore in frontend JavaScript must reference an approved Exception ID in this register.
2. **Compensating Controls Required:** An exemption cannot be approved based solely on operational convenience. A verifiable compensating architectural control (e.g., input validation, container isolation, network perimeter fencing) must neutralize the threat vector.
3. **Explicit Expiration:** All accepted risks carry an expiration date not exceeding 180 days. Expired exceptions fail CI gates during scheduled audit reviews.
4. **Architectural Sign-Off:** Exceptions require approval from the Principal Security Architect and Module Owner.

---

## 2. Active Security Exception Register

| Exception ID | Scanner | Rule / CVE ID | Affected Component | Risk / Severity | Approved By | Review / Expiry | Status |
|:---|:---|:---|:---|:---|:---|:---|:---:|
| **SEC-EXP-001** | Bandit | B108 (`hardcoded_tmp_directory`) | `backend/app/core/config.py:40` | Medium (CWE-377) | Platform Architect | May 5, 2027 | 🟢 Active |
| **SEC-EXP-002** | Pip-Audit | PyPI / OSV Transitive Packages | `backend/requirements.txt` (ML/OCR tools) | Moderate/High (SCA) | Security Lead | August 5, 2027 | 🟢 Active |
| **SEC-EXP-003** | NPM Audit | GitHub Advisory Database | `frontend/package.json` (Dev tools) | Moderate/High (SCA) | Frontend Lead | August 5, 2027 | 🟢 Active |

---

## 3. Detailed Technical Analysis & Compensating Controls

### SEC-EXP-001: Temporary File Maintenance Flag (`B108`)
* **Finding:** Bandit flags hardcoded `/tmp` path in `MAINTENANCE_FLAG_PATH: str = "/tmp/eduintel_maintenance.flag"`.
* **Vulnerability Class:** CWE-377: Insecure Temporary File Creation.
* **Threat Model:** A local unprivileged process creates a symlink or pre-creates the file to induce denial-of-service or hijack IPC signalling.
* **Architectural Justification (ADR-0009):**
  - The maintenance flag is a system-wide disaster recovery / quiescence signal used by operations during zero-downtime database migrations or failover.
  - The application runtime **only checks for file existence** (`os.path.exists`) and never writes untrusted content or follows untrusted symlinks.
* **Compensating Controls:**
  1. The path is fully configurable via the environment variable `MAINTENANCE_FLAG_PATH`.
  2. Production Docker containers run as a dedicated unprivileged user (`eduintel`) within an isolated Linux filesystem namespace where `/tmp` is mounted with `noexec,nosuid`.
  3. Code is explicitly annotated with `# nosec B108`.

---

### SEC-EXP-002: Python Data Science & ML Dependency Advisory Backlog
* **Finding:** `pip-audit` flags known vulnerabilities in transitive data-science dependencies (`aiohttp`, `pillow`, `pypdf`, `chromadb`, `filelock`, `mlflow`).
* **Vulnerability Class:** CWE-400 (DoS), CWE-20 (Input Validation), CWE-79 (ReDoS).
* **Threat Model:** Malicious PDF, image, or embeddings crafted to exploit parser vulnerabilities.
* **Architectural Justification:**
  - The core production web API relies on FastAPI, Uvicorn, and SQLAlchemy; data science libraries (`mlflow`, `shap`, `datasets`) are not directly in the public ingress request loop.
  - OCR image parsing (`pillow`, `pytesseract`) and RAG indexing are isolated behind strict domain gates.
* **Compensating Controls:**
  1. **SEC-05 Enforced:** Magic byte verification (verifying file signatures for PNG/JPEG) before passing byte buffers to imaging libraries.
  2. **Streaming Limits:** Strict 5 MB payload cutoff on file uploads preventing heap or memory exhaustion.
  3. **Concurrency Throttling:** OCR execution is bounded by an in-process asyncio Semaphore (`MAX_CONCURRENT_OCR_WORKERS=2`) with a strict 10-second timeout.
  4. **Network Fencing:** Outbound network calls from RAG and ML routines are blocked by the loopback-aware network guard.

---

### SEC-EXP-003: Frontend Tooling & Client Transitive Dependencies
* **Finding:** `npm audit` flags advisories in build tools and development dependencies (`vite`, `launch-editor`, `brace-expansion`, `axios`).
* **Vulnerability Class:** CWE-79 (XSS), CWE-94 (Code Injection via Dev Server), CWE-1333 (ReDoS).
* **Threat Model:** Exploit against local Vite development server (`launch-editor`) or Axios fetch adapter prototype pollution.
* **Architectural Justification:**
  - Development tools (`vite`, `launch-editor`, `eslint`) are executed exclusively at build time in CI and developer workstations.
  - The production artifact deployed to web servers consists strictly of compiled static HTML/CSS/JS (`frontend/dist/`), completely eliminating dev server runtime vulnerabilities.
* **Compensating Controls:**
  1. **SEC-11 Enforced:** Automated test verifies that all development credentials, mock login buttons, and demo mode flags are dead-code eliminated from the production build bundle.
  2. **SEC-10 Cookie Security:** Session tokens are transmitted exclusively via `HttpOnly`, `SameSite=Strict` cookies, preventing script access or cross-site theft.
  3. **Strict Input Sanitization:** All user inputs and API responses are rendered through React DOM escaping, preventing DOM-based XSS.

---

## 4. Verification & Continuous Monitoring

In the CI/CD pipeline (`.github/workflows/ci.yml`):
- **Bandit SAST** executes on every push: `bandit -r backend/app/ -ll -ii` (zero tolerance for unexempted Medium/High findings).
- **Gitleaks** scans git history on every pull request to ensure zero API keys or secrets leak.
- **Dependency Auditing** generates audit logs without breaking builds prematurely, allowing planned remediations during quarterly dependency update cycles.
