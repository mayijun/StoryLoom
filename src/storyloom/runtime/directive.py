"""
输出总线：舞台指令。

注意：StageDirective / StageScene / DirectiveKind 已迁至
storyloom.world.state（Layer 0 公共协议层），
这里只做 re-export 以保持旧 import 路径可用。

推荐新代码直接从 storyloom.world.state import。
"""

from storyloom.world.state import (
    DirectiveKind,
    StageDirective,
    StageScene,
)

__all__ = ["DirectiveKind", "StageDirective", "StageScene"]
