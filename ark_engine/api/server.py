from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
from typing import List, Dict
import glob
import os
from ark_engine.core.loader import ArkLoader
from ark_engine.core.rag import ArkRAG

app = FastAPI(title="Ark Engine API", version="0.1.0")

loaded_modules = {}

@app.on_event("startup")
def load_modules():
    module_files = glob.glob("*.ark")
    for f in module_files:
        try:
            mod = ArkLoader.load(f)
            loaded_modules[mod.header.id] = {
                "data": mod,
                "rag": ArkRAG(mod)
            }
            print(f"API: Loaded module {mod.header.id} ({f})")
        except Exception as e:
            print(f"API: Failed to load {f}: {e}")

class ModuleSummary(BaseModel):
    id: str
    title: str
    version: str

class AskRequest(BaseModel):
    module_id: str
    question: str

@app.get("/modules", response_model=List[ModuleSummary])
def list_modules():
    return [
        ModuleSummary(
            id=m["data"].header.id,
            title=m["data"].header.title,
            version=m["data"].header.version
        ) for m in loaded_modules.values()
    ]

@app.get("/module/{id}")
def get_module_details(id: str):
    if id not in loaded_modules:
        raise HTTPException(status_code=404, detail="Module not found")
    
    mod = loaded_modules[id]["data"]
    return mod.dict()

@app.post("/ask")
def ask_question(payload: AskRequest):
    if payload.module_id not in loaded_modules:
        raise HTTPException(status_code=404, detail="Module not found")
    
    rag_engine = loaded_modules[payload.module_id]["rag"]
    response = rag_engine.ask(payload.question)
    
    return {
        "module_id": payload.module_id,
        "query": payload.question,
        "answer": response
    }
