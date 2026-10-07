import hashlib
import hmac
import json
from decimal import Decimal

import requests
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework import permissions, viewsets

from .models import Order, OrderItem, Product
from .serializers import OrderSerializer, ProductSerializer


class IsAdminUserOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.method in permissions.SAFE_METHODS or
                    (request.user and request.user.is_authenticated and request.user.is_staff))


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.filter(is_active=True)
    serializer_class = ProductSerializer
    permission_classes = [IsAdminUserOrReadOnly]
    lookup_field = "slug"


class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Order.objects.prefetch_related("items").all()
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAdminUser]


def _cart(request):
    return request.session.setdefault("cart", {})


def product_list(request):
    products = Product.objects.filter(is_active=True)
    cart_count = sum(int(qty) for qty in _cart(request).values())
    return render(request, "playground/product_list.html", {"products": products, "cart_count": cart_count})


@require_POST
def add_to_cart(request, product_id):
    product = get_object_or_404(Product, pk=product_id, is_active=True)
    cart = _cart(request)
    key = str(product.pk)
    quantity = int(cart.get(key, 0))
    if quantity >= product.stock:
        messages.error(request, "There is not enough stock available.")
    else:
        cart[key] = quantity + 1
        request.session.modified = True
        messages.success(request, f"{product.name} added to your cart.")
    return redirect("shop:product_list")


def _sasapay_ready():
    return all((settings.SASAPAY_CLIENT_ID, settings.SASAPAY_CLIENT_SECRET, settings.SASAPAY_MERCHANT_CODE,
                settings.SASAPAY_CALLBACK_URL))


def _sasapay_checkout_url():
    return settings.SASAPAY_API_BASE.rstrip("/") + "/api/v1/payments/card-payments/"


