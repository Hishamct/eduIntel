# EduIntel AI — Master Documentation Index

Welcome to the central technical documentation repository for **EduIntel AI**. This documentation tree serves as the authoritative source of truth for software engineers, database architects, DevOps specialists, and academic stakeholders.

---

## 📚 Documentation Structure

```
docs/
├── README.md                           # This master documentation index
├── project/
│   ├── purpose-and-scope.md            # Vision, business requirements, personas & scope boundaries
│   └── feature-matrix.md               # Implementation status across 17 backend modules & 23 pages
├── architecture/
│   ├── system-overview.md              # System context, data topology, component interaction
│   ├── backend-modules.md              # Detailed guide to all 17 backend domain modules
│   └── adr/                            # Architecture Decision Records
│       ├── 0001-modular-monolith-pattern.md
│       ├── 0002-async-sqlalchemy-fastapi.md
│       ├── 0003-chromadb-vector-store.md
│       ├── 0004-langgraph-agent-orchestration.md
│       ├── 0005-multi-institution-tenant-isolation.md
│       └── 0006-cloud-database-target-rds-vs-supabase.md
├── api/
│   ├── conventions.md                  # REST conventions, status codes, JSON format & auth headers
│   └── route-inventory.md              # Complete catalog of all 82+ endpoints across 19 routers
├── database/
│   ├── schema-and-erd.md               # 34 PostgreSQL tables, dual-ledger FinOps, composite indexes & RLS
│   └── migrations.md                   # Alembic migration history (32 revisions) and reversibility
├── security/
│   ├── auth-and-rbac.md                # JWT authentication, HttpOnly cookies, tenant-scoping & RBAC
│   ├── authorization-matrix.md         # Authorization matrix & automated verification suite
│   ├── guardrails-and-pii.md           # Multi-stage guardrails, supervised 150ms ReDoS, PII & anti-cheating
│   ├── security-audit.md               # SEC-01 through SEC-19 vulnerability catalog & remediation tracker
│   └── security-exceptions.md          # Approved SAST, SCA, and dependency vulnerability exception register
├── ai/
│   ├── rag-architecture.md             # Semantic chunking, Request-Level Snapshot deletion & offline eval
│   ├── agents.md                       # LangGraph async state machines, thread tracking & quiescence barrier
│   └── machine-learning.md             # Ed25519 model signing, Laplace PSI drift & unified worksheet generator
├── development/
│   ├── local-setup.md                  # Local development installation, environment variables & Docker
│   └── standards-and-workflow.md       # Git branching, commit conventions, code formatting & review rules
├── testing/
│   └── testing-strategy.md             # Pytest harness (800+ tests), 227 FinOps tests, network guard & ratchet
├── production-readiness/
│   ├── 00-master-engineering-roadmap.md      # Authoritative Master Engineering Roadmap (Phases 00–10)
│   ├── 12-phase-4-testing-and-ci-cd-plan.md   # Authoritative Phase 4 plan, 7-step CI/CD roadmap & evidence
│   ├── 13-phase-4-testing-and-ci-cd-report.md # Final Phase 4 closure report & certification (Phase 04 complete)
│   ├── 14-phase-5-ai-safety-and-governance-plan.md # Authoritative Phase 5 plan & certification (Phase 05 complete)
│   ├── 15-phase-5-step-0-baseline-report.md  # Clean-room baseline measurements (608 tests, 67.13% coverage)
│   ├── 16-phase-5-step-1-execution-report.md # Provider architecture, data governance & tool idempotency
│   ├── 17-phase-5-step-2-execution-report.md # Multi-stage guardrails, supervised ReDoS & lookahead streaming
│   ├── 20-phase-5-step-3-1-execution-report.md # Worksheet generator provider unification (Task P5-03-01)
│   ├── 21-phase-5-step-3-2-execution-report.md # Parent report structured JSON serialization (Task P5-03-02)
│   ├── 23-phase-5-step-3-3-execution-report.md # Durable database sessions, fail-closed DB gates & lifecycle
│   ├── 24-phase-5-step-3-4-execution-report.md # Semantic chunking & Request-Level Snapshot RAG deletion
│   ├── 25-phase-5-step-3-5-execution-report.md # Automated offline RAG quality benchmark & MLflow proxy
│   ├── 31-phase-5-step-3-6-stage-4r-shutdown-quiescence-remediation-report.md # Concurrency & quiescence
│   ├── 32-phase-5-step-3-6-stage-5-offline-rag-benchmark-report.md # Hermetic offline RAG hardening
│   ├── 33-phase-5-step-3-6-stage-6-ml-integrity-drift-report.md # Ed25519 model signing & Laplace PSI drift
│   └── 34-phase-5-step-3-6-stage-7-quota-and-finops-report.md # Dual-ledger quotas, FinOps sweeper & UI
├── deployment/
│   ├── docker-architecture.md          # Docker Compose configurations, volumes & networking
│   └── deployment-topology.md          # Deployment topology: historical AWS, current local, proposed cloud
└── operations/
    ├── backup-and-recovery.md          # Logical backup procedures, ChromaDB snapshots & restore runbook
    └── observability.md                # Telemetry, LLM token & INR cost tracking, trace logging
```

