from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Boolean, Date, Numeric, ForeignKey, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.dialects.postgresql import insert
from datetime import date, timedelta
from pydantic import BaseModel
from typing import List
import os

# ================= 1. 数据库连接配置 =================
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://...") 
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ================= 2. 数据库模型定义 =================
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    role = Column(String(10), nullable=False)
    is_active = Column(Boolean, default=True)

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    unit = Column(String(20), nullable=False)
    is_active = Column(Boolean, default=True)

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    order_date = Column(Date, nullable=False, default=date.today)
    quantity = Column(Numeric(12, 2), nullable=False)
    remark = Column(String(200))

# ================= 3. FastAPI 与数据库会话初始化 =================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注意这里：get_db 必须在调用它的接口之前定义！
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ================= 4. 接口定义 =================

# 测试用：造假数据
@app.get("/seed_data")
def seed_data(db: Session = Depends(get_db)):
    if not db.query(User).first():
        db.add(User(name="测试店员", role="a", is_active=True))
    if not db.query(Product).first():
        db.add_all([
            Product(name="苹果", unit="斤", is_active=True),
            Product(name="香蕉", unit="斤", is_active=True),
            Product(name="可乐", unit="箱", is_active=True)
        ])
    db.commit()
    return {"message": "数据生成成功"}

# 获取上架商品列表
@app.get("/products/active")
def get_active_products(db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.is_active == True).all()
    return products

# 批量录入订单
class OrderItemCreate(BaseModel):
    product_id: int
    quantity: float

@app.post("/orders/batch")
def create_orders_batch(order_items: List[OrderItemCreate], db: Session = Depends(get_db)):
    today = date.today()
    valid_items = [item for item in order_items if item.quantity > 0]
    
    if not valid_items:
        raise HTTPException(status_code=400, detail="未提供有效数量")

    current_user_id = 1 # 暂时写死 user_id 为 1 测试
    
    for item in valid_items:
        stmt = insert(Order).values(
            user_id=current_user_id,
            product_id=item.product_id,
            order_date=today,
            quantity=item.quantity
        )
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