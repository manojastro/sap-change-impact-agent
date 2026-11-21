"""ALM adapter factory - always the local MOCK in this POC."""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.adapters.cloud_alm import LocalCloudAlmAdapter


def get_alm_adapter(db: Session) -> LocalCloudAlmAdapter:
    """Returns the local mock adapter (mock=True).

    A real deployment would read SAP Cloud ALM tenant credentials from
    settings and construct RealSapCloudAlmClient instead.
    """
    return LocalCloudAlmAdapter(db)
