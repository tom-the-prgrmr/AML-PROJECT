"""AC1 of specs/ui-foundation.md: ui config section, dependencies, .gitignore."""

from __future__ import annotations

import tomllib

import pytest
from pydantic import ValidationError

from aml.common.config import load_settings

from .helpers import ROOT

NO_DEFAULT = {"AML__UI__DEFAULT_USER": ""}


def test_ac1_defaults_from_config_yaml() -> None:
    ui = load_settings(environ={}).ui
    assert ui.host == "127.0.0.1"
    assert ui.port == 8000
    assert ui.dist_dir == "web/dist"
    assert ui.users == {"analyst01": "analyst", "supervisor01": "supervisor"}
    assert ui.default_user == "analyst01"
    assert ui.page_size == 50
    assert ui.max_page_size == 200
    assert ui.mock.sample is True


def test_ac1_empty_default_user_is_none() -> None:
    assert load_settings(environ=NO_DEFAULT).ui.default_user is None


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"AML__UI__PORT": "0"}, "ui port must be between 1 and 65535"),
        ({"AML__UI__PAGE_SIZE": "201"}, "ui page_size must be between 1 and max_page_size"),
        ({"AML__UI__DEFAULT_USER": "ghost"}, "ui default_user must be one of ui users"),
        ({"AML__UI__USERS": "{}", **NO_DEFAULT}, "ui users must not be empty"),
        (
            {"AML__UI__USERS": '{"system": "analyst"}', **NO_DEFAULT},
            "ui users must not contain audit.system_actor",
        ),
        ({"AML__UI__USERS": '{"a1": "admin"}', **NO_DEFAULT}, ""),
        ({"AML__UI__MOCK__SAMPLE": "maybe"}, ""),
        ({"AML__UI__MOCK__NO_SUCH_FEATURE": "true"}, ""),
    ],
)
def test_ac1_invalid_ui_settings_rejected(env: dict[str, str], message: str) -> None:
    with pytest.raises(ValidationError) as exc:
        load_settings(environ=env)
    assert message in str(exc.value)


def test_ac1_fastapi_and_uvicorn_importable() -> None:
    import fastapi
    import uvicorn

    assert fastapi is not None
    assert uvicorn is not None


def test_ac1_pyproject_declares_dependencies() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = [d.lower() for d in data["project"]["dependencies"]]
    dev = [d.lower() for d in data["dependency-groups"]["dev"]]
    assert any(d.startswith("fastapi") for d in deps)
    assert any(d.startswith("uvicorn") for d in deps)
    assert any(d.startswith("httpx") for d in dev)


def test_ac1_gitignore_lists_web_build_dirs() -> None:
    lines = [ln.strip() for ln in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
    assert "web/node_modules/" in lines
    assert "web/dist/" in lines
