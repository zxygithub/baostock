# 统一下载脚本设计方案

> 状态：待评审
> 创建日期：2026-07-05

---

## 一、背景

当前项目有两个下载入口脚本：

| 脚本 | 命令 | 用途 |
|------|------|------|
| `scripts/download_all.py` | `./start.sh full` | 全量下载，从历史起点遍历所有数据 |
| `scripts/update_daily.py` | `./start.sh update` | 增量更新，仅更新最近 1-2 个季度 |

两个脚本有大量重复逻辑（周线/月线判断、shutdown 检查等），且用户需要手动选择运行哪个命令。

## 二、目标

1. 合并为一个统一脚本 `scripts/sync.py`
2. 用户只需运行 `./start.sh run`，自动选择最优策略
3. **不遗漏任何数据**（核心约束）
4. 保持向后兼容：`full` 和 `update` 命令仍可用

## 三、当前两个脚本的区别

| 维度 | `download_all.py` (full) | `update_daily.py` (update) |
|------|-------------------------|---------------------------|
| 时间范围 | 从 config 起始日期（如 2007）开始 | 从数据库最大日期 +1 天开始 |
| 数据类型 | 全部 11 个阶段 | 仅 6 个阶段（无宏观、报告、分钟线） |
| 财务数据 | 2007→当前年，所有季度 | 仅当前年的 Q-1 和 Q |
| 分红数据 | 2007→当前年 | 仅当前年 |
| 公司报告 | 有 | 无 |
| 宏观数据 | 有 | 无 |
| 分钟K线 | 有（如开启） | 无 |
| 股票筛选 | `type=1`（所有A股） | `type=1 AND status=1`（仅正常上市） |
| 参数 | `--skip-*`, `--validate`, `--codes-file` | 无 |

## 四、核心原则

**所有数据都从历史起点遍历，但每个下载器都有高效的跳过机制。**

- 遍历全量 = 不会遗漏
- 跳过机制 = 不会重复浪费

## 五、各数据类型跳过机制现状与改进

| 数据类型 | 当前跳过机制 | 改进 |
|---------|-------------|------|
| 元数据 | 无（数据量小，直接覆盖） | 无需改进 |
| 宏观数据 | 无（数据量小，直接覆盖） | 无需改进 |
| 成分股 | 无（数据量小，直接覆盖） | 无需改进 |
| 指数K线 | 无（每次都全量） | **添加**：从 max_date+1 开始 |
| 股票K线（日/周/月） | 从 last_downloaded+1 开始 | 已有，无需改进 |
| 分钟K线 | 无（每次都全量） | **添加**：从 last_downloaded+1 开始 |
| 财务数据 | `_find_missing_quarters` 跳过已有 | 已有，无需改进 |
| 分红数据 | 无（每次都全量） | **添加**：负缓存（7天） |
| 公司报告 | 负缓存（7天） | 已有，无需改进 |

## 六、需要补充的跳过机制

### 6.1 指数K线：添加增量逻辑

```python
# src/downloaders/index_downloader.py
def download_index_daily(self, start_date=None, end_date=None):
    if start_date is None:
        max_date = self.get_max_date("index_daily")
        if max_date:
            start_date = (datetime.strptime(max_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            start_date = get_index_kline_start_date()
    # ... 下载逻辑
```

### 6.2 分钟K线：添加增量逻辑

```python
# src/downloaders/kline_downloader.py
def download_minute_kline(self, codes, frequency="5", start_date=None):
    if start_date is None:
        start_date = get_kline_start_date("minute")
    
    for code in codes:
        last = self.get_last_downloaded(f"all_stock_{frequency}min", code)
        if last:
            effective_start = max(start_date, 
                (datetime.strptime(last, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d"))
        else:
            effective_start = start_date
        # ... 下载逻辑
```

### 6.3 分红数据：添加负缓存

```python
# src/downloaders/dividend_downloader.py
def download_dividend(self, codes, start_year=None, end_year=None):
    recent_codes = self._get_recently_queried_codes("dividend", days=7)
    
    for code in codes:
        if code in recent_codes:
            continue
        # ... 下载逻辑
```

## 七、统一脚本设计

