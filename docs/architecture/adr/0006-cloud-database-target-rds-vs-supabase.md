# ADR 0006: Production Database Infrastructure Target — AWS RDS vs. Supabase PostgreSQL

- **Status**: Proposed (Scheduled for Phase 3)
- **Deciders**: EduIntel Engineering Team, Senior Database Architect, AWS Infrastructure Engineer
- **Date**: 2026-10-30

---

## Context and Problem Statement

EduIntel's historical production deployment ran PostgreSQL inside a Docker container on an AWS EC2 instance alongside the FastAPI application and Caddy proxy. That historical deployment has now been fully decommissioned (EC2 instance terminated, EBS volumes deleted, Elastic IP released) following verified local backup and data parity checks. Active development is now 100% local.

Our architectural audit identified critical operational risks with the single-server containerized database topology:
1. **Single Point of Failure (SPOF)**: An EC2 failure, kernel panic, or runaway memory leak took down both the web application and the database simultaneously.
2. **Resource Starvation**: PyTesseract OCR, PyPDF processing, and FastAPI asynchronous worker threads competed with PostgreSQL for CPU cores and memory on a modest EC2 instance (`t3.medium` / `t3.large`).
3. **Backup Risk**: Host-level Docker volume backups depended on custom cron scripts rather than automated point-in-time recovery (PITR) with continuous write-ahead log (WAL) archiving.
4. **Maintenance Overhead**: Engine upgrades, security patching, replication, and failover required manual engineer intervention.

We are evaluating whether to target **AWS RDS for PostgreSQL** or **Supabase PostgreSQL** as our managed database service when deploying to production in Phase 3 and Phase 8.

---

## Comparative Evaluation

| Evaluation Criteria | AWS RDS for PostgreSQL | Supabase Managed PostgreSQL | EC2 Docker Container (Historical) |
|---|---|---|---|
| **High Availability & Failover** | Multi-AZ automated failover with synchronous standby | Automated failover on Pro/Team tiers | None (Single node, manual rebuild) |
| **Backups & Recovery** | Automated daily snapshots + PITR (up to 35 days, 5-min granularity) | Automated daily backups + 7-day PITR on Pro tier | Manual `pg_dump` to host disk |
| **Connection Pooling** | AWS RDS Proxy (serverless, scales connections) | Built-in PgBouncer / Supavisor connection pooler | In-app `asyncpg` pool only |
| **Vector Search Support** | Native `pgvector` extension supported | Native `pgvector` with built-in dashboard & SQL editor | Manual extension compilation required |
| **Row-Level Security (RLS)** | Full PostgreSQL native RLS support | Full native RLS with rich dashboard visualization | Full native RLS supported |
| **Pricing / Cost Profile** | ~$25–$65/mo for `db.t4g.small`/`medium` + storage + IOPS | $25/mo flat Pro Tier (includes 8GB DB, compute, auth, storage) | Bundled into EC2 instance cost |
| **Ecosystem & DevOps Fit** | Fits within unified AWS VPC, CloudWatch metrics, IAM auth | Faster developer onboarding, integrated dashboard, instant API | High operational burden on small team |

---

## Proposed Decision Outcome

We propose migrating to **AWS RDS for PostgreSQL** (or **Supabase Pro Tier** as an alternative if AWS free/startup credits are exhausted).

### Migration Roadmap (Phase 3):
1. **Target Selection**:
   - Primary: **AWS RDS for PostgreSQL 16** (`db.t4g.small` or `db.t4g.medium` with gp3 storage in `ap-south-1` Mumbai region for low latency across Indian coaching institutes).
   - If operating on bootstrap budget without AWS credits, **Supabase Pro** ($25/mo) is the preferred alternative due to built-in PgBouncer and zero management overhead.
2. **Decoupled Architecture**:
   - Decouple the database from the application compute host.
   - Run backend compute on containerized services (AWS ECS/Fargate or a dedicated EC2 instance running only web processes).
3. **Automated Recovery**:
   - Enable 7-day Point-In-Time Recovery (PITR) with automated continuous WAL archiving to S3.
4. **pgvector Convergence**:
   - Leverage native `pgvector` to evaluate converging ChromaDB vector collections directly into PostgreSQL, unifying relational and semantic queries into a single backup lifecycle.

---

## Consequences

### Positive Consequences
- **Zero Compute Interference**: Heavy OCR image preprocessing and PDF chunking will never starve PostgreSQL memory or I/O.
- **Enterprise Disaster Recovery**: Point-in-time recovery guarantees a Recovery Point Objective (RPO) under 5 minutes in case of corruption.
- **Automated Patching**: Security maintenance and OS updates are managed by the cloud provider.

### Negative Consequences
- **Network Latency**: Moving the database off `localhost` introduces 1–3 ms of network round-trip latency per query across the VPC, necessitating rigorous connection pooling and minimizing chatty N+1 queries.
- **Dedicated Hosting Cost**: Incurs a predictable monthly cloud cost ($25–$50/mo) compared to co-locating on a single server.

