from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import web
from app.errors import AppError
from app.routers import appointments, auth, barbers, clients, services, stats, users

app = FastAPI(title="Barber Booking")

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(barbers.router)
app.include_router(services.router)
app.include_router(clients.router)
app.include_router(appointments.router)
app.include_router(stats.router)
app.include_router(web.router)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.exception_handler(AppError)
def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/web")


@app.get("/health")
def health():
    return {"status": "ok"}
