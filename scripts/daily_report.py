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

    today = date.today().isoformat()
    cursor = conn.execute("SELECT count FROM request_count WHERE date = ?", (today,))
    row = cursor.fetchone()
    today_requests = row[0] if row else 0

    total_requests = conn.execute("SELECT COALESCE(SUM(count), 0) FROM request_count").fetchone()[0]

    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    counts = {}
    for (t,) in tables:
        try:
            counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except:
            counts[t] = 0

    return conn, today_requests, total_requests, counts

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
def count_trading_days_in_range(trading_days, start, end=None):
    count = 0
    for d in trading_days:
        if d < start:
            continue
        if end and d > end:
            break
        count += 1
    return count


def get_precise_estimates(conn, counts):
    stocks = conn.execute(
        "SELECT code, ipo_date, out_date FROM stock_basic WHERE type = 1"
    ).fetchall()

    trading_days = conn.execute(
        "SELECT calendar_date FROM trade_dates WHERE is_trading_day = 1 ORDER BY calendar_date"
    ).fetchall()
    trading_days = [r[0] for r in trading_days]

    current_year = datetime.now().year
    total_trading_days = len(trading_days)

    est = {}

    total_daily = 0
    total_weekly = 0
    total_monthly = 0
    fin_totals = {t: 0 for t in ["profit_data", "operation_data", "growth_data",
                                   "balance_data", "cash_flow_data", "dupont_data"]}
    div_total = 0
    express_total = 0
    forecast_total = 0

    for code, ipo, out in stocks:
        if not ipo:
            continue
        try:
            ipo_year = int(ipo[:4])
        except (ValueError, IndexError):
            ipo_year = 2007

        days = count_trading_days_in_range(trading_days, ipo, out)
        total_daily += days * 3
        total_weekly += (days // 5) * 3
        total_monthly += (days // 21) * 3

        fin_start = max(2007, ipo_year)
        fin_years = current_year - fin_start + 1
        if fin_years > 0:
            quarters = fin_years * 4
            for t in fin_totals:
                fin_totals[t] += quarters

        div_start = max(2007, ipo_year)
        div_years = current_year - div_start + 1
        if div_years > 0:
            div_total += int(div_years * 0.6)

        rpt_start = max(2003, ipo_year)
        rpt_years = current_year - rpt_start + 1
        if rpt_years > 0:
            express_total += rpt_years
            forecast_total += rpt_years

    est["all_stock_daily"] = total_daily
    est["all_stock_weekly"] = total_weekly
    est["all_stock_monthly"] = total_monthly
    est.update(fin_totals)
    est["dividend"] = div_total
    est["adjust_factor"] = div_total
    est["performance_express"] = express_total
    est["forecast_report"] = forecast_total

    est["index_daily"] = 8 * total_trading_days
    est["index_weekly"] = 8 * (total_trading_days // 5) * 3
    est["index_monthly"] = 8 * (total_trading_days // 21) * 3

    est["stock_basic"] = counts.get("stock_basic", 0) or 9000
    est["trade_dates"] = counts.get("trade_dates", 0) or 13000
    est["stock_industry"] = counts.get("stock_industry", 0) or 6000
    est["sz50_stocks"] = counts.get("sz50_stocks", 0) or 50
    est["hs300_stocks"] = counts.get("hs300_stocks", 0) or 300
    est["zz500_stocks"] = counts.get("zz500_stocks", 0) or 500
    est["deposit_rate"] = 30
    est["loan_rate"] = 30
    est["reserve_ratio"] = 50
    est["money_supply_month"] = 320
    est["money_supply_year"] = 30

    return est


def get_api_request_estimates(conn, precise_est=None):
    """Calculate API request estimates by category.
    
    If precise_est is provided, uses precise per-table estimates for
    K-line and financial data calculations.
    """
    if precise_est is None:
        precise_est = get_precise_estimates(conn, {})

    stocks = conn.execute(
        "SELECT code, ipo_date, out_date FROM stock_basic WHERE type = 1"
    ).fetchall()
    stock_count = len(stocks)
    ADJUST_FLAGS = 3

    # K线: 1 API call per (stock, frequency, adjustflag), returns all rows for that combo
    kline_req = stock_count * 3 * ADJUST_FLAGS

    # 财务: each (stock, year, quarter) = 1 API request
    fin_tables = ["profit_data", "operation_data", "growth_data",
                  "balance_data", "cash_flow_data", "dupont_data"]
    fin_req = sum(precise_est.get(t, 0) for t in fin_tables)

    # 公司报告: 1 API call per stock (fetches all years in one call)
    report_req = stock_count * 2

    # 分红: each stock = 1 API request
    div_req = stock_count

    # 指数K线: 8 indices * 3 frequencies * 3 adjustflags
    index_req = 8 * 3 * 3

    # 宏观 + 元数据
    macro_req = 5
    meta_req = 4

    total = kline_req + fin_req + report_req + div_req + index_req + macro_req + meta_req
    daily_limit = conn.execute("SELECT count FROM request_count WHERE date = date('now')").fetchone()
    today_count = daily_limit[0] if daily_limit else 0

    DAILY_REQUEST_LIMIT = 49000

    return {
        "kline": kline_req,
        "financial": fin_req,
        "reports": report_req,
        "dividend": div_req,
        "index": index_req,
        "macro": macro_req,
        "meta": meta_req,
        "total": total,
        "daily_limit": DAILY_REQUEST_LIMIT,
        "today_count": today_count,
        "days_remaining": round(total / DAILY_REQUEST_LIMIT, 1) if total > 0 else 0,
    }


def get_progress_table(conn, counts):
    estimates = get_precise_estimates(conn, counts)
    api_req = get_api_request_estimates(conn, estimates)

    categories = {
        "K线数据（日/周/月）": ["all_stock_daily", "all_stock_weekly", "all_stock_monthly"],
        "财务数据（6类）": ["profit_data", "operation_data", "growth_data",
                         "balance_data", "cash_flow_data", "dupont_data"],
        "分红与报告": ["dividend", "adjust_factor", "performance_express", "forecast_report"],
        "指数K线": ["index_daily", "index_weekly", "index_monthly"],
        "元数据": ["stock_basic", "trade_dates", "stock_industry",
                  "sz50_stocks", "hs300_stocks", "zz500_stocks"],
        "宏观数据": ["deposit_rate", "loan_rate", "reserve_ratio",
                    "money_supply_month", "money_supply_year"],
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

    return rows_html, api_req

# ---------------------------------------------------------------------------
# Email Generation & Sending
# ---------------------------------------------------------------------------
def build_email(sender, start_time, end_time, today_requests, total_requests,
                blacklist_status, blacklist_detail, table_rows, api_req):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"BaoStock 数据下载日报 ({date.today().strftime('%Y-%m-%d')})"
    msg["From"] = sender

    pct_used = (today_requests / api_req["daily_limit"] * 100) if api_req["daily_limit"] else 0
    est_days = api_req["days_remaining"]

    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 20px; color: #333; margin: 0; }}
            h2 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; margin-top: 0; }}
            h3 {{ color: #2c3e50; margin: 20px 0 12px 0; font-size: 16px; }}
            .info-cards {{ display: flex; gap: 16px; margin-bottom: 20px; }}
            .card {{ flex: 1; background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 16px; }}
            .card p {{ margin: 8px 0; font-size: 14px; }}
            .card-label {{ font-weight: bold; color: #555; }}
            .status-ok {{ color: #27ae60; font-weight: bold; }}
            .status-warn {{ color: #f39c12; font-weight: bold; }}
            .status-error {{ color: #e74c3c; font-weight: bold; }}
            .api-card {{ background: #e8f4f8; }}
            .api-card h3 {{ margin-top: 0; }}
            .api-card p {{ margin: 6px 0; font-size: 14px; }}
            .api-divider {{ border-top: 1px solid #b0d4e8; margin: 10px 0; }}
            table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
            th {{ background: #2c3e50; color: white; padding: 10px 8px; text-align: left; }}
            td {{ padding: 8px; border-bottom: 1px solid #eee; }}
            .cat {{ font-weight: bold; color: #555; background: #f4f4f4; }}
            .num {{ text-align: right; font-family: monospace; }}
            tr:hover {{ background: #f9f9f9; }}
            .footer {{ margin-top: 30px; color: #7f8c8d; font-size: 12px; }}
        </style>
    </head>
    <body>
        <h2>📊 BaoStock 数据下载状态日报</h2>

        <div class="info-cards">
            <div class="card">
                <p><span class="card-label">⏱️ 最近一次拉取开始时间:</span> {start_time}</p>
                <p><span class="card-label">⏱️ 最近一次拉取结束时间:</span> {end_time}</p>
                <p><span class="card-label">📈 今日已使用请求次数:</span> {today_requests:,} 次 ({pct_used:.0f}%)</p>
                <p><span class="card-label">📊 累计总请求次数:</span> {total_requests:,} 次</p>
                <p><span class="card-label">🛡️ 黑名单状态:</span> <span class="{'status-ok' if '正常' in blacklist_status else 'status-error'}">{blacklist_status}</span> - {blacklist_detail}</p>
            </div>
            <div class="card api-card">
                <h3>🧮 API 请求估算（基于 IPO 日期精确计算）</h3>
                <p><strong>K 线（日/周/月 × 3 复权）:</strong> {api_req["kline"]:,} 次</p>
                <p><strong>财务数据（按 IPO 年份）:</strong> {api_req["financial"]:,} 次</p>
                <p><strong>公司报告:</strong> {api_req["reports"]:,} 次</p>
                <p><strong>分红数据:</strong> {api_req["dividend"]:,} 次</p>
                <p><strong>指数 K 线:</strong> {api_req["index"]:,} 次</p>
                <p><strong>宏观 + 元数据:</strong> {api_req["macro"] + api_req["meta"]:,} 次</p>
                <div class="api-divider"></div>
                <p><strong>总请求数:</strong> {api_req["total"]:,} 次 | <strong>按 49,000 次/天:</strong> 约 {est_days} 天</p>
            </div>
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

        <p class="footer">
            此邮件由 BaoStock 自动报告系统生成。<br>
            预估总量基于每只股票的实际 IPO 日期和交易日历精确计算，非统一起始日期估算。
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

    conn, today_requests, total_requests, counts = get_db_stats()
    start_time, end_time = get_latest_download_times()
    blacklist_status, blacklist_detail = check_blacklist_status()
    table_rows, api_req = get_progress_table(conn, counts)

    msg = build_email(
        email_cfg["sender"], start_time, end_time, today_requests, total_requests,
        blacklist_status, blacklist_detail, table_rows, api_req
    )
    send_email(email_cfg, msg)
    conn.close()

if __name__ == "__main__":
    main()
