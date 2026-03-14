import uuid
import hmac
import hashlib
import os
from app.core.logger import log

class PaymentGateway:
    """
    Enterprise Adapter Pattern for Payment Processing.
    Currently mocks Razorpay's exact flow. Can be swapped to real Razorpay with zero API route changes.
    """
    def __init__(self):
        # When you are ready for real money, we just change this to False
        self.is_mock = os.getenv("USE_MOCK_PAYMENTS", "True").lower() == "true"
        
        # Real Razorpay client will go here later:
        # self.client = razorpay.Client(auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET")))

    def create_order(self, amount_paise: int, receipt_id: str) -> dict:
        """Simulates razorpay.Order.create()"""
        if self.is_mock:
            log.info(f"💳 MOCK GATEWAY: Creating fake order for {amount_paise} paise")
            return {
                "id": f"order_mock_{uuid.uuid4().hex[:10]}",
                "amount": amount_paise,
                "currency": "INR",
                "receipt": receipt_id,
                "status": "created"
            }
        
        # Real Razorpay Logic (For later)
        # return self.client.order.create({"amount": amount_paise, "currency": "INR", "receipt": receipt_id})

    def verify_signature(self, order_id: str, payment_id: str, signature: str) -> bool:
        """Simulates Razorpay's cryptographic signature verification"""
        if self.is_mock:
            log.info(f"💳 MOCK GATEWAY: Verifying fake payment {payment_id}")
            # In our mock frontend, we will always pass this exact string to simulate a valid signature
            return signature == f"mock_sig_for_{payment_id}"

        # Real Razorpay Logic (For later)
        # try:
        #     self.client.utility.verify_payment_signature({
        #         'razorpay_order_id': order_id,
        #         'razorpay_payment_id': payment_id,
        #         'razorpay_signature': signature
        #     })
        #     return True
        # except Exception:
        #     return False

# Initialize a global instance we can import everywhere
gateway = PaymentGateway()