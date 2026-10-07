from django.urls import include, path
from rest_framework.routers import DefaultRouter
from . import views

app_name = "shop"
router = DefaultRouter()
router.register("products", views.ProductViewSet, basename="product")
router.register("orders", views.OrderViewSet, basename="order")

urlpatterns = [
    path("", views.product_list, name="product_list"),
    path("cart/add/<int:product_id>/", views.add_to_cart, name="add_to_cart"),
    path("checkout/", views.checkout, name="checkout"),
    path("checkout/success/", views.checkout_success, name="checkout_success"),
    path("checkout/cancel/", views.checkout_cancel, name="checkout_cancel"),
    path("webhooks/stripe/", views.stripe_webhook, name="stripe_webhook"),
    path("api/", include(router.urls)),
    path("api-auth/", include("rest_framework.urls")),
]
