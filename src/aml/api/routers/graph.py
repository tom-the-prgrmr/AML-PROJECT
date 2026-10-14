"""Case graph endpoint: accounts around a case and the transfers between them (SQL source)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from aml.api import envelope
from aml.api.constants import API_PREFIX
from aml.api.decisions import pii_viewed
from aml.api.deps import current_user, get_app_settings, get_database
from aml.api.identity import User
from aml.api.reads.graph import case_graph
from aml.common.config import Settings
from aml.common.db import Database

FEATURE = "graph"
router = APIRouter(prefix=f"{API_PREFIX}/cases")


@router.get("/{case_id}/graph")
def get_graph(
    case_id: str,
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[Database, Depends(get_database)],
    user: Annotated[User, Depends(current_user)],
) -> JSONResponse:
    graph = case_graph(
        db,
        case_id,
        masked=user.pii == "masked",
        max_counterparties=settings.ui.graph_max_counterparties,
    )
    if user.pii == "full" and graph.nodes:
        pii_viewed(
            db,
            user,
            entity_type="case",
            entity_id=case_id,
            what=f"graph data of case {case_id}",
            details={"cifs": graph.cifs},
        )
    data = {"nodes": graph.nodes, "edges": graph.edges}
    return envelope.live(
        FEATURE, data, pii=user.pii, graph_source="sql", backend=db.backend, **graph.meta
    )
