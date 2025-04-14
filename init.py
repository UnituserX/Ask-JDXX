# --- START OF FILE app/main/__init__.py ---
from flask import Blueprint
main = Blueprint('main', __name__)
from . import routes # Import routes and potentially errors
# --- END OF FILE app/main/__init__.py ---