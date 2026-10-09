import asyncio
import secrets
import sqlite3
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.responses import JSONResponse

from skillbook.audit import Audit
from skillbook.config import Settings
from skillbook.domain import Release, RunRequest, RunResult, canonical, digest
from skillbook.policy import authorize
from skillbook.provider import Provider, ProviderError
from skillbook.releases import ReleaseStore, public_key

bearer = HTTPBearer(auto_error=False)


class BodyLimit:
    def __init__(self, app, limit=49152):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.limit:
                return await JSONResponse({"detail": "Request too large"}, 413)(
                    scope, receive, send
                )
            if not message.get("more_body", False):
                break

        async def buffered_receive():
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, buffered_receive, send)


def demo_release() -> Release:
    return Release.model_validate_json(
        files("skillbook").joinpath("demo_release.json").read_bytes()
    )


def create_app(settings: Settings | None = None, provider: Provider | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        if len(settings.api_key.get_secret_value()) < 32:
            raise ValueError("Set SKILLBOOK_API_KEY to a random token of at least 32 characters")
        release = (
            ReleaseStore(
                Path(settings.release_state), public_key(Path(settings.trusted_key))
            ).load()
            if settings.release_state
            else demo_release()
        )
        app.state.release = release
        app.state.release_hash = digest(canonical(release.model_dump()))
        app.state.audit = Audit(settings.audit_db)
        app.state.audit.verify()
        app.state.audit.append(
            "startup",
            "system",
            release=release.version,
            release_sha256=app.state.release_hash,
            provider=settings.provider,
            model=settings.model,
        )
        app.state.busy = False
        yield

    app = FastAPI(title="Skillbook", version="0.1.0", lifespan=lifespan)
    app.add_middleware(BodyLimit)
    engine = provider or Provider(settings)

    async def authenticate(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ):
        if credentials is None or not secrets.compare_digest(
            credentials.credentials.encode(), settings.api_key.get_secret_value().encode()
        ):
            raise HTTPException(401, "Authentication required")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/v1/status", dependencies=[Depends(authenticate)])
    async def status(request: Request):
        return {
            "provider": settings.provider,
            "model": settings.model,
            "release_version": request.app.state.release.version,
            "release_sha256": request.app.state.release_hash,
            "release_mode": "signed" if settings.release_state else "builtin-demo",
        }

    @app.post("/v1/run", response_model=RunResult, dependencies=[Depends(authenticate)])
    async def run(payload: RunRequest):
        if app.state.busy:
            raise HTTPException(429, "One model request at a time; retry later")
        app.state.busy = True
        request_id = str(uuid4())
        audit = app.state.audit
        release = app.state.release
        try:
            skill = release.skills.get(payload.skill_id)
            if skill is None:
                audit.append("denied", request_id, reason="unknown_skill")
                raise HTTPException(404, "Unknown skill")
            audit.append(
                "requested",
                request_id,
                skill_id=payload.skill_id,
                release_sha256=app.state.release_hash,
            )
            try:
                async with asyncio.timeout(settings.timeout_seconds):
                    proposal = await engine.propose(payload, skill)
            except (ProviderError, TimeoutError) as exc:
                audit.append("provider_error", request_id)
                raise HTTPException(502, "Local model unavailable or invalid response") from exc
            decision = authorize(release, payload.skill_id, proposal)
            # Persist the decision before accessing data. Disk failure prevents execution.
            audit.append("decision", request_id, allowed=decision.allowed, reason=decision.reason)
            content = release.documents[decision.document_id] if decision.allowed else None
            audit.append("completed", request_id, allowed=decision.allowed)
            return RunResult(
                request_id=request_id,
                release_version=release.version,
                release_sha256=app.state.release_hash,
                provider=settings.provider,
                decision=decision,
                content=content,
            )
        except (OSError, sqlite3.Error) as exc:
            raise HTTPException(503, "Audit storage unavailable; request refused") from exc
        finally:
            app.state.busy = False

    return app
