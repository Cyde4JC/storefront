from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
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
        if not settings.STRIPE_SECRET_KEY:
            messages.error(request, "Checkout is not configured yet. Set STRIPE_SECRET_KEY to a Stripe test key.")
            return render(request, "playground/checkout.html", {"rows": rows, "total": total})
        order = Order.objects.create(customer_email=email, total=total)
        for row in rows:
            product = row["product"]
            OrderItem.objects.create(order=order, product=product, product_name=product.name,
                                     unit_price=product.price, quantity=row["quantity"])
        try:
            import stripe
            stripe.api_key = settings.STRIPE_SECRET_KEY
            session = stripe.checkout.Session.create(
                mode="payment", customer_email=email,
                line_items=[{
                    "price_data": {"currency": settings.STOREFRONT_CURRENCY,
                                   "product_data": {"name": row["product"].name},
                                   "unit_amount": int(row["product"].price * 100)},
                    "quantity": row["quantity"],
                } for row in rows],
                metadata={"order_id": str(order.pk)},
                success_url=request.build_absolute_uri(reverse("shop:checkout_success")) + "?session_id={CHECKOUT_SESSION_ID}",
                cancel_url=request.build_absolute_uri(reverse("shop:checkout_cancel")),
            )
            order.stripe_session_id = session.id
            order.save(update_fields=["stripe_session_id"])
            return redirect(session.url)
        except Exception:
            order.status = Order.Status.FAILED
            order.save(update_fields=["status"])
            messages.error(request, "Could not start Stripe Checkout. Verify your Stripe test credentials and try again.")
    return render(request, "playground/checkout.html", {"rows": rows, "total": total})


def checkout_success(request):
    session_id = request.GET.get("session_id")
    if session_id and settings.STRIPE_SECRET_KEY:
        try:
            import stripe
            stripe.api_key = settings.STRIPE_SECRET_KEY
            stripe_session = stripe.checkout.Session.retrieve(session_id)
            order = Order.objects.get(pk=stripe_session.metadata["order_id"], stripe_session_id=session_id)
            if stripe_session.payment_status == "paid":
                order.status = Order.Status.PAID
                order.save(update_fields=["status"])
                request.session["cart"] = {}
        except Exception:
            return HttpResponseBadRequest("Unable to verify checkout session.")
    else:
        order = None
    return render(request, "playground/checkout_success.html", {"order": order})


def checkout_cancel(request):
    return render(request, "playground/checkout_cancel.html")


@csrf_exempt
@require_POST
def stripe_webhook(request):
    if not settings.STRIPE_WEBHOOK_SECRET:
        return HttpResponse("Webhook is not configured", status=503)
    try:
        import stripe
        event = stripe.Webhook.construct_event(
            request.body,
            request.headers.get("Stripe-Signature", ""),
            settings.STRIPE_WEBHOOK_SECRET,
        )
    except (ValueError, Exception):
        return HttpResponseBadRequest("Invalid webhook signature or payload")
    if event.type == "checkout.session.completed":
        session = event.data.object
        if session.payment_status == "paid":
            Order.objects.filter(pk=session.metadata.get("order_id"), stripe_session_id=session.id,
                                 status=Order.Status.PENDING).update(status=Order.Status.PAID)
    elif event.type == "checkout.session.expired":
        session = event.data.object
        Order.objects.filter(pk=session.metadata.get("order_id"), stripe_session_id=session.id,
                             status=Order.Status.PENDING).update(status=Order.Status.FAILED)
    return HttpResponse(status=200)
