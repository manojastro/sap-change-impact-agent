"""Transport CRUD + changed-object listing."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.models import Transport, TransportObject
from backend.app.schemas import TransportIn, TransportObjectOut, TransportOut
from backend.app.services.transport_service import import_transport

router = APIRouter(prefix="/api/v1/transports", tags=["transports"])


@router.get("", response_model=list[TransportOut])
def list_transports(
    status: str | None = Query(None),
    db: Session = Depends(get_db),
) -> list[Transport]:
    q = db.query(Transport).order_by(Transport.id.desc())
    if status:
        q = q.filter_by(status=status)
    return q.limit(100).all()


@router.post("", response_model=TransportOut, status_code=201)
def create_transport(payload: TransportIn, db: Session = Depends(get_db)) -> Transport:
    return import_transport(db, payload)


@router.get("/{transport_pk}", response_model=TransportOut)
def get_transport(transport_pk: int, db: Session = Depends(get_db)) -> Transport:
    tr = db.get(Transport, transport_pk)
    if tr is None:
        raise HTTPException(404, "transport not found")
    return tr


@router.get("/{transport_pk}/objects", response_model=list[TransportObjectOut])
def transport_objects(transport_pk: int, db: Session = Depends(get_db)) -> list[TransportObject]:
    tr = db.get(Transport, transport_pk)
    if tr is None:
        raise HTTPException(404, "transport not found")
    return list(tr.objects)


@router.delete("/{transport_pk}", status_code=204)
def delete_transport(transport_pk: int, db: Session = Depends(get_db)) -> None:
    tr = db.get(Transport, transport_pk)
    if tr is None:
        raise HTTPException(404, "transport not found")
    db.delete(tr)
    db.commit()
