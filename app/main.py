from fastapi import FastAPI
app = FastAPI(title="Barber Booking")

@app.get("/health")
def health():
    return {"status": "ok"}