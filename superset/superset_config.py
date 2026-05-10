import os

SECRET_KEY = os.environ.get('SUPERSET_SECRET_KEY', 'changeme')
BABEL_DEFAULT_LOCALE = "ru"
LANGUAGES = {
    "ru": {"flag": "ru", "name": "Russian"},
    "en": {"flag": "us", "name": "English"},
}
# Разрешаем встраивание
WTF_CSRF_ENABLED = False
SESSION_COOKIE_SAMESITE = None
SESSION_COOKIE_SECURE = False

# Guest Token для Embedded режима
GUEST_TOKEN_JWT_SECRET = SECRET_KEY
GUEST_TOKEN_JWT_ALGO = 'HS256'
GUEST_TOKEN_HEADER_NAME = 'X-GuestToken'

# Feature flags
FEATURE_FLAGS = {
    'EMBEDDED_SUPERSET': True,
    'ENABLE_TEMPLATE_PROCESSING': True,
}
