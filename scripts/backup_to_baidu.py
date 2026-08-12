#!/usr/bin/env python3
"""Baidu Cloud Backup Script

Compress baostock database and upload to Baidu Pan (百度网盘).
Uses direct API calls with bypy token.

Usage:
    python scripts/backup_to_baidu.py
"""

import os
import sys
import json
import tarfile
import tempfile
import hashlib
import logging
import time
from pathlib import Path
from datetime import datetime

import requests

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Baidu API endpoints
FILE_API_URL = "https://pan.baidu.com/rest/2.0/xpan/file"
UPLOAD_API_URL = "https://d.pcs.baidu.com/rest/2.0/pcs/superfile2"

# Upload limits
CHUNK_SIZE = 4 * 1024 * 1024  # 4MB per chunk
UPLOAD_TIMEOUT = 120  # 2 minutes per chunk
MAX_RETRIES = 3

# Token file (from bypy)
TOKEN_FILE = Path.home() / ".bypy" / "bypy.json"

# Backup directory
BACKUP_DIR = "/apps/bypy/证券数据备份"


def load_token() -> str:
    """Load access token from bypy token file."""
    if not TOKEN_FILE.exists():
        raise RuntimeError(f"Token file not found: {TOKEN_FILE}\nPlease run: python -m bypy info")
    with open(TOKEN_FILE) as f:
        return json.load(f).get("access_token", "")


def create_backup_archive(data_dir: Path, output_path: Path) -> Path:
    """Create tar.gz archive of database files with streaming compression."""
    db_files = ["baostock.db", "baostock.db-shm", "baostock.db-wal"]
    logger.info(f"Creating backup archive: {output_path}")
    with tarfile.open(output_path, "w:gz") as tar:
        for filename in db_files:
            filepath = data_dir / filename
            if filepath.exists():
                tar.add(filepath, arcname=filename)
                logger.info(f"  Added: {filename} ({filepath.stat().st_size:,} bytes)")
            else:
                logger.warning(f"  Skipped (not found): {filename}")
    archive_size = output_path.stat().st_size
    logger.info(f"Archive: {archive_size:,} bytes ({archive_size / 1024 / 1024:.1f} MB)")
    return output_path


def upload_file(token: str, filepath: Path, remote_path: str) -> bool:
    """Upload file to Baidu Pan using streaming reads to avoid OOM."""
    file_size = filepath.stat().st_size
    total_chunks = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE
    logger.info(f"Uploading {filepath.name}: {file_size:,} bytes ({total_chunks} chunks)")

    block_list = []
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            block_list.append(hashlib.md5(chunk).hexdigest())
    logger.info(f"  {len(block_list)} chunk MD5s calculated")

    # Step 1: Precreate
    logger.info("Step 1/3: Precreate...")
    resp = requests.post(FILE_API_URL,
        params={"access_token": token, "method": "precreate", "openapi": "xpansdk"},
        data={"path": remote_path, "size": file_size, "isdir": 0, "autoinit": 1, "rtype": 3, "block_list": json.dumps(block_list)},
        timeout=30)
    result = resp.json()
    if result.get("errno") != 0:
        logger.error(f"Precreate failed: {result}")
        return False
    uploadid = result["uploadid"]
    logger.info(f"  uploadid: {uploadid}")

    # Step 2: Upload chunks
    logger.info("Step 2/3: Uploading chunks...")
    t0 = time.time()
    with open(filepath, "rb") as f:
        for i in range(total_chunks):
            chunk = f.read(CHUNK_SIZE)
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    resp = requests.post(UPLOAD_API_URL,
                        params={"access_token": token, "method": "upload", "type": "tmpfile",
                                "path": remote_path, "uploadid": uploadid, "partseq": i, "openapi": "xpansdk"},
                        files={"file": ("chunk", chunk, "application/octet-stream")},
                        timeout=UPLOAD_TIMEOUT)
                    result = resp.json()
                    if "md5" not in result:
                        raise RuntimeError(f"Chunk {i+1} failed: {result}")
                    logger.info(f"  Chunk {i+1}/{total_chunks} OK")
                    break
                except Exception as e:
                    if attempt == MAX_RETRIES:
                        logger.error(f"Chunk {i+1} failed after {MAX_RETRIES} attempts: {e}")
                        return False
                    logger.warning(f"  Chunk {i+1} attempt {attempt} failed, retrying...")
                    time.sleep(5)
    logger.info(f"  Upload done in {time.time()-t0:.0f}s")

    # Step 3: Create file
    logger.info("Step 3/3: Create file...")
    resp = requests.post(FILE_API_URL,
        params={"access_token": token, "method": "create", "openapi": "xpansdk"},
        data={"path": remote_path, "size": file_size, "isdir": 0, "rtype": 3,
              "uploadid": uploadid, "block_list": json.dumps(block_list)},
        timeout=60)
    result = resp.json()
    if result.get("errno") != 0:
        logger.error(f"Create failed: {result}")
        return False
    logger.info(f"  fs_id: {result.get('fs_id')}")
    return True


def list_remote_files(token: str, dir_path: str) -> list:
    """List files in remote directory."""
    try:
        resp = requests.get(FILE_API_URL,
            params={"access_token": token, "method": "list", "dir": dir_path, "order": "time", "openapi": "xpansdk"},
            timeout=30)
        return resp.json().get("list", [])
    except Exception as e:
        logger.warning(f"Failed to list: {e}")
        return []


def cleanup_old_backups(token: str, dir_path: str, keep_count: int = 7):
    """Remove old backups, keeping only the latest N."""
    files = list_remote_files(token, dir_path)
    backup_files = [f for f in files if f.get("server_filename", "").startswith("baostock_backup_")]
    if len(backup_files) <= keep_count:
        return
    backup_files.sort(key=lambda x: x.get("mtime", 0), reverse=True)
    for f in backup_files[keep_count:]:
        filename = f.get("server_filename")
        if filename:
            logger.info(f"Deleting old backup: {filename}")
            try:
                requests.post(FILE_API_URL,
                    params={"access_token": token, "method": "filemanager", "opera": "delete", "openapi": "xpansdk"},
                    data={"filelist": json.dumps([f"{dir_path}/{filename}"])},
                    timeout=30)
            except Exception as e:
                logger.warning(f"Failed to delete {filename}: {e}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Backup baostock to Baidu Pan")
    parser.add_argument("--keep", type=int, default=7, help="Number of backups to keep")
    parser.add_argument("--data-dir", type=str, default="data", help="Data directory")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        logger.error(f"Data directory not found: {data_dir}")
        sys.exit(1)

    try:
        token = load_token()
        logger.info("Token loaded")
    except Exception as e:
        logger.error(str(e))
        sys.exit(1)

    # Cleanup old archives
    tmp_dir = Path(tempfile.gettempdir())
    for archive in tmp_dir.glob("baostock_backup_*.tar.gz"):
        logger.info(f"Cleaning up: {archive.name}")
        archive.unlink()

    # Create archive
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"baostock_backup_{timestamp}.tar.gz"
    archive_path = tmp_dir / archive_name

    try:
        create_backup_archive(data_dir, archive_path)
        remote_path = f"{BACKUP_DIR}/{archive_name}"
        logger.info(f"Uploading to: {remote_path}")

        if upload_file(token, archive_path, remote_path):
            cleanup_old_backups(token, BACKUP_DIR, args.keep)
            logger.info("Backup completed successfully!")
        else:
            logger.error("Backup failed!")
            sys.exit(1)
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        sys.exit(1)
    finally:
        if archive_path.exists():
            archive_path.unlink()


if __name__ == "__main__":
    main()
