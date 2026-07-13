import os
import sys

# 将 backend 根目录加入 Python 路径，使 `import app.*` 在测试中可用
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.dirname(PROJECT_ROOT)
sys.path.insert(0, BACKEND_ROOT)
