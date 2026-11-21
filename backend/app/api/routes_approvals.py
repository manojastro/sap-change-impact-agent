"""Approvals: HIGH/CRITICAL risk transports require human approval."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app import metrics
from backend.app.db import get_db
from backend.app.models import Approval, EventRow, RiskAssessment, Transport
from backend.app.schemas import ApprovalDecisionIn, ApprovalOut

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalOut])
def list_approvals(status: str | None = None, db: Session = Depends(get_db)) -> list[Approval]:
    q = db.query(Approval).order_by(Approval.id.desc())
    if status:
        q = q.filter_by(status=status)
    return q.limit(100).all()


def _decide(db: Session, approval_pk: int, decision: str,
            payload: ApprovalDecisionIn) -> Approval:
    ap = db.get(Approval, approval_pk)
    if ap is None:
        raise HTTPException(404, "approval not found")
    if ap.status != "PENDING":
        raise HTTPException(409, f"approval already decided ({ap.status})")
    transport = db.get(Transport, ap.transport_fk)
    now = dt.datetime.now(dt.timezone.utc)
    requested = ap.requested_at if ap.requested_at.tzinfo else ap.requested_at.replace(tzinfo=dt.timezone.utc)
    ap.status = decision
    ap.approver = payload.approver
    ap.comment = payload.comment or ""
    ap.decided_at = now
    ap.turnaround_minutes = round((now - requested).total_seconds() / 60.0, 2)
    if decision == "APPROVED":
        transport.status = "APPROVED"
    else:
        transport.status = "BLOCKED"
        transport.blocked_reason = (
            f"Rejected by {payload.approver}: {payload.comment or 'no reason given'}"
        )
    metrics.APPROVALS_TOTAL.labels(decision=decision.lower()).inc()
    db.add(EventRow(kind=f"APPROVAL_{decision}", ref_type="TRANSPORT", ref_id=transport.id,
                    message=f"{transport.transport_id} {decision.lower()} by {payload.approver}"))
    db.commit()
    db.refresh(ap)
    return ap


@router.post("/{approval_pk}/approve", response_model=ApprovalOut)
def approve(approval_pk: int, payload: ApprovalDecisionIn,
            db: Session = Depends(get_db)) -> Approval:
    return _decide(db, approval_pk, "APPROVED", payload)


@router.post("/{approval_pk}/reject", response_model=ApprovalOut)
def reject(approval_pk: int, payload: ApprovalDecisionIn,
           db: Session = Depends(get_db)) -> Approval:
    return _decide(db, approval_pk, "REJECTED", payload)


@router.get("/for-transport/{transport_pk}", response_model=ApprovalOut | None)
def approval_for_transport(transport_pk: int,
                           db: Session = Depends(get_db)) -> Approval | None:
    return (
        db.query(Approval).filter_by(transport_fk=transport_pk)
        .order_by(Approval.id.desc()).first()
    )
