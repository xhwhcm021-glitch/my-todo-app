from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime, timedelta
from pydantic import BaseModel

# SQLite数据库，文件在项目根目录 ./todo.db
SQLALCHEMY_DATABASE_URL = "sqlite:///./todo.db"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

app = FastAPI()

# 跨域配置，允许全部前端访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 数据库模型 Todo
class Todo(Base):
    __tablename__ = "todos"
    id = Column(Integer, primary_key=True, index=True)
    content = Column(String, nullable=False)
    is_done = Column(Boolean, default=False)
    # 创建时间：自动记录北京时间 UTC+8
    created_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(hours=8))

# Pydantic 校验模型，接收前端JSON
class TodoCreate(BaseModel):
    content: str

# 创建数据表
Base.metadata.create_all(bind=engine)

# 获取数据库会话
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

# 新增待办（接收JSON）
@app.post("/todos")
def create_todo(todo: TodoCreate, db: Session = Depends(get_db)):
    new_todo = Todo(content=todo.content)
    db.add(new_todo)
    db.commit()
    db.refresh(new_todo)
    return new_todo

# 更新完成状态
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
