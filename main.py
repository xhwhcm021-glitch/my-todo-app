from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime

# ========== 数据库配置 ==========
SQLALCHEMY_DATABASE_URL = "sqlite:///./todo.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ========== TODO模型，增加创建时间 ==========
class Todo(Base):
    __tablename__ = "todos"
    id = Column(Integer, primary_key=True, index=True)
    content = Column(String, index=True)
    is_done = Column(Boolean, default=False)
    create_time = Column(DateTime, default=datetime.now)

# 创建表
Base.metadata.create_all(bind=engine)

# ========== FastAPI ==========
app = FastAPI()

# 跨域，允许网页前端访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 原来根接口不变
@app.get("/")
def read_root():
    return {"message": "我的后端服务器跑路了！"}

# 数据库依赖
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 获取所有待办
@app.get("/todos")
def get_all_todos(db: Session = Depends(get_db)):
    todos = db.query(Todo).order_by(Todo.id).all()
    result = []
    for t in todos:
        result.append({
            "id": t.id,
            "text": t.content,
            "done": t.is_done,
            "create_time": t.create_time.strftime("%Y-%m-%d %H:%M:%S")
        })
    return result

# 新增待办
@app.post("/todos")
def create_todo(item: dict, db: Session = Depends(get_db)):
    new_todo = Todo(content=item["text"], is_done=False)
    db.add(new_todo)
    db.commit()
    db.refresh(new_todo)
    return {"ok": True}

# 切换完成状态
@app.put("/todos/{todo_id}")
def toggle_todo(todo_id: int, db: Session = Depends(get_db)):
    todo = db.query(Todo).filter(Todo.id == todo_id).first()
    if not todo:
        raise HTTPException(status_code=404, detail="不存在")
    todo.is_done = not todo.is_done
    db.commit()
    return {"ok": True}

# 删除待办
@app.delete("/todos/{todo_id}")
def delete_todo(todo_id: int, db: Session = Depends(get_db)):
    todo = db.query(Todo).filter(Todo.id == todo_id).first()
    if not todo:
        raise HTTPException(status_code=404, detail="不存在")
    db.delete(todo)
    db.commit()
    return {"ok": True}
if __name__ == "__main__":
    import uvicorn
    import os
    # 读取云平台分配的端口，本地默认8000
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)