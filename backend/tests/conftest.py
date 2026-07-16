import os
import sys

import pytest

# 将 backend 根目录加入 Python 路径，使 `import app.*` 在测试中可用
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.dirname(PROJECT_ROOT)
sys.path.insert(0, BACKEND_ROOT)


@pytest.fixture(autouse=True)
def _isolate_runtime_settings():
    """每个用例前后清掉 SettingsService 的进程级 DB 快照缓存，并屏蔽环境变量污染。

    pymilvus 在 import 时会执行 load_dotenv()，把 backend/.env 注入 os.environ；
    此后 `Settings(_env_file=None)` 仍会从环境变量读到 .env 的值，
    导致 model_fields_set 随测试执行顺序变化。这里在每个用例前剥离
    Settings 字段对应的环境变量，用例结束后恢复。
    """
    from app.config import Settings
    from app.services.settings_service import SettingsService

    SettingsService.invalidate_cache()
    scrubbed: dict[str, str] = {}
    for name in Settings.model_fields:
        for env_name in (name, name.upper()):
            if env_name in os.environ:
                scrubbed[env_name] = os.environ.pop(env_name)
    yield
    os.environ.update(scrubbed)
    SettingsService.invalidate_cache()
