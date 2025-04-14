# --- START OF FILE config.py ---
import os
import sys
import logging
import logging.handlers
from typing import Optional, Dict, Type
from dotenv import load_dotenv

# --- Base Setup ---
basedir = os.path.abspath(os.path.dirname(__file__))
dotenv_path = os.path.join(basedir, '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
else:
    if os.environ.get('FLASK_CONFIG') != 'testing':
        print(f"Warning: .env file not found at {dotenv_path}", file=sys.stderr)

INSTANCE_FOLDER_PATH = os.path.join(basedir, 'instance')
try: os.makedirs(INSTANCE_FOLDER_PATH, exist_ok=True)
except OSError as e: print(f"Error creating instance folder {INSTANCE_FOLDER_PATH}: {e}", file=sys.stderr)

DEFAULT_SQLITE_URI = f'sqlite:///{os.path.join(INSTANCE_FOLDER_PATH, "app.db")}'
WEAK_DEFAULT_SECRET_KEY = 'a-very-hard-to-guess-string-CHANGE-ME'

class Config:
    SECRET_KEY: Optional[str] = os.environ.get('SECRET_KEY')
    DEBUG: bool = False
    TESTING: bool = False
    SQLALCHEMY_DATABASE_URI: Optional[str] = os.environ.get('DATABASE_URL') or DEFAULT_SQLITE_URI
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_ECHO: bool = False
    WTF_CSRF_ENABLED: bool = True
    OPENAI_API_KEY: Optional[str] = os.environ.get('OPENAI_API_KEY')
    STRIPE_SECRET_KEY: Optional[str] = os.environ.get('STRIPE_SECRET_KEY')
    STRIPE_PUBLISHABLE_KEY: Optional[str] = os.environ.get('STRIPE_PUBLISHABLE_KEY')
    STRIPE_WEBHOOK_SECRET: Optional[str] = os.environ.get('STRIPE_WEBHOOK_SECRET')
    STRIPE_PRICE_ID: Optional[str] = os.environ.get('STRIPE_PRICE_ID')
    GDRIVE_APP_FOLDER_NAME: str = os.environ.get('GDRIVE_APP_FOLDER_NAME', 'AskJDXX_Memory_Backups')
    USER_MEMORY_STORE_PATH: str = os.environ.get('USER_MEMORY_STORE_PATH', './user_memory_stores')
    GDRIVE_CREDENTIALS_PATH: str = os.environ.get('GDRIVE_CREDENTIALS_PATH', 'credentials.json')
    GDRIVE_TOKEN_PATH: str = os.environ.get('GDRIVE_TOKEN_PATH', 'token.pickle')
    GDRIVE_SYNC_INTERVAL_HOURS: int = int(os.environ.get('GDRIVE_SYNC_INTERVAL_HOURS', 1))
    APP_DESCRIPTION: str = "Your intelligent AI assistant with memory and expertise tracking."
    EMBEDDING_MODEL: str = os.environ.get('EMBEDDING_MODEL', "all-MiniLM-L6-v2")
    FAST_MODEL: str = os.environ.get('FAST_MODEL', "gpt-3.5-turbo")
    BALANCED_MODEL: str = os.environ.get('BALANCED_MODEL', "gpt-4-turbo-preview")
    THOROUGH_MODEL: str = os.environ.get('THOROUGH_MODEL', "gpt-4-turbo-preview")
    LOG_TO_STDOUT: bool = os.environ.get('LOG_TO_STDOUT') == '1'

    @staticmethod
    def check_required_keys(keys_to_check: list[str], config_name: str):
        missing_keys = [key for key in keys_to_check if not os.environ.get(key)]
        if missing_keys: raise ValueError(f"Missing env vars for {config_name}: {', '.join(missing_keys)}")

    @staticmethod
    def init_app(app):
        log_level = logging.DEBUG if app.debug else logging.INFO
        log_formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]')
        has_custom_handler = False
        if Config.LOG_TO_STDOUT:
            stream_handler = logging.StreamHandler(sys.stdout)
            stream_handler.setLevel(log_level); stream_handler.setFormatter(log_formatter)
            app.logger.addHandler(stream_handler); has_custom_handler = True
            print(" * Logging to stdout")
        elif not app.testing:
            log_dir = os.path.join(basedir, 'logs')
            os.makedirs(log_dir, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(os.path.join(log_dir, 'askjdxx.log'), maxBytes=10485760, backupCount=10)
            file_handler.setLevel(log_level); file_handler.setFormatter(log_formatter)
            app.logger.addHandler(file_handler); has_custom_handler = True
            print(f" * Logging to file: {os.path.join(log_dir, 'askjdxx.log')}")
        if has_custom_handler and app.logger.hasHandlers() and len(app.logger.handlers) > 1:
             # Try removing default Flask handler if we added our own
             try: app.logger.removeHandler(app.logger.handlers[0])
             except IndexError: pass
        app.logger.setLevel(log_level)
        app.logger.info(f'Ask JDXX starting up with {app.config.get("FLASK_CONFIG", "unknown")} config.')

class DevelopmentConfig(Config):
    DEBUG: bool = True; SQLALCHEMY_ECHO: bool = False
    @classmethod
    def init_app(cls, app):
        print(" * Loading Development Configuration")
        Config.init_app(app)
        if not cls.SECRET_KEY or cls.SECRET_KEY == WEAK_DEFAULT_SECRET_KEY:
            print("WARNING: SECRET_KEY is weak/missing. SET in .env!", file=sys.stderr)
            app.config['SECRET_KEY'] = WEAK_DEFAULT_SECRET_KEY

class TestingConfig(Config):
    TESTING: bool = True; SQLALCHEMY_DATABASE_URI: str = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED: bool = False; SECRET_KEY: str = 'test-secret-key'
    OPENAI_API_KEY: Optional[str] = os.environ.get('OPENAI_API_KEY', 'test_openai_key')
    STRIPE_SECRET_KEY: Optional[str] = os.environ.get('STRIPE_SECRET_KEY', 'sk_test_testing')
    STRIPE_PUBLISHABLE_KEY: Optional[str] = os.environ.get('STRIPE_PUBLISHABLE_KEY', 'pk_test_testing')
    STRIPE_PRICE_ID: Optional[str] = os.environ.get('STRIPE_PRICE_ID', 'price_test')
    STRIPE_WEBHOOK_SECRET: Optional[str] = os.environ.get('STRIPE_WEBHOOK_SECRET', 'whsec_test')
    GDRIVE_SYNC_INTERVAL_HOURS: int = 0 # Disable scheduler

class ProductionConfig(Config):
    DEBUG: bool = False
    @classmethod
    def init_app(cls, app):
        print(" * Loading Production Configuration")
        Config.init_app(app)
        required_keys = [
            'SECRET_KEY', 'DATABASE_URL', 'OPENAI_API_KEY', 'STRIPE_SECRET_KEY',
            'STRIPE_PUBLISHABLE_KEY', 'STRIPE_WEBHOOK_SECRET', 'STRIPE_PRICE_ID'
        ]
        try:
            cls.check_required_keys(required_keys, 'production')
            if cls.SECRET_KEY == WEAK_DEFAULT_SECRET_KEY: raise ValueError("FATAL: Default SECRET_KEY in production!")
        except ValueError as e: app.logger.error(f"CONFIGURATION ERROR: {e}"); raise

config: Dict[str, Type[Config]] = {
    'development': DevelopmentConfig, 'testing': TestingConfig,
    'production': ProductionConfig, 'default': DevelopmentConfig
}
# --- END OF FILE config.py ---