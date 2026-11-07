from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import create_engine, Column, Integer, String, Boolean, Date, Numeric, ForeignKey, func
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
    hashed_password = Column(String(255), nullable=False)
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

# 自动建表（如果表不存在会自动创建）
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
        raise HTTPException(status_code=401, detail="登录已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效的凭证")

class RoleChecker:
    def __init__(self, allowed_roles: list):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: dict = Depends(get_current_user)):
        if current_user["role"] not in self.allowed_roles:
            raise HTTPException(status_code=403, detail="权限不足")
        return current_user

# ================= 5. Pydantic 数据模型 =================
class UserLogin(BaseModel):
    name: str
    password: str

class OrderItemCreate(BaseModel):
    product_id: int
    quantity: float

class RoleUpdate(BaseModel):
    role: str

class ProductCreate(BaseModel):
    name: str
    unit: str

class ProductUpdate(BaseModel):
    name: str
    unit: str

class UserCreate(BaseModel):
    name: str
    password: str
    role: str

class PasswordReset(BaseModel):
    new_password: str

class OrderUpdate(BaseModel):
    quantity: float

# ================= 6. 基础与测试接口 =================
@app.post("/login")
def login(user_data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.name == user_data.name).first()
    if not user or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    access_token = create_access_token(data={"user_id": user.id, "role": user.role})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/seed_data")
def seed_data(db: Session = Depends(get_db)):
    # 如果没有 admin 账号，创建一个默认的
    if not db.query(User).filter(User.role == "admin").first():
        db.add(User(name="admin", role="admin", hashed_password=get_password_hash("123456"), is_active=True))
    if not db.query(Product).first():
        db.add_all([
            Product(name="苹果", unit="斤", is_active=True),
            Product(name="香蕉", unit="斤", is_active=True),
            Product(name="可乐", unit="箱", is_active=True),
        ])
    db.commit()
    return {"message": "数据生成成功，默认管理员: admin/123456"}

