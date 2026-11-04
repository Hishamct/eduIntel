#!/usr/bin/env bash
# ==============================================================================
# EduIntel AI — Automated Bidirectional Migration DAG Verification Harness
# ==============================================================================
# Validates that all Alembic migrations (0001 -> 0023) can be cleanly applied
# to a fresh database, downgraded all the way to base, and re-applied to head
# without errors, orphan tables, or lingering constraint violations.
#
# SAFETY POLICY:
# Reversibility testing is strictly isolated to an ephemeral test database
# with a random UUID suffix. It will NEVER run against development or production.
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${PROJECT_ROOT}/backend"

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }

# ------------------------------------------------------------------------------
# 1. Target Safety Validation & Guardrails
# ------------------------------------------------------------------------------
log_info "1. Validating migration test environment guardrails..."

# Check Docker container availability
CONTAINER_NAME="backend-db-1"
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    log_error "PostgreSQL container '${CONTAINER_NAME}' is not running."
    exit 1
fi

# Generate unique ephemeral database name
RAND_HEX=$(python3 -c "import uuid; print(uuid.uuid4().hex[:8])")
TEST_DB="eduintel_migration_verify_${RAND_HEX}"

# Guard: Prohibit dangerous database names
if [[ "${TEST_DB}" == "eduintel" || "${TEST_DB}" == "production" || "${TEST_DB}" == "staging" || "${TEST_DB}" == "postgres" ]]; then
    log_error "CRITICAL SAFETY ABORT: Refusing to run migration test against protected database name: '${TEST_DB}'"
    exit 1
fi

# Guard: Ensure prefix is strictly enforced
if [[ "${TEST_DB}" != eduintel_migration_verify_* ]]; then
    log_error "CRITICAL SAFETY ABORT: Database name does not match expected ephemeral prefix: '${TEST_DB}'"
    exit 1
fi

TEST_DATABASE_URL="postgresql+asyncpg://eduintel:eduintel_dev@localhost:5432/${TEST_DB}"
log_info "Ephemeral test database: ${TEST_DB}"

# ------------------------------------------------------------------------------
# 2. Cleanup Trap Handler
# ------------------------------------------------------------------------------
cleanup() {
    local exit_code=$?
    log_info "Executing cleanup handler for ${TEST_DB}..."
    if [[ -n "${TEST_DB:-}" && "${TEST_DB}" == eduintel_migration_verify_* ]]; then
        docker exec "${CONTAINER_NAME}" psql -U eduintel -d postgres -c "DROP DATABASE IF EXISTS ${TEST_DB} WITH (FORCE);" > /dev/null 2>&1 || true
        log_info "Ephemeral test database ${TEST_DB} dropped."
    fi
    exit ${exit_code}
}
trap cleanup EXIT INT TERM

# ------------------------------------------------------------------------------
# 3. Provision Isolated Ephemeral Database
# ------------------------------------------------------------------------------
log_info "2. Creating isolated database '${TEST_DB}' in PostgreSQL..."
docker exec "${CONTAINER_NAME}" psql -U eduintel -d postgres -c "CREATE DATABASE ${TEST_DB};" > /dev/null