---

## 🗺️ Quick Navigation by Topic

### 🎯 1. Project & Scope
- **[Purpose and Scope](project/purpose-and-scope.md)**: Problem statement, user personas (Student, Teacher, Admin, Parent), academic workflows, and boundary constraints.
- **[Feature Status Matrix](project/feature-matrix.md)**: Exhaustive feature readiness assessment categorized into *Implemented*, *Partially Implemented*, *Planned*, and *Unverified*.

### 🏛️ 2. Architecture & Design
- **[System Overview](architecture/system-overview.md)**: High-level architectural patterns, C4 context diagrams, polyglot persistence architecture.
- **[Backend Modules](architecture/backend-modules.md)**: Four-tier modular monolith layout (Shared, Portal, Intelligence, Cross-Cutting) with module dependency graphs.
- **[Architecture Decision Records (ADRs)](architecture/adr/)**: Formal ADRs documenting foundational technical decisions and proposed architectural evolutions.

### 🔌 3. APIs & Communication
- **[API Conventions](api/conventions.md)**: REST standard practices, response envelope formats, error handling structures, and HTTP status codes.
- **[Route Inventory](api/route-inventory.md)**: Full inventory of 82+ API endpoints across 19 routers including new FinOps tenant analytics and Platform Admin quota controls.

### 🗄️ 4. Data & Persistence
- **[Schema and ERD](database/schema-and-erd.md)**: 34 PostgreSQL relational models, dual-ledger FinOps ledger, session storage, tool idempotency, Migration 0023 composite B-tree indexes, Migration 0025 Row-Level Security policies, and entity relationship diagrams.
- **[Database Migrations](database/migrations.md)**: Alembic migration sequence (32 revisions through `0032_c3d4e5f6a7b8`), baseline history, bidirectional downgrade reversibility, and ephemeral verification harness.
- **[Phase 3 Database Integrity Implementation Plan](production-readiness/09-phase-3-database-integrity-implementation-plan.md)**: Structured plan for async connection pooling resilience, composite indexing, ephemeral migration verification, AEAD encrypted backups, and Level 4 disaster recovery drills.
- **[Phase 3 Database Integrity Closure Report](production-readiness/10-phase-3-database-integrity-report.md)**: Final signed-off closure report certifying completion of Phase 03 across Stages 3A–3E (Verdict: **CERTIFIED PRODUCTION READY**).

### 🛡️ 5. Security & Governance
- **[Authentication & RBAC](security/auth-and-rbac.md)**: Password hashing with bcrypt, JWT token issuance via `HttpOnly` cookies, dual-mode auth, `require_platform_admin` & `require_tenant_role` dependencies, and privilege escalation mitigations.
- **[AI Guardrails & PII](security/guardrails-and-pii.md)**: Automated PII redaction engine (Aadhaar, phone, email, IP, credit cards), multi-stage prompt injection defenses, 150ms supervised ReDoS subprocess isolation, and Socratic anti-cheating mechanisms.
- **[Security Audit & Remediation Tracker](security/security-audit.md)**: Comprehensive vulnerability catalog and Phase 2B remediation tracker for SEC-01 through SEC-19.
- **[Authorization Matrix](security/authorization-matrix.md)**: Complete endpoint-by-endpoint RBAC, institutional scoping, multi-factor relational ownership matrix, and 58-test Grounded Authorization Matrix test suite.
- **[Security Exceptions Register](security/security-exceptions.md)**: Formally approved SAST, SCA, and dependency vulnerability exception register with owners, rationale, and expiry cycles.
- **[Phase 2B Security Closure Report](production-readiness/06-phase-2b-security-remediation-closure-report.md)**: Final signed-off closure report detailing the 10 remediated findings (SEC-01 through SEC-11).
- **[Multi-Tenant Architecture](architecture/multi-tenant-architecture.md)**: Verified multi-tenant isolation specifications, membership model, and PostgreSQL RLS design.
- **[Stage 3 Diff Review & Live RLS Validation](production-readiness/07-stage-3-diff-review-and-rls-validation-report.md)**: Independent diff review and empirical PostgreSQL 16 RLS engine validation report.
- **[Stage 3 Multi-Tenancy Closure Audit](production-readiness/08-stage-3-closure-audit.md)**: Final closure audit certifying completion of Phase 2 Stage 3 (Verdict: **READY TO CLOSE**).
- **[Platform Admin Implementation & Remediation Plan](production-readiness/11-platform-admin-implementation-plan.md)**: Plan, security audit remediation (SEC-01 through SEC-05), Migration 0025 command-specific RLS policies, and final sign-off.

