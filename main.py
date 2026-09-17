from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase
from datetime import datetime, timedelta
from pydantic import BaseModel
import os
import uvicorn

# 读取数据库连接地址，兼容Render的PostgreSQL，自动把postgres://改成postgresql://
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./todo.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# 创建数据库引擎
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ✅ 严格顺序：先定义Base，后面Todo模型继承Base
class Base(DeclarativeBase):
    pass

app = FastAPI()

# CORS跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 数据库表模型 Todo，必须写在Base定义之后
class Todo(Base):
    __tablename__ = "todos"
    id = Column(Integer, primary_key=True, index=True)
    content = Column(String, nullable=False)
    is_done = Column(Boolean, default=False)
    # 北京时间，UTC+8
    created_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(hours=8))

# Pydantic 请求校验模型
class TodoCreate(BaseModel):
    content: str

# 创建数据表
Base.metadata.create_all(bind=engine)

# 获取数据库会话依赖
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 首页接口
@app.get("/")
def read_root():
    return {"message": "我的后端服务器跑路了！"}

# 获取全部待办
@app.get("/todos")
def get_all_todos(db: Session = Depends(get_db)):
    return db.query(Todo).all()

# 新增待办，接收JSON
@app.post("/todos")
def create_todo(todo: TodoCreate, db: Session = Depends(get_db)):
    new_todo = Todo(content=todo.content)
    db.add(new_todo)
    db.commit()
    db.refresh(new_todo)
    return new_todo

# 更新待办完成状态
@app.put("/todos/{todo_id}")
def update_todo(todo_id: int, is_done: bool, db: Session = Depends(get_db)):
    todo_item = db.query(Todo).filter(Todo.id == todo_id).first()
    if not todo_item:
        return {"error": "找不到这条待办"}
    todo_item.is_done = is_done
    db.commit()
    db.refresh(todo_item)
    return todo_item

# 删除待办
@app.delete("/todos/{todo_id}")
def delete_todo(todo_id: int, db: Session = Depends(get_db)):
    todo_item = db.query(Todo).filter(Todo.id == todo_id).first()
    if not todo_item:
        return {"error": "找不到这条待办"}
    db.delete(todo_item)
    db.commit()
    return {"ok": True}

# 本地运行入口，读取PORT环境变量，适配Render
if __name__ == '__main__':
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
