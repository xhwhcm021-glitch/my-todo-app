from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from datetime import date
from pydantic import BaseModel
from typing import List
from fastapi.middleware.cors import CORSMiddleware

# 假设你现有的导入
# from database import get_db
# from models import Product, Order, User
# from auth import get_current_user

app = FastAPI()

# 解决跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= 数据模型 (Pydantic) =================
class OrderItemCreate(BaseModel):
    product_id: int
    quantity: float

# ================= 你原有的接口（保持不动） =================
@app.get("/")
def root():
    return {"message": "Hello World"}

# (你的 /register, /login, /todos 接口原样保留在这里...)

# ================= 新加的订货接口 =================
@app.get("/products/active")
def get_active_products(
    db: Session = Depends(get_db),
    # current_user: User = Depends(get_current_user) 
):
    # 先去掉权限验证测试一下，通了再把权限加上
    products = db.query(Product).filter(Product.is_active == True).all()
    return products

@app.post("/orders/batch")
def create_orders_batch(
    order_items: List[OrderItemCreate],
    db: Session = Depends(get_db),
    # current_user: User = Depends(get_current_user)
):
    today = date.today()
    valid_items = [item for item in order_items if item.quantity > 0]
    
    for item in valid_items:
        stmt = insert(Order).values(
            user_id=1, # 测试用，写死 user_id=1。通了再换成 current_user.id
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
    return {"status": "success", "message": f"成功录入 {len(valid_items)} 条商品数据"}
