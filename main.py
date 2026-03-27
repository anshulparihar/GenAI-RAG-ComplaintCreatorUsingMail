from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
app = FastAPI(
    title= "Complaint Creator",
    description="Create complaint from mails",
    version = "1.0.0",
    docs_url = "/docs",
    redoc_url="/redoc"
)
app.add_middleware(
    CORSMiddleware
)

@app.get("/")
async def root():
    return {"message": "Hello World"}