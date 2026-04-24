#!/usr/bin/env python
"""BaoStock daily download status email report.

Generates and sends an HTML email with download progress statistics.
Designed to be run daily via cron at 07:00.

Usage:
    python scripts/daily_report.py
"""

import sys
import re
import os
import smtplib
import sqlite3
import baostock as bs
from pathlib import Path
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "data" / "baostock.db"
LOG_DIR = PROJECT_ROOT / "logs"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
ENV_PATH = PROJECT_ROOT / ".env"

def load_dotenv():
    """Load environment variables from .env file if it exists."""
    if not ENV_PATH.exists():
        return
    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def load_config():
    if not CONFIG_PATH.exists():
        print(f"Config not found: {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)

def get_email_config(cfg):
    email_cfg = cfg.get("email", {})
    if not email_cfg.get("enabled"):
        print("Email reporting is disabled. Set email.enabled: true in config.yaml")
        sys.exit(0)
    
    # 优先使用环境变量，保护敏感信息
    email_cfg["sender"] = os.getenv("EMAIL_SENDER", email_cfg.get("sender", ""))
    email_cfg["password"] = os.getenv("EMAIL_PASSWORD", email_cfg.get("password", ""))
    email_cfg["receiver"] = os.getenv("EMAIL_RECEIVER", email_cfg.get("receiver", ""))
    
    required = ["smtp_server", "smtp_port", "sender", "password", "receiver"]
    missing = [k for k in required if not email_cfg.get(k)]
    if missing:
        print(f"Missing email config keys: {missing}")
        print("Please set them in config.yaml or environment variables (EMAIL_SENDER, EMAIL_PASSWORD, etc.)")
        sys.exit(1)
    return email_cfg

# ---------------------------------------------------------------------------
# Database Statistics
# ---------------------------------------------------------------------------
def get_db_stats():
    conn = sqlite3.connect(str(DB_PATH))
    
    # Request count
    today = date.today().isoformat()
    cursor = conn.execute("SELECT count FROM request_count WHERE date = ?", (today,))
    row = cursor.fetchone()
    today_requests = row[0] if row else 0
    
    # Active stocks & trading days
    active_stocks = conn.execute("SELECT COUNT(*) FROM stock_basic WHERE type = 1 AND status = 1").fetchone()[0]
    trading_days = conn.execute("SELECT COUNT(*) FROM trade_dates WHERE is_trading_day = 1").fetchone()[0]
    current_year = datetime.now().year
    financial_years = current_year - 2007 + 1
    
    # Table row counts
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    counts = {}
    for (t,) in tables:
        try:
            counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except:
            counts[t] = 0
            
    conn.close()
    return today_requests, active_stocks, trading_days, financial_years, counts

# ---------------------------------------------------------------------------
# Log Parsing
# ---------------------------------------------------------------------------
def get_latest_download_times():
    if not LOG_DIR.exists():
        return "N/A", "N/A"
        
    # Only match download logs (start with date pattern like 20260424_000501.log)
    logs = sorted([f for f in LOG_DIR.glob("*.log") if re.match(r"2\d{7}_\d{6}\.log", f.name)])
    if not logs:
        return "N/A", "N/A"
        
    latest_log = logs[-1]
    content = latest_log.read_text(encoding="utf-8")
    
    start_time = "N/A"
    end_time = "N/A"
    
    stem = latest_log.stem
    if "_" in stem and len(stem) == 15:
        start_time = f"{stem[:4]}-{stem[4:6]}-{stem[6:8]} {stem[9:11]}:{stem[11:13]}:{stem[13:15]}"
        
    end_match = re.search(r'\[(\d{8}_\d{6})\]\s*(DONE|FAILED)', content)
    if end_match:
        ts = end_match.group(1)
        end_time = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}"
        
    return start_time, end_time

# ---------------------------------------------------------------------------
# Blacklist Check
# ---------------------------------------------------------------------------
def check_blacklist_status():
    """Check if current IP/account is blacklisted by BaoStock."""
    try:
        lg = bs.login()
        if lg.error_code == "10001011":
            bs.logout()
            return "❌ 黑名单", "IP 已被列入黑名单 (10001011)"
        if lg.error_code != "0":
            bs.logout()
            return "⚠️ 异常", f"登录失败: {lg.error_msg}"
        
        # Test a simple query
        rs = bs.query_stock_basic(code="sh.600000")
        bs.logout()
        
        if rs.error_code == "10001011":
            return "❌ 黑名单", "查询时被限流或封禁"
        if rs.error_code != "0":
            return "⚠️ 异常", f"查询失败: {rs.error_msg}"
            
        return "✅ 正常", "IP/账号状态正常"
    except Exception as e:
        return "⚠️ 异常", f"检测出错: {e}"

