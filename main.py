from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # 测试阶段允许所有，上线后改回你真实的前端域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)