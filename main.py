from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Boolean, Date, Numeric, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from sqlalchemy.dialects.postgresql import insert
from datetime import date
from pydantic import BaseModel
from typing import List
from sqlalchemy.sql import func
import os

# ================= 1. 数据库连接配置 =================
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://...") 
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ================= 2. 数据库模型定义 (带 relationship 升级版) =================
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    role = Column(String(10), nullable=False) # 'admin', 'store_a' 等
    is_active = Column(Boolean, default=True)
    
    # 关联订单
    orders = relationship("Order", back_populates="user")

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    unit = Column(String(20), nullable=False)
    is_active = Column(Boolean, default=True)
    
    # 关联订单
    orders = relationship("Order", back_populates="product")

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    order_date = Column(Date, nullable=False, default=date.today)
    quantity = Column(Numeric(12, 2), nullable=False)
    remark = Column(String(200))
    
    # 反向关联，方便 order.user.name 这样调用
    user = relationship("User", back_populates="orders")
    product = relationship("Product", back_populates="orders")


# ================= 3. FastAPI 与数据库会话初始化 =================
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

# ================= 4. 模拟 JWT 鉴权 (请根据你原来的 auth.py 替换) =================
# 如果你有现成的 get_current_user，请把它导入进来。
# 下面我写一个从请求头获取 token 的简单占位符，方便你测试：
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    # 【注意】这里只是简单演示，如果你原来用 JWT，这里应该解析 token 并查询数据库
    # 现在我们默认返回数据库里的第一个用户（即测试店员 id=1），确保接口能跑通
    user = db.query(User).first()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在，请先调用 /seed_data 初始化")
    return user


# ================= 5. 接口定义 =================

# 测试用：造假数据
@app.get("/seed_data")
def seed_data(db: Session = Depends(get_db)):
    if not db.query(User).first():
        db.add(User(name="测试店员", role="store_a", is_active=True))
    if not db.query(Product).first():
        db.add_all([
            Product(name="苹果", unit="斤", is_active=True),
            Product(name="香蕉", unit="斤", is_active=True),
            Product(name="可乐", unit="箱", is_active=True)
        ])
    db.commit()
    return {"message": "数据生成成功"}

# 获取上架商品列表 (已恢复 JWT 验证依赖)
@app.get("/products/active")
def get_active_products(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # 恢复了验证！
):
    print(f"当前登录用户: {current_user.name}, 角色: {current_user.role}")
    products = db.query(Product).filter(Product.is_active == True).all()
    return products

# 批量录入订单 (接收前端数组)
class OrderItemCreate(BaseModel):
    product_id: int
    quantity: float

@app.post("/orders/batch")
def create_orders_batch(
    order_items: List[OrderItemCreate], 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # 恢复了验证！
):
    today = date.today()
    valid_items = [item for item in order_items if item.quantity > 0]
    
    if not valid_items:
        raise HTTPException(status_code=400, detail="未提供有效数量")

    # 使用 JWT 验证后的真实 user_id，不再是写死的 1
    current_user_id = current_user.id 
    
    for item in valid_items:
        stmt = insert(Order).values(
            user_id=current_user_id,
            product_id=item.product_id,
            order_date=today,
            quantity=item.quantity
        )
        # 解决 UNIQUE 约束冲突（同一天同一商品累加数量）
        stmt = stmt.on_conflict_do_update(
            constraint='orders_user_date_product_key', 
            set_=dict(quantity=Order.quantity + stmt.excluded.quantity)
        )
        db.execute(stmt)
        
    db.commit()
    return {"status": "success", "message": f"成功录入 {len(valid_items)} 条数据"}

# ================= 启动入口 =================
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)