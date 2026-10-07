from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.modules.auth.models import User
from app.modules.auth.schemas import ErrorResponse
from app.modules.analytics import anomalies, queries, rating
from app.modules.analytics.schemas import (
    AnomaliesResponse, PeriodQuery, RatingResponse, ShiftQuery, ShiftReportResponse,
)

router = APIRouter(tags=["analytics"])
ERRORS = {code: {"model": ErrorResponse} for code in (401, 403, 404, 422)}


@router.get("/reports/shift", response_model=ShiftReportResponse, responses=ERRORS)
def shift_report(response: Response, params: Annotated[ShiftQuery, Query()],
                 actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    data = queries.load_history(db, actor, params, datetime.now(timezone.utc))
    return queries.shift_report(data)


@router.get("/reports/rating", response_model=RatingResponse, responses=ERRORS)
def worker_rating(response: Response, params: Annotated[PeriodQuery, Query()],
                  actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return rating.build_rating(queries.load_history(db, actor, params, datetime.now(timezone.utc)))


@router.get("/analytics/anomalies", response_model=AnomaliesResponse, responses=ERRORS)
def repair_anomalies(response: Response, params: Annotated[PeriodQuery, Query()],
                     actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return anomalies.find_anomalies(queries.load_history(db, actor, params, datetime.now(timezone.utc), insights=True))
