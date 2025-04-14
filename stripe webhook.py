# --- START OF FILE app/stripe_webhooks/__init__.py ---
from flask import Blueprint
stripe_bp = Blueprint('stripe_webhooks', __name__)
from . import routes
# --- END OF FILE app/stripe_webhooks/__init__.py ---