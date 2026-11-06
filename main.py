from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import create_engine, Column, Integer, String, Boolean, Date, Numeric, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from sqlalchemy.dialects.postgresql import insert
from pydantic import BaseModel
from typing import List
from datetime import date, datetime, timedelta, timezone
import os
import jwt
from passlib.context import CryptContext

# ================= 1. 基础配置 =================
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://...")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# 生产环境建议把 SECRET_KEY 放到 Render 的环境变量里
SECRET_KEY = os.environ.get("SECRET_KEY", "my-super-secret-key-123456")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7 # Token 7天过期

# 密码加密工具
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ================= 2. 数据库模型 =================
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, unique=True)
    hashed_password = Column(String(255), nullable=False) # 🌟 新增密码字段
    role = Column(String(50), nullable=False)
    is_active = Column(Boolean, default=True)
    
    orders = relationship("Order", back_populates="user")

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    unit = Column(String(20), nullable=False)
    is_active = Column(Boolean, default=True)
    
    orders = relationship("Order", back_populates="product")

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    order_date = Column(Date, nullable=False, default=date.today)
    quantity = Column(Numeric(12, 2), nullable=False)
    remark = Column(String(200))
    
    user = relationship("User", back_populates="orders")
    product = relationship("Product", back_populates="orders")

# 🌟 自动建表（如果表不存在，会自动创建，不需要你手动敲 SQL）
Base.metadata.create_all(bind=engine)

# ================= 3. FastAPI 与跨域配置 =================
app = FastAPI()
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ================= 4. 核心鉴权逻辑 =================

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

security = HTTPBearer()

# 🌟 真实的 JWT 解析依赖
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("user_id")
        role: str = payload.get("role")
        if user_id is None or role is None:
            raise HTTPException(status_code=401, detail="无效的 Token 载荷")
        return {"user_id": user_id, "role": role}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效的凭证")

# 🌟 权限拦截器
class RoleChecker:
    def __init__(self, allowed_roles: list):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: dict = Depends(get_current_user)):
        if current_user["role"] not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足，需要以下角色之一: {self.allowed_roles}"
            )
        return current_user

# ================= 5. 接口定义 =================

# Pydantic 数据模型
class UserLogin(BaseModel):
    name: str
    password: str

class OrderItemCreate(BaseModel):
    product_id: int
    quantity: float

# 登录接口
@app.post("/login")
def login(user_data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.name == user_data.name).first()
    if not user or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    # 生成 Token，塞入 user_id 和 role
    access_token = create_access_token(
        data={"user_id": user.id, "role": user.role}
    )
    return {"access_token": access_token, "token_type": "bearer"}

# 测试用：生成账号和商品数据（重置后第一次必须调用这个接口）
@app.get("/seed_data")
def seed_data(db: Session = Depends(get_db)):
    if not db.query(User).first():
        # 生成一个店员账号: 账号 test，密码 123456
        db.add(User(
            name="test", 
            role="store_a", 
            hashed_password=get_password_hash("123456"),
            is_active=True
        ))
        # 生成一个老板账号: 账号 boss，密码 123456
        db.add(User(
            name="boss", 
            role="h", 
            hashed_password=get_password_hash("123456"),
            is_active=True
        ))
    if not db.query(Product).first():
        db.add_all([
            Product(name="苹果", unit="斤", is_active=True),
            Product(name="香蕉", unit="斤", is_active=True),
            Product(name="可乐", unit="箱", is_active=True),
        ])
    db.commit()
    return {"message": "数据生成成功，测试店员: test/123456，测试老板: boss/123456"}

# 获取商品（只要登录就能看）
@app.get("/products/active")
def get_active_products(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    products = db.query(Product).filter(Product.is_active == True).all()
    return products

# 批量下单（只有店员 store_a, store_b 才能下单）
@app.post("/orders/batch")
def create_orders_batch(
    order_items: List[OrderItemCreate], 
    db: Session = Depends(get_db),
    current_user: dict = Depends(RoleChecker(["store_a", "store_b"])) 
):
    today = date.today()
    valid_items = [item for item in order_items if item.quantity > 0]
    
    if not valid_items:
        raise HTTPException(status_code=400, detail="未提供有效数量")

    current_user_id = current_user["user_id"]
    
    for item in valid_items:
        stmt = insert(Order).values(
            user_id=current_user_id,
            product_id=item.product_id,
            order_date=today,
            quantity=item.quantity
        )
        stmt = stmt.on_conflict_do_update(
            constraint='orders_user_id_order_date_product_id_key', # 注意：PG自动生成的名字可能不同，如果报错需检查
            set_=dict(quantity=Order.quantity + stmt.excluded.quantity)
        )
        db.execute(stmt)
        
    db.commit()
    return {"status": "success", "message": f"成功录入 {len(valid_items)} 条数据"}

# 老板看所有人订单（只有老板 h 才能看）
@app.get("/orders/all")
def get_all_orders(db: Session = Depends(get_db), current_user: dict = Depends(RoleChecker(["h"]))):
    orders = db.query(Order).all()
    return orders

# ================= 启动入口 =================
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)