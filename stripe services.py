# --- START OF FILE app/services/stripe_service.py ---
import os
import logging
from datetime import datetime, timezone
from typing import Optional
from flask import current_app, flash, url_for
import stripe
# Import db instance and User model safely
# This assumes db is initialized in app/__init__ before routes using this are called
from .. import db
from ..models import User

log = logging.getLogger(__name__)
_stripe_initialized = False

def initialize_stripe():
    """Initializes the Stripe library with the API key from Flask config."""
    global _stripe_initialized
    if not _stripe_initialized:
        api_key = current_app.config.get('STRIPE_SECRET_KEY')
        if not api_key:
            log.error("Stripe API secret key not found in configuration.")
            raise ValueError("STRIPE_SECRET_KEY is not configured.")
        try:
            stripe.api_key = api_key
            _stripe_initialized = True
            log.info("Stripe client initialized.")
        except Exception as e:
            log.exception(f"Failed to initialize Stripe client: {e}")
            raise RuntimeError("Could not initialize Stripe client") from e

def create_stripe_customer_if_not_exists(user: User) -> Optional[str]:
    """Creates a Stripe Customer if one doesn't exist for the user, returns Customer ID."""
    if user.stripe_customer_id:
        # Optional: Verify customer exists on Stripe side? Good for robustness.
        # try: stripe.Customer.retrieve(user.stripe_customer_id); return user.stripe_customer_id
        # except stripe.error.InvalidRequestError: log.warning(f"Stripe customer {user.stripe_customer_id} not found for user {user.id}. Creating new one."); user.stripe_customer_id = None
        # except Exception as e: log.error(f"Error verifying Stripe customer {user.stripe_customer_id}: {e}"); # Fallthrough to create
        return user.stripe_customer_id # Assume exists if ID present

    initialize_stripe()
    try:
        log.info(f"User {user.id}: Creating Stripe Customer for email {user.email}")
        customer = stripe.Customer.create(
            email=user.email, name=user.username,
            metadata={'app_user_id': str(user.id), 'app_username': user.username}
        )
        user.stripe_customer_id = customer.id
        db.session.add(user)
        db.session.commit() # Commit customer ID immediately
        log.info(f"User {user.id}: Stripe Customer created: {customer.id}")
        return customer.id
    except stripe.error.StripeError as e: log.error(f"Stripe error creating customer for user {user.id}: {e}"); db.session.rollback(); flash("Could not create billing profile.", "danger"); return None
    except Exception as e: log.exception(f"Unexpected error creating customer for user {user.id}: {e}"); db.session.rollback(); flash("Error setting up billing.", "danger"); return None

def create_stripe_checkout_session(user: User, price_id: str) -> Optional[str]:
    """Creates a Stripe Checkout session for a subscription."""
    initialize_stripe()
    customer_id = create_stripe_customer_if_not_exists(user)
    if not customer_id: return None # Error flashed previously

    try:
        # Generate URLs within request context if possible, otherwise ensure SERVER_NAME is set
        success_url = url_for('main.subscription', session_id='{CHECKOUT_SESSION_ID}', _external=True)
        cancel_url = url_for('main.subscription', cancelled='true', _external=True) # Use 'true' string
    except RuntimeError:
         log.error("Cannot generate external URLs for Stripe outside of request context or without SERVER_NAME config.")
         flash("Configuration error creating checkout link.", "danger")
         return None

    try:
        log.info(f"User {user.id}: Creating Stripe Checkout session for price {price_id}")
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id, payment_method_types=['card'],
            line_items=[{'price': price_id, 'quantity': 1}],
            mode='subscription', success_url=success_url, cancel_url=cancel_url,
            metadata={ 'app_user_id': str(user.id) },
            # allow_promotion_codes=True, # Optional
        )
        log.info(f"User {user.id}: Stripe Checkout session created: {checkout_session.id}")
        return checkout_session.url # URL for redirection
    except stripe.error.StripeError as e: log.error(f"Stripe error creating checkout session for user {user.id}: {e}"); flash("Could not initiate checkout.", "danger"); return None
    except Exception as e: log.exception(f"Unexpected error creating checkout session for user {user.id}: {e}"); flash("Error during checkout setup.", "danger"); return None

def create_customer_portal_session(user: User) -> Optional[str]:
    """Creates a Stripe Billing Portal session for a user."""
    initialize_stripe()
    if not user.stripe_customer_id: log.error(f"User {user.id} requested portal but has no stripe_customer_id."); flash("Could not find billing profile.", "warning"); return None

    try: return_url = url_for('main.subscription', _external=True)
    except RuntimeError: log.error("Cannot generate external URLs for Stripe Portal."); flash("Config error creating portal link.", "danger"); return None

    try:
        portal_session = stripe.billing_portal.Session.create(customer=user.stripe_customer_id, return_url=return_url)
        log.info(f"User {user.id}: Created Stripe Billing Portal session.")
        return portal_session.url
    except stripe.error.StripeError as e: log.error(f"Stripe error creating portal session for user {user.id}: {e}"); flash("Could not open billing portal.", "danger"); return None
    except Exception as e: log.exception(f"Unexpected error creating portal session for user {user.id}: {e}"); flash("Error opening billing portal.", "danger"); return None

