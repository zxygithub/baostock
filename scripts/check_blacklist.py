#!/usr/bin/env python
"""Check if current IP/account is blacklisted by BaoStock.

This script attempts to login and make a simple query to verify
if the current connection is blocked or blacklisted.

Usage:
    python scripts/check_blacklist.py
"""

import sys
import baostock as bs


def check_blacklist():
    """Check if current IP/account is blacklisted by BaoStock."""
    print("=" * 60)
    print("  BaoStock 黑名单检测工具")
    print("=" * 60)
    print()

    # Step 1: Check login
    print("[1/3] 尝试登录 BaoStock...")
    lg = bs.login()
    
    if lg.error_code == "10001011":
        print("❌ 登录失败：IP 已被加入黑名单 (error_code: 10001011)")
        print("   建议：")
        print("   - 更换 IP 地址或使用代理")
        print("   - 加入 BaoStock QQ 群寻求帮助")
        print("   - 等待 24 小时后重试")
        bs.logout()
        return False
    
    if lg.error_code != "0":
        print(f"❌ 登录失败：{lg.error_msg}")
        print("   建议：检查网络连接或 BaoStock 服务状态")
        bs.logout()
        return False
    
    print("✅ 登录成功")

    # Step 2: Check simple query
    print()
    print("[2/3] 尝试查询股票基本信息...")
    rs = bs.query_stock_basic(code="sh.600000")
    
    if rs.error_code == "10001011":
        print("❌ 查询失败：IP 已被加入黑名单 (error_code: 10001011)")
        print("   建议：同上")
        bs.logout()
        return False
    
    if rs.error_code != "0":
        print(f"❌ 查询失败：{rs.error_msg}")
        print("   建议：可能是临时网络问题，请稍后重试")
        bs.logout()
        return False
    
    print("✅ 查询成功")

    # Step 3: Check data retrieval
    print()
    print("[3/3] 尝试获取 K 线数据...")
    rs = bs.query_history_k_data_plus(
        code="sh.600000",
        fields="date,close",
        start_date="2026-04-20",
        end_date="2026-04-20",
        frequency="d",
        adjustflag="3",
    )
    
    if rs.error_code == "10001011":
        print("❌ K 线查询失败：IP 已被加入黑名单 (error_code: 10001011)")
        print("   建议：同上")
        bs.logout()
        return False
    
    if rs.error_code != "0":
        print(f"❌ K 线查询失败：{rs.error_msg}")
        print("   建议：可能是临时网络问题，请稍后重试")
        bs.logout()
        return False
    
    # Check if we got data
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    
    if rows:
        print(f"✅ K 线数据获取成功（返回 {len(rows)} 行）")
    else:
        print("⚠️  K 线查询成功但无数据返回（可能是非交易日）")

    # Final result
    print()
    print("=" * 60)
    print("  ✅ 检测结果：当前 IP/账号 状态正常，未被列入黑名单")
    print("=" * 60)
    
    bs.logout()
    return True


if __name__ == "__main__":
    success = check_blacklist()
    sys.exit(0 if success else 1)
