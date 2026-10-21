"""Slice 1 tests: schemas + config + validation + error taxonomy.

Pure stdlib + pytest (no fastmcp, no model downloads).
"""

from __future__ import annotations

import pytest

from src.mcp_server import __version__
from src.mcp_server.config import ServerConfig
from src.mcp_server.errors import (
    BackendUnavailableError,
    ERROR_CODES,
    GenerationFailedError,
    McpServerError,
    ModelMissingError,
    PolicyDeniedError,
    PostprocessFailedError,
    QueuedError,
    error_class_for_sibling_code,
    translate_sibling_error,
)
from src.mcp_server.schemas import (
    BEAR_AVATAR_EXAMPLE,
    GENERATE_APP_ASSET_SCHEMA,
    PATH_ESCAPE_EXAMPLE,
    REFINE_ASSET_SCHEMA,
    SERVER_INFO_SCHEMA,
)
from src.mcp_server.validation import resolve_save_path, validate_tool_args


def test_package_version():
    assert __version__ == "0.1.0"


def test_error_codes_distinct_and_shaped():
    assert sorted(ERROR_CODES) == sorted(
        [
            "BACKEND_UNAVAILABLE",
            "MODEL_MISSING",
            "POLICY_DENIED",
            "GENERATION_FAILED",
            "POSTPROCESS_FAILED",
            "QUEUED",
        ]
    )
    for cls, code in [
        (BackendUnavailableError, "BACKEND_UNAVAILABLE"),
        (ModelMissingError, "MODEL_MISSING"),
        (PolicyDeniedError, "POLICY_DENIED"),
        (GenerationFailedError, "GENERATION_FAILED"),
        (PostprocessFailedError, "POSTPROCESS_FAILED"),
        (QueuedError, "QUEUED"),
    ]:
        assert issubclass(cls, McpServerError)
        assert cls.code == code
        assert code in str(cls("boom"))


def test_generate_schema_shape():
    props = GENERATE_APP_ASSET_SCHEMA["input_schema"]["properties"]
    required = GENERATE_APP_ASSET_SCHEMA["input_schema"]["required"]
    assert required == ["prompt", "category", "save_path"]
    for field in [
        "prompt",
        "category",
        "save_path",
        "width",
        "height",
        "format",
        "remove_bg",
        "style_preset",
        "seed",
        "overwrite",
        "job_id",
    ]:
        assert field in props, field
    assert props["category"]["enum"] == ["icon", "illustration", "avatar", "splash"]
    assert props["format"]["enum"] == ["png", "svg"]
    assert props["style_preset"]["enum"] == ["flat", "clay", "line", "pixel"]
    out_required = GENERATE_APP_ASSET_SCHEMA["output_schema"]["required"]
    assert out_required == [
        "asset_path",
        "width",
        "height",
        "format",
        "seed",
        "style_preset",
        "job_id",
    ]


def test_refine_and_server_info_schema_shape():
    refine_in = REFINE_ASSET_SCHEMA["input_schema"]
    assert refine_in["required"] == ["instruction"]
    assert refine_in["anyOf"] == [{"required": ["asset_id"]}, {"required": ["asset_path"]}]
    assert REFINE_ASSET_SCHEMA["output_schema"]["required"] == [
        "asset_path",
        "job_id",
        "parent_job_id",
    ]
    assert SERVER_INFO_SCHEMA["input_schema"]["properties"] == {}
    assert SERVER_INFO_SCHEMA["output_schema"]["required"] == [
        "backend",
        "comfyui_url",
        "models",
        "version",
        "project_root",
        "reachable",
        "queue_depth",
    ]


@pytest.mark.parametrize(
    "evil",
    ["../../etc/pass.png", "/etc/pass.png", "a/../../b.png", "..\\windows\\x.png", "C:/evil.png"],
)
def test_path_escape_rejected(tmp_path, evil):
    with pytest.raises(PolicyDeniedError) as excinfo:
        resolve_save_path(evil, tmp_path)
    assert "POLICY_DENIED" in str(excinfo.value)
    with pytest.raises(PolicyDeniedError):
        validate_tool_args("p", "avatar", evil)


def test_golden_escape_example_rejected(tmp_path):
    with pytest.raises(PolicyDeniedError) as excinfo:
        resolve_save_path(PATH_ESCAPE_EXAMPLE["save_path"], tmp_path)
    assert excinfo.value.code == "POLICY_DENIED"


