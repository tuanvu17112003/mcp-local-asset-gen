"""Server configuration (contract ``C1-mcp-asset-tool`` v0.1.0).

Pure stdlib, frozen dataclass, no I/O at import or construction.
``project_root`` is stored as given; containment checks happen per call in
:mod:`src.mcp_server.validation`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Union
from urllib.parse import urlparse

DEFAULT_COMFYUI_URL = "http://127.0.0.1:8188"
DEFAULT_MAX_CONCURRENT = 2
DEFAULT_JOB_TIMEOUT_S = 300.0
SERVER_VERSION = "0.1.0"

#: Hostnames treated as loopback for the default localhost-only policy.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _is_loopback_url(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    return host.lower() in LOOPBACK_HOSTS


@dataclass(frozen=True)
class ServerConfig:
    """MCP server configuration.

    :param project_root: asset jail root; every ``save_path`` must resolve
        inside it (enforced by ``resolve_save_path``).
    :param comfyui_url: ComfyUI base URL. Non-loopback hosts are refused
        unless ``allow_remote`` is explicitly ``True``.
    :param max_concurrent: VRAM guard; jobs beyond this return ``QUEUED``.
    :param job_timeout_s: per-job timeout in seconds.
    :param allow_remote: explicit opt-in to a non-loopback ``comfyui_url``.
    :param version: server version string.
    """

    project_root: Union[str, os.PathLike]
    comfyui_url: str = DEFAULT_COMFYUI_URL
    max_concurrent: int = DEFAULT_MAX_CONCURRENT
    job_timeout_s: float = DEFAULT_JOB_TIMEOUT_S
    allow_remote: bool = False
    version: str = SERVER_VERSION

    def __post_init__(self) -> None:
        root = os.fspath(self.project_root) if isinstance(self.project_root, os.PathLike) else self.project_root
        if not isinstance(root, str) or not root:
            raise ValueError("INVALID_PROJECT_ROOT: project_root must be a non-empty path")
        if not isinstance(self.comfyui_url, str) or not self.comfyui_url:
            raise ValueError("INVALID_COMFYUI_URL: comfyui_url must be a non-empty URL string")
        parsed = urlparse(self.comfyui_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(
                "INVALID_COMFYUI_URL: scheme must be http(s), got %r" % (self.comfyui_url,)
            )
        if not parsed.hostname:
            raise ValueError(
                "INVALID_COMFYUI_URL: no hostname in %r" % (self.comfyui_url,)
            )
        if not self.allow_remote and not _is_loopback_url(self.comfyui_url):
            raise ValueError(
                "INVALID_COMFYUI_URL: non-loopback url %r refused without "
                "explicit allow_remote=True" % (self.comfyui_url,)
            )
        if isinstance(self.max_concurrent, bool) or not isinstance(self.max_concurrent, int):
            raise ValueError(
                "INVALID_MAX_CONCURRENT: must be an int >= 1, got %r" % (self.max_concurrent,)
            )
        if self.max_concurrent < 1:
            raise ValueError(
                "INVALID_MAX_CONCURRENT: must be an int >= 1, got %r" % (self.max_concurrent,)
            )
        if isinstance(self.job_timeout_s, bool) or not isinstance(self.job_timeout_s, (int, float)):
            raise ValueError(
                "INVALID_JOB_TIMEOUT: must be a positive number of seconds, got %r"
                % (self.job_timeout_s,)
            )
        if self.job_timeout_s <= 0:
            raise ValueError(
                "INVALID_JOB_TIMEOUT: must be a positive number of seconds, got %r"
                % (self.job_timeout_s,)
            )
        if not isinstance(self.version, str) or not self.version:
            raise ValueError("INVALID_VERSION: version must be a non-empty string")


__all__ = [
    "ServerConfig",
    "DEFAULT_COMFYUI_URL",
    "DEFAULT_MAX_CONCURRENT",
    "DEFAULT_JOB_TIMEOUT_S",
    "SERVER_VERSION",
    "LOOPBACK_HOSTS",
]
