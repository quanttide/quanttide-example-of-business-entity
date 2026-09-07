# 量潮课堂工作台——测试夹具：离屏 Qt + 隔离的临时数据库

import os
import sys
from pathlib import Path

import pytest

# src 在路径最前，保证 `import store / workbench` 指向被测代码
SRC = Path(__file__).resolve().parent.parent / 'src'
sys.path.insert(0, str(SRC))

# 必须在任何 Qt 导入之前设置离屏平台
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture()
def tmp_store(tmp_path, monkeypatch):
    """每个测试独享的临时数据库，不触碰 data/ 演示数据。"""
    import store
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'workbench.db')
    return store


@pytest.fixture(scope='session')
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(tmp_store, qapp):
    """被测工作台窗口：面板重建逻辑在真实构造流程中生效。"""
    import workbench
    w = workbench.WorkbenchWindow()
    yield w
    w.close()
