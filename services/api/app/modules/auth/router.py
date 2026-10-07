from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import AuthError, get_current_user
from app.modules.auth import service
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    AuthResponse,
    CsrfResponse,
    ErrorResponse,
    LoginRequest,
    UserView,
)

router = APIRouter(prefix="/auth", tags=["auth"])
ERRORS = {code: {"model": ErrorResponse} for code in (401, 403, 422, 429, 503)}


def register_auth_handlers(app: FastAPI) -> None:
    async def auth_error(request: Request, exc: AuthError):
        headers = {"Cache-Control": "no-store"}
        if exc.retry_after is not None:
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {"code": exc.code, "message": exc.message, "details": []}
            },
            headers=headers,
        )

    async def validation_error(request: Request, exc: RequestValidationError):
        if not (request.url.path.startswith("/api/v1/auth/") or
                request.url.path.startswith("/api/v1/photos/") or
                request.url.path.startswith("/api/v1/work-orders") or
                request.url.path.startswith("/api/v1/reports/") or
                request.url.path.startswith("/api/v1/analytics/")):
            return await request_validation_exception_handler(request, exc)
        details = [
            {
                "field": ".".join(str(x) for x in e["loc"] if x != "body"),
                "message": "Некорректное значение",
            }
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Проверьте введённые данные",
                    "details": details,
                }
            },
            headers={"Cache-Control": "no-store"},
        )

    app.add_exception_handler(AuthError, auth_error)
    app.add_exception_handler(RequestValidationError, validation_error)


@router.get(
    "/csrf", response_model=CsrfResponse, responses={429: ERRORS[429], 503: ERRORS[503]}
)
def csrf(request: Request, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return CsrfResponse(csrf_token=service.csrf(db, request, response))


@router.post("/login", response_model=AuthResponse, responses=ERRORS)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    user, token = service.login(db, request, response, payload)
    return AuthResponse(user=UserView.model_validate(user), csrf_token=token)


@router.get("/me", response_model=AuthResponse, responses={401: ERRORS[401]})
def me(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    session = service.read_session(db, request)
    if session is None:
        raise AuthError(401, "unauthenticated", "Требуется вход")
    return AuthResponse(
        user=UserView.model_validate(user),
        csrf_token=session.csrf_token,
    )


@router.post(
    "/logout",
    status_code=204,
    responses={401: ERRORS[401], 403: ERRORS[403], 503: ERRORS[503]},
)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    service.logout(db, request, response)
