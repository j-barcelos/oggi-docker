#!/usr/bin/env python3
"""
OGGI BARUERI - DEPLOY AUTOMATIZADO

Projeto:
    Django + MySQL + Gunicorn + Docker Compose + Nginx

Repositório:
    https://github.com/j-barcelos/aluguel_carrinho-sorvete

Estrutura esperada:
    app/
        manage.py
        meusite/
            settings.py
            urls.py
            wsgi.py
        aluguel/
        requirements.txt

O script:
    1. Conecta ao servidor por SSH.
    2. Instala Docker/Compose/Git.
    3. Clona ou atualiza o repositório.
    4. Faz backup do settings.py existente.
    5. Ajusta settings.py para produção.
    6. Adiciona Gunicorn ao requirements.txt.
    7. Cria Dockerfile.
    8. Cria docker-compose.yml.
    9. Cria configuração Nginx HTTP.
   10. Sobe MySQL + Django + Nginx.
   11. Executa migrations.
   12. Executa collectstatic.
   13. Configura backup diário.
   14. Opcionalmente configura Let's Encrypt.
   15. Executa verificações finais.

IMPORTANTE:
    - O script NÃO remove o volume do MySQL.
    - O script NÃO executa "docker compose down -v".
    - Migrações de banco não são revertidas automaticamente em caso de rollback.
"""

from __future__ import annotations

import getpass
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


# ============================================================================
# CONFIGURAÇÃO
# ============================================================================

GIT_REPO = "https://github.com/j-barcelos/aluguel_carrinho-sorvete.git"
DEFAULT_BRANCH = "main"

REMOTE_BASE_DIR = "/var/www/oggi-sorvetes"
APP_DIR = f"{REMOTE_BASE_DIR}/app"

DEFAULT_DOMAIN = "oggibarueri.com.br"

SSH_CONNECT_TIMEOUT = 20
SSH_COMMAND_TIMEOUT = 900


# ============================================================================
# CORES
# ============================================================================

class Colors:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    RESET = "\033[0m"
    BOLD = "\033[1m"

    @staticmethod
    def success(msg):
        return f"{Colors.GREEN}✓{Colors.RESET} {msg}"

    @staticmethod
    def warning(msg):
        return f"{Colors.YELLOW}⚠{Colors.RESET} {msg}"

    @staticmethod
    def error(msg):
        return f"{Colors.RED}✗{Colors.RESET} {msg}"

    @staticmethod
    def info(msg):
        return f"{Colors.BLUE}ℹ{Colors.RESET} {msg}"

    @staticmethod
    def prompt(msg):
        return f"{Colors.CYAN}➜{Colors.RESET} {msg}"

    @staticmethod
    def header(msg):
        line = "=" * 70
        return (
            f"\n{Colors.BOLD}{Colors.MAGENTA}{line}{Colors.RESET}\n"
            f"{Colors.CYAN}{Colors.BOLD}{msg}{Colors.RESET}\n"
            f"{Colors.BOLD}{Colors.MAGENTA}{line}{Colors.RESET}\n"
        )


def step(msg):
    return f"{Colors.CYAN}▸{Colors.RESET} {msg}"


# ============================================================================
# UTILITÁRIOS
# ============================================================================

def q(value: str) -> str:
    """Shell-quote seguro."""
    return shlex.quote(str(value))


def generate_password(length=32):
    alphabet = (
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789"
        "!@#$%^&*_-+="
    )

    return "".join(
        secrets.choice(alphabet)
        for _ in range(length)
    )


def generate_secret_key():
    return secrets.token_urlsafe(64)


def require_local_command(command):
    if shutil.which(command) is None:
        raise RuntimeError(
            f"Comando local obrigatório não encontrado: {command}"
        )


# ============================================================================
# SSH
# ============================================================================

