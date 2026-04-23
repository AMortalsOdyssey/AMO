from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import characters, chat, entities, graph, lore, search, site, stats, storyplay, timeline
from app.core.config import settings
from app.db.connections import lifespan

app = FastAPI(
    title="AMO - A Mortal's Odyssey",
    description="凡人修仙传 世界观数据库 API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(characters.router, prefix="/api")
app.include_router(graph.router, prefix="/api")
app.include_router(timeline.router, prefix="/api")
app.include_router(entities.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(lore.router, prefix="/api")
app.include_router(storyplay.router, prefix="/api")
app.include_router(site.router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "amo-server"}
