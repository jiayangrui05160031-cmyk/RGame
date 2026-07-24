"""允许通过 ``python -m rgame`` 启动游戏。"""

from __future__ import annotations

import sys

from main import main


if __name__ == "__main__":
    sys.exit(main())
