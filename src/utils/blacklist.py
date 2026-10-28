"""IP 黑名单标记与退避判定的唯一事实源(设计方案组件 1,跨平台)。

自愈性三条不变量(设计方案第 4 章):

① 闸判的是年龄(mtime),不是存在性——窗口一过自动放行,不依赖外部删除者;
② fail-open——文件不存在/stat 抛错/mtime 在未来/JSON 损坏或为空/window<=0
   一律放行,绝不因本地状态问题把下载永久锁死;
③ 退避期内绝不 touch/续期——只有真实观测到服务端返回 10001011 才 arm()。
   若退避判定也刷新 mtime,窗口会被自己无限续期,就真的永远起不来了。

标记内容(JSON)仅供诊断;**mtime 才是年龄的权威信号**,因为
monitor_baostock.sh 只会 `touch`(空文件)或 `rm -f`,必须双向兼容。
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

from src.config import DB_PATH
from src.config_loader import get_blacklist_backoff_minutes

logger = logging.getLogger("baostock")

_BYPASS = False  # --ignore-blacklist / set_bypass(True) 的进程内旁路开关


def marker_path() -> Path:
    """data/.blacklisted,与 monitor_baostock.sh 的标记路径一致;调用时求值。"""
    return DB_PATH.parent / ".blacklisted"


def set_bypass(enabled: bool) -> None:
    """进程内旁路开关(--ignore-blacklist 用);亦支持环境变量
    BAOSTOCK_IGNORE_BLACKLIST=1(monitor 启动进程时无法传旗标)。"""
    global _BYPASS
    _BYPASS = bool(enabled)


def _bypassed() -> bool:
    return _BYPASS or os.environ.get("BAOSTOCK_IGNORE_BLACKLIST") == "1"


def in_backoff(
    marker: Path | None = None,
    now: float | None = None,
) -> tuple[bool, int]:
    """返回 (是否阻塞, 剩余秒数)。严格按 fail-open 六条处理异常。"""
    if _bypassed():
        return False, 0

    window = get_blacklist_backoff_minutes() * 60
    if window <= 0:
        logger.warning("api.blacklist_backoff_minutes <= 0,黑名单闸门视为禁用")
        return False, 0

    path = marker or marker_path()
    try:
        mtime = path.stat().st_mtime
    except OSError as e:
        logger.warning(f"读取黑名单标记失败,视为未封禁(fail-open): {e}")
        return False, 0

    now = time.time() if now is None else now
    age = now - mtime
    if age < 0:
        logger.warning(f"黑名单标记 mtime 在未来(age={age:.0f}s),视为未封禁(fail-open)")
        return False, 0
    if age >= window:
        return False, 0

    # JSON 仅诊断:损坏/为空(monitor touch 形态)回落纯 mtime 判定,不报错
    return True, int(window - age)


def arm(source: str, detail: str = "") -> None:
    """写/刷新封禁标记(唯一写入口,仅在真实观测到 10001011 时调用)。

    读到既有 JSON 则 consecutive_hits += 1 并保留 first_banned_at;
    写失败只 WARN 不抛——标记是诊断辅助,不是正确性依赖。
    """
    path = marker_path()
    now_iso = datetime.now().isoformat(timespec="seconds")
    payload: dict = {}
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError) as e:
        logger.warning(f"读取既有黑名单标记失败,按全新标记写入: {e}")
        payload = {}

    payload.setdefault("first_banned_at", now_iso)
    payload["last_banned_at"] = now_iso
    payload["consecutive_hits"] = int(payload.get("consecutive_hits", 0)) + 1
    payload["source"] = source
    payload["detail"] = detail

    try:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.warning(f"已记录封禁标记 {path}: source={source} detail={detail}")
    except OSError as e:
        logger.warning(f"写入黑名单标记失败(忽略,不影响后续流程): {e}")


def clear() -> None:
    """删除标记(成功 login 后调用);文件不存在时静默。"""
    try:
        marker_path().unlink(missing_ok=True)
    except OSError as e:
        logger.warning(f"清除黑名单标记失败(忽略): {e}")


def describe() -> str:
    """一行人类可读状态,供日志/报错使用。"""
    blocked, remain = in_backoff()
    if not blocked:
        return "黑名单标记: 无或已过期(可正常请求)"
    return f"黑名单标记: 退避中,剩余 {remain // 60} 分钟(标记 {marker_path()})"