# --- Webhook Event Handlers (Refined) ---
def handle_checkout_session_completed(session_data: dict):
    """Handles the 'checkout.session.completed' event."""
    metadata = session_data.get('metadata', {}); customer_id = session_data.get('customer')
    subscription_id = session_data.get('subscription'); user_id_str = metadata.get('app_user_id')
    session_id = session_data.get('id')
    log.info(f"Webhook: checkout.session.completed session:{session_id} user:{user_id_str} sub:{subscription_id}")
    if not user_id_str: log.error(f"Webhook Error: Missing app_user_id session:{session_id}"); return
    try:
        user_id = int(user_id_str)
        user = db.session.get(User, user_id)
        if not user: log.error(f"Webhook Error: User {user_id} not found session:{session_id}"); return
        if not subscription_id: log.error(f"Webhook Error: Missing subscription ID session:{session_id} user:{user_id}"); return
        if user.stripe_subscription_id == subscription_id and user.is_subscribed: log.warning(f"Webhook Info: User {user_id} already processed sub:{subscription_id}. Skipping."); return

        initialize_stripe() # Ensure key set in this context
        subscription = stripe.Subscription.retrieve(subscription_id)
        ends_at = datetime.fromtimestamp(subscription.current_period_end, tz=timezone.utc) if subscription.current_period_end else None
        is_active = subscription.status in ('active', 'trialing')

        user.update_subscription(status=is_active, sub_id=subscription_id, ends_at=ends_at)
        if customer_id and user.stripe_customer_id != customer_id: user.stripe_customer_id = customer_id # Update customer ID if needed
        elif customer_id and not user.stripe_customer_id: user.stripe_customer_id = customer_id

        db.session.commit()
        log.info(f"Webhook success: User {user.id} sub activated via checkout. Status:{subscription.status} Ends:{ends_at}")
    except stripe.error.StripeError as e: log.error(f"Webhook Stripe Error handling checkout user:{user_id_str} session:{session_id}: {e}"); db.session.rollback()
    except ValueError: log.error(f"Webhook Error: Invalid user_id '{user_id_str}' session:{session_id}.")
    except Exception as e: log.exception(f"Webhook Error handling checkout user:{user_id_str} session:{session_id}: {e}"); db.session.rollback()

def handle_subscription_updated(subscription_data: dict):
    """Handles 'customer.subscription.updated' events."""
    subscription_id = subscription_data.get('id'); customer_id = subscription_data.get('customer')
    status = subscription_data.get('status'); cancel_at_period_end = subscription_data.get('cancel_at_period_end', False)
    current_period_end = subscription_data.get('current_period_end')
    log.info(f"Webhook: subscription.updated sub:{subscription_id} status:{status} cancel_at_end:{cancel_at_period_end}")

    user = User.query.filter_by(stripe_subscription_id=subscription_id).first()
    if not user and customer_id: user = User.query.filter_by(stripe_customer_id=customer_id).order_by(User.id.desc()).first()
    if not user: log.warning(f"Webhook Warning: Sub update for unknown user/sub: {subscription_id}"); return

    try:
        is_newly_active = status in ('active', 'trialing') and not cancel_at_period_end
        new_ends_at = datetime.fromtimestamp(current_period_end, tz=timezone.utc) if current_period_end else None
        if user.is_subscribed != is_newly_active or user.subscription_ends_at != new_ends_at:
            log.info(f"Webhook: Updating user:{user.id} sub:{subscription_id}. Active:{is_newly_active}, End:{new_ends_at}")
            user.update_subscription(status=is_newly_active, sub_id=subscription_id, ends_at=new_ends_at)
            db.session.commit()
        else: log.info(f"Webhook: No change detected user:{user.id} sub:{subscription_id}.")
    except Exception as e: log.exception(f"Webhook Error handling sub update user:{user.id} sub:{subscription_id}: {e}"); db.session.rollback()

def handle_subscription_deleted(subscription_data: dict):
    """Handles 'customer.subscription.deleted' event."""
    subscription_id = subscription_data.get('id')
    log.info(f"Webhook: subscription.deleted sub:{subscription_id}")
    user = User.query.filter_by(stripe_subscription_id=subscription_id).first()
    if not user: log.warning(f"Webhook Warning: Sub deletion for unknown user/sub: {subscription_id}"); return
    try:
        user.clear_subscription()
        db.session.commit()
        log.info(f"Webhook success: User {user.id} subscription cleared sub:{subscription_id}.")
    except Exception as e: log.exception(f"Webhook Error handling sub deletion user:{user.id} sub:{subscription_id}: {e}"); db.session.rollback()
# --- END OF FILE app/services/stripe_service.py ---