# ---------------------------------------------------------------------------
# Estimate & Progress Calculation
# ---------------------------------------------------------------------------
def get_progress_table(active_stocks, trading_days, financial_years, counts):
    estimates = {
        "all_stock_daily": active_stocks * trading_days * 3,
        "all_stock_weekly": active_stocks * (trading_days // 5) * 3,
        "all_stock_monthly": active_stocks * (financial_years * 12) * 3,
        "profit_data": active_stocks * financial_years * 4,
        "operation_data": active_stocks * financial_years * 4,
        "growth_data": active_stocks * financial_years * 4,
        "balance_data": active_stocks * financial_years * 4,
        "cash_flow_data": active_stocks * financial_years * 4,
        "dupont_data": active_stocks * financial_years * 4,
        "dividend": active_stocks * financial_years * 2,
        "performance_express": active_stocks * financial_years // 2,
        "forecast_report": active_stocks * financial_years // 2,
        "index_daily": 8 * trading_days,
        "index_weekly": 8 * (trading_days // 5),
        "index_monthly": 8 * (financial_years * 12),
        "stock_basic": 9000,
        "trade_dates": 13000,
        "stock_industry": 6000,
        "deposit_rate": 30,
        "loan_rate": 30,
        "reserve_ratio": 50,
        "money_supply_month": 320,
        "money_supply_year": 30,
    }
    
    categories = {
        "K线数据": ["all_stock_daily", "all_stock_weekly", "all_stock_monthly"],
        "财务数据": ["profit_data", "operation_data", "growth_data", "balance_data", "cash_flow_data", "dupont_data"],
        "分红与报告": ["dividend", "performance_express", "forecast_report"],
        "指数数据": ["index_daily", "index_weekly", "index_monthly"],
        "元数据": ["stock_basic", "trade_dates", "stock_industry"],
        "宏观数据": ["deposit_rate", "loan_rate", "reserve_ratio", "money_supply_month", "money_supply_year"],
    }
    
    rows_html = ""
    for cat, tables in categories.items():
        for i, table in enumerate(tables):
            est = estimates.get(table, 0)
            current = counts.get(table, 0)
            pct = (current / est * 100) if est > 0 else 0
            
            if pct >= 100: status, icon = "100%", "✅ 完成"
            elif pct > 50: status, icon = f"{pct:.1f}%", "🟢 进行中"
            elif pct > 10: status, icon = f"{pct:.1f}%", "🟡 进度缓慢"
            elif pct > 0: status, icon = f"{pct:.1f}%", "🔴 几乎未开始"
            else: status, icon = "0%", "⚪ 未开始"
            
            cat_label = cat if i == 0 else ""
            rows_html += f"""
            <tr>
                <td class="cat">{cat_label}</td>
                <td>{table}</td>
                <td class="num">{est:,}</td>
                <td class="num">{current:,}</td>
                <td>{status}</td>
                <td>{icon}</td>
            </tr>"""
            
    return rows_html

# ---------------------------------------------------------------------------
# Email Generation & Sending
# ---------------------------------------------------------------------------
def build_email(sender, start_time, end_time, today_requests, blacklist_status, blacklist_detail, table_rows):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"BaoStock 数据下载日报 ({date.today().strftime('%Y-%m-%d')})"
    msg["From"] = sender
    
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 20px; color: #333; }}
            h2 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
            .summary {{ background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
            .summary p {{ margin: 8px 0; font-size: 15px; }}
            .summary strong {{ color: #2980b9; }}
            .status-ok {{ color: #27ae60; font-weight: bold; }}
            .status-warn {{ color: #f39c12; font-weight: bold; }}
            .status-error {{ color: #e74c3c; font-weight: bold; }}
            table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
            th {{ background: #34495e; color: white; padding: 10px 8px; text-align: left; }}
            td {{ padding: 8px; border-bottom: 1px solid #eee; }}
            .cat {{ font-weight: bold; color: #555; background: #f4f4f4; }}
            .num {{ text-align: right; font-family: monospace; }}
            tr:hover {{ background: #f9f9f9; }}
        </style>
    </head>
    <body>
        <h2>📊 BaoStock 数据下载状态日报</h2>
        
        <div class="summary">
            <p><strong>🕒 最近一次拉取开始时间:</strong> {start_time}</p>
            <p><strong>🏁 最近一次拉取结束时间:</strong> {end_time}</p>
            <p><strong>📈 今日已使用请求次数:</strong> {today_requests:,} 次</p>
            <p><strong>🛡️ 黑名单状态:</strong> <span class="{'status-ok' if '正常' in blacklist_status else 'status-error'}">{blacklist_status}</span> - {blacklist_detail}</p>
        </div>
        
        <h3>数据拉取情况综合评估表</h3>
        <table>
            <thead>
                <tr>
                    <th>数据类别</th>
                    <th>表名</th>
                    <th style="text-align:right">预估总量</th>
                    <th style="text-align:right">当前已拉取</th>
                    <th>完成度</th>
                    <th>状态</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
        
        <p style="margin-top: 30px; color: #7f8c8d; font-size: 12px;">
            此邮件由 BaoStock 自动报告系统生成。<br>
            预估总量基于活跃股票数 × 交易日 × 复权类型动态计算。
        </p>
    </body>
    </html>
    """
    msg.attach(MIMEText(html, "html", "utf-8"))
    return msg

def send_email(cfg, msg):
    smtp_server = cfg["smtp_server"]
    smtp_port = int(cfg["smtp_port"])
    sender = cfg["sender"]
    password = cfg["password"]
    receiver = cfg["receiver"]
    
    msg["To"] = receiver
    
    try:
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            
        server.login(sender, password)
        server.send_message(msg)
        server.quit()
        print(f"✅ Email sent successfully to {receiver}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        sys.exit(1)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    load_dotenv()
    cfg = load_config()
    email_cfg = get_email_config(cfg)
    
    today_requests, active_stocks, trading_days, fin_years, counts = get_db_stats()
    start_time, end_time = get_latest_download_times()
    blacklist_status, blacklist_detail = check_blacklist_status()
    table_rows = get_progress_table(active_stocks, trading_days, fin_years, counts)
    
    msg = build_email(
        email_cfg["sender"], start_time, end_time, today_requests,
        blacklist_status, blacklist_detail, table_rows
    )
    send_email(email_cfg, msg)

if __name__ == "__main__":
    main()
