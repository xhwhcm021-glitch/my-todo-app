from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import create_engine, Column, Integer, String, Boolean, Date, Numeric, ForeignKey, func
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from sqlalchemy.dialects.postgresql import insert
from pydantic import BaseModel
from typing import List, Optional
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
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7 

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ================= 2. 数据库模型 =================
class Shop(Base):
    __tablename__ = "shops"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    
    # 关系：一个门店可以有多个员工
    users = relationship("User", back_populates="shop")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, unique=True)
    hashed_password = Column(String(255), nullable=False)
    
    # 角色：admin, boss, staff, partner
    role = Column(String(50), nullable=False) 
    
    # 门店外键 (可为空，比如 boss 不需要门店)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=True)
    
    is_active = Column(Boolean, default=True)
    
    shop = relationship("Shop", back_populates="users")
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

Base.metadata.create_all(bind=engine)

# ================= 3. FastAPI 与跨域 =================
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
        shop_id: int = payload.get("shop_id") # 提取 shop_id
        
        if user_id is None or role is None:
            raise HTTPException(status_code=401, detail="无效的 Token")
            
        return {"user_id": user_id, "role": role, "shop_id": shop_id}
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

# ================= 5. Pydantic 模型 =================
class UserLogin(BaseModel):
    name: str
    password: str

class OrderItemCreate(BaseModel):
    product_id: int
    quantity: float

class RoleUpdate(BaseModel):
    role: str
    shop_id: Optional[int] = None

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
    shop_id: Optional[int] = None  # 新增用户时可指定门店

class PasswordReset(BaseModel):
    new_password: str

class OrderUpdate(BaseModel):
    quantity: float

class ShopCreate(BaseModel):
    name: str

# ================= 6. 登录与初始化数据 =================
@app.post("/login")
def login(user_data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.name == user_data.name).first()
    if not user or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    # 把 shop_id 也一起塞进 Token 载荷里
    access_token = create_access_token(data={
        "user_id": user.id, 
        "role": user.role,
        "shop_id": user.shop_id
    })
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/seed_data")
def seed_data(db: Session = Depends(get_db)):
    # 1. 造门店
    if not db.query(Shop).first():
        db.add_all([Shop(name="东城分店"), Shop(name="西城分店")])
        db.commit()
    
    shop_dong = db.query(Shop).filter(Shop.name == "东城分店").first()

    # 2. 造用户
    if not db.query(User).filter(User.name == "admin").first():
        db.add(User(name="admin", role="admin", hashed_password=get_password_hash("123456")))
    if not db.query(User).filter(User.name == "boss").first():
        db.add(User(name="boss", role="boss", hashed_password=get_password_hash("123456")))
    if not db.query(User).filter(User.name == "staff1").first():
        db.add(User(name="staff1", role="staff", shop_id=shop_dong.id, hashed_password=get_password_hash("123456")))

    # 3. 造商品
    if not db.query(Product).first():
        db.add_all([
            Product(name="苹果", unit="斤", is_active=True),
            Product(name="香蕉", unit="斤", is_active=True),
            Product(name="可乐", unit="箱", is_active=True),
        ])
    db.commit()
    return {"message": "初始化成功！账号: admin, boss, staff1，密码均为 123456"}

