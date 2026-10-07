# Storefront

A Django storefront with admin-managed products, a session cart, Stripe Checkout, and a Django REST Framework API.

## Local setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env`, then set a unique `DJANGO_SECRET_KEY` and Stripe **test-mode** keys from your Stripe Dashboard. Do not commit `.env`; it is excluded by `.gitignore`. No Stripe account or credentials are created by this project. Create/verify your developer account yourself at https://dashboard.stripe.com/ and use keys prefixed with `pk_test_` and `sk_test_` for testing.

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Visit `/admin/` to add products (name, price, stock, optional description and image URL). The shop is at `/`. Checkout posts to Stripe-hosted Checkout; without test credentials, it shows a configuration message and does not create a payment. Stripe redirect success is verified against Stripe, and `/webhooks/stripe/` verifies signed `checkout.session.completed` and `checkout.session.expired` events. During local testing, install the Stripe CLI and run `stripe listen --forward-to localhost:8000/webhooks/stripe/`; put the CLI-provided `whsec_...` value in `STRIPE_WEBHOOK_SECRET`. In the Stripe Dashboard, configure the same endpoint for deployed environments.

Use Stripe's test card `4242 4242 4242 4242`, any future expiry, and any CVC when testing Stripe Checkout. Test-mode transactions do not charge a real card.

## REST API

- `GET /api/products/` — list active products
- `GET /api/products/{slug}/` — product detail
- `POST /api/products/` — create product (staff/admin only)
- `GET /api/orders/` — list orders (admin only)
- `GET /api/orders/{id}/` — order detail (admin only)

The API is paginated. Product writes require an authenticated staff user; read access is public.

## Environment settings

`DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, and `STOREFRONT_CURRENCY` are read from the process environment or `.env`.

Before deployment, set `DJANGO_DEBUG=false`, a strong secret, and explicit allowed hosts; serve HTTPS and configure Stripe webhooks.
