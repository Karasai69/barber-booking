from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.errors import AppError
from app.routers import appointments, barbers, clients, services

app = FastAPI(title="Barber Booking")

app.include_router(barbers.router)
app.include_router(services.router)
app.include_router(clients.router)
app.include_router(appointments.router)


@app.exception_handler(AppError)
def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.get("/health")
def health():
    return {"status": "ok"}
