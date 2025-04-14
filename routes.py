# --- START OF FILE app/stripe_webhooks/routes.py ---
import logging
from flask import request, abort, current_app, jsonify
import stripe
from . import stripe_bp
# Import service functions and ensure db is accessible via app context
from ..services.stripe_service import (initialize_stripe, handle_checkout_session_completed,
                                       handle_subscription_updated, handle_subscription_deleted)

log = logging.getLogger(__name__)

@stripe_bp.route('/', methods=['POST'])
def stripe_webhook():
    """Handles incoming Stripe webhook events."""
    try: initialize_stripe() # Ensure key set
    except Exception as e: log.error(f"Webhook Error: Stripe init failed: {e}"); return jsonify(error={"message": "Config error"}), 500

    payload = request.data; sig_header = request.headers.get('Stripe-Signature')
    webhook_secret = current_app.config.get('STRIPE_WEBHOOK_SECRET')
    if not webhook_secret: log.error("Webhook Error: Stripe secret missing."); return jsonify(error={"message": "Config error"}), 500

    event = None
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        log.info(f"Webhook received - ID: {event.id}, Type: {event.type}")
    except ValueError as e: log.error(f"Webhook Error: Invalid payload: {e}"); return jsonify(error={"message": "Invalid payload"}), 400
    except stripe.error.SignatureVerificationError as e: log.error(f"Webhook Error: Invalid signature: {e}"); return jsonify(error={"message": "Invalid signature"}), 400
    except Exception as e: log.error(f"Webhook Error: Event construction error: {e}"); return jsonify(error={"message": "Webhook error"}), 500

    # Handle specific event types
    event_type = event['type']; data_object = event['data']['object']
    event_handlers = {
        'checkout.session.completed': handle_checkout_session_completed,
        'customer.subscription.updated': handle_subscription_updated,
        'customer.subscription.deleted': handle_subscription_deleted,
        # Add other handlers: 'invoice.payment_failed': handle_invoice_payment_failed,
    }
    handler = event_handlers.get(event_type)
    if handler:
        try:
            # Handlers use app context implicitly if needed (e.g., for db)
            # Handlers should commit/rollback their own sessions.
            # If handler needs app directly: with current_app.app_context(): handler(data_object)
            handler(data_object) # Assume handler can access db via imported instance
        except Exception as e:
             log.error(f"Webhook handler error {event_type} (ID: {event.id}): {e}", exc_info=True)
             return jsonify(error={"message": f"Internal error handling {event_type}"}), 500 # Signal error to Stripe
    else: log.warning(f"Webhook Received: Unhandled event type '{event_type}' (ID: {event.id})")

    return jsonify(received=True), 200 # Acknowledge receipt
# --- END OF FILE app/stripe_webhooks/routes.py ---