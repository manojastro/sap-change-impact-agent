"""Transport creation / import."""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.models import EventRow, Transport, TransportObject
from backend.app.schemas import TransportIn
from backend.app.tools.sap_tools import classify_change_types, size_metrics


def import_transport(db: Session, payload: TransportIn) -> Transport:
    existing = db.query(Transport).filter_by(transport_id=payload.transport_id).first()
    if existing is not None:
        return existing  # idempotent get-or-create

    tr = Transport(
        transport_id=payload.transport_id,
        title=payload.title,
        kind=payload.kind,
        change_type=payload.change_type,
        scenario_tag=payload.scenario_tag or "",
        source_system=payload.source_system,
        target_release=payload.target_release,
        loc_delta=payload.loc_delta,
        status="IMPORTED",
    )
    db.add(tr)
    db.flush()
    for o in payload.objects:
        db.add(TransportObject(
            transport_fk=tr.id,
            object_type=o.object_type,
            object_key=o.object_key,
            field_name=o.field_name or "",
            change_action=o.change_action,
            value_affecting=o.value_affecting,
            details=dict(o.details or {}),
        ))
    db.flush()  # autoflush=False: make pending objects visible to tr.objects
    objs = list(tr.objects) if not hasattr(tr.objects, "all") else list(tr.objects.all())
    config_changes = sum(1 for o in objs if o.object_type == "CONFIG_ITEM")
    sm = size_metrics(tr, len(objs), config_changes)
    tr.objects_changed = sm["objects_changed"]
    tr.config_changes = sm["config_changes"]
    tr.size_bucket = sm["size_bucket"]
    db.add(EventRow(kind="TRANSPORT_IMPORTED", ref_type="TRANSPORT", ref_id=tr.id,
                    message=f"{tr.transport_id} imported ({tr.change_type}, {len(objs)} objects)"))
    db.commit()
    return tr
