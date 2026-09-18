import os
import requests
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.orm import DeclarativeBase

# ===================== 数据库配置 =====================
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./todo.db")
# Render postgres 兼容：postgres:// 替换为 postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

# Todo表，新增 category 字段
class Todo(Base):
    __tablename__ = "todos"
    id = Column(Integer, primary_key=True, index=True)
    content = Column(String, nullable=False)
    is_done = Column(Boolean, default=False)
    category = Column(String, default="其他") # AI分类标签
    created_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(hours=8)) # UTC+8北京时间

# 创建数据表
Base.metadata.create_all(bind=engine)

# ===================== Pydantic模型 =====================
class TodoCreate(BaseModel):
    content: str

class TodoItem(BaseModel):
    id: int
    content: str
    is_done: bool
    category: str
    created_at: datetime

    class Config:
        orm_mode = True

# ===================== AI分类函数 =====================
def get_todo_category(content: str) -> str:
    ai_api_key = os.environ.get("AI_API_KEY")
    # 没有key直接返回其他
    if not ai_api_key:
        return "其他"
    url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    headers = {
        "Authorization": f"Bearer {ai_api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "glm-4-flash",
        "messages": [
            {
                "role": "user",
                "content": f"""请根据下面待办文本，只返回一个分类标签，可选标签：学习、生活、工作、其他。
只输出标签文字，不要任何多余解释、标点符号。
待办内容：{content}"""
            }
        ],
        "temperature": 0
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        res_json = resp.json()
        label = res_json["choices"][0]["message"]["content"].strip()
        # 校验返回标签，不在列表内就强制改为其他
        allow_tags = ["学习", "生活", "工作", "其他"]
        if label not in allow_tags:
            label = "其他"
        return label
    except Exception as e:
        # AI调用出错，默认返回其他，不阻断待办创建
        print("AI分类接口调用异常：", e)
        return "其他"

# ===================== FastAPI初始化 =====================
app = FastAPI()
# CORS跨域，允许所有来源
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 获取数据库会话（依赖注入，正确写法！）
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ===================== 接口 =====================
@app.get("/")
def root():
    return {"message": "我的后端服务器跑路了！"}

# 获取全部待办
@app.get("/todos", response_model=list[TodoItem])
def get_all_todos(db: Session = Depends(get_db)):
    todos = db.query(Todo).all()
    return todos

# 新增待办（自动AI分类）
@app.post("/todos", response_model=TodoItem)
def create_todo(todo: TodoCreate, db: Session = Depends(get_db)):
    # AI自动获取分类
    category = get_todo_category(todo.content)
    new_todo = Todo(content=todo.content, category=category)
    db.add(new_todo)
    db.commit()
    db.refresh(new_todo)
    return new_todo

# 修改完成状态
@app.put("/todos/{todo_id}", response_model=TodoItem)
def update_todo(todo_id: int, is_done: bool, db: Session = Depends(get_db)):
    todo = db.query(Todo).filter(Todo.id == todo_id).first()
    if not todo:
        raise HTTPException(status_code=404, detail="待办不存在")
    todo.is_done = is_done
    db.commit()
    db.refresh(todo)
    return todo

# 删除待办
@app.delete("/todos/{todo_id}")
def delete_todo(todo_id: int, db: Session = Depends(get_db)):
    todo = db.query(Todo).filter(Todo.id == todo_id).first()
    if not todo:
        raise HTTPException(status_code=404, detail="待办不存在")
    db.delete(todo)
    db.commit()
    return {"msg": "删除成功"}

# 本地启动入口
if __name__ == '__main__':
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
