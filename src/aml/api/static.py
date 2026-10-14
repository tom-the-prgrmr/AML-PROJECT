"""The built SPA: files from ``ui.dist_dir`` and the ``index.html`` fallback for SPA routes."""

from __future__ import annotations

from pathlib import Path

from fastapi.responses import FileResponse

from aml.common.config import Settings

NOT_BUILT = "web UI is not built: run `npm --prefix web run build`"


def dist_dir(settings: Settings) -> Path | None:
    """The SPA directory, or None when it has no ``index.html`` (not built)."""
    root = settings.path(settings.ui.dist_dir)
    return root if (root / "index.html").is_file() else None


ASSETS_PREFIX = "/assets/"  # Vite's build output; nothing under it is a SPA route


def spa_response(root: Path, url_path: str) -> FileResponse | None:
    """The file at ``url_path`` inside ``root``; a SPA route -> ``index.html``.

    ``None`` for a missing build asset: a stale ``index.html`` asking for an old bundle must get a
    404, not the page itself with status 200.
    """
    base = root.resolve()
    try:
        candidate = (base / url_path.lstrip("/")).resolve()
        is_file = candidate.is_file() and candidate.is_relative_to(base)
    except (ValueError, OSError):  # e.g. a null byte in the path: not a file, never a 500
        is_file = False
    if is_file:
        return FileResponse(candidate)
    return None if url_path.startswith(ASSETS_PREFIX) else FileResponse(base / "index.html")
