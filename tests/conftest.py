"""测试与生产 data/.blacklisted 隔离(评审焦点 3)。

marker_path() 默认指向仓库 data/,真实封禁后跑测试会被启动闸打红;
故 autouse 默认旁路黑名单闸门,需要验证闸门行为的用例显式
`blacklist.set_bypass(False)` 并把 marker_path 指向 tmp_path。
"""

import pytest

from src.utils import blacklist


@pytest.fixture(autouse=True)
def _blacklist_bypass():
    blacklist.set_bypass(True)
    yield
    blacklist.set_bypass(False)