def test_overwrite_refusal(tmp_path):
    target = tmp_path / "assets" / "x.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"png")
    rel = "assets/x.png"
    with pytest.raises(PolicyDeniedError) as excinfo:
        resolve_save_path(rel, tmp_path)
    assert "overwrite" in str(excinfo.value).lower()
    ok = resolve_save_path(rel, tmp_path, overwrite=True)
    assert ok.name == "x.png"
    fresh = resolve_save_path("assets/new.png", tmp_path)
    assert str(fresh).endswith("new.png")


def test_bear_avatar_example_passes():
    args = validate_tool_args(**BEAR_AVATAR_EXAMPLE)
    assert args["category"] == "avatar"
    assert args["save_path"] == "assets/images/bear_avatar.png"
    assert args["remove_bg"] is True
    assert args["width"] == 512 and args["height"] == 512
    assert args["format"] == "png"
    assert args["style_preset"] == "flat"


@pytest.mark.parametrize(
    "category,expected",
    [("icon", True), ("avatar", True), ("illustration", False), ("splash", False)],
)
def test_remove_bg_defaults(category, expected):
    args = validate_tool_args("p", category, "a/b.png")
    assert args["remove_bg"] is expected


def test_param_validation_messages():
    with pytest.raises(ValueError, match="INVALID_CATEGORY"):
        validate_tool_args("p", "logo", "a/b.png")
    with pytest.raises(ValueError, match="INVALID_WIDTH"):
        validate_tool_args("p", "icon", "a/b.png", width=0)
    with pytest.raises(ValueError, match="INVALID_HEIGHT"):
        validate_tool_args("p", "icon", "a/b.png", height=-1)
    with pytest.raises(ValueError, match="INVALID_FORMAT"):
        validate_tool_args("p", "icon", "a/b.png", format="jpg")
    with pytest.raises(ValueError, match="INVALID_STYLE_PRESET"):
        validate_tool_args("p", "icon", "a/b.png", style_preset="oil")
    with pytest.raises(ValueError, match="INVALID_SEED"):
        validate_tool_args("p", "icon", "a/b.png", seed=-1)
    with pytest.raises(ValueError, match="INVALID_PROMPT"):
        validate_tool_args("  ", "icon", "a/b.png")


def test_error_code_mapping_spot_checks():
    assert error_class_for_sibling_code("COMFY_UNREACHABLE") is BackendUnavailableError
    assert error_class_for_sibling_code("MODEL_NOT_FOUND") is ModelMissingError
    assert error_class_for_sibling_code("QUEUE_FULL") is QueuedError
    assert error_class_for_sibling_code("JOB_FAILED") is GenerationFailedError
    assert error_class_for_sibling_code("JOB_TIMEOUT") is GenerationFailedError
    assert error_class_for_sibling_code("DECODE_FAILED") is PostprocessFailedError
    assert error_class_for_sibling_code("SEGMENTATION_FAILED") is PostprocessFailedError
    assert error_class_for_sibling_code("LICENSE_REQUIRED") is PostprocessFailedError
    with pytest.raises(KeyError):
        error_class_for_sibling_code("NOPE_UNKNOWN")


def test_translate_sibling_error():
    class FakeBackendErr(Exception):
        code = "QUEUE_FULL"

        def __init__(self):
            super().__init__("QUEUE_FULL: saturated")
            self.job_id = "j1"

    out = translate_sibling_error(FakeBackendErr())
    assert isinstance(out, QueuedError)
    assert out.code == "QUEUED"
    assert out.job_id == "j1"


def test_server_config_defaults_and_remote_policy(tmp_path):
    cfg = ServerConfig(project_root=str(tmp_path))
    assert cfg.comfyui_url == "http://127.0.0.1:8188"
    assert cfg.max_concurrent == 2
    assert cfg.job_timeout_s == 300
    assert cfg.version == "0.1.0"
    with pytest.raises(ValueError, match="allow_remote"):
        ServerConfig(project_root=str(tmp_path), comfyui_url="http://192.168.1.10:8188")
    ok = ServerConfig(
        project_root=str(tmp_path),
        comfyui_url="http://192.168.1.10:8188",
        allow_remote=True,
    )
    assert ok.allow_remote is True
    with pytest.raises(ValueError, match="INVALID_MAX_CONCURRENT"):
        ServerConfig(project_root=str(tmp_path), max_concurrent=0)