# ================= 7. 店员接口 =================
@app.get("/products/active")
def get_active_products(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    return db.query(Product).filter(Product.is_active == True).all()

@app.post("/orders/batch")
def create_orders_batch(
    order_items: List[OrderItemCreate], 
    db: Session = Depends(get_db),
    current_user: dict = Depends(RoleChecker(["store_a", "store_b"])) 
):
    today = date.today()
    valid_items = [item for item in order_items if item.quantity > 0]
    if not valid_items: raise HTTPException(status_code=400, detail="未提供有效数量")

    current_user_id = current_user["user_id"]
    
    try:
        for item in valid_items:
            stmt = insert(Order).values(
                user_id=current_user_id, product_id=item.product_id,
                order_date=today, quantity=item.quantity
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=['user_id', 'order_date', 'product_id'], 
                set_=dict(quantity=Order.quantity + stmt.excluded.quantity)
            )
            db.execute(stmt)
        db.commit()
        return {"status": "success", "message": f"成功录入 {len(valid_items)} 条数据"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# ================= 8. 老板看板接口 =================
@app.get("/boss/daily_summary")
def get_daily_summary(db: Session = Depends(get_db), current_user: dict = Depends(RoleChecker(["h", "boss_h"]))):
    today = date.today()
    results = db.query(
        Product.name.label("product_name"), Product.unit.label("unit"), func.sum(Order.quantity).label("total_quantity")
    ).join(Order, Product.id == Order.product_id)\
     .filter(Order.order_date == today)\
     .group_by(Product.id, Product.name, Product.unit).all()

    return {"date": str(today), "summary": [{"product_name": r.product_name, "unit": r.unit, "total_quantity": float(r.total_quantity)} for r in results]}

# ================= 9. 管理员接口 =================
@app.get("/admin/users")
def admin_get_users(db: Session = Depends(get_db), current_user: dict = Depends(RoleChecker(["admin"]))):
    return [{"id": u.id, "name": u.name, "role": u.role, "is_active": u.is_active} for u in db.query(User).all()]

@app.post("/admin/users")
def admin_create_user(user_data: UserCreate, db: Session = Depends(get_db), current_user: dict = Depends(RoleChecker(["admin"]))):
    if db.query(User).filter(User.name == user_data.name).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    new_user = User(name=user_data.name, role=user_data.role, hashed_password=get_password_hash(user_data.password), is_active=True)
    db.add(new_user)
    db.commit()
    return {"message": "创建成功"}

@app.put("/admin/users/{user_id}/role")
def admin_update_role(user_id: int, role_data: RoleUpdate, db: Session = Depends(get_db), current_user: dict = Depends(RoleChecker(["admin"]))):
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(status_code=404, detail="用户不存在")
    user.role = role_data.role
    db.commit()
    return {"message": "角色已更新"}

@app.put("/admin/users/{user_id}/password")
def admin_reset_password(user_id: int, pwd_data: PasswordReset, db: Session = Depends(get_db), current_user: dict = Depends(RoleChecker(["admin"]))):
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(status_code=404, detail="用户不存在")
    user.hashed_password = get_password_hash(pwd_data.new_password)
    db.commit()
    return {"message": "密码已重置"}

@app.delete("/admin/users/{user_id}")
def admin_delete_user(user_id: int, db: Session = Depends(get_db), current_user: dict = Depends(RoleChecker(["admin"]))):
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(status_code=404, detail="用户不存在")
    if user.name == "admin": raise HTTPException(status_code=400, detail="不能删除超级管理员")
    try:
        db.delete(user); db.commit()
    except Exception:
        raise HTTPException(status_code=400, detail="该用户有历史订单，无法删除")
    return {"message": "用户已删除"}

@app.get("/admin/products")
def admin_get_products(db: Session = Depends(get_db), current_user: dict = Depends(RoleChecker(["admin"]))):
    return db.query(Product).all()

@app.post("/admin/products")
def admin_create_product(product_data: ProductCreate, db: Session = Depends(get_db), current_user: dict = Depends(RoleChecker(["admin"]))):
    db.add(Product(name=product_data.name, unit=product_data.unit, is_active=True))
    db.commit()
    return {"message": "商品新增成功"}

@app.put("/admin/products/{product_id}")
def admin_update_product(product_id: int, prod_data: ProductUpdate, db: Session = Depends(get_db), current_user: dict = Depends(RoleChecker(["admin"]))):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product: raise HTTPException(status_code=404, detail="商品不存在")
    product.name = prod_data.name; product.unit = prod_data.unit
    db.commit()
    return {"message": "商品信息已更新"}

@app.put("/admin/products/{product_id}/toggle")
def admin_toggle_product(product_id: int, db: Session = Depends(get_db), current_user: dict = Depends(RoleChecker(["admin"]))):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product: raise HTTPException(status_code=404, detail="商品不存在")
    product.is_active = not product.is_active
    db.commit()
    return {"message": "状态已切换"}

@app.delete("/admin/products/{product_id}")
def admin_delete_product(product_id: int, db: Session = Depends(get_db), current_user: dict = Depends(RoleChecker(["admin"]))):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product: raise HTTPException(status_code=404, detail="商品不存在")
    try:
        db.delete(product); db.commit()
    except Exception:
        raise HTTPException(status_code=400, detail="该商品有历史订单，无法直接删除，建议下架")
    return {"message": "商品已彻底删除"}

@app.get("/admin/orders")
def admin_get_orders(db: Session = Depends(get_db), current_user: dict = Depends(RoleChecker(["admin"]))):
    results = db.query(
        Order.id, User.name.label("user_name"), Product.name.label("product_name"), Order.quantity, Order.order_date
    ).join(User, Order.user_id == User.id).join(Product, Order.product_id == Product.id)\
     .order_by(Order.order_date.desc(), Order.id.desc()).all()
    return [{"id": r.id, "user_name": r.user_name, "product_name": r.product_name, "quantity": float(r.quantity), "date": str(r.order_date)} for r in results]

@app.put("/admin/orders/{order_id}")
def admin_update_order(order_id: int, order_data: OrderUpdate, db: Session = Depends(get_db), current_user: dict = Depends(RoleChecker(["admin"]))):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order: raise HTTPException(status_code=404, detail="订单不存在")
    if order_data.quantity <= 0:
        db.delete(order)
    else:
        order.quantity = order_data.quantity
    db.commit()
    return {"message": "订单已修改"}

@app.delete("/admin/orders/{order_id}")
def admin_delete_order(order_id: int, db: Session = Depends(get_db), current_user: dict = Depends(RoleChecker(["admin"]))):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order: raise HTTPException(status_code=404, detail="订单不存在")
    db.delete(order); db.commit()
    return {"message": "订单已删除"}

# ================= 启动入口 =================
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)