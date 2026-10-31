# EduIntel AI — Master Documentation Index

Welcome to the central technical documentation repository for **EduIntel AI**. This documentation tree serves as the authoritative source of truth for software engineers, database architects, DevOps specialists, and academic stakeholders.

---

## 📚 Documentation Structure

```
docs/
├── README.md                           # This master documentation index
├── project/
│   ├── purpose-and-scope.md            # Vision, business requirements, personas & scope boundaries
│   └── feature-matrix.md               # Implementation status across 16 backend modules & 21 pages
├── architecture/
│   ├── system-overview.md              # System context, data topology, component interaction
│   ├── backend-modules.md              # Detailed guide to all 16 backend domain modules
│   └── adr/                            # Architecture Decision Records
│       ├── 0001-modular-monolith-pattern.md
│       ├── 0002-async-sqlalchemy-fastapi.md
│       ├── 0003-chromadb-vector-store.md
│       ├── 0004-langgraph-agent-orchestration.md
│       ├── 0005-multi-institution-tenant-isolation.md
│       └── 0006-cloud-database-target-rds-vs-supabase.md
├── api/
│   ├── conventions.md                  # REST conventions, status codes, JSON format & auth headers
│   └── route-inventory.md              # Complete catalog of all 57 endpoints across 16 routers
├── database/
│   ├── schema-and-erd.md               # 19 PostgreSQL tables, relationships, indexes & Mermaid ERD
│   └── migrations.md                   # Alembic migration history (20 revisions) and hygiene
├── security/
│   ├── auth-and-rbac.md                # JWT authentication, role enforcement & Phase 0A SQLi containment
│   └── guardrails-and-pii.md           # PII redaction, prompt injection defense, audit logs & anti-cheating
├── ai/
│   ├── rag-architecture.md             # Dual vector collections, Gemini embeddings & Socratic flow
│   ├── agents.md                       # LangGraph state machines, Admin Assistant & MCP server
│   └── machine-learning.md             # XGBoost at-risk models, SHAP explainability & MLflow
├── development/
│   ├── local-setup.md                  # Local development installation, environment variables & Docker
│   └── standards-and-workflow.md       # Git branching, commit conventions, code formatting & review rules
├── testing/
│   └── testing-strategy.md             # Pytest harness, test suites, mock strategies & coverage gaps
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
- **[Route Inventory](api/route-inventory.md)**: Full inventory of 57 API endpoints with HTTP verbs, path parameters, role requirements, request schemas, and responses.

### 🗄️ 4. Data & Persistence
- **[Schema and ERD](database/schema-and-erd.md)**: PostgreSQL relational models, data types, constraints, foreign key mappings, and entity relationship diagrams.
- **[Database Migrations](database/migrations.md)**: Alembic migration sequence, baseline history, downgrade capabilities, and migration hygiene guidelines.

### 🛡️ 5. Security & Governance
- **[Authentication & RBAC](security/auth-and-rbac.md)**: Password hashing with bcrypt, JWT token issuance via `HttpOnly` cookies, dual-mode auth, FastAPI role-enforcing dependencies, and privilege escalation mitigations.
- **[AI Guardrails & PII](security/guardrails-and-pii.md)**: Automated PII redaction engine (Aadhaar, phone, email, IP, credit cards), prompt injection defenses, and Socratic anti-cheating mechanisms.
- **[Security Audit & Remediation Tracker](security/security-audit.md)**: Comprehensive vulnerability catalog and Phase 2B remediation tracker for SEC-01 through SEC-19.
- **[Authorization Matrix](security/authorization-matrix.md)**: Complete endpoint-by-endpoint RBAC and multi-factor relational ownership matrix.
- **[Phase 2B Security Closure Report](production-readiness/06-phase-2b-security-remediation-closure-report.md)**: Final signed-off closure report detailing the 10 remediated findings, 278 backend test cases, and 8 frontend test cases.
- **[Multi-Tenant Architecture](architecture/multi-tenant-architecture.md)**: Foundational multi-tenant isolation specifications and schema partitioning design for Phase 2C.

### 🤖 6. Artificial Intelligence & Analytics
- **[RAG Architecture](ai/rag-architecture.md)**: Vector embedding pipelines using Google Gemini, persistent ChromaDB collections, chunking strategies, and Socratic query synthesis.
- **[AI Agents & Tools](ai/agents.md)**: LangGraph state machines, Admin Assistant reporting tools, Portal documentation retrieval, and FastMCP protocol servers.
- **[Machine Learning & Diagnostics](ai/machine-learning.md)**: XGBoost classification pipelines for at-risk student detection, weak topic prediction, SHAP attribution, and MLflow logging.

### 🛠️ 7. Engineering & DevOps
- **[Local Development Setup](development/local-setup.md)**: Step-by-step developer onboarding, Docker configurations, virtual environment setup, and verification checks.
- **[Engineering Standards](development/standards-and-workflow.md)**: Coding conventions, Git branching strategy, semantic versioning, and commit conventions.
- **[Testing Strategy](testing/testing-strategy.md)**: Test execution instructions, pytest fixtures, unit/integration boundaries, and mocking protocols.
- **[Docker Architecture](deployment/docker-architecture.md)**: Container topology, volume persistence, multi-stage build patterns, and environment variable isolation.
- **[Deployment Topology](deployment/deployment-topology.md)**: Deployment topology (decommissioned AWS, current local development, proposed Phase 8 cloud architecture).
- **[Backup & Recovery](operations/backup-and-recovery.md)**: Comprehensive backup scripts (`pg_dump`, ChromaDB sync, upload archiving), restoration runbooks, and recovery verification.
- **[Observability & Monitoring](operations/observability.md)**: LLM token tracking, INR expenditure calculations, trace logs, and future Prometheus/Grafana integrations.

---

## 📌 Document Conventions

1. **Source of Truth**: All documentation reflects the *actual verified state* of the codebase on branch `develop/production-readiness`. Where features or capabilities are planned or in-progress, they are explicitly labeled as such.
2. **Mermaid Diagrams**: Diagrams are authored in standard Mermaid markdown blocks. If viewing locally in editors without native Mermaid rendering, refer to the HTML viewer or GitHub/GitLab markdown previews.
3. **Paths & File Links**: All code references include repository-relative paths to facilitate direct source inspection.