### 🤖 6. Artificial Intelligence & Analytics
- **[Phase 5 AI Safety & Governance Plan & Certification](production-readiness/14-phase-5-ai-safety-and-governance-plan.md)**: Authoritative Phase 5 master plan, 8-step roadmap, and final certification (Verdict: **ACCEPTED**).
- **[Phase 5 Stage 7 Quotas & FinOps Final Report](production-readiness/34-phase-5-step-3-6-stage-7-quota-and-finops-report.md)**: Dual-ledger accounting, canonical lock hierarchy, automated reconciliation sweeper, administrative APIs, and React dashboards.
- **[RAG Architecture](ai/rag-architecture.md)**: Document-aware semantic chunking (`RecursiveCharacterTextSplitter`), Request-Level Authorized Context Snapshot Policy (`DELETION_PENDING` exclusion), and offline hermetic CI evaluation benchmark.
- **[AI Agents & Tools](ai/agents.md)**: LangGraph async state machines (`ainvoke`), recursion limits, `BoundedWorkerPool` dynamic thread tracking, session quiescence barrier, and quota pre-flight reservation.
- **[Machine Learning & Diagnostics](ai/machine-learning.md)**: Ed25519 model weight verification (`manifest.json.sig`), Laplace-smoothed PSI feature drift monitoring, and unified worksheet generation.

### 🛠️ 7. Engineering & DevOps
- **[Local Development Setup](development/local-setup.md)**: Step-by-step developer onboarding, Docker configurations, virtual environment setup, and verification checks.
- **[Engineering Standards](development/standards-and-workflow.md)**: Coding conventions, Git branching strategy, semantic versioning, CI quality gates (Lint, Security, Backend, Frontend), and commit conventions.
- **[Testing Strategy](testing/testing-strategy.md)**: Pytest harness with 800+ backend tests, 227 FinOps tests across 15 suites, savepoint isolation, loopback network guard, coverage ratchet ($\ge 66\%$), and Vitest portal suites.
- **[Phase 4 Testing Suite & CI/CD Implementation Plan](production-readiness/12-phase-4-testing-and-ci-cd-plan.md)**: Authoritative Phase 4 plan, 7-step incremental execution sequence, GitHub Actions CI workflow, and checkpoint verification evidence.
- **[Phase 4 Testing Suite & CI/CD Closure Report](production-readiness/13-phase-4-testing-and-ci-cd-report.md)**: Final signed-off closure report certifying completion of Phase 04 across all 7 steps (Verdict: **CERTIFIED PRODUCTION READY**).
- **[Docker Architecture](deployment/docker-architecture.md)**: Container topology, volume persistence, multi-stage build patterns, and environment variable isolation.
- **[Deployment Topology](deployment/deployment-topology.md)**: Deployment topology (decommissioned AWS, current local development, proposed Phase 8 cloud architecture).
- **[Backup & Recovery](operations/backup-and-recovery.md)**: Authenticated AES-256-GCM backup engine (`scripts/backup.sh`), 4-step quiescence, isolated Level 4 restore sandbox drill (`scripts/restore.sh`), and verified RTO/RPO metrics.
- **[Observability & Monitoring](operations/observability.md)**: Dual-ledger token volume and monetary INR tracking, FinOps sweeper telemetry, trace logs, and future Prometheus/Grafana integrations.

---

## 📌 Document Conventions

1. **Source of Truth**: All documentation reflects the *actual verified state* of the codebase on branch `develop/production-readiness`. Where features or capabilities are planned or in-progress, they are explicitly labeled as such.
2. **Mermaid Diagrams**: Diagrams are authored in standard Mermaid markdown blocks. If viewing locally in editors without native Mermaid rendering, refer to the HTML viewer or GitHub/GitLab markdown previews.
3. **Paths & File Links**: All code references include repository-relative paths to facilitate direct source inspection.