class SSH:
    def __init__(self, config):
        self.host = config["ssh_host"]
        self.user = config["ssh_user"]
        self.auth_method = config["auth_method"]
        self.key_path = config.get("ssh_key_path")
        self.password = config.get("ssh_password")

    def base_command(self):
        command = [
            "ssh",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"ConnectTimeout={SSH_CONNECT_TIMEOUT}",
        ]

        if self.auth_method == "key":
            command += [
                "-i",
                os.path.expanduser(self.key_path),
            ]

        command.append(
            f"{self.user}@{self.host}"
        )

        return command

    def run(
        self,
        command,
        timeout=SSH_COMMAND_TIMEOUT,
        check=False,
    ):
        cmd = self.base_command() + [command]

        if self.auth_method == "password":
            env = os.environ.copy()
            env["SSHPASS"] = self.password

            cmd = [
                "sshpass",
                "-e",
                *cmd,
            ]
        else:
            env = None

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return False, "", "Timeout na execução SSH."

        success = result.returncode == 0

        if check and not success:
            raise RuntimeError(
                f"Comando remoto falhou:\n\n"
                f"{command}\n\n"
                f"STDOUT:\n{result.stdout}\n\n"
                f"STDERR:\n{result.stderr}"
            )

        return (
            success,
            result.stdout,
            result.stderr,
        )

    def upload_text(self, remote_path, content):
        """
        Envia arquivo pelo stdin do SSH.

        O conteúdo não é colocado na linha de comando.
        """

        cmd = self.base_command() + [
            f"cat > {q(remote_path)}"
        ]

        if self.auth_method == "password":
            env = os.environ.copy()
            env["SSHPASS"] = self.password

            cmd = [
                "sshpass",
                "-e",
                *cmd,
            ]
        else:
            env = None

        try:
            result = subprocess.run(
                cmd,
                input=content,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return False, "Timeout."

        return (
            result.returncode == 0,
            result.stderr,
        )


# ============================================================================
# INPUT
# ============================================================================

def collect_config():
    print(
        Colors.header(
            "🍦 OGGI BARUERI - DEPLOY"
        )
    )

    print(
        f"{Colors.info('Repositório:')} {GIT_REPO}"
    )

    # ------------------------------------------------------------------------
    # SSH
    # ------------------------------------------------------------------------

    print(
        f"\n{Colors.prompt('🔹 SERVIDOR SSH')}"
    )

    ssh_host = input(
        "  IP ou hostname: "
    ).strip()

    if not ssh_host:
        raise ValueError(
            "O IP/hostname do servidor é obrigatório."
        )

    ssh_user = input(
        "  Usuário SSH [root]: "
    ).strip() or "root"

    auth = input(
        "  Autenticação [1=Chave SSH, 2=Senha]: "
    ).strip()

    if auth == "1":
        auth_method = "key"

        ssh_key_path = input(
            "  Chave SSH [~/.ssh/id_rsa]: "
        ).strip() or "~/.ssh/id_rsa"

        ssh_key_path = os.path.expanduser(
            ssh_key_path
        )

        if not Path(ssh_key_path).is_file():
            raise FileNotFoundError(
                f"Chave SSH não encontrada: {ssh_key_path}"
            )

        ssh_password = None

    elif auth == "2":
        auth_method = "password"
        ssh_key_path = None

        if shutil.which("sshpass") is None:
            raise RuntimeError(
                "Autenticação por senha requer sshpass. "
                "Instale sshpass ou use uma chave SSH."
            )

        ssh_password = getpass.getpass(
            "  Senha SSH: "
        )

    else:
        raise ValueError(
            "Escolha 1 ou 2."
        )

    # ------------------------------------------------------------------------
    # DOMÍNIO
    # ------------------------------------------------------------------------

    print(
        f"\n{Colors.prompt('🔹 DOMÍNIO')}"
    )

    main_domain = input(
        f"  Domínio principal [{DEFAULT_DOMAIN}]: "
    ).strip() or DEFAULT_DOMAIN

    www_domain = input(
        f"  Domínio WWW [www.{main_domain}]: "
    ).strip() or f"www.{main_domain}"

    admin_email = input(
        "  E-mail administrativo/SSL: "
    ).strip()

    if not admin_email:
        raise ValueError(
            "O e-mail é obrigatório."
        )

    # ------------------------------------------------------------------------
    # BANCO
    # ------------------------------------------------------------------------

    print(
        f"\n{Colors.prompt('🔹 MYSQL')}"
    )

    db_name = input(
        "  Banco [oggi_baru_sorvete]: "
    ).strip() or "oggi_baru_sorvete"

    db_user = input(
        "  Usuário [oggi_baru_user]: "
    ).strip() or "oggi_baru_user"

    # ------------------------------------------------------------------------
    # GIT
    # ------------------------------------------------------------------------

    print(
        f"\n{Colors.prompt('🔹 GIT')}"
    )

    branch = input(
        f"  Branch [{DEFAULT_BRANCH}]: "
    ).strip() or DEFAULT_BRANCH

    # ------------------------------------------------------------------------
    # SEGREDOS
    # ------------------------------------------------------------------------

    db_password = generate_password()
    mysql_root_password = generate_password()
    secret_key = generate_secret_key()

    config = {
        "ssh_host": ssh_host,
        "ssh_user": ssh_user,
        "auth_method": auth_method,
        "ssh_key_path": ssh_key_path,
        "ssh_password": ssh_password,

        "main_domain": main_domain,
        "www_domain": www_domain,
        "admin_email": admin_email,

        "db_name": db_name,
        "db_user": db_user,
        "db_password": db_password,
        "mysql_root_password": mysql_root_password,

        "secret_key": secret_key,

        "git_branch": branch,
    }

    # ------------------------------------------------------------------------
    # RESUMO
    # ------------------------------------------------------------------------

    print(
        Colors.header(
            "📋 RESUMO"
        )
    )

    print(
        f"Servidor:     {ssh_user}@{ssh_host}"
    )
    print(
        f"Domínio:      {main_domain}"
    )
    print(
        f"WWW:          {www_domain}"
    )
    print(
        f"Banco:        {db_name}"
    )
    print(
        f"Usuário DB:   {db_user}"
    )
    print(
        f"Branch:       {branch}"
    )
    print(
        f"Diretório:    {REMOTE_BASE_DIR}"
    )

    print(
        f"\n{Colors.warning('Uma nova senha de banco e SECRET_KEY serão geradas.')}"
    )

    confirm = input(
        "\nConfirmar e iniciar deploy? [s/N]: "
    ).strip().lower()

    if confirm not in (
        "s",
        "sim",
        "y",
        "yes",
    ):
        print(
            Colors.info(
                "Deploy cancelado."
            )
        )
        sys.exit(0)

    return config


# ============================================================================
# CONTEÚDO DOS ARQUIVOS
# ============================================================================

def get_env(config):
    return f"""SECRET_KEY={config['secret_key']}
DEBUG=False

ALLOWED_HOSTS=localhost,127.0.0.1,{config['main_domain']},{config['www_domain']}

CSRF_TRUSTED_ORIGINS=https://{config['main_domain']},https://{config['www_domain']}

DB_NAME={config['db_name']}
DB_USER={config['db_user']}
DB_PASSWORD={config['db_password']}
DB_HOST=db
DB_PORT=3306

ADMIN_EMAIL={config['admin_email']}
"""


def get_dockerfile():
    return """FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONFAULTHANDLER=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        default-libmysqlclient-dev \
        gcc \
        pkg-config \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/staticfiles \
    && mkdir -p /app/media

EXPOSE 8000

CMD [
    "gunicorn",
    "--bind", "0.0.0.0:8000",
    "--workers", "2",
    "--timeout", "120",
    "--access-logfile", "-",
    "--error-logfile", "-",
    "meusite.wsgi:application"
]
"""


def get_compose(config):
    root_password = config["mysql_root_password"]

    return f"""services:

  db:
    image: mysql:8.0
    container_name: oggi_db
    restart: unless-stopped

    environment:
      MYSQL_DATABASE: {config['db_name']}
      MYSQL_USER: {config['db_user']}
      MYSQL_PASSWORD: {config['db_password']}
      MYSQL_ROOT_PASSWORD: {root_password}

    volumes:
      - db_data:/var/lib/mysql

    networks:
      - oggi_network

    healthcheck:
      test:
        [
          "CMD-SHELL",
          "mysqladmin ping -h localhost -uroot -p$${{MYSQL_ROOT_PASSWORD}} --silent"
        ]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 40s

  django:
    build:
      context: ./app
      dockerfile: Dockerfile

    container_name: oggi_django
    restart: unless-stopped

    env_file:
      - .env

    depends_on:
      db:
        condition: service_healthy

    volumes:
      - static_volume:/app/staticfiles
      - ./media:/app/media

    networks:
      - oggi_network

    healthcheck:
      test:
        [
          "CMD-SHELL",
          "python manage.py check --deploy"
        ]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s

  nginx:
    image: nginx:alpine
    container_name: oggi_nginx
    restart: unless-stopped

    depends_on:
      django:
        condition: service_healthy

    ports:
      - "80:80"
      - "443:443"

    volumes:
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
      - static_volume:/var/www/static:ro
      - ./media:/var/www/media:ro
      - certbot_www:/var/www/certbot
      - letsencrypt:/etc/letsencrypt:ro

    networks:
      - oggi_network

  certbot:
    image: certbot/certbot:latest

    volumes:
      - certbot_www:/var/www/certbot
      - letsencrypt:/etc/letsencrypt

    networks:
      - oggi_network

volumes:
  db_data:
  static_volume:
  certbot_www:
  letsencrypt:

networks:
  oggi_network:
    driver: bridge
"""


def get_nginx_http(config):
    return f"""server {{
    listen 80;
    server_name {config['main_domain']} {config['www_domain']};

    client_max_body_size 10M;

    location /.well-known/acme-challenge/ {{
        root /var/www/certbot;
    }}

    location /static/ {{
        alias /var/www/static/;
        expires 30d;
        add_header Cache-Control "public";
        access_log off;
    }}

    location /media/ {{
        alias /var/www/media/;
        expires 30d;
    }}

    location / {{
        proxy_pass http://django:8000;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 120s;
        proxy_connect_timeout 120s;
        proxy_send_timeout 120s;
    }}
}}
"""


def get_nginx_https(config):
    return f"""server {{
    listen 80;
    server_name {config['main_domain']} {config['www_domain']};

    location /.well-known/acme-challenge/ {{
        root /var/www/certbot;
    }}

    location / {{
        return 301 https://$host$request_uri;
    }}
}}

server {{
    listen 443 ssl;
    http2 on;

    server_name {config['main_domain']} {config['www_domain']};

    ssl_certificate /etc/letsencrypt/live/{config['main_domain']}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{config['main_domain']}/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;

    client_max_body_size 10M;

    location /static/ {{
        alias /var/www/static/;
        expires 30d;
        add_header Cache-Control "public";
        access_log off;
    }}

    location /media/ {{
        alias /var/www/media/;
        expires 30d;
    }}

    location / {{
        proxy_pass http://django:8000;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 120s;
        proxy_connect_timeout 120s;
        proxy_send_timeout 120s;
    }}
}}
"""


def get_backup_script():
    return """#!/bin/sh

set -eu

BACKUP_DIR="/var/backups/mysql"
DATE="$(date +%Y%m%d_%H%M%S)"

mkdir -p "$BACKUP_DIR"

echo "Iniciando backup: $(date)"

docker exec oggi_db \
    sh -c 'exec mysqldump -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' \
    | gzip > "$BACKUP_DIR/backup_$DATE.sql.gz"

if [ ! -s "$BACKUP_DIR/backup_$DATE.sql.gz" ]; then
    echo "Backup vazio ou inválido."
    rm -f "$BACKUP_DIR/backup_$DATE.sql.gz"
    exit 1
fi

find "$BACKUP_DIR" \
    -type f \
    -name "backup_*.sql.gz" \
    -mtime +7 \
    -delete

echo "Backup concluído: $BACKUP_DIR/backup_$DATE.sql.gz"
"""


# ============================================================================
# PATCH DO SETTINGS.PY
# ============================================================================

def patch_settings(settings_text):
    """
    Ajusta somente os pontos conhecidos do settings.py do projeto.

    Não substitui o arquivo inteiro.
    """

    original = settings_text

    # ------------------------------------------------------------------------
    # DEBUG
    # ------------------------------------------------------------------------

    debug_pattern = re.compile(
        r"^DEBUG\s*=\s*.*$",
        re.MULTILINE,
    )

    if debug_pattern.search(settings_text):
        settings_text = debug_pattern.sub(
            'DEBUG = config("DEBUG", default=False, cast=bool)',
            settings_text,
            count=1,
        )

    # Remove uma segunda ocorrência de DEBUG.
    matches = list(
        debug_pattern.finditer(settings_text)
    )

    if len(matches) > 1:
        first = True

        def remove_duplicate(match):
            nonlocal first

            if first:
                first = False
                return match.group(0)

            return ""

        settings_text = debug_pattern.sub(
            remove_duplicate,
            settings_text,
        )

    # ------------------------------------------------------------------------
    # ALLOWED_HOSTS
    # ------------------------------------------------------------------------

    hosts_pattern = re.compile(
        r"^ALLOWED_HOSTS\s*=\s*\[.*?\]\s*$",
        re.MULTILINE | re.DOTALL,
    )

    hosts_code = '''ALLOWED_HOSTS = [
    host.strip()
    for host in config(
        "ALLOWED_HOSTS",
        default="localhost,127.0.0.1",
    ).split(",")
    if host.strip()
]'''

    if hosts_pattern.search(settings_text):
        settings_text = hosts_pattern.sub(
            hosts_code,
            settings_text,
            count=1,
        )
    else:
        marker = 'DEBUG = config("DEBUG", default=False, cast=bool)'

        settings_text = settings_text.replace(
            marker,
            marker + "\n\n" + hosts_code,
            1,
        )

    # ------------------------------------------------------------------------
    # STATIC_URL
    # ------------------------------------------------------------------------

    settings_text = re.sub(
        r'^STATIC_URL\s*=\s*.*$',
        'STATIC_URL = "/static/"',
        settings_text,
        count=1,
        flags=re.MULTILINE,
    )

    # ------------------------------------------------------------------------
    # STATIC_ROOT
    # ------------------------------------------------------------------------

    if "STATIC_ROOT" not in settings_text:
        static_marker = 'STATIC_URL = "/static/"'

        settings_text = settings_text.replace(
            static_marker,
            static_marker
            + '\nSTATIC_ROOT = BASE_DIR / "staticfiles"',
            1,
        )

    # ------------------------------------------------------------------------
    # CSRF
    # ------------------------------------------------------------------------

    csrf_code = '''CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in config(
        "CSRF_TRUSTED_ORIGINS",
        default="",
    ).split(",")
    if origin.strip()
]'''

    if "CSRF_TRUSTED_ORIGINS" not in settings_text:
        marker = hosts_code

        settings_text = settings_text.replace(
            marker,
            marker + "\n\n" + csrf_code,
            1,
        )

    # ------------------------------------------------------------------------
    # PROXY HTTPS
    # ------------------------------------------------------------------------

    proxy_code = '''SECURE_PROXY_SSL_HEADER = (
    "HTTP_X_FORWARDED_PROTO",
    "https",
)

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
'''

    if "SECURE_PROXY_SSL_HEADER" not in settings_text:
        marker = 'CSRF_TRUSTED_ORIGINS = ['

        # Inserção antes do bloco CSRF
        position = settings_text.find(
            marker
        )

        if position >= 0:
            settings_text = (
                settings_text[:position]
                + proxy_code
                + "\n"
                + settings_text[position:]
            )
        else:
            settings_text += "\n\n" + proxy_code

    if settings_text == original:
        raise RuntimeError(
            "Não foi possível identificar alterações necessárias "
            "no settings.py."
        )

    return settings_text


# ============================================================================
# GIT
# ============================================================================

def get_remote_head(ssh):
    ok, out, err = ssh.run(
        f"cd {q(APP_DIR)} && git rev-parse HEAD"
    )

    if not ok:
        return None

    return out.strip()


def update_repository(ssh, config):
    print(
        f"\n{step('Atualizando repositório Git')}"
    )

    # Verifica se já é um repositório.
    ok, _, _ = ssh.run(
        f"test -d {q(APP_DIR + '/.git')}"
    )

    if ok:
        old_commit = get_remote_head(ssh)

        branch = q(config["git_branch"])

        commands = [
            f"cd {q(APP_DIR)} && git fetch origin {branch}",
            f"cd {q(APP_DIR)} && git checkout {branch}",
            f"cd {q(APP_DIR)} && git reset --hard origin/{branch}",
        ]

        for command in commands:
            success, _, err = ssh.run(
                command,
                timeout=300,
            )

            if not success:
                raise RuntimeError(
                    f"Git falhou:\n{err}"
                )

        new_commit = get_remote_head(ssh)

        print(
            Colors.success(
                f"Atualizado: {old_commit} -> {new_commit}"
            )
        )

        return old_commit

    # Primeiro deploy.
    print(
        Colors.info(
            "Primeiro deploy: clonando repositório."
        )
    )

    # Confirma que o diretório pode ser usado.
    ok, _, err = ssh.run(
        f"mkdir -p {q(APP_DIR)}"
    )

    if not ok:
        raise RuntimeError(err)

    command = (
        f"rm -rf {q(APP_DIR)}/* "
        f"{q(APP_DIR)}/.[!.]* "
        f"{q(APP_DIR)}/..?* 2>/dev/null || true; "
        f"git clone --branch {q(config['git_branch'])} "
        f"--depth 1 "
        f"{q(GIT_REPO)} "
        f"{q(APP_DIR)}"
    )

    success, _, err = ssh.run(
        command,
        timeout=600,
    )

    if not success:
        raise RuntimeError(
            f"Git clone falhou:\n{err}"
        )

    print(
        Colors.success(
            "Repositório clonado."
        )
    )

    return None


# ============================================================================
# ARQUIVOS REMOTOS
# ============================================================================

def write_remote_file(
    ssh,
    path,
    content,
    mode=None,
):
    parent = str(
        Path(path).parent
    )

    ok, _, err = ssh.run(
        f"mkdir -p {q(parent)}"
    )

    if not ok:
        raise RuntimeError(
            f"Não foi possível criar {parent}: {err}"
        )

    ok, err = ssh.upload_text(
        path,
        content,
    )

    if not ok:
        raise RuntimeError(
            f"Não foi possível escrever {path}: {err}"
        )

    if mode:
        ok, _, err = ssh.run(
            f"chmod {mode} {q(path)}"
        )

        if not ok:
            raise RuntimeError(
                f"chmod falhou em {path}: {err}"
            )


def read_remote_file(ssh, path):
    ok, out, err = ssh.run(
        f"cat {q(path)}"
    )

    if not ok:
        raise RuntimeError(
            f"Não foi possível ler {path}: {err}"
        )

    return out


# ============================================================================
# CONFIGURAÇÃO DO PROJETO
# ============================================================================

def configure_project(ssh, config):
    print(
        f"\n{step('Configurando Django para produção')}"
    )

    settings_path = (
        f"{APP_DIR}/meusite/settings.py"
    )

    settings_text = read_remote_file(
        ssh,
        settings_path,
    )

    # Backup.
    backup_path = (
        f"{settings_path}.backup-"
        f"{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )

    write_remote_file(
        ssh,
        backup_path,
        settings_text,
        mode="600",
    )

    patched = patch_settings(
        settings_text
    )

    write_remote_file(
        ssh,
        settings_path,
        patched,
    )

    print(
        Colors.success(
            "settings.py ajustado."
        )
    )

    # ------------------------------------------------------------------------
    # requirements.txt
    # ------------------------------------------------------------------------

    requirements_path = (
        f"{APP_DIR}/requirements.txt"
    )

    requirements = read_remote_file(
        ssh,
        requirements_path,
    )

    if not re.search(
        r"(?im)^gunicorn(?:[<>=!~].*)?$",
        requirements,
    ):
        requirements = (
            requirements.rstrip()
            + "\ngunicorn>=23.0\n"
        )

        write_remote_file(
            ssh,
            requirements_path,
            requirements,
        )

        print(
            Colors.success(
                "Gunicorn adicionado ao requirements.txt."
            )
        )
    else:
        print(
            Colors.info(
                "Gunicorn já está no requirements.txt."
            )
        )


# ============================================================================
# DOCKERFILE / COMPOSE / NGINX
# ============================================================================

def create_infrastructure_files(
    ssh,
    config,
):
    print(
        f"\n{step('Criando infraestrutura Docker/Nginx')}"
    )

    files = {
        f"{APP_DIR}/Dockerfile":
            get_dockerfile(),

        f"{REMOTE_BASE_DIR}/docker-compose.yml":
            get_compose(config),

        f"{REMOTE_BASE_DIR}/nginx/default.conf":
            get_nginx_http(config),

        f"{REMOTE_BASE_DIR}/backup-db.sh":
            get_backup_script(),
    }

    for path, content in files.items():
        mode = None

        if path.endswith(
            "backup-db.sh"
        ):
            mode = "700"

        write_remote_file(
            ssh,
            path,
            content,
            mode=mode,
        )

        print(
            Colors.success(
                path.replace(
                    REMOTE_BASE_DIR,
                    "",
                )
            )
        )

    # .env
    env_path = (
        f"{REMOTE_BASE_DIR}/.env"
    )

    write_remote_file(
        ssh,
        env_path,
        get_env(config),
        mode="600",
    )

    print(
        Colors.success(".env")
    )

    # Diretórios.
    ssh.run(
        f"mkdir -p "
        f"{q(REMOTE_BASE_DIR + '/media')} "
        f"{q(REMOTE_BASE_DIR + '/nginx')} "
        f"/var/backups/mysql"
    )


# ============================================================================
# DOCKER
# ============================================================================

def compose(
    ssh,
    command,
    timeout=SSH_COMMAND_TIMEOUT,
):
    full = (
        f"cd {q(REMOTE_BASE_DIR)} && "
        f"docker compose {command}"
    )

    return ssh.run(
        full,
        timeout=timeout,
    )


def validate_compose(ssh):
    print(
        f"\n{step('Validando Docker Compose')}"
    )

    ok, out, err = compose(
        ssh,
        "config",
        timeout=120,
    )

    if not ok:
        raise RuntimeError(
            f"docker compose config falhou:\n{err}"
        )

    print(
        Colors.success(
            "Compose válido."
        )
    )


def start_stack(ssh):
    print(
        f"\n{step('Construindo imagens')}"
    )

    ok, out, err = compose(
        ssh,
        "build",
        timeout=1800,
    )

    if not ok:
        raise RuntimeError(
            f"Build Docker falhou:\n{err}"
        )

    print(
        Colors.success(
            "Imagens construídas."
        )
    )

    print(
        f"\n{step('Iniciando containers')}"
    )

    ok, out, err = compose(
        ssh,
        "up -d",
        timeout=600,
    )

    if not ok:
        raise RuntimeError(
            f"docker compose up falhou:\n{err}"
        )

    print(
        Colors.success(
            "Containers iniciados."
        )
    )


def wait_for_database(ssh):
    print(
        f"\n{step('Aguardando MySQL ficar saudável')}"
    )

    for _ in range(36):
        ok, out, _ = ssh.run(
            "docker inspect "
            "--format='{{.State.Health.Status}}' "
            "oggi_db"
        )

        if ok:
            status = out.strip()

            if status == "healthy":
                print(
                    Colors.success(
                        "MySQL está saudável."
                    )
                )
                return

            print(
                f"  Status MySQL: {status}"
            )

        time.sleep(5)

    raise RuntimeError(
        "MySQL não ficou saudável dentro do tempo esperado."
    )


def run_django_commands(ssh):
    print(
        f"\n{step('Executando Django check --deploy')}"
    )

    ok, out, err = compose(
        ssh,
        "exec -T django python manage.py check --deploy",
        timeout=180,
    )

    if not ok:
        raise RuntimeError(
            f"Django check --deploy falhou:\n{err}\n{out}"
        )

    print(
        Colors.success(
            "Django check --deploy OK."
        )
    )

    print(
        f"\n{step('Executando migrations')}"
    )

    ok, out, err = compose(
        ssh,
        "exec -T django python manage.py migrate --noinput",
        timeout=600,
    )

    if not ok:
        raise RuntimeError(
            f"Migrations falharam:\n{err}\n{out}"
        )

    print(
        Colors.success(
            "Migrations concluídas."
        )
    )

    print(
        f"\n{step('Executando collectstatic')}"
    )

    ok, out, err = compose(
        ssh,
        "exec -T django python manage.py collectstatic --noinput",
        timeout=600,
    )

    if not ok:
        raise RuntimeError(
            f"collectstatic falhou:\n{err}\n{out}"
        )

    print(
        Colors.success(
            "Staticfiles coletados."
        )
    )


# ============================================================================
# BACKUP
# ============================================================================

def configure_backup(ssh):
    print(
        f"\n{step('Configurando backup diário')}"
    )

    backup_script = (
        f"{REMOTE_BASE_DIR}/backup-db.sh"
    )

    # Evita duplicar a entrada no cron.
    command = (
        f"ENTRY='0 2 * * * {backup_script} "
        f">> /var/log/oggi-db-backup.log 2>&1'; "
        f"(crontab -l 2>/dev/null | "
        f"grep -Fv {q(backup_script)} || true; "
        f"echo \"$ENTRY\") | crontab -"
    )

    ok, _, err = ssh.run(
        command
    )

    if not ok:
        raise RuntimeError(
            f"Falha ao configurar cron:\n{err}"
        )

    print(
        Colors.success(
            "Backup configurado para 02:00."
        )
    )


# ============================================================================
# SSL
# ============================================================================

def domain_points_to_server(
    ssh,
    config,
):
    """
    Verificação simples no servidor.

    Não substitui uma consulta DNS externa, mas ajuda a detectar
    erros comuns antes de chamar o Let's Encrypt.
    """

    print(
        f"\n{step('Verificando DNS')}"
    )

    for domain in (
        config["main_domain"],
        config["www_domain"],
    ):
        ok, out, _ = ssh.run(
            f"getent ahostsv4 {q(domain)} "
            f"| awk '{{print $1}}' | sort -u"
        )

        if not ok or not out.strip():
            print(
                Colors.warning(
                    f"Não foi possível resolver {domain} "
                    "a partir do servidor."
                )
            )
            return False

        ips = out.strip().splitlines()

        print(
            f"  {domain}: {', '.join(ips)}"
        )

    return True


def obtain_ssl(
    ssh,
    config,
):
    print(
        Colors.header(
            "🔐 SSL / LET'S ENCRYPT"
        )
    )

    print(
        f"""
Antes desta etapa:

  {config['main_domain']}
  {config['www_domain']}

precisam apontar para o IP deste servidor.

O Nginx está atualmente em HTTP justamente para permitir
que o Let's Encrypt valide o domínio.
"""
    )

    answer = input(
        "Tentar configurar SSL agora? [s/N]: "
    ).strip().lower()

    if answer not in (
        "s",
        "sim",
        "y",
        "yes",
    ):
        print(
            Colors.info(
                "SSL será deixado para depois."
            )
        )
        return False

    if not domain_points_to_server(
        ssh,
        config,
    ):
        answer = input(
            "DNS parece incorreto. Continuar mesmo assim? [s/N]: "
        ).strip().lower()

        if answer not in (
            "s",
            "sim",
            "y",
            "yes",
        ):
            return False

    print(
        f"\n{step('Solicitando certificado')}"
    )

    command = (
        f"cd {q(REMOTE_BASE_DIR)} && "
        f"docker compose run --rm certbot certonly "
        f"--webroot "
        f"--webroot-path=/var/www/certbot "
        f"--email {q(config['admin_email'])} "
        f"--agree-tos "
        f"--no-eff-email "
        f"-d {q(config['main_domain'])} "
        f"-d {q(config['www_domain'])}"
    )

    ok, out, err = ssh.run(
        command,
        timeout=600,
    )

    if not ok:
        print(
            Colors.error(
                "Let's Encrypt falhou."
            )
        )
        print(err)
        return False

    print(
        Colors.success(
            "Certificado obtido."
        )
    )

    # Substitui Nginx HTTP por HTTPS.
    nginx_path = (
        f"{REMOTE_BASE_DIR}/nginx/default.conf"
    )

    write_remote_file(
        ssh,
        nginx_path,
        get_nginx_https(config),
    )

    print(
        Colors.success(
            "Configuração HTTPS instalada."
        )
    )

    # Teste antes de reiniciar.
    ok, out, err = compose(
        ssh,
        "exec -T nginx nginx -t",
        timeout=120,
    )

    if not ok:
        # Reverte para HTTP.
        write_remote_file(
            ssh,
            nginx_path,
            get_nginx_http(config),
        )

        print(
            Colors.error(
                "Configuração HTTPS inválida. "
                "Nginx mantido em HTTP."
            )
        )

        print(err)

        return False

    compose(
        ssh,
        "restart nginx",
        timeout=120,
    )

    print(
        Colors.success(
            "HTTPS ativado."
        )
    )

    return True


# ============================================================================
# HEALTH CHECK
# ============================================================================

def check_services(ssh, config):
    print(
        f"\n{step('Verificando containers')}"
    )

    ok, out, err = compose(
        ssh,
        "ps",
        timeout=120,
    )

    if not ok:
        raise RuntimeError(
            f"docker compose ps falhou:\n{err}"
        )

    print(out)

    # Verifica Django.
    print(
        f"\n{step('Verificando Django')}"
    )

    ok, out, err = compose(
        ssh,
        "exec -T django python manage.py check",
        timeout=180,
    )

    if not ok:
        raise RuntimeError(
            f"Django check falhou:\n{err}\n{out}"
        )

    print(
        Colors.success(
            "Django está respondendo ao check."
        )
    )

    # Verifica Nginx.
    print(
        f"\n{step('Verificando Nginx')}"
    )

    ok, out, err = compose(
        ssh,
        "exec -T nginx nginx -t",
        timeout=120,
    )

    if not ok:
        raise RuntimeError(
            f"Nginx check falhou:\n{err}"
        )

    print(
        Colors.success(
            "Nginx está válido."
        )
    )

    # HTTP local no host.
    print(
        f"\n{step('Testando HTTP local')}"
    )

    ok, out, err = ssh.run(
        "curl -fsS --max-time 15 "
        "-H 'Host: "
        + config["main_domain"]
        + "' "
        "http://127.0.0.1/ "
        "-o /dev/null",
        timeout=30,
    )

    if ok:
        print(
            Colors.success(
                "HTTP respondeu corretamente."
            )
        )
    else:
        print(
            Colors.warning(
                "HTTP não respondeu com status 2xx."
            )
        )


# ============================================================================
# ROLLBACK
# ============================================================================

def rollback_git(
    ssh,
    previous_commit,
):
    if not previous_commit:
        return

    print(
        Colors.warning(
            f"Tentando rollback para {previous_commit}"
        )
    )

    command = (
        f"cd {q(APP_DIR)} && "
        f"git reset --hard {q(previous_commit)}"
    )

    ok, _, err = ssh.run(
        command,
        timeout=180,
    )

    if not ok:
        print(
            Colors.error(
                f"Rollback Git falhou: {err}"
            )
        )
        return

    # Reconstrói a aplicação.
    compose(
        ssh,
        "build django",
        timeout=1200,
    )

    compose(
        ssh,
        "up -d django",
        timeout=300,
    )

    print(
        Colors.warning(
            "Código revertido."
        )
    )

    print(
        Colors.warning(
            "As migrations do banco NÃO foram revertidas automaticamente."
        )
    )


# ============================================================================
# CREDENCIAIS
# ============================================================================

def save_credentials_locally(config):
    filename = Path(
        "OGGIBARUERI_CREDENTIALS.txt"
    )

    content = f"""# OGGI BARUERI - CREDENCIAIS
# Gerado em: {datetime.now().isoformat()}

SSH_HOST={config['ssh_host']}
SSH_USER={config['ssh_user']}

DOMAIN={config['main_domain']}
WWW_DOMAIN={config['www_domain']}

DB_NAME={config['db_name']}
DB_USER={config['db_user']}
DB_PASSWORD={config['db_password']}

MYSQL_ROOT_PASSWORD={config['mysql_root_password']}

SECRET_KEY={config['secret_key']}
"""

    filename.write_text(
        content,
        encoding="utf-8",
    )

    try:
        filename.chmod(0o600)
    except OSError:
        pass

    print(
        Colors.warning(
            f"Credenciais salvas em {filename}"
        )
    )

    print(
        Colors.warning(
            "NÃO envie esse arquivo para o GitHub."
        )
    )


# ============================================================================
# DASHBOARD
# ============================================================================

def show_dashboard(
    config,
    ssl_enabled,
):
    protocol = (
        "https"
        if ssl_enabled
        else "http"
    )

    print(
        Colors.header(
            "🎉 DEPLOY FINALIZADO"
        )
    )

    print(
        f"""
SITE
  {protocol}://{config['main_domain']}
  {protocol}://{config['www_domain']}

ADMIN
  {protocol}://{config['main_domain']}/admin/

SERVIDOR
  {config['ssh_user']}@{config['ssh_host']}

DIRETÓRIO
  {REMOTE_BASE_DIR}

DOCKER
  cd {REMOTE_BASE_DIR}

  docker compose ps
  docker compose logs -f django
  docker compose logs -f nginx
  docker compose logs -f db

  docker compose restart
  docker compose restart django
  docker compose restart nginx

BANCO
  MySQL não está publicado na porta 3306 do host.

BACKUP
  /var/backups/mysql/
  Horário: 02:00 diariamente

GIT
  Branch: {config['git_branch']}
"""
    )

    if not ssl_enabled:
        print(
            Colors.warning(
                "\nSSL ainda não foi ativado."
            )
        )

        print(
            f"""
Para ativar posteriormente, execute o script novamente
ou configure o certificado usando o mesmo volume Docker.

Antes disso, confirme que:

  {config['main_domain']} -> IP do VPS
  {config['www_domain']} -> IP do VPS
"""
        )


# ============================================================================
# MAIN
# ============================================================================

def main():
    print(
        f"""
{Colors.CYAN}{Colors.BOLD}
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║              🍦 OGGI BARUERI - DEPLOY                       ║
║                                                              ║
║        Django + MySQL + Gunicorn + Docker + Nginx           ║
║                                                              ║
║        Projeto: meusite / aluguel                            ║
║        Domínio: oggibarueri.com.br                           ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
{Colors.RESET}
"""
    )

    config = None
    ssh = None
    previous_commit = None

    try:
        # --------------------------------------------------------------------
        # Pré-requisitos locais
        # --------------------------------------------------------------------

        require_local_command(
            "ssh"
        )

        # --------------------------------------------------------------------
        # Inputs
        # --------------------------------------------------------------------

        config = collect_config()

        # --------------------------------------------------------------------
        # SSH
        # --------------------------------------------------------------------

        ssh = SSH(config)

        print(
            f"\n{step('Testando conexão SSH')}"
        )

        ok, out, err = ssh.run(
            "hostname"
        )

        if not ok:
            raise RuntimeError(
                f"Falha SSH:\n{err}"
            )

        print(
            Colors.success(
                f"Servidor: {out.strip()}"
            )
        )

        # --------------------------------------------------------------------
        # Docker/Git
        # --------------------------------------------------------------------

        print(
            f"\n{step('Preparando servidor')}"
        )

        commands = [
            "apt-get update",
            (
                "DEBIAN_FRONTEND=noninteractive "
                "apt-get install -y "
                "docker.io docker-compose-plugin git curl"
            ),
            "systemctl enable --now docker",

            f"mkdir -p {q(REMOTE_BASE_DIR)}",
            f"mkdir -p {q(APP_DIR)}",
            f"mkdir -p {q(REMOTE_BASE_DIR + '/nginx')}",
            f"mkdir -p {q(REMOTE_BASE_DIR + '/media')}",
            "mkdir -p /var/backups/mysql",
        ]

        for command in commands:
            ok, _, err = ssh.run(
                command,
                timeout=600,
            )

            if not ok:
                raise RuntimeError(
                    f"Setup do servidor falhou:\n"
                    f"{command}\n\n"
                    f"{err}"
                )

        print(
            Colors.success(
                "Servidor preparado."
            )
        )

        # --------------------------------------------------------------------
        # Git
        # --------------------------------------------------------------------

        previous_commit = update_repository(
            ssh,
            config,
        )

        # --------------------------------------------------------------------
        # Configuração Django
        # --------------------------------------------------------------------

        configure_project(
            ssh,
            config,
        )

        # --------------------------------------------------------------------
        # Infraestrutura
        # --------------------------------------------------------------------

        create_infrastructure_files(
            ssh,
            config,
        )

        validate_compose(
            ssh,
        )

        # --------------------------------------------------------------------
        # Docker
        # --------------------------------------------------------------------

        start_stack(
            ssh,
        )

        wait_for_database(
            ssh,
        )

        # --------------------------------------------------------------------
        # Django
        # --------------------------------------------------------------------

        run_django_commands(
            ssh,
        )

        # --------------------------------------------------------------------
        # Backup
        # --------------------------------------------------------------------

        configure_backup(
            ssh,
        )

        # --------------------------------------------------------------------
        # Health check
        # --------------------------------------------------------------------

        check_services(
            ssh,
            config,
        )

        # --------------------------------------------------------------------
        # SSL
        # --------------------------------------------------------------------

        ssl_enabled = obtain_ssl(
            ssh,
            config,
        )

        # --------------------------------------------------------------------
        # Health final
        # --------------------------------------------------------------------

        check_services(
            ssh,
            config,
        )

        # --------------------------------------------------------------------
        # Credenciais
        # --------------------------------------------------------------------

        save = input(
            "\nSalvar credenciais localmente? [s/N]: "
        ).strip().lower()

        if save in (
            "s",
            "sim",
            "y",
            "yes",
        ):
            save_credentials_locally(
                config
            )

        # --------------------------------------------------------------------
        # Dashboard
        # --------------------------------------------------------------------

        show_dashboard(
            config,
            ssl_enabled,
        )

        return 0

    except KeyboardInterrupt:
        print(
            Colors.warning(
                "\nDeploy interrompido pelo usuário."
            )
        )
        return 130

    except Exception as exc:
        print(
            Colors.error(
                f"\nDEPLOY FALHOU:\n{exc}"
            )
        )

        # --------------------------------------------------------------------
        # Rollback básico
        # --------------------------------------------------------------------

        if ssh and previous_commit:
            answer = input(
                "\nTentar rollback do código Git? [s/N]: "
            ).strip().lower()

            if answer in (
                "s",
                "sim",
                "y",
                "yes",
            ):
                try:
                    rollback_git(
                        ssh,
                        previous_commit,
                    )
                except Exception as rollback_error:
                    print(
                        Colors.error(
                            f"Erro no rollback: {rollback_error}"
                        )
                    )

        return 1


if __name__ == "__main__":
    sys.exit(main())