def _start_sasapay_checkout(order, rows, email, request):
    base = settings.SASAPAY_API_BASE.rstrip("/")
    token_response = requests.get(
        f"{base}/api/v1/auth/token/",
        params={"grant_type": "client_credentials"},
        auth=(settings.SASAPAY_CLIENT_ID, settings.SASAPAY_CLIENT_SECRET),
        timeout=20,
    )
    token_response.raise_for_status()
    token = token_response.json().get("access_token")
    if not token:
        raise ValueError("SasaPay did not return an access token")

    payload = {
        "MerchantCode": settings.SASAPAY_MERCHANT_CODE,
        "Amount": f"{order.total:.2f}",
        "Reference": f"ORDER-{order.pk}",
        "Description": f"Storefront order {order.pk}",
        "Currency": "KES",
        "PayerEmail": email,
        "CallbackUrl": settings.SASAPAY_CALLBACK_URL,
        "RedirectUrl": request.build_absolute_uri(reverse("shop:checkout_success")) + f"?order_id={order.pk}",
        "SuccessUrl": request.build_absolute_uri(reverse("shop:checkout_success")) + f"?order_id={order.pk}",
        "FailureUrl": request.build_absolute_uri(reverse("shop:checkout_cancel")) + f"?order_id={order.pk}",
        "RedirectEnabled": True,
        "SasaPayWalletEnabled": True,
        "MpesaEnabled": True,
        "AirtelEnabled": True,
        "CardEnabled": True,
    }
    response = requests.post(
        _sasapay_checkout_url(), json=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    result = response.json()
    checkout_url = result.get("CheckoutUrl")
    if result.get("status") is not True or not checkout_url:
        raise ValueError(result.get("ResponseDescription") or result.get("detail") or "SasaPay did not return a checkout URL")
    order.checkout_request_id = result.get("CheckoutRequestID") or None
    order.merchant_request_id = str(result.get("MerchantRequestID") or f"ORDER-{order.pk}")
    order.save(update_fields=["checkout_request_id", "merchant_request_id"])
    return checkout_url


def checkout(request):
    cart = _cart(request)
    products = Product.objects.filter(pk__in=cart.keys(), is_active=True)
    rows = []
    total = Decimal("0.00")
    for product in products:
        quantity = min(int(cart.get(str(product.pk), 0)), product.stock)
        if quantity:
            line_total = product.price * quantity
            rows.append({"product": product, "quantity": quantity, "line_total": line_total})
            total += line_total
    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        if not email or not rows:
            messages.error(request, "Enter a valid email and add at least one available product.")
            return render(request, "playground/checkout.html", {"rows": rows, "total": total})
        if not _sasapay_ready():
            messages.error(request, "SasaPay sandbox is not configured. Add its developer credentials and callback URL to your local .env file.")
            return render(request, "playground/checkout.html", {"rows": rows, "total": total})
        order = Order.objects.create(customer_email=email, total=total)
        for row in rows:
            product = row["product"]
            OrderItem.objects.create(order=order, product=product, product_name=product.name,
                                     unit_price=product.price, quantity=row["quantity"])
        try:
            return redirect(_start_sasapay_checkout(order, rows, email, request))
        except (requests.RequestException, ValueError, KeyError) as exc:
            order.status = Order.Status.FAILED
            order.save(update_fields=["status"])
            if settings.DEBUG:
                messages.error(request, f"Could not start SasaPay checkout: {exc}")
            else:
                messages.error(request, "Could not start SasaPay checkout. Verify your sandbox settings and try again.")
    return render(request, "playground/checkout.html", {"rows": rows, "total": total})


def checkout_success(request):
    order = None
    order_id = request.GET.get("order_id")
    if order_id:
        order = Order.objects.filter(pk=order_id).first()
        if order and order.status == Order.Status.PAID:
            request.session["cart"] = {}
    return render(request, "playground/checkout_success.html", {"order": order})


def checkout_cancel(request):
    return render(request, "playground/checkout_cancel.html")


@csrf_exempt
@require_POST
def sasapay_callback(request):
    """Validate SasaPay's HMAC-SHA512 callback before changing order status."""
    if not settings.SASAPAY_CALLBACK_SECRET:
        return HttpResponse("SasaPay callback verification is not configured", status=503)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return HttpResponseBadRequest("Invalid JSON callback")

    signature = request.headers.get("X-SasaPay-Signature", "")
    signature_values = (
        payload.get("TransactionCode") or payload.get("TransID") or "",
        payload.get("MerchantCode") or "",
        payload.get("CustomerMobile") or payload.get("AccountNumber") or "",
        payload.get("MerchantRequestID") or payload.get("MerchantReference") or "",
        payload.get("TransAmount") or payload.get("RequestedAmount") or "",
    )
    message = "-".join(str(value) for value in signature_values)
    expected = hmac.new(settings.SASAPAY_CALLBACK_SECRET.encode(), message.encode(), hashlib.sha512).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature):
        return HttpResponse("Invalid SasaPay callback signature", status=401)
    if str(payload.get("MerchantCode", "")) != settings.SASAPAY_MERCHANT_CODE:
        return HttpResponse("Merchant code mismatch", status=400)

    merchant_reference = str(payload.get("MerchantRequestID") or payload.get("MerchantReference") or "")
    checkout_id = str(payload.get("CheckoutRequestID") or payload.get("CheckoutId") or "")
    result_code = str(payload.get("ResultCode", ""))
    success = result_code == "0" and (payload.get("Paid") is not False)
    try:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(merchant_request_id=merchant_reference)
            if order.checkout_request_id and checkout_id and order.checkout_request_id != checkout_id:
                return HttpResponse("Checkout ID mismatch", status=400)
            amount = Decimal(str(payload.get("TransAmount") or payload.get("PaidAmount") or payload.get("RequestedAmount") or "0"))
            if success and amount == order.total and order.status == Order.Status.PENDING:
                order.status = Order.Status.PAID
                order.save(update_fields=["status"])
            elif not success and order.status == Order.Status.PENDING:
                order.status = Order.Status.FAILED
                order.save(update_fields=["status"])
    except Order.DoesNotExist:
        return HttpResponse("Unknown order reference", status=404)
    except (ValueError, TypeError):
        return HttpResponseBadRequest("Invalid amount in callback")
    return HttpResponse(status=200)
