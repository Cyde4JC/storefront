from django.contrib.auth import get_user_model
import hashlib
import hmac

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import Product


class StorefrontTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(name="Demo mug", price="12.50", stock=3)

    def test_product_list_and_add_to_cart(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Demo mug")
        self.assertContains(response, "KSh 12.50")
        response = self.client.post(f"/cart/add/{self.product.pk}/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session["cart"][str(self.product.pk)], 1)

    def test_public_api_can_list_products_but_not_create(self):
        api = APIClient()
        response = api.get("/api/products/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][0]["name"], "Demo mug")
        response = api.post("/api/products/", {"name": "Nope", "price": "1.00", "stock": 1})
        self.assertEqual(response.status_code, 403)

    def test_staff_can_create_product_through_api(self):
        staff = get_user_model().objects.create_user(username="staff", password="safe-test", is_staff=True)
        api = APIClient()
        api.force_authenticate(staff)
        response = api.post("/api/products/", {"name": "Notebook", "price": "4.25", "stock": 8})
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Product.objects.filter(name="Notebook").exists())

    @override_settings(SASAPAY_CLIENT_ID="", SASAPAY_CLIENT_SECRET="", SASAPAY_MERCHANT_CODE="", SASAPAY_CALLBACK_URL="")
    def test_checkout_without_sasapay_credentials_does_not_start_payment(self):
        self.client.post(f"/cart/add/{self.product.pk}/")
        response = self.client.post("/checkout/", {"email": "buyer@example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SasaPay sandbox is not configured")

    @override_settings(SASAPAY_CALLBACK_SECRET="test-client-id", SASAPAY_MERCHANT_CODE="600980")
    def test_signed_sasapay_callback_marks_matching_order_paid(self):
        from .models import Order

        order = Order.objects.create(customer_email="buyer@example.com", total="12.50",
                                     checkout_request_id="checkout-123", merchant_request_id="ORDER-1")
        payload = {
            "TransactionCode": "TX-1", "MerchantCode": "600980", "CustomerMobile": "254700000000",
            "MerchantRequestID": "ORDER-1", "CheckoutRequestID": "checkout-123",
            "ResultCode": "0", "TransAmount": "12.50",
        }
        message = "TX-1-600980-254700000000-ORDER-1-12.50"
        signature = hmac.new(b"test-client-id", message.encode(), hashlib.sha512).hexdigest()
        response = self.client.post("/webhooks/sasapay/", payload, content_type="application/json",
                                    HTTP_X_SASAPAY_SIGNATURE=signature)
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)