```python
# scripts/sync.py

def main():
    parser = argparse.ArgumentParser(description="BaoStock data sync")
    parser.add_argument("--force-full", action="store_true",
                        help="Force full download, ignore skip mechanisms")
    parser.add_argument("--skip-kline", action="store_true")
    parser.add_argument("--skip-financial", action="store_true")
    parser.add_argument("--skip-minute", action="store_true")
    parser.add_argument("--skip-macro", action="store_true")
    parser.add_argument("--skip-reports", action="store_true")
    parser.add_argument("--skip-dividend", action="store_true")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--codes-file", default=None)
    parser.add_argument("--log-file", default=None)
    
    logger.info("=== BaoStock Data Sync ===")
    
    # Phase 1: 元数据（每次都全量，数据量小）
    run_meta_download()
    
    # Phase 2: 宏观数据（每次都全量，数据量小）
    if not args.skip_macro:
        run_macro_download()
    
    # Phase 3: 成分股（每次都全量，数据量小）
    run_component_download()
    
    # Phase 4: 指数K线（从 max_date+1 开始）
    if not args.skip_index_kline:
        run_index_kline_download()
    
    # Phase 5: 股票K线（从 last_downloaded+1 开始）
    if not args.skip_kline:
        run_stock_kline_download()
    
    # Phase 6: 分钟K线（从 last_downloaded+1 开始）
    if not args.skip_minute:
        run_minute_kline_download()
    
    # Phase 7: 财务数据（全量遍历，_find_missing_quarters 跳过已有）
    if not args.skip_financial:
        run_financial_download()
    
    # Phase 8: 分红数据（全量遍历，负缓存跳过近期已查）
    if not args.skip_dividend:
        run_dividend_download()
    
    # Phase 9: 公司报告（全量遍历，负缓存跳过近期已查）
    if not args.skip_reports:
        run_report_download()
    
    # Phase 10: 数据验证（可选）
    if args.validate:
        run_validation()
    
    logger.info("=== Sync Complete ===")
```

## 八、向后兼容

保留 `start.sh full` 和 `start.sh update` 命令：

```bash
# start.sh
case "$1" in
    full)
        .venv/bin/python scripts/sync.py --force-full "${@:2}"
        ;;
    update)
        .venv/bin/python scripts/sync.py "${@:2}"
        ;;
    run)
        .venv/bin/python scripts/sync.py "${@:2}"
        ;;
esac
```

- `full`: 强制全量，忽略所有跳过机制（用于数据修复）
- `update` / `run`: 智能全量，使用所有跳过机制

## 九、不遗漏的保证

| 数据类型 | 跳过机制 | 不遗漏保证 |
|---------|---------|-----------|
| K线数据 | 从 `last_downloaded+1` 开始 | 不会遗漏中间日期 |
| 财务数据 | 从 2007 年遍历所有季度，`_find_missing_quarters` 只跳过数据库中**确实存在**的记录 | 不会遗漏任何缺失季度 |
| 分红/报告 | 负缓存只跳过 7 天内查过的 | 超过 7 天会重新查询，不会永久遗漏 |
| 指数K线 | 从 `max_date+1` 开始 | 不会遗漏中间日期 |

## 十、实施步骤

1. **补充跳过机制**（3 个文件）
   - `src/downloaders/index_downloader.py`: 添加增量逻辑
   - `src/downloaders/kline_downloader.py`: 分钟K线添加增量逻辑
   - `src/downloaders/dividend_downloader.py`: 添加负缓存

2. **创建统一脚本**
   - `scripts/sync.py`: 合并 `download_all.py` 和 `update_daily.py`

3. **更新入口脚本**
   - `start.sh`: 添加 `run` 命令，`full` 和 `update` 改为调用 `sync.py`

4. **测试验证**
   - 运行 `./start.sh run`，验证数据完整性
   - 对比 `full` 和 `run` 的结果

5. **清理旧脚本**
   - 删除 `scripts/download_all.py` 和 `scripts/update_daily.py`
   - 更新文档

## 十一、风险与注意事项

1. **负缓存时间窗口**：7 天是经验值，如果财报发布延迟超过 7 天，可能遗漏。建议根据实际数据发布节奏调整。

2. **增量逻辑的正确性**：需要确保 `last_downloaded` 的查询逻辑正确，特别是周线/月线的边界情况。

3. **向后兼容**：旧命令 `full` 和 `update` 必须继续工作，避免破坏现有的 cron 任务。

---

*文档创建时间：2026-07-05*
