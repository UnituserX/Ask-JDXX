# --- START OF FILE app/__init__.py ---
import os
import logging
import logging.handlers
import glob
import atexit
import json
import time
from datetime import datetime # For logging timestamps if needed
from flask import Flask, current_app # Import current_app for context
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect, generate_csrf # Import generate_csrf
from flask_bcrypt import Bcrypt
from apscheduler.schedulers.background import BackgroundScheduler

from config import config # Import the config dictionary from root

# --- Initialize Extensions (outside factory) ---
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
bcrypt = Bcrypt()
scheduler = BackgroundScheduler(daemon=True)

# --- Configure Flask-Login ---
login_manager.login_view = 'auth.login' # Blueprint 'auth', view func 'login'
login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "info"

# --- GDrive Sync Status Helpers ---
INSTANCE_FOLDER_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'instance'))
SYNC_STATUS_FILE = os.path.join(INSTANCE_FOLDER_PATH, 'gdrive_sync_status.json')

def load_sync_status() -> Dict[int, float]:
    """Loads the last successful sync timestamp for each user."""
    try:
        os.makedirs(INSTANCE_FOLDER_PATH, exist_ok=True) # Ensure exists before read
        if os.path.exists(SYNC_STATUS_FILE):
            with open(SYNC_STATUS_FILE, 'r') as f:
                # Convert string keys back to int during load
                return {int(k): v for k, v in json.load(f).items()}
    except (IOError, json.JSONDecodeError, ValueError, TypeError) as e:
        logging.warning(f"Could not load GDrive sync status file '{SYNC_STATUS_FILE}': {e}")
    return {}

def save_sync_status(status_data: Dict[int, float]):
    """Saves the sync status data."""
    try:
        os.makedirs(INSTANCE_FOLDER_PATH, exist_ok=True) # Ensure exists before write
        with open(SYNC_STATUS_FILE, 'w') as f:
            json.dump(status_data, f, indent=2)
    except IOError as e:
        logging.error(f"Could not save GDrive sync status file '{SYNC_STATUS_FILE}': {e}")

# --- Scheduled Job Definition ---
def scheduled_gdrive_sync_job(app_context):
    """Scheduled job to sync MODIFIED user memories TO GDrive."""
    with app_context: # Use the passed application context
        logger = current_app.logger
        storage_base = current_app.config.get('USER_MEMORY_STORE_PATH')
        if not storage_base or not os.path.isdir(storage_base):
            logger.error(f"USER_MEMORY_STORE_PATH ('{storage_base}') invalid or not found. Skipping scheduled GDrive sync.")
            return

        logger.info("Starting scheduled GDrive sync job...")
        last_sync_times = load_sync_status()
        current_sync_times = last_sync_times.copy() # Track successes in this run

        try:
            # Import Syncer class here, within the app context
            from .google_drive_sync import GoogleDriveSyncManager, SYNC_SUCCESS, SYNC_FAILED_PARTIAL

            # Initialize the manager once per job run
            sync_manager = GoogleDriveSyncManager(
                credentials_path=current_app.config['GDRIVE_CREDENTIALS_PATH'],
                token_path=current_app.config['GDRIVE_TOKEN_PATH'],
                app_folder_name=current_app.config['GDRIVE_APP_FOLDER_NAME'],
                persistent_store_base_path=storage_base
            )
            if not sync_manager.is_available:
                logger.error("GDrive sync job: Google libraries unavailable.")
                return

            user_dirs = glob.glob(os.path.join(storage_base, 'user_*'))
            logger.info(f"Found {len(user_dirs)} potential user directories to check.")

            for user_dir_path in user_dirs:
                 if os.path.isdir(user_dir_path):
                    user_id = None # Define before try block
                    try:
                        user_id_str = os.path.basename(user_dir_path).split('user_')[-1]
                        user_id = int(user_id_str)
                        last_success_time = last_sync_times.get(user_id, 0)

                        # Check Modification Time
                        mod_file_path = os.path.join(user_dir_path, '.last_modified')
                        should_sync = True
                        try:
                            if os.path.exists(mod_file_path):
                                modified_time = os.path.getmtime(mod_file_path)
                                if modified_time <= last_success_time: should_sync = False
                            # else: Sync if file doesn't exist (e.g., first time)
                        except OSError as e: logger.error(f"User {user_id}: Error checking mod time: {e}. Syncing.")

                        if not should_sync:
                             #logger.debug(f"User {user_id} memory unchanged. Skipping sync.")
                             if user_id in last_sync_times: current_sync_times[user_id] = last_sync_times[user_id]
                             continue

                        logger.info(f"Attempting scheduled sync TO GDrive for user {user_id}")
                        sync_status = sync_manager.sync_db_to_gdrive(user_id) # Call method

                        if sync_status == SYNC_SUCCESS or sync_status == SYNC_FAILED_PARTIAL:
                            current_sync_times[user_id] = time.time()
                            logger.log(logging.INFO if sync_status == SYNC_SUCCESS else logging.WARNING,
                                       f"Scheduled sync TO GDrive finished for user {user_id}. Status: {sync_status}")
                        else:
                            logger.error(f"Scheduled sync TO GDrive failed for user {user_id}. Status: {sync_status}")
                            if user_id in last_sync_times: current_sync_times[user_id] = last_sync_times[user_id]

                    except (ValueError, TypeError): logger.warning(f"Could not parse user ID from directory: {user_dir_path}")
                    except Exception as user_sync_err:
                         logger.error(f"Error during scheduled sync for path {user_dir_path}: {user_sync_err}", exc_info=True)
                         if user_id and user_id in last_sync_times: current_sync_times[user_id] = last_sync_times[user_id]

            # Save updated successful sync times
            save_sync_status(current_sync_times)
            logger.info("Finished scheduled GDrive sync job.")

        except ImportError: logger.error("GoogleDriveSyncManager could not be imported. Skipping scheduled sync.")
        except Exception as e: logger.error(f"Critical error in scheduled GDrive sync job setup/loop: {e}", exc_info=True)

