"""SQLite engine, session factory and seed data for the ShopKart mock environment."""
import logging
import os
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mock_services.data.models import Base, CustomerDB, OrderDB

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("shopkart_db")

# The database file lives next to this script (each container gets its own copy)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "shopkart_mock.db"))
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Create the tables and seed mock customers + orders the first time."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(CustomerDB).first():
            return
        logger.info("Database is empty. Seeding ShopKart mock data...")
        db.add_all([
            CustomerDB(customer_id="C001", name="Rahul Mehta",  email="rahul@example.com",  tier="Silver",  refund_claims_90d=0),
            CustomerDB(customer_id="C002", name="Anita Rao",    email="anita@example.com",  tier="Regular", refund_claims_90d=0),
            CustomerDB(customer_id="C003", name="Vikram Singh", email="vikram@example.com", tier="Regular", refund_claims_90d=0),
            CustomerDB(customer_id="C004", name="Sneha Iyer",   email="sneha@example.com",  tier="Gold",    refund_claims_90d=0),
            CustomerDB(customer_id="C005", name="Arjun Das",    email="arjun@example.com",  tier="Regular", refund_claims_90d=3),
            CustomerDB(customer_id="C006", name="Meera Nair",   email="meera@example.com",  tier="Silver",  refund_claims_90d=0),
            CustomerDB(customer_id="C007", name="Karan Gupta",  email="karan@example.com",  tier="Regular", refund_claims_90d=0),
            CustomerDB(customer_id="C008", name="Pooja Sharma", email="pooja@example.com",  tier="Gold",    refund_claims_90d=0),
            CustomerDB(customer_id="C009", name="Imran Khan",   email="imran@example.com",  tier="Regular", refund_claims_90d=1),
        ])
        db.commit()
        d = date.fromisoformat
        db.add_all([
            OrderDB(order_id="ORD1001", customer_id="C001", item="Wireless Headphones",   category="electronics", price_inr=2499,  shipping_fee_inr=0,  status="DELIVERED",  delivered_on=d("2026-10-14"), expected_by=d("2026-10-14"), payment_method="UPI"),
            OrderDB(order_id="ORD1002", customer_id="C002", item="Cotton Kurta",          category="apparel",     price_inr=1299,  shipping_fee_inr=49, status="DELIVERED",  delivered_on=d("2026-10-05"), expected_by=d("2026-10-05"), payment_method="Card"),
            OrderDB(order_id="ORD1003", customer_id="C003", item="Smart Watch",           category="electronics", price_inr=3999,  shipping_fee_inr=99, status="IN_TRANSIT", delivered_on=None,            expected_by=d("2026-10-12"), payment_method="Card"),
            OrderDB(order_id="ORD1004", customer_id="C004", item="14-inch Laptop",        category="electronics", price_inr=62000, shipping_fee_inr=0,  status="DELIVERED",  delivered_on=d("2026-10-15"), expected_by=d("2026-10-15"), payment_method="Card"),
            OrderDB(order_id="ORD1005", customer_id="C005", item="Smartphone",            category="electronics", price_inr=18999, shipping_fee_inr=0,  status="DELIVERED",  delivered_on=d("2026-10-13"), expected_by=d("2026-10-13"), payment_method="UPI"),
            OrderDB(order_id="ORD1006", customer_id="C006", item="20000mAh Power Bank",   category="electronics", price_inr=1499,  shipping_fee_inr=0,  status="DELIVERED",  delivered_on=d("2026-10-10"), expected_by=d("2026-10-10"), payment_method="COD"),
            OrderDB(order_id="ORD1007", customer_id="C007", item="Organic Fruit Basket",  category="grocery",     price_inr=850,   shipping_fee_inr=40, status="DELIVERED",  delivered_on=d("2026-10-16"), expected_by=d("2026-10-16"), payment_method="UPI"),
            OrderDB(order_id="ORD1008", customer_id="C008", item="Running Shoes",         category="apparel",     price_inr=4599,  shipping_fee_inr=0,  status="DELIVERED",  delivered_on=d("2026-09-15"), expected_by=d("2026-09-15"), payment_method="Card"),
            OrderDB(order_id="ORD1009", customer_id="C009", item="Data Science Handbook", category="books",       price_inr=899,   shipping_fee_inr=40, status="DELIVERED",  delivered_on=d("2026-10-14"), expected_by=d("2026-10-14"), payment_method="Card"),
        ])
        db.commit()
        logger.info("Seeded 9 customers and 9 orders.")
    finally:
        db.close()


def get_db():
    """FastAPI dependency: one database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
