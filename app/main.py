import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from .database import Base, engine
from .routes import users, markers

os.makedirs("/data/uploads", exist_ok=True)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Roadwatch")

app.include_router(users.router)
app.include_router(markers.router)

app.mount("/uploads", StaticFiles(directory="/data/uploads"), name="uploads")
app.mount("/static", StaticFiles(directory="/app/static"), name="static")


@app.get("/")
def root():
    return FileResponse("/app/static/index.html")
