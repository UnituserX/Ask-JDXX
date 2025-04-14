# --- START OF FILE app/forms.py ---
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField, EmailField # Use EmailField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError, Regexp
from .models import User # Import User for validation checks

class LoginForm(FlaskForm):
    """Form for users to login."""
    email = EmailField('Email', validators=[
        DataRequired(message="Email address is required."),
        Length(1, 120),
        Email(message="Please enter a valid email address.")
    ], render_kw={"autocomplete": "email"}) # Add autocomplete hints
    password = PasswordField('Password', validators=[
        DataRequired(message="Password is required.")
    ], render_kw={"autocomplete": "current-password"})
    remember_me = BooleanField('Remember Me')
    submit = SubmitField('Log In')

class RegistrationForm(FlaskForm):
    """Form for users to register an account."""
    username = StringField('Username', validators=[
        DataRequired(message="Username is required."),
        Length(min=3, max=64, message="Username must be between 3 and 64 characters."),
        Regexp('^[A-Za-z][A-Za-z0-9_.]*$', 0, 'Username must start with a letter and contain only letters, numbers, dots, or underscores.')
    ], render_kw={"autocomplete": "username"})
    email = EmailField('Email', validators=[
        DataRequired(message="Email address is required."),
        Length(1, 120),
        Email(message="Please enter a valid email address.")
    ], render_kw={"autocomplete": "email"})
    password = PasswordField('New Password', validators=[ # Label changed for clarity
        DataRequired(message="Password is required."),
        Length(min=8, message="Password must be at least 8 characters long.")
        # TODO: Add stronger password complexity regex if desired
    ], render_kw={"autocomplete": "new-password"})
    confirm_password = PasswordField('Confirm New Password', validators=[
        DataRequired(message="Please confirm your password."),
        EqualTo('password', message='Passwords must match.')
    ], render_kw={"autocomplete": "new-password"})
    submit = SubmitField('Register')

    # --- Custom Validators ---
    def validate_username(self, username):
        """Check if the username is already taken."""
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('That username is already taken. Please choose a different one.')

    def validate_email(self, email):
        """Check if the email address is already registered."""
        # Check case-insensitively for email
        user = User.query.filter(User.email.ilike(email.data)).first()
        if user:
            raise ValidationError('That email address is already registered. Please use a different one or log in.')

# --- Optional Password Reset Forms ---
# class RequestPasswordResetForm(FlaskForm): ...
# class ResetPasswordForm(FlaskForm): ...
# --- END OF FILE app/forms.py ---