# ================= 7. 业务接口 (店员) =================
@app.get("/products/active")
def get_active_products(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    return db.query(Product).filter(Product.is_active == True).all()

@app.post("/orders/batch")
def create_orders_batch(
    order_items: List[OrderItemCreate], 
    db: Session = Depends(get_db),
    current_user: dict = Depends(RoleChecker(["staff"])) # 只有 staff 能下单
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

# ================= 8. 业务接口 (老板) =================
@app.get("/boss/daily_summary")
def get_daily_summary(db: Session = Depends(get_db), current_user: dict = Depends(RoleChecker(["boss"]))):
    today = date.today()
    results = db.query(
        Product.name.label("product_name"), Product.unit.label("unit"), func.sum(Order.quantity).label("total_quantity")
    ).join(Order, Product.id == Order.product_id)\
     .filter(Order.order_date == today)\
     .group_by(Product.id, Product.name, Product.unit).all()

    return {"date": str(today), "summary": [{"product_name": r.product_name, "unit": r.unit, "total_quantity": float(r.total_quantity)} for r in results]}

# ================= 9. 业务接口 (管理员) =================
# 门店管理
@app.get("/admin/shops")
def admin_get_shops(db: Session = Depends(get_db), current_user: dict = Depends(RoleChecker(["admin"]))):
    return db.query(Shop).all()

@app.post("/admin/shops")
def admin_create_shop(shop_data: ShopCreate, db: Session = Depends(get_db), current_user: dict = Depends(RoleChecker(["admin"]))):
    if db.query(Shop).filter(Shop.name == shop_data.name).first():
        raise HTTPException(status_code=400, detail="门店已存在")
    db.add(Shop(name=shop_data.name))
    db.commit()
    return {"message": "门店创建成功"}

# 用户管理
@app.get("/admin/users")
def admin_get_users(db: Session = Depends(get_db), current_user: dict = Depends(RoleChecker(["admin"]))):
    users = db.query(User).all()
    return [{"id": u.id, "name": u.name, "role": u.role, "shop_id": u.shop_id, "is_active": u.is_active} for u in users]

@app.post("/admin/users")
def admin_create_user(user_data: UserCreate, db: Session = Depends(get_db), current_user: dict = Depends(RoleChecker(["admin"]))):
    if db.query(User).filter(User.name == user_data.name).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    new_user = User(
        name=user_data.name, role=user_data.role, shop_id=user_data.shop_id,
        hashed_password=get_password_hash(user_data.password), is_active=True
    )
    db.add(new_user)
    db.commit()
    return {"message": "用户创建成功"}

@app.put("/admin/users/{user_id}/role")
def admin_update_role(user_id: int, role_data: RoleUpdate, db: Session = Depends(get_db), current_user: dict = Depends(RoleChecker(["admin"]))):
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(status_code=404, detail="用户不存在")
    user.role = role_data.role
    user.shop_id = role_data.shop_id
    db.commit()
    return {"message": "用户信息已更新"}

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

# 商品管理
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
        raise HTTPException(status_code=400, detail="该商品有历史订单，无法直接删除")
    return {"message": "商品已彻底删除"}

# 订单管理
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
# ================= 10. 密码管理接口 =================

# 定义 Pydantic 模型
class ChangePasswordReq(BaseModel):
    old_password: str
    new_password: str

class AdminResetPasswordReq(BaseModel):
    user_id: int
    new_password: str

# 10.1 用户修改自己的密码 (任何登录用户可用)
@app.post("/auth/change-password")
def change_my_password(
    pwd_data: ChangePasswordReq, 
    db: Session = Depends(get_db), 
    current_user: dict = Depends(get_current_user) # 任何有效 Token 都可以进
):
    # 从 JWT 解析出的字典中获取当前登录用户 ID
    user_id = current_user["user_id"]
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
        
    # 验证旧密码是否正确
    if not verify_password(pwd_data.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="旧密码错误，请重新输入")
        
    # 校验新密码长度（可选，做个简单的安全拦截）
    if len(pwd_data.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码不能少于 6 位")
        
    # 更新密码
    user.hashed_password = get_password_hash(pwd_data.new_password)
    db.commit()
    
    return {"message": "密码修改成功，请重新登录"}


# 10.2 管理员或老板重置他人密码 (admin 和 boss 可用)
@app.post("/admin/reset-password")
def admin_reset_other_password(
    pwd_data: AdminResetPasswordReq, 
    db: Session = Depends(get_db), 
    current_user: dict = Depends(RoleChecker(["admin", "boss"])) # 权限拦截
):
    # 查找目标用户
    target_user = db.query(User).filter(User.id == pwd_data.user_id).first()
    
    if not target_user:
        raise HTTPException(status_code=404, detail="目标用户不存在")
        
    # 校验新密码长度
    if len(pwd_data.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码不能少于 6 位")

    # 权限细化（可选）：老板只能重置店员/自己的密码，不能重置超级管理员的密码
    if current_user["role"] == "boss" and target_user.role == "admin":
        raise HTTPException(status_code=403, detail="老板无权重置超级管理员的密码")

    # 直接覆盖密码，不需要验证旧密码
    target_user.hashed_password = get_password_hash(pwd_data.new_password)
    db.commit()
    
    return {"message": f"已成功重置用户 {target_user.name} 的密码"}
# ================= 启动入口 =================
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)