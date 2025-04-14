# --- START OF FILE app/auth/__init__.py ---
from flask import Blueprint
auth = Blueprint('auth', __name__)
from . import routes # Import routes after blueprint creation
# --- END OF FILE app/auth/__init__.py ---