# --- Application Factory Function ---
def create_app(config_name: str = 'default') -> Flask:
    """Creates and configures the Flask application instance."""
    app = Flask(__name__,
                instance_path=INSTANCE_FOLDER_PATH, # Tell Flask where instance folder is
                instance_relative_config=False)

    # --- Load Configuration ---
    app_config = config.get(config_name)
    if app_config is None: raise ValueError(f"Invalid FLASK_CONFIG: {config_name}")
    app.config.from_object(app_config)
    app.config['FLASK_CONFIG'] = config_name
    print(f" * Loading configuration: '{config_name}'")

    # --- Initialize Flask Extensions ---
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    bcrypt.init_app(app)

    # --- Call Config's init_app (for logging etc.) ---
    if hasattr(app_config, 'init_app'): app_config.init_app(app)
    else: logging.basicConfig(level=logging.INFO if config_name == 'production' else logging.DEBUG) # Basic fallback

    app.logger.info(f"Ask JDXX application factory created with '{config_name}' config.")

    # --- Initialize Services (Singletons) ---
    # Eagerly initialize after config is loaded
    try:
        from .services import memory_manager, openai_service # Import here
        with app.app_context(): # Need context to access config during init
             memory_manager.get_chroma_client(force_reload=True) # Force reload on app start
             memory_manager.get_embedding_function(force_reload=True)
             memory_manager.get_nlp_model() # Load spaCy model
             openai_service.get_openai_client(force_reload=True)
        app.logger.info("Core services initialized.")
    except Exception as service_init_err:
        app.logger.error(f"FATAL: Failed to initialize core services: {service_init_err}", exc_info=True)
        raise RuntimeError("Core service initialization failed.") from service_init_err

    # --- Start Background Scheduler ---
    if not app.config.get('TESTING', False):
        if not scheduler.running:
            try:
                sync_interval_hours = app.config.get('GDRIVE_SYNC_INTERVAL_HOURS', 1)
                if sync_interval_hours > 0:
                    job_func_with_context = lambda: scheduled_gdrive_sync_job(app.app_context())
                    scheduler.add_job(
                        func=job_func_with_context, trigger='interval', hours=sync_interval_hours,
                        id='gdrive_sync_job', name='Periodic GDrive Upload Sync',
                        replace_existing=True, misfire_grace_time=300
                    )
                    scheduler.start()
                    app.logger.info(f"Background scheduler started. GDrive sync interval: {sync_interval_hours} hours.")
                    # Ensure shutdown happens cleanly
                    atexit.register(lambda: scheduler.shutdown(wait=False))
                else: app.logger.info("GDrive sync interval <= 0. Scheduler job not added.")
            except Exception as e: app.logger.error(f"Failed to start background scheduler: {e}", exc_info=True)

    # --- Register Blueprints ---
    # Wrap in try/except to allow app to start even if a blueprint fails temporarily
    try:
        from .auth import auth as auth_blueprint
        app.register_blueprint(auth_blueprint, url_prefix='/auth')
        app.logger.debug("Registered Authentication Blueprint at /auth")
    except Exception as e: app.logger.error(f"Failed to register Auth Blueprint: {e}", exc_info=True)

    try:
        from .main import main as main_blueprint
        app.register_blueprint(main_blueprint)
        app.logger.debug("Registered Main Blueprint at /")
    except Exception as e: app.logger.error(f"Failed to register Main Blueprint: {e}", exc_info=True)

    try:
        from .stripe_webhooks import stripe_bp as stripe_webhook_blueprint
        app.register_blueprint(stripe_webhook_blueprint, url_prefix='/webhook')
        app.logger.debug("Registered Stripe Webhook Blueprint at /webhook")
    except ImportError: app.logger.warning("Stripe Webhook Blueprint not found.")
    except Exception as e: app.logger.error(f"Failed to register Stripe Blueprint: {e}", exc_info=True)

    # --- Global Context Processors ---
    @app.context_processor
    def inject_global_vars():
        return dict(
             app_name="Ask JDXX",
             # Pass CSRF token function to make it easily available in templates
             csrf_token=generate_csrf
        )

    app.logger.info("Application setup complete.")
    return app
# --- END OF FILE app/__init__.py ---