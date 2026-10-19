"""SQLAlchemy table definitions for the ShopKart mock database."""
from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class CustomerDB(Base):
    __tablename__ = "customers"
    customer_id = Column(String, primary_key=True)          # e.g. C001
    name = Column(String)
    email = Column(String)
    tier = Column(String, default="Regular")               # Regular, Silver, Gold
    refund_claims_90d = Column(Integer, default=0)         # used by the fraud rule

    orders = relationship("OrderDB", back_populates="customer")


class OrderDB(Base):
    __tablename__ = "orders"
    order_id = Column(String, primary_key=True)             # e.g. ORD1001
    customer_id = Column(String, ForeignKey("customers.customer_id"))
    item = Column(String)
    category = Column(String)                               # electronics, apparel, grocery, books, home
    price_inr = Column(Float)
    shipping_fee_inr = Column(Float, default=0)
    status = Column(String)                                 # DELIVERED, IN_TRANSIT, CANCELLED
    delivered_on = Column(Date, nullable=True)
    expected_by = Column(Date)
    payment_method = Column(String)                         # UPI, Card, COD
    refund_status = Column(String, nullable=True)
    refunded_amount_inr = Column(Float, default=0)

    customer = relationship("CustomerDB", back_populates="orders")
    refunds = relationship("RefundDB", back_populates="order")


class RefundDB(Base):
    __tablename__ = "refunds"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String, ForeignKey("orders.order_id"))
    amount_inr = Column(Float)
    reason = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    order = relationship("OrderDB", back_populates="refunds")


class TicketDB(Base):
    __tablename__ = "escalation_tickets"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String, nullable=True)
    priority = Column(String)                               # P1..P4
    team = Column(String)
    triggered_rules = Column(String)                        # comma-separated rule IDs
    summary = Column(String)
    customer_message = Column(String)
    status = Column(String, default="OPEN")
    created_at = Column(DateTime, default=datetime.utcnow)
