from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient
from motor.motor_asyncio import AsyncIOMotorCollection
from contextlib import asynccontextmanager
from fastapi import Request



@asynccontextmanager
async def lifespan(app: FastAPI):
    app.mongodb_client = AsyncIOMotorClient("mongodb://localhost:27017/")
    app.mongodb = app.mongodb_client["userdetails"]
    
    yield
    app.mongodb_client.close()

def get_collection(request: Request, name: str) -> AsyncIOMotorCollection:
    return request.app.mongodb[name]


avpp = FastAPI(lifespan=lifespan)
