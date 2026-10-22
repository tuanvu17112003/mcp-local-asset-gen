"""Server configuration (contract ``C1-mcp-asset-tool`` v0.1.5).

Pure stdlib, frozen dataclass, no I/O at import or construction.
``project_root`` is normalized to an absolute path in ``__post_init__``;
containment checks happen per call in :mod:`src.mcp_server.validation`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Union
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
    :param project_roots: named extra jail roots (``{name: abspath}``);
        each value is abspath-normalized and must be an existing
        directory (``INVALID_PROJECT_ROOT`` otherwise). The name
        ``"default"`` is reserved — it always maps to ``project_root``.
    :param comfyui_url: ComfyUI base URL. Non-loopback hosts are refused
        unless ``allow_remote`` is explicitly ``True``.
    :param max_concurrent: VRAM guard; jobs beyond this return ``QUEUED``.
    :param job_timeout_s: per-job timeout in seconds.
    :param allow_remote: explicit opt-in to a non-loopback ``comfyui_url``.
    :param allow_any_path: explicit opt-in that lets an ABSOLUTE
        ``save_path`` land outside every approved root (C1 v0.1.5).
        Default ``False`` — containment stays enforced.
    :param version: server version string.
    """

    project_root: Union[str, os.PathLike]
    comfyui_url: str = DEFAULT_COMFYUI_URL
    max_concurrent: int = DEFAULT_MAX_CONCURRENT
    job_timeout_s: float = DEFAULT_JOB_TIMEOUT_S
    allow_remote: bool = False
    version: str = SERVER_VERSION
    project_roots: Dict[str, str] = field(default_factory=dict)
    allow_any_path: bool = False

    def __post_init__(self) -> None:
        root = os.fspath(self.project_root) if isinstance(self.project_root, os.PathLike) else self.project_root
        if not isinstance(root, str) or not root:
            raise ValueError("INVALID_PROJECT_ROOT: project_root must be a non-empty path")
        absolute_root = os.path.abspath(root)
        if not os.path.isdir(absolute_root):
            raise ValueError(
                "INVALID_PROJECT_ROOT: project_root %r is not an existing directory"
                % (root,)
            )
        object.__setattr__(self, "project_root", absolute_root)
        normalized: Dict[str, str] = dict(self.project_roots) if self.project_roots else {}
        for _name, _path in normalized.items():
            if not isinstance(_name, str) or not _name:
                raise ValueError(
                    "INVALID_PROJECT_ROOT: workspace name must be a non-empty "
                    "string, got %r" % (_name,)
                )
            if _name == "default":
                raise ValueError(
                    "INVALID_PROJECT_ROOT: workspace name %r is reserved "
                    "(it maps to project_root)" % (_name,)
                )
            _raw = os.fspath(_path) if isinstance(_path, os.PathLike) else _path
            if not isinstance(_raw, str) or not _raw:
                raise ValueError(
                    "INVALID_PROJECT_ROOT: workspace %r root must be a "
                    "non-empty path" % (_name,)
                )
            _abs = os.path.abspath(_raw)
            if not os.path.isdir(_abs):
                raise ValueError(
                    "INVALID_PROJECT_ROOT: workspace %r root %r is not an "
                    "existing directory" % (_name, _path)
                )
            normalized[_name] = _abs
        object.__setattr__(self, "project_roots", normalized)
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
        if not isinstance(self.allow_any_path, bool):
            raise ValueError(
                "INVALID_ALLOW_ANY_PATH: allow_any_path must be a bool, got %r"
                % (self.allow_any_path,)
            )

    def workspace_root(self, name: str) -> str:
        """Return the abspath jail root for workspace ``name``.

        ``"default"`` maps to :attr:`project_root`; any other known name
        maps to its configured root. Unknown names raise ``ValueError``
        ``INVALID_WORKSPACE`` (call ``server_info`` for the configured map).
        """
        if name == "default":
            return self.project_root
        try:
            return self.project_roots[name]
        except (KeyError, TypeError):
            raise ValueError(
                "INVALID_WORKSPACE: unknown workspace %r (see server_info "
                "workspaces for the configured names)" % (name,)
            ) from None


__all__ = [
    "ServerConfig",
    "DEFAULT_COMFYUI_URL",
    "DEFAULT_MAX_CONCURRENT",
    "DEFAULT_JOB_TIMEOUT_S",
    "SERVER_VERSION",
    "LOOPBACK_HOSTS",
]
