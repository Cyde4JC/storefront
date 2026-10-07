from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Product


class StorefrontTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(name="Demo mug", price="12.50", stock=3)

    def test_product_list_and_add_to_cart(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Demo mug")
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

    def test_checkout_without_stripe_key_does_not_create_charge(self):
        self.client.post(f"/cart/add/{self.product.pk}/")
        response = self.client.post("/checkout/", {"email": "buyer@example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not configured yet")
