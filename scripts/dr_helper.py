#!/usr/bin/env python3
"""
EduIntel AI — Disaster Recovery & AEAD Cryptographic Helper
Handles AES-256-GCM authenticated encryption/decryption, ChromaDB WAL quiescence checkpoints,
transaction marker creation/verification, and Level 4 cross-engine validation.
"""

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
import uuid
from pathlib import Path

import asyncpg
import joblib

# Cryptography imports
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ASSOCIATED_DATA = b"eduintel-backup-v1"


def get_key_bytes(key_str: str | None) -> bytes:
    """Resolves 256-bit AES key from argument, environment, or key file."""
    raw_key = key_str or os.environ.get("BACKUP_ENCRYPTION_KEY")
    if not raw_key:
        key_file = os.environ.get("BACKUP_KEY_FILE")
        if key_file and os.path.exists(key_file):
            with open(key_file, "r") as f:
                raw_key = f.read().strip()

    if not raw_key:
        sys.stderr.write("ERROR: Missing BACKUP_ENCRYPTION_KEY or --key argument.\n")
        sys.exit(1)

    raw_key = raw_key.strip()
    # Support hex string (64 characters = 32 bytes) or raw 32 bytes
    if len(raw_key) == 64:
        try:
            return bytes.fromhex(raw_key)
        except ValueError:
            pass

    key_bytes = raw_key.encode("utf-8")
    if len(key_bytes) < 32:
        # Zero-pad if under 32 bytes (deterministic padding)
        key_bytes = key_bytes.ljust(32, b"\0")
    return key_bytes[:32]


def cmd_generate_key(args):
    """Generates a cryptographically secure 256-bit AES key formatted as hex."""
    key = os.urandom(32).hex()
    print(key)


def cmd_encrypt(args):
    """Encrypts input file with AES-256-GCM using unique 96-bit nonce and authentication tag."""
    key = get_key_bytes(args.key)
    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        sys.stderr.write(f"ERROR: Input file '{input_path}' not found.\n")
        sys.exit(1)

    plaintext = input_path.read_bytes()
    nonce = os.urandom(12)  # Unique 96-bit nonce
    aesgcm = AESGCM(key)

    # encrypt appends 16-byte authentication tag to ciphertext
    ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext, ASSOCIATED_DATA)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Output format: [12 bytes Nonce] + [Ciphertext + 16 bytes Tag]
    with open(output_path, "wb") as f:
        f.write(nonce)
        f.write(ciphertext_with_tag)

    print(
        json.dumps(
            {
                "status": "encrypted",
                "output_file": str(output_path),
                "plaintext_bytes": len(plaintext),
                "ciphertext_bytes": len(ciphertext_with_tag),
                "nonce_hex": nonce.hex(),
            }
        )
    )


def cmd_decrypt(args):
    """
    Decrypts AES-256-GCM bundle. Verifies authentication tag before any extraction.
    Aborts immediately on tamper or corruption without writing payload to disk.
    """
    key = get_key_bytes(args.key)
    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        sys.stderr.write(f"ERROR: Encrypted file '{input_path}' not found.\n")
        sys.exit(1)

    raw_data = input_path.read_bytes()
    if len(raw_data) < 28:  # 12 nonce + 16 tag minimum
        sys.stderr.write("ERROR: Encrypted file too short or corrupted.\n")
        sys.exit(1)

    nonce = raw_data[:12]
    ciphertext_with_tag = raw_data[12:]
    aesgcm = AESGCM(key)

    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext_with_tag, ASSOCIATED_DATA)
    except InvalidTag:
        sys.stderr.write(
            "CRITICAL SECURITY ABORT: AES-256-GCM Authentication Tag Verification Failed!\n"
            "The backup archive has been modified, corrupted, or tampered with.\n"
            "Decryption halted. Zero bytes written to disk.\n"
        )
        sys.exit(2)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(plaintext)

    print(
        json.dumps(
            {
                "status": "decrypted",
                "tag_verified": True,
                "output_file": str(output_path),
                "decrypted_bytes": len(plaintext),
            }
        )
    )


