#!/usr/bin/env python3
"""Baidu Cloud Backup Script

Compress baostock database and upload to Baidu Pan (百度网盘).
Uses direct API calls with bypy token.

Usage:
    python scripts/backup_to_baidu.py
"""

import os
import io
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

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config_loader import load_config
from src.utils.email_notifier import load_dotenv, load_email_config, send_email

# Force unbuffered output
for _stream in (sys.stdout, sys.stderr):
    if isinstance(_stream, io.TextIOWrapper):
        _stream.reconfigure(line_buffering=True)

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


def cleanup_old_backups(token: str, dir_path: str, keep_count: int = 7) -> int:
    """Remove old backups, keeping only the latest N. Returns number deleted."""
    files = list_remote_files(token, dir_path)
    backup_files = [f for f in files if f.get("server_filename", "").startswith("baostock_backup_")]
    if len(backup_files) <= keep_count:
        return 0
    backup_files.sort(key=lambda x: x.get("mtime", 0), reverse=True)
    deleted = 0
    for f in backup_files[keep_count:]:
        filename = f.get("server_filename")
        if filename:
            logger.info(f"Deleting old backup: {filename}")
            try:
                requests.post(FILE_API_URL,
                    params={"access_token": token, "method": "filemanager", "opera": "delete", "openapi": "xpansdk"},
                    data={"filelist": json.dumps([f"{dir_path}/{filename}"])},
                    timeout=30)
                deleted += 1
            except Exception as e:
                logger.warning(f"Failed to delete {filename}: {e}")
    return deleted


def format_size(nbytes: int) -> str:
    if nbytes >= 1024 ** 3:
        return f"{nbytes / 1024 ** 3:.1f} GB({nbytes:,} 字节)"
    return f"{nbytes / 1024 / 1024:.1f} MB({nbytes:,} 字节)"


def build_subject(run_date: datetime) -> str:
    return f"证券数据baostock百度云备份结果-{run_date.year}年{run_date.month:02d}月{run_date.day:02d}日"


def build_success_text(result: dict) -> str:
    return (
        "证券数据baostock百度云备份已完成。\n"
        "结果:成功\n"
        f"备份时间:{result['started_at'].strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"归档文件:{result['archive_name']}\n"
        f"归档大小:{format_size(result['archive_size'])}\n"
        f"远端路径:{result['remote_path']}\n"
        f"总耗时:{result['duration']:.0f} 秒\n"
        f"保留策略:保留最近 {result['keep_count']} 份,本次清理旧备份 {result['deleted_old']} 份"
    )


def build_failure_text(result: dict) -> str:
    return (
        "证券数据baostock百度云备份失败,请尽快处理。\n"
        "结果:失败\n"
        f"失败阶段:{result['stage']}\n"
        f"错误信息:{result['error']}\n"
        f"备份时间:{result['started_at'].strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"归档文件:{result['archive_name']}\n"
        "详细日志:logs/backup.log"
    )


def notify_result(result: dict, args) -> None:
    """Send backup result email. Never raises; never affects backup exit code."""
    try:
        if getattr(args, "no_email", False):
            logger.info("Email notification skipped (--no-email)")
            return
        cfg = load_config()
        if not cfg.get("email", {}).get("backup_notify", True):
            logger.info("Email notification disabled (email.backup_notify: false)")
            return
        load_dotenv()
        email_cfg = load_email_config()
        if email_cfg is None:
            logger.warning("Email config incomplete in .env, notification skipped")
            return
        subject = build_subject(result["started_at"])
        body = build_success_text(result) if result["success"] else build_failure_text(result)
        if send_email(email_cfg, subject, body):
            logger.info("Notification email sent to %s", email_cfg["receiver"])
        else:
            logger.warning("Notification email not sent (see warning above)")
    except Exception as e:
        logger.warning("Notification error (ignored): %s", e)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Backup baostock to Baidu Pan")
    parser.add_argument("--keep", type=int, default=7, help="Number of backups to keep")
    parser.add_argument("--data-dir", type=str, default="data", help="Data directory")
    parser.add_argument("--no-email", action="store_true", help="Skip email notification")
    args = parser.parse_args()

    started_at = datetime.now()
    t0 = time.time()
    timestamp = started_at.strftime("%Y%m%d_%H%M%S")
    archive_name = f"baostock_backup_{timestamp}.tar.gz"
    result = {
        "success": False,
        "stage": "初始化",
        "error": None,
        "archive_name": archive_name,
        "archive_size": 0,
        "remote_path": f"{BACKUP_DIR}/{archive_name}",
        "duration": 0.0,
        "keep_count": args.keep,
        "deleted_old": 0,
        "started_at": started_at,
    }
    exit_code = 0
    archive_path = None
    token = None

    try:
        data_dir = Path(args.data_dir)
        if not data_dir.exists():
            result["error"] = f"Data directory not found: {data_dir}"
            logger.error(result["error"])
            exit_code = 1
        else:
            try:
                token = load_token()
                logger.info("Token loaded")
            except Exception as e:
                result["error"] = str(e)
                logger.error(str(e))
                exit_code = 1

        if exit_code == 0 and token is not None:
            # Cleanup old archives
            tmp_dir = Path(tempfile.gettempdir())
            for archive in tmp_dir.glob("baostock_backup_*.tar.gz"):
                logger.info(f"Cleaning up: {archive.name}")
                archive.unlink()

            archive_path = tmp_dir / archive_name
            try:
                result["stage"] = "打包"
                create_backup_archive(data_dir, archive_path)
                result["archive_size"] = archive_path.stat().st_size
                logger.info(f"Uploading to: {result['remote_path']}")

                result["stage"] = "上传"
                if upload_file(token, archive_path, result["remote_path"]):
                    result["deleted_old"] = cleanup_old_backups(token, BACKUP_DIR, args.keep)
                    result["success"] = True
                    logger.info("Backup completed successfully!")
                else:
                    result["error"] = "上传失败,详见日志"
                    logger.error("Backup failed!")
                    exit_code = 1
            except Exception as e:
                result["error"] = str(e)
                logger.error(f"Backup failed: {e}")
                exit_code = 1
    finally:
        result["duration"] = time.time() - t0
        if archive_path is not None and archive_path.exists():
            archive_path.unlink()
        notify_result(result, args)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
