"""ShopKart Order Service (port 8001): orders, customers and refund execution."""
import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from mock_services.data.database import get_db, init_db
from mock_services.data.models import OrderDB, RefundDB

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("order_service")

# Defence in depth: even if an agent misbehaves, this service refuses large automatic refunds
AUTO_APPROVAL_LIMIT_INR = 10000


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="ShopKart Order Service", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    logger.info(f"{request.method} {request.url.path} - Status: {response.status_code} - Latency: {(time.time() - start) * 1000:.2f}ms")
    return response


def order_to_dict(o: OrderDB) -> dict:
    return {
        "order_id": o.order_id,
        "customer_id": o.customer_id,
        "customer_name": o.customer.name,
        "customer_email": o.customer.email,
        "tier": o.customer.tier,
        "refund_claims_90d": o.customer.refund_claims_90d,
        "item": o.item,
        "category": o.category,
        "price_inr": o.price_inr,
        "shipping_fee_inr": o.shipping_fee_inr,
        "status": o.status,
        "delivered_on": o.delivered_on.isoformat() if o.delivered_on else None,
        "expected_by": o.expected_by.isoformat() if o.expected_by else None,
        "payment_method": o.payment_method,
        "refund_status": o.refund_status,
        "refunded_amount_inr": o.refunded_amount_inr,
    }


@app.get("/health")
def health():
    return {"status": "healthy", "service": "order_service"}


@app.get("/orders")
def list_orders(db: Session = Depends(get_db)):
    return {"orders": [order_to_dict(o) for o in db.query(OrderDB).order_by(OrderDB.order_id).all()]}


@app.get("/orders/{order_id}")
def get_order(order_id: str, db: Session = Depends(get_db)):
    o = db.query(OrderDB).filter(OrderDB.order_id == order_id.strip().upper()).first()
    if not o:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    return order_to_dict(o)


class RefundRequest(BaseModel):
    amount_inr: float
    reason: str


@app.post("/orders/{order_id}/refund")
def issue_refund(order_id: str, req: RefundRequest, db: Session = Depends(get_db)):
    o = db.query(OrderDB).filter(OrderDB.order_id == order_id.strip().upper()).first()
    if not o:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    if req.amount_inr <= 0:
        raise HTTPException(status_code=400, detail="Refund amount must be positive")
    if req.amount_inr > AUTO_APPROVAL_LIMIT_INR:
        logger.warning(f"Blocked automatic refund of Rs {req.amount_inr} for {o.order_id}: above limit")
        raise HTTPException(status_code=403, detail=f"Refunds above Rs {AUTO_APPROVAL_LIMIT_INR} need manual approval")
    if o.refunded_amount_inr + req.amount_inr > o.price_inr + o.shipping_fee_inr:
        raise HTTPException(status_code=400, detail="Refund would exceed the amount paid for this order")

    db.add(RefundDB(order_id=o.order_id, amount_inr=req.amount_inr, reason=req.reason))
    o.refunded_amount_inr += req.amount_inr
    o.refund_status = "INITIATED (5-7 business days)" if o.payment_method != "COD" else "INITIATED (bank transfer / store credit)"
    db.commit()
    logger.info(f"Refund of Rs {req.amount_inr} initiated for {o.order_id}")
    return {"message": "Refund initiated", "order_id": o.order_id, "amount_inr": req.amount_inr,
            "refund_status": o.refund_status, "total_refunded_inr": o.refunded_amount_inr}
