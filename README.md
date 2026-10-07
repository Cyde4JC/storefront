# Storefront

A Django storefront with admin-managed products priced in Kenyan shillings (KES), a session cart, SasaPay-hosted checkout and a Django REST Framework API.

## Local setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Git Bash on Windows: source .venv/Scripts/activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Set a unique `DJANGO_SECRET_KEY` in `.env`. Do not commit `.env`; it is excluded by `.gitignore`.

## SasaPay sandbox setup

1. Register a merchant account at https://merchants.sasapay.app/auth/register and complete any onboarding required to obtain/use a merchant code.
2. Register at https://developer.sasapay.app/ and create a **Sandbox Application**. Set its callback URL to your publicly reachable URL ending in `/webhooks/sasapay/`.
3. Copy the sandbox Client ID and Client Secret into `SASAPAY_CLIENT_ID` and `SASAPAY_CLIENT_SECRET` in local `.env`. Add the sandbox merchant code to `SASAPAY_MERCHANT_CODE`. Keep all credentials private.
4. SasaPay must reach the callback over HTTPS. For local development, run a tunnel such as Cloudflare Tunnel or ngrok to port 8000, configure the resulting HTTPS URL plus `/webhooks/sasapay/` in both the SasaPay app and `SASAPAY_CALLBACK_URL`.
5. Start Django and test checkout from the site. SasaPay sandbox checkout offers payment choices according to the sandbox application, including M-Pesa, Airtel Money, SasaPay wallet and card as enabled by its API.

The project requests an OAuth token from the sandbox, creates a KES hosted checkout, redirects the customer, and validates the SasaPay `X-SasaPay-Signature` HMAC-SHA512 callback before marking a matching order paid. The signing key defaults to the app Client ID as described in SasaPay's callback-security documentation; override `SASAPAY_CALLBACK_SECRET` only if the provider gives a different value. Callback amount, merchant and order references are checked. The return/redirect page is not treated as proof of payment; the callback updates status.

For production, get SasaPay approval and production app credentials, use the provider's production base URL and HTTPS domain, and follow the provider's merchant onboarding and callback security guidance. Do not use production credentials for testing.

## Run Django

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Visit `/admin/` to add products (price in KES); the shop is at `/`.

## REST API

- `GET /api/products/` — list active products
- `GET /api/products/{slug}/` — product detail
- `POST /api/products/` — create product (staff/admin only)
- `GET /api/orders/` — list orders (admin only)
- `GET /api/orders/{id}/` — order detail (admin only)

The API is paginated. Product writes require an authenticated staff user; read access is public.

Before deployment, set `DJANGO_DEBUG=false`, a strong secret, and explicit allowed hosts; serve HTTPS.

## Official SasaPay documentation

- [Getting started](https://developer.sasapay.app/docs/getting-started)
- [Authentication](https://developer.sasapay.app/docs/apis/authentication)
- [Checkout payments](https://developer.sasapay.app/docs/checkout-payments)
- [Callback security](https://developer.sasapay.app/docs/apis/callback-security)
