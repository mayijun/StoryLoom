"""扩展层：manifest 与 per-instance 宿主。"""

from storyloom.extensions.host import (
    ExtensionHost,
    ExtensionRegistry,
    host_from_paths,
)
from storyloom.extensions.manifest import (
    BUILTIN_HANDLERS,
    ExtensionManifest,
    ManifestError,
    discover,
    load_manifest,
    validate_manifest,
)

__all__ = [
    "BUILTIN_HANDLERS",
    "ExtensionHost",
    "ExtensionManifest",
    "ExtensionRegistry",
    "ManifestError",
    "discover",
    "host_from_paths",
    "load_manifest",
    "validate_manifest",
]
