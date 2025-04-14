# --- START OF FILE run.py ---
import os
import sys
import logging

# Load environment variables from .env file FIRST
try:
    from dotenv import load_dotenv
    dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(dotenv_path):
        print(f" * Loading environment variables from: {dotenv_path}")
        load_dotenv(dotenv_path)
    else:
        print(" * Warning: .env file not found.", file=sys.stderr)
except ImportError:
    print(" * Warning: python-dotenv not installed, skipping .env load.", file=sys.stderr)

# Import after dotenv potentially loaded environment variables
# Assume app package exists or will be created next
try:
    from app import create_app
except ModuleNotFoundError:
    print("FATAL: Cannot find the 'app' package. Ensure app/__init__.py exists.", file=sys.stderr)
    sys.exit(1)

# Get config name AFTER loading .env
config_name = os.getenv('FLASK_CONFIG', 'default')

# Create the Flask app instance using the factory
try:
    app = create_app(config_name)
except ValueError as e:
     print(f"FATAL: Invalid configuration name '{config_name}'. Error: {e}", file=sys.stderr)
     sys.exit(1)
except RuntimeError as e:
     print(f"FATAL: Failed to create application. Error: {e}", file=sys.stderr)
     sys.exit(1)
except Exception as e:
     print(f"FATAL: An unexpected error occurred during app creation: {e}", file=sys.stderr)
     sys.exit(1)


if __name__ == '__main__':
    host = os.getenv('FLASK_RUN_HOST', '127.0.0.1')
    try:
        port: int = int(os.getenv('FLASK_RUN_PORT', '5000'))
    except ValueError:
        # Use logger only if app was created successfully
        app.logger.warning("Invalid FLASK_RUN_PORT value. Using default 5000.")
        port = 5000

    is_debug_mode = app.config.get('DEBUG', False)

    app.logger.info(f"Starting Flask app (config: {config_name}, debug: {is_debug_mode})")
    print(f" * Environment: {config_name}")
    print(f" * Debug mode: {'on' if is_debug_mode else 'off'}")
    print(f" * Running on http://{host}:{port}/ (Press CTRL+C to quit)")

    # Run using Flask's built-in server (for development)
    app.run(host=host, port=port, debug=is_debug_mode)

# --- END OF FILE run.py ---