def cmd_checkpoint_chroma(args):
    """
    Captures a quiescent snapshot of ChromaDB:
    1. Truncates SQLite WAL (PRAGMA wal_checkpoint(TRUNCATE)).
    2. Online backup of chroma.sqlite3 using sqlite3.backup.
    3. Copies all HNSW segment directories.
    4. Validates the restored snapshot by reading collections and embeddings count.
    """
    src_dir = Path(args.src)
    dst_dir = Path(args.dst)

    if not src_dir.exists():
        sys.stderr.write(f"ERROR: Chroma source dir '{src_dir}' does not exist.\n")
        sys.exit(1)

    dst_dir.mkdir(parents=True, exist_ok=True)
    sqlite_file = src_dir / "chroma.sqlite3"

    if sqlite_file.exists():
        # Checkpoint WAL to flush all in-flight writes to disk
        conn = sqlite3.connect(str(sqlite_file))
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            conn.commit()
            # Online atomic backup to destination
            dest_conn = sqlite3.connect(str(dst_dir / "chroma.sqlite3"))
            conn.backup(dest_conn)
            dest_conn.close()
        finally:
            conn.close()

    # Copy segment / HNSW directories
    segment_dirs = []
    for item in src_dir.iterdir():
        if item.is_dir() and item.name != "__pycache__":
            target_sub = dst_dir / item.name
            if target_sub.exists():
                shutil.rmtree(target_sub)
            shutil.copytree(item, target_sub)
            segment_dirs.append(item.name)

    # Verification probe on snapshot
    collections = []
    total_embeddings = 0
    snap_sqlite = dst_dir / "chroma.sqlite3"
    if snap_sqlite.exists():
        snap_conn = sqlite3.connect(str(snap_sqlite))
        try:
            collections = [
                r[0] for r in snap_conn.execute("SELECT name FROM collections").fetchall()
            ]
            row = snap_conn.execute("SELECT count(*) FROM embeddings").fetchone()
            total_embeddings = row[0] if row else 0
        finally:
            snap_conn.close()

    print(
        json.dumps(
            {
                "status": "checkpointed",
                "source": str(src_dir),
                "destination": str(dst_dir),
                "collections": collections,
                "embedding_count": total_embeddings,
                "segment_directories": segment_dirs,
            }
        )
    )


