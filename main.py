import os
import jwt
import requests
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase, relationship

# ===================== 数据库配置 =====================
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./todo.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

# ===================== 用户表 =====================
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    todos = relationship("Todo", back_populates="owner")

# ===================== 待办表 =====================
class Todo(Base):
    __tablename__ = "todos"
    id = Column(Integer, primary_key=True, index=True)
    content = Column(String, nullable=False)
    is_done = Column(Boolean, default=False)
    category = Column(String, default="其他")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(hours=8))
    owner = relationship("User", back_populates="todos")

Base.metadata.create_all(bind=engine)

# ===================== JWT 配置 =====================
SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-to-a-random-secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 天

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# ===================== 密码哈希（关键修复） =====================
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def normalize_password(password: str) -> str:
    """
    按字节截断密码到最多 72 字节，满足 bcrypt 限制。
    注意：不能用 password[:72]（按字符截），中文会超字节。
    这里按 UTF-8 字节截断，避免 ValueError。
    """
    return password.encode("utf-8")[:72].decode("utf-8", errors="ignore")

def hash_password(password: str) -> str:
    # 哈希前先截断到 72 字节
    return pwd_context.hash(normalize_password(password))

def verify_password(password: str, hashed: str) -> bool:
    # 校验前必须用同样的方式截断，否则永远验证失败
    return pwd_context.verify(normalize_password(password), hashed)

# ===================== Pydantic 模型 =====================
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

class UserRegister(BaseModel):
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

ALLOWED_CATEGORIES = ["学习", "工作", "生活", "运动", "其他"]

# ===================== 本地关键词兜底分类 =====================
def local_rule_category(content: str) -> str:
    text = content or ""
    if any(k in text for k in ["学", "书", "课", "考试", "复习", "作业", "论文", "实验",
                               "物理", "数学", "英语", "编程", "代码", "医", "化学",
                               "生物", "历史", "考研", "读书"]):
        return "学习"
    if any(k in text for k in ["跑步", "健身", "运动", "锻炼", "打球", "游泳", "瑜伽",
                               "散步", "骑行", "篮球", "足球", "羽毛球"]):
        return "运动"
    if any(k in text for k in ["工作", "开会", "项目", "任务", "客户", "报告", "会议",
                               "加班", "方案", "汇报", "邮件", "面试"]):
        return "工作"
    if any(k in text for k in ["买", "吃", "睡", "玩", "家", "购物", "旅行", "打扫",
                               "做饭", "电影", "游戏", "牛奶", "蔬菜"]):
        return "生活"
    return "其他"

# ===================== AI 分类函数 =====================
def get_todo_category(content: str) -> str:
    ai_api_key = os.environ.get("AI_API_KEY")
    if ai_api_key:
        url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        headers = {
            "Authorization": f"Bearer {ai_api_key}",
            "Content-Type": "application/json"
        }
        messages = [
            {"role": "system", "content": "你是一个待办事项分类助手，只负责把待办内容归类到指定分类中。"},
            {"role": "user", "content": "数学作业"},
            {"role": "assistant", "content": "学习"},
            {"role": "user", "content": "去跑步"},
            {"role": "assistant", "content": "运动"},
            {"role": "user", "content": "买牛奶"},
            {"role": "assistant", "content": "生活"},
            {"role": "user", "content": "开会写周报"},
            {"role": "assistant", "content": "工作"},
            {
                "role": "user",
                "content": (
                    "请对下面这条待办进行分类。分类只能从以下5个中选一个："
                    "【学习、工作、生活、运动、其他】。"
                    "你必须只输出这一个分类词本身，不要输出任何标点符号、引号、"
                    "解释或多余内容。\n待办内容：" + content
                )
            }
        ]
        payload = {"model": "glm-4-flash", "messages": messages, "temperature": 0}
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            resp.raise_for_status()
            res_json = resp.json()
            raw = res_json["choices"][0]["message"]["content"].strip()
            label = raw.strip(' "\'“”‘’《》【】[]()（）.,，。!！?？:：;；\n\t')
            for tag in ALLOWED_CATEGORIES:
                if tag in label or label in tag:
                    print(f"AI分类成功：{content} -> {tag}")
                    return tag
            print(f"AI返回无法识别：{repr(raw)}，使用本地规则")
        except Exception as e:
            print("AI分类接口调用异常，使用本地规则：", e)
    else:
        print("未配置AI_API_KEY，使用本地规则分类")
    return local_rule_category(content)

# ===================== FastAPI 初始化 =====================
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(
    authorization: str = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=401,
        detail="无效或过期的凭证，请先登录",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not authorization or not authorization.startswith("Bearer "):
        raise credentials_exception
    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise credentials_exception
    return user

# ===================== 认证接口 =====================
@app.get("/")
def root():
    return {"message": "我的后端服务器跑路了！"}

@app.post("/register")
def register(user: UserRegister, db: Session = Depends(get_db)):
    exist = db.query(User).filter(User.username == user.username).first()
    if exist:
        raise HTTPException(status_code=400, detail="用户名已存在")
    new_user = User(username=user.username, hashed_password=hash_password(user.password))
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"msg": "注册成功", "username": new_user.username}

@app.post("/login")
def login(user: UserLogin, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if not db_user or not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_access_token({"sub": db_user.username})
    return {"access_token": token, "token_type": "bearer", "username": db_user.username}

# ===================== 待办接口 =====================
@app.get("/todos", response_model=list[TodoItem])
def get_all_todos(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Todo).filter(Todo.user_id == current_user.id).all()

@app.post("/todos", response_model=TodoItem)
def create_todo(todo: TodoCreate, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    category = get_todo_category(todo.content)
    new_todo = Todo(content=todo.content, category=category, user_id=current_user.id)
    db.add(new_todo)
    db.commit()
    db.refresh(new_todo)
    return new_todo

@app.put("/todos/{todo_id}", response_model=TodoItem)
def update_todo(todo_id: int, is_done: bool, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    todo = db.query(Todo).filter(Todo.id == todo_id, Todo.user_id == current_user.id).first()
    if not todo:
        raise HTTPException(status_code=404, detail="待办不存在")
    todo.is_done = is_done
    db.commit()
    db.refresh(todo)
    return todo

@app.delete("/todos/{todo_id}")
def delete_todo(todo_id: int, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    todo = db.query(Todo).filter(Todo.id == todo_id, Todo.user_id == current_user.id).first()
    if not todo:
        raise HTTPException(status_code=404, detail="待办不存在")
    db.delete(todo)
    db.commit()
    return {"msg": "删除成功"}

if __name__ == '__main__':
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
