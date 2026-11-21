"""SAP Cloud ALM adapter - protocol + LOCAL MOCK implementation.

MOCK LABELLING: LocalCloudAlmAdapter persists to cloud_alm_* tables in the
local database and is clearly a stand-in. RealSapCloudAlm documents the future
integration surface but raises NotImplementedError by default so nothing
pretends to talk to a real SAP Cloud ALM tenant.
"""
from __future__ import annotations

import typing

from sqlalchemy.orm import Session

from backend.app.models import (
    AlmDefect, AlmExecution, AlmFeature, AlmReleasePlan, AlmTask, AlmTestLink,
)


class CloudAlmAdapter(typing.Protocol):
    mock: bool

    def upsert_feature(self, external_id: str, name: str, description: str = "") -> dict: ...
    def upsert_requirement(self, feature_external_id: str, external_id: str, title: str,
                           transport_id: str = "") -> dict: ...
    def link_test_case(self, requirement_external_id: str, test_code: str) -> dict: ...
    def record_test_execution(self, test_code: str, status: str, details: dict | None = None) -> dict: ...
    def record_defect(self, external_id: str, title: str, severity: str,
                      transport_id: str = "", test_code: str = "") -> dict: ...
    def export_release_plan(self, release: str, transport_ids: list[str]) -> dict: ...


class LocalCloudAlmAdapter:
    """LOCAL MOCK of SAP Cloud ALM backed by local tables. mock=True."""

    mock = True

    def __init__(self, session: Session) -> None:
        self._db = session

    def upsert_feature(self, external_id: str, name: str, description: str = "") -> dict:
        row = self._db.query(AlmFeature).filter_by(external_id=external_id).first()
        if row is None:
            row = AlmFeature(external_id=external_id, name=name, description=description)
            self._db.add(row)
        else:
            row.name, row.description = name, description
        self._db.commit()
        return {"mock": True, "feature": {"external_id": external_id, "name": name}}

    def upsert_requirement(self, feature_external_id: str, external_id: str,
                           title: str, transport_id: str = "") -> dict:
        feat = self._db.query(AlmFeature).filter_by(external_id=feature_external_id).first()
        if feat is None:
            self.upsert_feature(feature_external_id, f"Feature {feature_external_id}")
            feat = self._db.query(AlmFeature).filter_by(external_id=feature_external_id).first()
        row = self._db.query(AlmTask).filter_by(external_id=external_id).first()
        if row is None:
            row = AlmTask(feature_id=feat.id if feat else 0, external_id=external_id,
                          title=title, task_type="REQUIREMENT", transport_id=transport_id)
            self._db.add(row)
        else:
            row.title, row.transport_id = title, transport_id or row.transport_id
        self._db.commit()
        return {"mock": True, "requirement": {"external_id": external_id, "title": title}}

    def link_test_case(self, requirement_external_id: str, test_code: str) -> dict:
        exists = self._db.query(AlmTestLink).filter_by(
            task_external_id=requirement_external_id, test_code=test_code).first()
        if not exists:
            self._db.add(AlmTestLink(task_external_id=requirement_external_id, test_code=test_code))
            self._db.commit()
        return {"mock": True, "requirement": requirement_external_id, "test": test_code}

    def record_test_execution(self, test_code: str, status: str, details: dict | None = None) -> dict:
        self._db.add(AlmExecution(test_code=test_code, status=status, details=details or {}))
        self._db.commit()
        return {"mock": True, "test": test_code, "status": status}

    def record_defect(self, external_id: str, title: str, severity: str,
                      transport_id: str = "", test_code: str = "") -> dict:
        row = self._db.query(AlmDefect).filter_by(external_id=external_id).first()
        if row is None:
            row = AlmDefect(external_id=external_id, title=title, severity=severity,
                            transport_id=transport_id, test_code=test_code)
            self._db.add(row)
            self._db.commit()
        return {"mock": True, "defect": external_id}

    def export_release_plan(self, release: str, transport_ids: list[str]) -> dict:
        row = AlmReleasePlan(release=release, transport_ids=list(transport_ids))
        self._db.add(row)
        self._db.commit()
        return {"mock": True, "release": release, "transports": len(transport_ids),
                "exported_at": row.exported_at.isoformat()}


class RealSapCloudAlmClient:
    """Documented real-integration point (NOT implemented in this POC).

    A production adapter would call SAP Cloud ALM open APIs, e.g.
      POST /api-cb-service/v1/features
      POST /api-cbs-service/v1/requirements/{id}/testCases
      POST /api-te-service/v1/testRuns
    authenticated via OAuth2 client credentials against the tenant subaccount.
    Kept as an explicit stub so the platform fails loudly instead of silently
    faking a real integration.
    """

    mock = False

    def __init__(self, base_url: str, client_id: str, client_secret: str) -> None:
        raise NotImplementedError(
            "Real SAP Cloud ALM integration is out of scope for this simulation "
            "POC; use LocalCloudAlmAdapter (mock)."
        )