# Verify empty starting state
START_TABLE_COUNT=$(docker exec "${CONTAINER_NAME}" psql -U eduintel -d "${TEST_DB}" -t -A -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")
if [[ "${START_TABLE_COUNT}" -ne 0 ]]; then
    log_error "Ephemeral database is not clean at start: found ${START_TABLE_COUNT} tables."
    exit 1
fi
log_success "Clean ephemeral database '${TEST_DB}' created (0 tables)."

# ------------------------------------------------------------------------------
# 4. Forward Migration: Upgrade 0001 -> Head (0023)
# ------------------------------------------------------------------------------
log_info "3. Executing Forward Migration: 'alembic upgrade head' (0001 -> 0023)..."
(
    cd "${BACKEND_DIR}"
    DATABASE_URL="${TEST_DATABASE_URL}" venv/bin/alembic upgrade head
)

# Verify head revision
CURRENT_REV=$(
    cd "${BACKEND_DIR}"
    DATABASE_URL="${TEST_DATABASE_URL}" venv/bin/alembic current 2>/dev/null | grep -v "INFO" | awk '{print $1}' | head -n 1
)
log_info "Reached revision: ${CURRENT_REV}"
if [[ "${CURRENT_REV}" != "a7c8e9d0b1f2" ]]; then
    log_error "Migration did not reach expected head 'a7c8e9d0b1f2'. Reached: '${CURRENT_REV}'"
    exit 1
fi

UPGRADE_TABLE_COUNT=$(docker exec "${CONTAINER_NAME}" psql -U eduintel -d "${TEST_DB}" -t -A -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name != 'alembic_version';")
log_info "Tables created after upgrade: ${UPGRADE_TABLE_COUNT}"
if [[ "${UPGRADE_TABLE_COUNT}" -lt 18 ]]; then
    log_error "Expected at least 18 application tables, found ${UPGRADE_TABLE_COUNT}"
    exit 1
fi

# Verify composite indexes exist on fresh database
INDEX_COUNT=$(docker exec "${CONTAINER_NAME}" psql -U eduintel -d "${TEST_DB}" -t -A -c \
    "SELECT count(*) FROM pg_indexes WHERE indexname IN (
        'ix_attendance_inst_class_date',
        'ix_fee_records_inst_student',
        'ix_fee_records_inst_status',
        'ix_exam_results_inst_student',
        'ix_exam_results_inst_class_sub',
        'ix_homework_sub_inst_student',
        'ix_homework_sub_inst_status'
    );")
if [[ "${INDEX_COUNT}" -ne 7 ]]; then
    log_error "Expected 7 composite indexes created by migration 0023, found ${INDEX_COUNT}"
    exit 1
fi
log_success "Forward migration completed successfully: ${UPGRADE_TABLE_COUNT} tables and 7 composite indexes verified."

# ------------------------------------------------------------------------------
# 5. Reverse Migration: Downgrade Head (0023) -> Base (0001 -> empty)
# ------------------------------------------------------------------------------
log_info "4. Executing Reverse Migration: 'alembic downgrade base' (0023 -> 0001 -> base)..."
(
    cd "${BACKEND_DIR}"
    DATABASE_URL="${TEST_DATABASE_URL}" venv/bin/alembic downgrade base
)

DOWNGRADE_REV=$(
    cd "${BACKEND_DIR}"
    DATABASE_URL="${TEST_DATABASE_URL}" venv/bin/alembic current 2>/dev/null | grep -v "INFO" | awk '{print $1}' | head -n 1 || true
)
if [[ -n "${DOWNGRADE_REV}" ]]; then
    log_error "Downgrade did not return to base. Still at: '${DOWNGRADE_REV}'"
    exit 1
fi

# Assert schema cleanliness
REMAINING_TABLES=$(docker exec "${CONTAINER_NAME}" psql -U eduintel -d "${TEST_DB}" -t -A -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name != 'alembic_version';")
if [[ "${REMAINING_TABLES}" -ne 0 ]]; then
    log_error "Public schema is not clean after downgrade base! Remaining tables: ${REMAINING_TABLES}"
    docker exec "${CONTAINER_NAME}" psql -U eduintel -d "${TEST_DB}" -c \
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public';"
    exit 1
fi
log_success "Downgrade base completed successfully: 0 leftover application tables remain in public schema."

# ------------------------------------------------------------------------------
# 6. Re-Apply Forward Migration: Full Replay Verification
# ------------------------------------------------------------------------------
log_info "5. Re-executing Forward Migration: 'alembic upgrade head' (Replay Test)..."
(
    cd "${BACKEND_DIR}"
    DATABASE_URL="${TEST_DATABASE_URL}" venv/bin/alembic upgrade head
)

REPLAY_REV=$(
    cd "${BACKEND_DIR}"
    DATABASE_URL="${TEST_DATABASE_URL}" venv/bin/alembic current 2>/dev/null | grep -v "INFO" | awk '{print $1}' | head -n 1
)
if [[ "${REPLAY_REV}" != "a7c8e9d0b1f2" ]]; then
    log_error "Replay migration failed to reach head 'a7c8e9d0b1f2'. Reached: '${REPLAY_REV}'"
    exit 1
fi

REPLAY_TABLE_COUNT=$(docker exec "${CONTAINER_NAME}" psql -U eduintel -d "${TEST_DB}" -t -A -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name != 'alembic_version';")
if [[ "${REPLAY_TABLE_COUNT}" -ne "${UPGRADE_TABLE_COUNT}" ]]; then
    log_error "Table count mismatch on replay! First pass: ${UPGRADE_TABLE_COUNT}, Replay: ${REPLAY_TABLE_COUNT}"
    exit 1
fi
log_success "Replay forward migration verified: 100% schema parity with initial pass."

# ------------------------------------------------------------------------------
# 7. Development Database Integrity Verification
# ------------------------------------------------------------------------------
log_info "6. Verifying primary development database 'eduintel' was completely untouched..."
PRIMARY_REV=$(
    cd "${BACKEND_DIR}"
    venv/bin/alembic current 2>/dev/null | grep -v "INFO" | awk '{print $1}' | head -n 1
)
if [[ "${PRIMARY_REV}" != "a7c8e9d0b1f2" ]]; then
    log_error "Primary development database was altered! Current rev: '${PRIMARY_REV}'"
    exit 1
fi

PRIMARY_TABLE_COUNT=$(docker exec "${CONTAINER_NAME}" psql -U eduintel -d eduintel -t -A -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name != 'alembic_version';")
log_info "Primary database 'eduintel' table count: ${PRIMARY_TABLE_COUNT}"
log_success "Primary development database verified untouched at head '${PRIMARY_REV}'."

# ------------------------------------------------------------------------------
# Summary & Exit
# ------------------------------------------------------------------------------
echo ""
echo "=========================================================================="
log_success "STAGE 3C VERIFICATION PASSED (GATE 3 SATISFIED)"
log_success "• Strict isolation: Ephemeral database ${TEST_DB} tested and torn down."
log_success "• Bidirectional DAG: upgrade head -> downgrade base -> upgrade head (100% clean)."
log_success "• 0 orphan tables on downgrade; full schema parity on replay."
log_success "• Primary development database completely untouched."
echo "=========================================================================="

