from fastapi import FastAPI
from db.db import lifespan
from routers.router import router as user_router
from routers.router import test_router 
from routers.automations.recommendations.interaction import router as interactions_router 

from fastapi.staticfiles import StaticFiles


app = FastAPI(lifespan=lifespan)
app.include_router(user_router)
app.include_router(interactions_router)
app.mount("/media", StaticFiles(directory="media"), name="media")





















# from enum import Enum
# from typing import Annotated
# from fastapi import FastAPI, Query
# from pydantic import BaseModel, Field
# from thebox.db.db import lifespan

# class ModelName(str, Enum):
#     alexnet = "alexnet"
#     resnet = "resnet"
#     lenet = "lenet"
#     price: float = Field(gt=0, description="The price must be greater than zero")
#     tax: float | None = None
#     tags: list = []

# app = FastAPI(lifespan=lifespan)


# @app.get("/models/{model_name}")
# async def get_model(model_name: ModelName):
#     if model_name is ModelName.alexnet:
#         return {"model_name": model_name, "message": "Deep learning FTW!"}
#     if model_name.value == 'lenet':
#         return {"model_name": model_name, "message":"lecnn all the images"}
    
#     return {"model_name": model_name, "message": "have some residual"}
    

# @app.get("/items/{item_id}")
# async def read_item(item_id:str, q: Annotated[str | None, Query(min_length=3, max_length=50, regex="^fixedquery$")]= None,):
#     item = {"item_id": item_id}
#     if q:
#         item.update({"q": q})
    
#     return item