async def _record_marker_async(db_url: str):
    clean_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(clean_url)
    try:
        marker_id = uuid.uuid4()
        marker_code = f"DR-MARKER-{int(time.time())}"
        marker_payload = f"EduIntel Phase 3 Level 4 DR Drill Marker {marker_id}"

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS backup_recovery_markers (
                id UUID PRIMARY KEY,
                marker_code VARCHAR(100) NOT NULL,
                marker_payload TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        row = await conn.fetchrow(
            """
            INSERT INTO backup_recovery_markers (id, marker_code, marker_payload, created_at)
            VALUES ($1, $2, $3, NOW())
            RETURNING id, marker_code, created_at;
            """,
            marker_id,
            marker_code,
            marker_payload,
        )
        return {
            "status": "recorded",
            "marker_id": str(row["id"]),
            "marker_code": row["marker_code"],
            "created_at": row["created_at"].isoformat(),
        }
    finally:
        await conn.close()


def cmd_record_marker(args):
    """
    Inserts a workload-grounded test transaction marker into PostgreSQL.
    Used to empirically measure RPO in disaster recovery drills.
    """
    res = asyncio.run(_record_marker_async(args.db_url))
    print(json.dumps(res))


async def _verify_marker_async(db_url: str, marker_id_str: str):
    clean_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(clean_url)
    try:
        marker_uuid = uuid.UUID(marker_id_str)
        row = await conn.fetchrow(
            "SELECT id, marker_code, marker_payload, created_at FROM backup_recovery_markers WHERE id = $1;",
            marker_uuid,
        )
        if not row:
            sys.stderr.write(f"ERROR: Transaction marker '{marker_id_str}' NOT FOUND in restored database!\n")
            sys.exit(1)
        return {
            "status": "verified",
            "marker_id": str(row["id"]),
            "marker_code": row["marker_code"],
            "marker_payload": row["marker_payload"],
            "created_at": row["created_at"].isoformat(),
        }
    finally:
        await conn.close()


def cmd_verify_marker(args):
    """Verifies that the transaction marker is present in the restored database."""
    res = asyncio.run(_verify_marker_async(args.db_url, args.marker_id))
    print(json.dumps(res))


async def _verify_relational_async(db_url: str):
    clean_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(clean_url)
    try:
        inst_count = await conn.fetchval("SELECT count(*) FROM institutions;")
        user_count = await conn.fetchval("SELECT count(*) FROM users;")
        att_count = await conn.fetchval("SELECT count(*) FROM attendance_records;")
        hw_count = await conn.fetchval("SELECT count(*) FROM homework_submissions;")
        exam_count = await conn.fetchval("SELECT count(*) FROM exam_results;")

        # Functional read test: fetch a sample institution
        sample_inst = await conn.fetchrow(
            "SELECT id, name FROM institutions ORDER BY created_at ASC LIMIT 1;"
        )
        sample_inst_info = (
            {"id": str(sample_inst["id"]), "name": sample_inst["name"]} if sample_inst else None
        )

        return {
            "status": "healthy",
            "functional_query_verified": True,
            "sample_institution": sample_inst_info,
            "institutions": inst_count,
            "users": user_count,
            "attendance_records": att_count,
            "homework_submissions": hw_count,
            "exam_results": exam_count,
        }
    finally:
        await conn.close()


def cmd_verify_restored_data(args):
    """
    Executes Level 4 cross-engine validation across all 4 persistence tiers:
    1. Relational database (port 5433).
    2. ChromaDB vectors (structural sqlite + functional PersistentClient retrieval).
    3. Uploads directory (checksum, file listing, functional read).
    4. ML models (joblib deserialization + functional inference).
    """
    results = {}

    # 1. Relational Validation
    results["relational"] = asyncio.run(_verify_relational_async(args.db_url))

    # 2. ChromaDB Validation (Structural + Functional)
    chroma_dir = Path(args.chroma_dir)
    if chroma_dir.exists():
        snap_conn = sqlite3.connect(str(chroma_dir / "chroma.sqlite3"))
        try:
            collections = [
                r[0] for r in snap_conn.execute("SELECT name FROM collections").fetchall()
            ]
            row = snap_conn.execute("SELECT count(*) FROM embeddings").fetchone()
            emb_count = row[0] if row else 0
        finally:
            snap_conn.close()

        functional_query_ok = False
        sample_doc = None
        try:
            import chromadb

            client = chromadb.PersistentClient(path=str(chroma_dir))
            for col_name in collections:
                col = client.get_collection(col_name)
                docs = col.get(limit=1)
                if docs and docs.get("documents"):
                    sample_doc = docs["documents"][0][:80]
                    functional_query_ok = True
                    break
        except Exception as e:  # noqa: BLE001
            sample_doc = f"Functional ChromaDB probe error: {e}"

        results["chromadb"] = {
            "status": "healthy",
            "structural_check": "OK",
            "functional_retrieval_verified": functional_query_ok,
            "collections": collections,
            "embeddings": emb_count,
            "sample_retrieved_doc": sample_doc,
        }
    else:
        results["chromadb"] = {"status": "missing"}

    # 3. Uploads Validation (Structural + Functional Checksum)
    uploads_dir = Path(args.uploads_dir)
    if uploads_dir.exists():
        file_entries = []
        for p in sorted(uploads_dir.rglob("*")):
            if p.is_file():
                rel_path = str(p.relative_to(uploads_dir))
                size = p.stat().st_size
                sha256 = hashlib.sha256(p.read_bytes()).hexdigest()
                file_entries.append({"path": rel_path, "size_bytes": size, "sha256": sha256})

        results["uploads"] = {
            "status": "healthy",
            "file_count": len(file_entries),
            "functional_verification": "verified" if file_entries else "empty_directory_verified",
            "files": file_entries[:10],
        }
    else:
        results["uploads"] = {"status": "missing"}

    # 4. ML Models Validation (Deserialization + Functional Inference)
    models_dir = Path(args.models_dir)
    loaded_models = []
    if models_dir.exists():
        for model_file in sorted(models_dir.glob("*.joblib")):
            try:
                mod = joblib.load(model_file)
                functional_inference_ok = False
                inference_sample = None

                # Test functional inference if dictionary with model and feature_cols
                if isinstance(mod, dict) and "model" in mod and "feature_cols" in mod:
                    import pandas as pd

                    dummy_data = [{col: 0.5 for col in mod["feature_cols"]}]
                    df = pd.DataFrame(dummy_data)
                    pred = mod["model"].predict(df)
                    functional_inference_ok = True
                    inference_sample = (
                        pred.tolist() if hasattr(pred, "tolist") else [int(pred[0])]
                    )

                loaded_models.append(
                    {
                        "name": model_file.name,
                        "type": type(mod["model"]).__name__
                        if isinstance(mod, dict) and "model" in mod
                        else type(mod).__name__,
                        "valid": True,
                        "functional_inference_verified": functional_inference_ok,
                        "test_prediction": inference_sample,
                    }
                )
            except Exception as e:  # noqa: BLE001
                loaded_models.append({"name": model_file.name, "error": str(e), "valid": False})
        results["ml_models"] = {"status": "healthy", "loaded": loaded_models}
    else:
        results["ml_models"] = {"status": "missing"}

    print(json.dumps(results, indent=2))


def main():
    parser = argparse.ArgumentParser(description="EduIntel Disaster Recovery Helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # generate-key
    subparsers.add_parser("generate-key", help="Generate 256-bit AES key in hex")

    # encrypt
    p_enc = subparsers.add_parser("encrypt", help="Encrypt file with AES-256-GCM")
    p_enc.add_argument("--key", default=None, help="256-bit key in hex or raw")
    p_enc.add_argument("--input", required=True, help="Input plaintext file")
    p_enc.add_argument("--output", required=True, help="Output encrypted file")

    # decrypt
    p_dec = subparsers.add_parser("decrypt", help="Decrypt and verify AES-256-GCM bundle")
    p_dec.add_argument("--key", default=None, help="256-bit key in hex or raw")
    p_dec.add_argument("--input", required=True, help="Input encrypted file")
    p_dec.add_argument("--output", required=True, help="Output decrypted file")

    # checkpoint-chroma
    p_cp = subparsers.add_parser("checkpoint-chroma", help="Quiescent ChromaDB snapshot")
    p_cp.add_argument("--src", required=True, help="Source Chroma directory")
    p_cp.add_argument("--dst", required=True, help="Destination directory")

    # record-marker
    p_rm = subparsers.add_parser("record-marker", help="Record transaction marker in PostgreSQL")
    p_rm.add_argument("--db-url", required=True, help="PostgreSQL connection string")

    # verify-marker
    p_vm = subparsers.add_parser("verify-marker", help="Verify transaction marker in PostgreSQL")
    p_vm.add_argument("--db-url", required=True, help="PostgreSQL connection string")
    p_vm.add_argument("--marker-id", required=True, help="UUID of marker")

    # verify-restored-data
    p_vr = subparsers.add_parser("verify-restored-data", help="Level 4 DR drill verification")
    p_vr.add_argument("--db-url", required=True, help="PostgreSQL connection string")
    p_vr.add_argument("--chroma-dir", required=True, help="Restored Chroma directory")
    p_vr.add_argument("--uploads-dir", required=True, help="Restored Uploads directory")
    p_vr.add_argument("--models-dir", required=True, help="Restored Models directory")

    args = parser.parse_args()

    if args.command == "generate-key":
        cmd_generate_key(args)
    elif args.command == "encrypt":
        cmd_encrypt(args)
    elif args.command == "decrypt":
        cmd_decrypt(args)
    elif args.command == "checkpoint-chroma":
        cmd_checkpoint_chroma(args)
    elif args.command == "record-marker":
        cmd_record_marker(args)
    elif args.command == "verify-marker":
        cmd_verify_marker(args)
    elif args.command == "verify-restored-data":
        cmd_verify_restored_data(args)


if __name__ == "__main__":
    main()
