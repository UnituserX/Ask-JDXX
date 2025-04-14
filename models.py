# --- START OF FILE app/models.py ---
from datetime import datetime, timezone
from typing import Optional
from flask_login import UserMixin
# Import db, login_manager, bcrypt instances created in app/__init__.py
from . import db, login_manager, bcrypt

@login_manager.user_loader
def load_user(user_id):
    """Callback function used by Flask-Login to load a user by ID."""
    try:
        return db.session.get(User, int(user_id)) # Use newer session.get method
    except (TypeError, ValueError):
        return None

class User(UserMixin, db.Model):
    """User model for authentication and storing user information."""
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True, nullable=False)
    email = db.Column(db.String(120), index=True, unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    last_seen = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Subscription related fields
    is_subscribed = db.Column(db.Boolean, default=False, nullable=False, index=True)
    stripe_customer_id = db.Column(db.String(120), index=True, unique=True, nullable=True)
    stripe_subscription_id = db.Column(db.String(120), unique=True, nullable=True)
    subscription_ends_at = db.Column(db.DateTime(timezone=True), nullable=True) # Store timezone info

    def __repr__(self):
        return f'<User {self.username} (ID: {self.id})>'

    def set_password(self, password):
        """Hashes the password and stores it."""
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password) -> bool:
        """Checks if the provided password matches the stored hash."""
        if not self.password_hash: return False
        return bcrypt.check_password_hash(self.password_hash, password)

    def update_last_seen(self):
        """Updates the last_seen timestamp."""
        self.last_seen = datetime.now(timezone.utc)
        # Commit should happen in the route/service layer

    # --- Subscription Helper Methods ---
    def update_subscription(self, status: bool, sub_id: Optional[str] = None, ends_at: Optional[datetime] = None):
        """Updates subscription status and related info. Marks for commit."""
        self.is_subscribed = status
        if sub_id: self.stripe_subscription_id = sub_id
        self.subscription_ends_at = ends_at
        db.session.add(self)

    def clear_subscription(self):
        """Clears subscription details. Marks for commit."""
        self.is_subscribed = False
        self.stripe_subscription_id = None
        self.subscription_ends_at = None
        db.session.add(self)

# --- Reminder ---
# After defining/modifying models, run migrations:
# flask db migrate -m "Descriptive message about changes"
# flask db upgrade
# --- END OF FILE app/models.py ---