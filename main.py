from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.mailAPI.routes import router as mail_retrieve_route
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
app.include_router(mail_retrieve_route)