"""
Django settings for financeiro project - VERSÃO SEGURA
"""
import dj_database_url
from urllib.parse import quote_plus
from pathlib import Path
import os
from dotenv import load_dotenv

# Carrega as variáveis do arquivo .env
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# ============================================
# SEGURANÇA BÁSICA
# ============================================
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-chave-padrao')
DEBUG = os.getenv('DEBUG', 'False') == 'True'
ALLOWED_HOSTS = ['*']  # ⚠️ Em produção, colocar domínio específico: ['seuapp.com']

# ============================================
# APLICAÇÕES
# ============================================
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'contas',
    'rest_framework',  # Mantém para a API
]

# ============================================
# MIDDLEWARE
# ============================================
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'financeiro.urls'

# ============================================
# TEMPLATES
# ============================================
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'financeiro.wsgi.application'

# ============================================
# BANCO DE DADOS
# ============================================

# ✅ OPÇÃO 1: Usar DATABASE_URL do Supabase (Transaction Pooler)
DATABASE_URL = os.getenv('DATABASE_URL')

if DATABASE_URL:
    # Usa a connection string completa do Supabase (Transaction Pooler)
    DATABASES = {
        'default': dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=600,
            conn_health_checks=True,
        )
    }
    print("🚀 Conectando ao Supabase via Transaction Pooler")
else:
    # ✅ OPÇÃO 2: Montar manualmente (se não tiver DATABASE_URL)
    senha_banco = os.getenv('DB_PASSWORD')
    if senha_banco:
        senha_codificada = quote_plus(senha_banco)
    else:
        senha_codificada = ''

    db_port = os.getenv('DB_PORT', '6543')  # ✅ Porta do Transaction Pooler

    DATABASE_URL_MANUAL = f"postgresql://{os.getenv('DB_USER')}:{senha_codificada}@{os.getenv('DB_HOST')}:{db_port}/{os.getenv('DB_NAME')}"

    if os.getenv('DB_USER'):
        DATABASES = {
            'default': dj_database_url.config(
                default=DATABASE_URL_MANUAL,
                conn_max_age=600,
                conn_health_checks=True,
            )
        }
        print(f"🚀 Conectando ao Supabase: {os.getenv('DB_HOST')}:{db_port}")
    else:
        # Fallback para SQLite se não tiver credenciais
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': BASE_DIR / 'db.sqlite3',
            }
        }
        print("🔧 Usando SQLite local (sem credenciais de banco)")


# ============================================
# VALIDAÇÃO DE SENHAS
# ============================================
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ============================================
# INTERNACIONALIZAÇÃO
# ============================================
LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True

# ============================================
# ARQUIVOS ESTÁTICOS
# ============================================
STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# ============================================
# 🔒 CONFIGURAÇÕES DE SEGURANÇA (CRÍTICO)
# ============================================

# 1. Proteção de Sessões
SESSION_COOKIE_HTTPONLY = True  # ✅ JavaScript não consegue ler cookies de sessão
SESSION_COOKIE_SECURE = not DEBUG  # ✅ Cookies só via HTTPS em produção
SESSION_COOKIE_SAMESITE = 'Lax'  # ✅ Proteção contra CSRF
SESSION_COOKIE_AGE = 86400  # 24 horas (pode ajustar)

# 2. Proteção CSRF
CSRF_COOKIE_HTTPONLY = True  # ✅ JavaScript não consegue ler token CSRF
CSRF_COOKIE_SECURE = not DEBUG  # ✅ CSRF token só via HTTPS em produção
CSRF_COOKIE_SAMESITE = 'Lax'

# 3. Proteção contra Clickjacking
X_FRAME_OPTIONS = 'DENY'

# 4. Forçar HTTPS em produção
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# ============================================
# REST FRAMEWORK (API) - AUTENTICAÇÃO SEGURA
# ============================================
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',  # ✅ Usa sessão Django
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',  # ✅ Exige autenticação
    ],
}

# ============================================
# CONFIGURAÇÕES DE LOGIN
# ============================================
LOGIN_REDIRECT_URL = 'listagem'
LOGOUT_REDIRECT_URL = 'login'
LOGIN_URL = 'login'

# ============================================
# LOGGING (para debug de problemas)
# ============================================
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django.security': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
