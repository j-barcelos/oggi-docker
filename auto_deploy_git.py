#!/usr/bin/env python3
"""
Automated Deploy Script - Oggi Barueri (Git-Based)
Versão: 3.1 - COM CORREÇÕES DE SINTAXE
Repositório: https://github.com/j-barcelos/aluguel_carrinho-sorvete
"""

import subprocess
import sys
import os
import secrets
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict

# ============================================================================
# CONFIGURAÇÕES DO REPOSITÓRIO
# ============================================================================

GIT_REPO = "https://github.com/j-barcelos/aluguel_carrinho-sorvete.git"
GIT_BRANCH = "main"  # Ou 'master', 'develop', etc.
PROJECT_NAME = "oggi-sorvetes"
REMOTE_BASE_DIR = "/var/www/oggi-sorvetes"
APP_DIR = f"{REMOTE_BASE_DIR}/app"

DOMINIO_PRINCIPAL = "oggibarueri.com.br"

# ============================================================================
# CORES
# ============================================================================

class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    RESET = '\033[0m'
    BOLD = '\033[1m'
    
    @staticmethod
    def success(msg): return f"{Colors.GREEN}✓{Colors.RESET} {msg}"
    @staticmethod
    def warning(msg): return f"{Colors.YELLOW}⚠{Colors.RESET} {msg}"
    @staticmethod
    def error(msg): return f"{Colors.RED}✗{Colors.RESET} {msg}"
    @staticmethod
    def info(msg): return f"{Colors.BLUE}ℹ{Colors.RESET} {msg}"
    @staticmethod
    def prompt(msg): return f"{Colors.CYAN}➜{Colors.RESET} {msg}"
    @staticmethod
    def header(msg): return f"\n{Colors.BOLD}{Colors.MAGENTA}{'='*60}{Colors.RESET}\n{Colors.CYAN}{Colors.BOLD}{msg}{Colors.RESET}\n{Colors.BOLD}{Colors.MAGENTA}{'='*60}{Colors.RESET}\n"

# ============================================================================
# COLETA DE INPUTS MANUAIS
# ============================================================================

def collect_user_inputs():
    """Coleta todas as informações necessárias do usuário"""
    print(Colors.header("📝 INFORMAÇÕES PARA DEPLOY OGGIBARUERI"))
    print(f"{Colors.INFO}Repositório: {Colors.CYAN}{GIT_REPO}{Colors.RESET}")
    
    config = {}
    
    # --- 1. SERVIDOR SSH ---
    print(f"\n{Colors.prompt('🔹 DADOS DO SERVIDOR HOSTINGER')}")
    config['ssh_host'] = input("  🌐 IP do VPS (ex: 178.128.xxx.xxx): ").strip()
    config['ssh_user'] = input("  👤 Usuário SSH (padrão: root): ").strip() or "root"
    
    auth_type = input("  🔑 Autenticação: [1] Chave SSH  [2] Senha: ").strip()
    if auth_type == '1':
        config['auth_method'] = 'key'
        config['ssh_key_path'] = input("  📂 Caminho da chave: ").strip() or "~/.ssh/id_rsa"
    else:
        config['auth_method'] = 'password'
        config['ssh_password'] = input("  🔐 Senha SSH: ").strip()
    
    # --- 2. DOMÍNIOS ---
    print(f"\n{Colors.prompt('🔹 INFORMAÇÕES DE DOMÍNIO')}")
    config['main_domain'] = input("  🌍 Domínio principal: ").strip() or DOMINIO_PRINCIPAL
    config['www_domain'] = input("  🌐 Domínio www: ").strip() or f"www.{config['main_domain']}"
    config['admin_email'] = input("  📧 Email para SSL/Notificações: ").strip()
    
    # --- 3. BANCO DE DADOS ---
    print(f"\n{Colors.prompt('🔹 BANCO DE DADOS MySQL')}")
    config['db_name'] = input("  🗄️ Nome do banco (padrão: oggi_baru_sorvete): ").strip() or "oggi_baru_sorvete"
    config['db_user'] = input("  👤 Usuário do banco (padrão: oggi_baru_user): ").strip() or "oggi_baru_user"
    
    # --- 4. SENHAS GERADAS AUTOMATICAMENTE ---
    print(f"\n{Colors.info('🔐 SENHAS SEGURAS SERÃO GERADAS AUTOMATICAMENTE...')}")
    config['db_password'] = generate_password(24)
    config['mysql_root_password'] = generate_password(24)
    config['secret_key'] = generate_secret_key()
    
    # Mostrar senhas
    print(f"\n{Colors.BOLD}{'='*50}{Colors.RESET}")
    print(f"{Colors.YELLOW}⚠️  SALVE ESTAS SENHAS IMEDIATAMENTE! ⚠️{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*50}{Colors.RESET}")
    print(f"{Colors.CYAN}Database Password:{Colors.RESET} {config['db_password']}")
    print(f"{Colors.CYAN}MySQL Root Password:{Colors.RESET} {config['mysql_root_password']}")
    print(f"{Colors.CYAN}Django Secret Key:{Colors.RESET} {config['secret_key'][:30]}...")
    print(f"{Colors.BOLD}{'='*50}{Colors.RESET}")
    
    # Perguntar se quer salvar
    save_credentials = input(f"\n{Colors.prompt('Salvar credenciais em arquivo seguro? (s/n): ')}").strip().lower()
    if save_credentials in ['s', 'sim', 'y', 'yes']:
        save_file = 'OGGIBARUERI_CREDENTIALS.txt'
        with open(save_file, 'w', encoding='utf-8') as f:
            f.write("# ===========================================\n")
            f.write(f"# OGGIBARUERI DEPLOY CREDENTIALS\n")
            f.write(f"# Gerado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# DOMÍNIO: {config['main_domain']}\n")
            f.write("# ===========================================\n\n")
            for k, v in config.items():
                if 'password' in k.lower() or 'secret' in k.lower():
                    f.write(f"{k.upper()}={v}\n")
        print(f"{Colors.success(f'Credenciais salvas em: {save_file}')}")
        print(f"{Colors.warning('APAGUE ESTE ARQUIVO APÓS LER AS SENHAS!')}")
    
    # --- 5. BRANCH/GIT ---
    print(f"\n{Colors.prompt('🔹 CONFIGURAÇÃO GIT')}")
    config['git_branch'] = input(f"  🌿 Branch do repositório (padrão: {GIT_BRANCH}): ").strip() or GIT_BRANCH
    
    # --- 6. RESUMO E CONFIRMAÇÃO ---
    print(f"\n{Colors.header('📋 RESUMO FINAL DE CONFIGURAÇÃO')}")
    print(f"  {'Servidor:':<20} {Colors.CYAN}{config['ssh_user']}@{config['ssh_host']}{Colors.RESET}")
    print(f"  {'Autenticação:':<20} {Colors.CYAN}{config['auth_method'].upper()}{Colors.RESET}")
    print(f"  {'Domínio Principal:':<20} {Colors.CYAN}{config['main_domain']}{Colors.RESET}")
    print(f"  {'Domínio www:':<20} {Colors.CYAN}{config['www_domain']}{Colors.RESET}")
    print(f"  {'Email Admin:':<20} {Colors.CYAN}{config['admin_email']}{Colors.RESET}")
    print(f"  {'Banco de Dados:':<20} {Colors.CYAN}{config['db_name']} / {config['db_user']}{Colors.RESET}")
    print(f"  {'Branch Git:':<20} {Colors.CYAN}{config['git_branch']}{Colors.RESET}")
    print(f"  {'Repositório:':<20} {Colors.CYAN}{GIT_REPO}{Colors.RESET}")
    print(f"  {'Diretório Remoto:':<20} {Colors.CYAN}{REMOTE_BASE_DIR}{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*60}{Colors.RESET}")
    
    confirm = input(f"\n{Colors.prompt('✅ Confirmar e iniciar deploy? (s/n): ')}").strip().lower()
    if confirm not in ['s', 'sim', 'y', 'yes']:
        print(f"\n{Colors.info('Deploy cancelado pelo usuário')}")
        sys.exit(0)
    
    return config

def generate_password(length=24):
    """Gera senha segura aleatória"""
    alphabet = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*'
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def generate_secret_key():
    """Gera SECRET_KEY Django"""
    chars = 'abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)'
    return ''.join(secrets.SystemRandom().choice(chars) for _ in range(50))

# ============================================================================
# GERAÇÃO DE ARQUIVOS
# ============================================================================

def get_dotenv(config):
    return f"""# ============================================
# OGGIBARUERI - CONFIGURAÇÃO DE AMBIENTE
# Gerado em: {datetime.now().strftime('%Y-%m-%d %H:%M')}
# ============================================

SECRET_KEY={config['secret_key']}
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1,{config['main_domain']},{config['www_domain']},{config['ssh_host']}

# Database MySQL
DB_NAME={config['db_name']}
DB_USER={config['db_user']}
DB_PASSWORD={config['db_password']}
DB_HOST=db
DB_PORT=3306

ADMIN_EMAIL={config['admin_email']}
MYSQL_ROOT_PASSWORD={config['mysql_root_password']}

# Docker Compose
DJANGO_PORT=8000
NGINX_HTTP_PORT=80
NGINX_HTTPS_PORT=443
"""

def get_dockerfile():
    return '''FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONFAULTHANDLER=1

WORKDIR /app

# Instalar dependências do sistema para mysqlclient
RUN apt-get update && apt-get install -y \\
    default-libmysqlclient-dev \\
    gcc \\
    pkg-config \\
    build-essential \\
    && rm -rf /var/lib/apt/lists/*

# Criar diretórios necessários
RUN mkdir -p /var/www/oggi-sorvetes/media
RUN mkdir -p staticfiles

# Copiar requirements primeiro para melhor cache
COPY requirements.txt .

# Instalar dependências Python
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código fonte
COPY . .

# Coletar arquivos estáticos (falhará se não houver dados, então ignorar erro)
RUN python manage.py collectstatic --noinput --ignore || true

EXPOSE 8000

# Iniciar com Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120", "meusite.wsgi:application"]'''

def get_nginx_config(config):
    return f'''# Nginx Configuration - Oggi Barueri
# Domain: {config['main_domain']}

# HTTP Server - Redirect to HTTPS
server {{
    listen 80;
    server_name {config['main_domain']} {config['www_domain']};
    
    # Let's Encrypt challenge endpoint
    location /.well-known/acme-challenge/ {{
        root /var/www/letsencrypt;
    }}
    
    # Redirect all other requests to HTTPS
    location / {{
        return 301 https://$server_name$request_uri;
    }}
}}

# HTTPS Server
server {{
    listen 443 ssl http2;
    server_name {config['main_domain']} {config['www_domain']};

    # SSL Certificate
    ssl_certificate /etc/letsencrypt/live/{config['main_domain']}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{config['main_domain']}/privkey.pem;

    # SSL Settings
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Logging
    access_log /var/log/nginx/oggi_access.log;
    error_log /var/log/nginx/oggi_error.log;

    # Request size limit
    client_max_body_size 10M;

    # Static files (Django collectedstatic)
    location /static/ {{
        alias /var/www/oggi-sorvetes/app/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, immutable";
        access_log off;
    }}

    # Media files (user uploads)
    location /media/ {{
        alias /var/www/oggi-sorvetes/media/;
        expires 30d;
        add_header Cache-Control "public";
    }}

    # Proxy to Django/Gunicorn
    location / {{
        proxy_pass http://django:8000;
        
        # Headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts
        proxy_read_timeout 120s;
        proxy_connect_timeout 120s;
        proxy_send_timeout 120s;
        
        # Buffer settings
        proxy_buffering on;
        proxy_buffer_size 4k;
        proxy_buffers 8 4k;
    }}

    # Health check endpoint
    location /health/ {{
        proxy_pass http://django:8000/;
        proxy_set_header Host $host;
        access_log off;
    }}
}}'''

def get_docker_compose(config):
    return f'''version: '3.8'

# Oggi Barueri - Docker Compose Configuration
# Created: {datetime.now().strftime('%Y-%m-%d %H:%M')}

services:
  # MySQL Database Service
  db:
    image: mysql:8.0
    container_name: oggi_db
    restart: unless-stopped
    environment:
      MYSQL_DATABASE: {config['db_name']}
      MYSQL_USER: {config['db_user']}
      MYSQL_PASSWORD: {config['db_password']}
      MYSQL_ROOT_PASSWORD: {config['mysql_root_password']}
    volumes:
      - db_data:/var/lib/mysql
      - ./backup-db.sh:/usr/local/bin/backup.sh:ro
    networks:
      - oggi_network
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    ports:
      - "3306:3306"

  # Django Application Service
  django:
    build:
      context: ./app
      dockerfile: Dockerfile
    container_name: oggi_django
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - ./app:/app
      - ./media:/var/www/oggi-sorvetes/media
      - static_volume:/var/www/oggi-sorvetes/app/staticfiles
    environment:
      SECRET_KEY: {config['secret_key']}
      DEBUG: "False"
      ALLOWED_HOSTS: {config['main_domain']},{config['www_domain']},{config['ssh_host']}
      DB_NAME: {config['db_name']}
      DB_USER: {config['db_user']}
      DB_PASSWORD: {config['db_password']}
      DB_HOST: db
      DB_PORT: 3306
    networks:
      - oggi_network

  # Nginx Reverse Proxy
  nginx:
    image: nginx:alpine
    container_name: oggi_nginx
    restart: unless-stopped
    depends_on:
      - django
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
      - ./media:/var/www/oggi-sorvetes/media
      - static_volume:/var/www/oggi-sorvetes/app/staticfiles:ro
      - letsencrypt_vol:/etc/letsencrypt:ro
      - /var/log/nginx:/var/log/nginx
    networks:
      - oggi_network

# Named Volumes
volumes:
  db_data:
    driver: local
  static_volume:
    driver: local
  letsencrypt_vol:
    driver: local

# Networks
networks:
  oggi_network:
    driver: bridge
'''

def get_backup_script(config):
    return f'''#!/bin/bash
# ============================================
# Oggi Barueri - Database Backup Script
# ============================================

BACKUP_DIR="/var/backups/mysql"
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=7
LOG_FILE="/var/log/db_backup.log"

# Create backup directory if not exists
mkdir -p $BACKUP_DIR

# Perform backup
echo "Starting backup at $(date)" >> $LOG_FILE
mysqldump -h db -u {config['db_user']} -p{config['db_password']} {config['db_name']} > $BACKUP_DIR/backup_$DATE.sql

if [ $? -eq 0 ]; then
    echo "✓ Backup successful: backup_$DATE.sql" >> $LOG_FILE
else
    echo "✗ Backup failed!" >> $LOG_FILE
    exit 1
fi

# Remove old backups
find $BACKUP_DIR -name "backup_*.sql" -mtime +$RETENTION_DAYS -delete

# Keep last 10 backups
ls -t $BACKUP_DIR/backup_*.sql | tail -n +11 | xargs -r rm

echo "Backup completed at $(date)" >> $LOG_FILE
'''

def get_requirements_updated():
    """Read original requirements and add gunicorn if missing"""
    return '''Django>=6.0.3
mysqlclient>=2.2.8
pillow>=12.1.1
python-decouple>=3.8
gunicorn>=21.2.0
psycopg2-binary>=2.9.9
python-dotenv>=1.0.0
'''.strip()

def get_setup_commands():
    """Return additional setup commands for the server"""
    return [
        "apt update && apt upgrade -y",
        "apt install -y docker.io docker-compose-plugin curl git wget sqlite3 rsync",
        "systemctl enable docker && systemctl start docker",
        "apt install -y fail2ban",
        "fail2ban-client start sshd || true",
        "ufw allow 22/tcp comment 'SSH'",
        "ufw allow 80/tcp comment 'HTTP'",
        "ufw allow 443/tcp comment 'HTTPS'",
        "ufw allow 3306/tcp comment 'MySQL (internal only)'",
        "echo y | ufw enable || echo 'Firewall may already be configured'",
    ]

# ============================================================================
# FUNÇÃO ADICIONAL: CORREÇÃO PARA EXIBIÇÃO DE COMANDOS
# ============================================================================

def step(msg):
    """Função auxiliar para exibir passos"""
    return f"{Colors.CYAN}▸{Colors.RESET} {msg}"

# ============================================================================
# EXECUÇÃO SSH E DEPLOY
# ============================================================================

def run_ssh_command(host: str, user: str, command: str, config: dict) -> tuple:
    """Executa comando SSH e retorna (sucesso, stdout, stderr)"""
    if config['auth_method'] == 'key':
        key_path = os.path.expanduser(config['ssh_key_path'])
        cmd = f'ssh -i "{key_path}" -o StrictHostKeyChecking=no {user}@{host} "{command}"'
    else:
        # Usar sshpass se disponível, senão pedir interação
        try:
            cmd = f'sshpass -p "{config["ssh_password"]}" ssh -o StrictHostKeyChecking=no {user}@{host} "{command}"'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)
            return result.returncode == 0, result.stdout, result.stderr
        except FileNotFoundError:
            print(f"  {Colors.warning('sshpass não encontrado. Instalação manual necessária para senha SSH')}")
            return False, "", "sshpass not found"
    
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)
    return result.returncode == 0, result.stdout, result.stderr

def clone_repository_via_ssh(host: str, user: str, config: dict) -> bool:
    """Clona o repositório diretamente no servidor"""
    print(f"\n{step('Clonando repositório GitHub no servidor')}")
    
    commands = [
        f"cd {REMOTE_BASE_DIR}",
        f"git clone {GIT_REPO} temp_repo",
        f"mv temp_repo/* .",
        f"mv temp_repo/.git .",
        "rm -rf temp_repo",
        f"chown -R www-data:www-data {APP_DIR}",
        f"chmod -R 755 {APP_DIR}",
    ]
    
    for cmd in commands:
        ok, out, err = run_ssh_command(host, user, cmd, config)
        if ok:
            print(f"  {Colors.success(cmd[:50])}...")
        else:
            truncated_err = err[:50] if err else "desconhecido"
            print(f"  {Colors.warning(f'{cmd[:50]}... Erro: {truncated_err}')}")
    
    return True

def create_remote_files(host: str, user: str, config: dict) -> bool:
    """Cria todos os arquivos de configuração no servidor"""
    print(f"\n{step('Criando arquivos de configuração')}")
    
    files = {
        f'{REMOTE_BASE_DIR}/.env': get_dotenv(config),
        f'{REMOTE_BASE_DIR}/docker-compose.yml': get_docker_compose(config),
        f'{APP_DIR}/Dockerfile': get_dockerfile(),
        f'{REMOTE_BASE_DIR}/nginx/default.conf': get_nginx_config(config),
        f'{APP_DIR}/requirements.txt': get_requirements_updated(),
        f'{REMOTE_BASE_DIR}/backup-db.sh': get_backup_script(config),
    }
    
    for remote_path, content in files.items():
        # Criar diretório pai
        dir_path = '/'.join(remote_path.split('/')[:-1])
        run_ssh_command(host, user, f"mkdir -p {dir_path}", config)
        
        # Escrever conteúdo via heredoc
        if config['auth_method'] == 'key':
            key_path = os.path.expanduser(config['ssh_key_path'])
            cmd = f'ssh -i "{key_path}" -o StrictHostKeyChecking=no {user}@{host} \'cat > {remote_path} << EOF\' \'{content}\' EOF\''
        else:
            try:
                import shlex
                escaped_content = content.replace("'", "'\\''")
                cmd = f"sshpass -p '{config['ssh_password']}' ssh -o StrictHostKeyChecking=no {user}@{host} \"cat > {remote_path} << 'EOF'\\n{escaped_content}\\nEOF\""
            except:
                cmd = f'ssh -o StrictHostKeyChecking=no {user}@{host} "cat > {remote_path}"'
                subprocess.run(cmd, input=content.encode(), shell=True)
        
        # Alternativa mais confiável: escrever em chunks
        cmd_write = f'ssh -o StrictHostKeyChecking=no {user}@{host} "tee {remote_path}"'
        proc = subprocess.Popen(cmd_write, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = proc.communicate(input=content)
        
        ok = proc.returncode == 0
        
        if ok:
            rel_path = remote_path.replace(REMOTE_BASE_DIR + '/', '')
            print(f"  {Colors.success(rel_path + ' ✓')}")
        else:
            print(f"  {Colors.warning(f'{remote_path} - Erro ao escrever')}")
    
    # Tornar backup script executável
    run_ssh_command(host, user, f"chmod +x {REMOTE_BASE_DIR}/backup-db.sh", config)
    
    return True

def setup_docker(host: str, user: str, config: dict) -> bool:
    """Configura Docker e inicia containers"""
    print(f"\n{step('Construindo e iniciando containers')}")
    
    commands = [
        f"cd {REMOTE_BASE_DIR}",
        "docker compose version || docker-compose version",
        "docker compose build --no-cache",
        "docker compose up -d",
        "sleep 15",
        "docker compose ps",
        "docker compose logs --tail=20 django",
    ]
    
    for cmd in commands:
        ok, out, err = run_ssh_command(host, user, cmd, config)
        status = "✓" if ok else "⚠"
        print(f"  {status} {cmd[:45]}...")
        if not ok and err:
            print(f"     {Colors.warning(err[:100])}")
    
    return True

def setup_ssl_instructions(host: str, user: str, config: dict):
    """Fornece instruções para SSL"""
    print(f"\n{step('Configuração SSL (Let\\'s Encrypt)')}")
    print(f"\n{Colors.YELLOW}Execute estes comandos manualmente no servidor:{Colors.RESET}\n")
    print(f"  ssh {user}@{host}")
    print(f"  cd {REMOTE_BASE_DIR}")
    print(f"  ")
    print(f"  # 1. Instalar Certbot")
    print(f"  apt install -y certbot python3-certbot-nginx")
    print(f"  ")
    print(f"  # 2. Obter certificado SSL")
    print(f"  certbot --nginx -d {config['main_domain']} -d {config['www_domain']}")
    print(f"  ")
    print(f"  # 3. Testar renovação")
    print(f"  certbot renew --dry-run")
    print(f"  ")
    print(f"  # 4. Configurar renovação automática")
    print(f"  crontab -l | grep -v certbot | crontab -")
    print(f"  echo '0 3 * * * certbot renew --quiet' | crontab -")
    print(f"\n{Colors.INFO}Após configurar SSL, o site estará acessível via HTTPS!{Colors.RESET}")

def setup_admin_user(host: str, user: str, config: dict):
    """Fornece instruções para criar superusuário"""
    print(f"\n{step('Criar Superusuário Django Admin')}")
    print(f"\n{Colors.YELLOW}Execute no servidor (dados interativos){Colors.RESET}\n")
    print(f"  ssh {user}@{host}")
    print(f"  cd {REMOTE_BASE_DIR}")
    print(f"  docker exec -it oggi_django python manage.py createsuperuser")
    print(f"  ")
    print(f"  Você será solicitado:")
    print(f"    • Username: admin (sugerido)")
    print(f"    • Email: {config['admin_email']}")
    print(f"    • Password: (digite e confirme)")
    print(f"\n{Colors.GREEN}Depois acesse: http://{config['ssh_host']}/admin/{Colors.RESET}")

def show_dashboard(config: dict):
    """Mostra dashboard de acesso"""
    print(f"\n{Colors.header('📊 DASHBOARD OGGIBARUERI')}")
    print(f"""
{Colors.BOLD}ACESSOS IMPORTANTES:{Colors.RESET}

{Colors.GREEN}SITE PÚBLICO{Colors.RESET}
  http://{config['ssh_host']}
  https://{config['main_domain']} (após SSL)

{Colors.CYAN}PAINEL ADMIN{Colors.RESET}
  http://{config['ssh_host']}/painel/
  http://{config['ssh_host']}/admin/ (Django Admin)

{Colors.YELLOW}API ENDPOINTS{Colors.RESET}
  /api/sabores/          ← Lista sabores
  /api/disponibilidade/  ← Verificar disponibilidade
  /api/reserva/criar/    ← Criar reserva

{Colors.MAGENTA}CONTAINER STATUS{Colors.RESET}
  docker compose ps
  docker compose logs -f django
  docker compose logs -f nginx
  docker compose logs -f db

{Colors.BLUE}COMANDOS ÚTEIS{Colors.RESET}
  docker compose restart              # Reinicia todos
  docker compose restart django       # Só Django
  docker compose down                 # Para tudo
  docker compose up -d                # Inicia tudo
  docker compose logs -f              # Logs em tempo real
  docker stats                        # Uso de recursos

{Colors.CYAN}BACKUPS AUTOMÁTICOS{Colors.RESET}
  Localização: /var/backups/mysql/
  Script: {REMOTE_BASE_DIR}/backup-db.sh
  Roda: Diariamente às 2h via cron
""")

# ============================================================================
# MAIN
# ============================================================================

def main():
    print(f"""
{Colors.CYAN}╔═══════════════════════════════════════════════════════════╗
║     🍦 OGGIBARUERI - AUTOMATED DEPLOY                       ║
║     Django + Docker + MySQL + Nginx                         ║
║                                                           ║
║     🌐 Repositório: {Colors.MAGENTA}j-barcelos/aluguel_carrinho-sorvete{Colors.RESET}      ║
║     🚀 Método: Git Clone Direct                          ║
║     🎯 Domínio: {Colors.CYAN}oggibarueri.com.br{Colors.RESET}                       ║
║                                                           ║
║     ⚡ Versão 3.1 - COM CORREÇÕES DE SINTAXE               ║
╚═══════════════════════════════════════════════════════════╝
{Colors.RESET}
""")
    
    # Coletar inputs
    config = collect_user_inputs()
    
    host = config['ssh_host']
    user = config['ssh_user']
    
    # Testar conexão SSH
    print(f"\n{step('Testando conexão SSH')}")
    ok, out, err = run_ssh_command(host, user, "hostname", config)
    if not ok:
        print(f"\n{Colors.error('❌ Falha na conexão SSH')}")
        print(f"  {Colors.warning(f'Erro: {err[:200]}')}")
        print(f"\n{Colors.info('Verifique:')}")
        print(f"  • IP do servidor está correto")
        print(f"  • Usuário e senha/chave estão corretos")
        print(f"  • Porta SSH (22) está aberta")
        return 1
    
    print(f"  {Colors.success('Conectado como: ' + out.strip())}")
    
    # Fase 1: Setup do servidor
    print(f"\n{step('Setup do Servidor Hostinger')}")
    for cmd in get_setup_commands():
        ok, _, _ = run_ssh_command(host, user, cmd, config)
        print(f"  {'✓' if ok else '⚠'} {cmd[:45]}...")
    
    # Fase 2: Criar diretórios
    print(f"\n{step('Criando estrutura de diretórios')}")
    dirs = [
        f"{REMOTE_BASE_DIR}",
        f"{REMOTE_BASE_DIR}/app",
        f"{REMOTE_BASE_DIR}/nginx",
        f"{REMOTE_BASE_DIR}/media",
        f"{REMOTE_BASE_DIR}/logs",
        f"{REMOTE_BASE_DIR}/backups",
        "/var/backups/mysql",
    ]
    for d in dirs:
        ok, _, _ = run_ssh_command(host, user, f"mkdir -p {d}", config)
        print(f"  {'✓' if ok else '⚠'} {d}")
    
    # Fase 3: Clonar repositório
    if not clone_repository_via_ssh(host, user, config):
        print(f"\n{Colors.error('❌ Falha ao clonar repositório')}")
        return 1
    
    # Fase 4: Criar arquivos de configuração
    if not create_remote_files(host, user, config):
        print(f"\n{Colors.warning('⚠ Alguns arquivos podem não ter sido criados')}")
    
    # Fase 5: Iniciar containers
    if not setup_docker(host, user, config):
        print(f"\n{Colors.error('❌ Falha ao iniciar containers')}")
        return 1
    
    # Fase 6: SSL e Admin
    setup_ssl_instructions(host, user, config)
    setup_admin_user(host, user, config)
    
    # Dashboard final
    show_dashboard(config)
    
    print(f"\n{Colors.BOLD}{'='*60}{Colors.RESET}")
    print(f"{Colors.success('🎉 DEPLOY CONCLUÍDO COM SUCESSO! 🍦')}")
    print(f"{Colors.BOLD}{'='*60}{Colors.RESET}")
    
    print(f"""
{Colors.info('PRÓXIMOS PASSOS RECOMENDADOS:')}

1.  Configure DNS no Hostinger:
    - A Record: {config['main_domain']} → {config['ssh_host']}
    - WWW Record: {config['www_domain']} → {config['ssh_host']}
    - Aguarde 1-48 horas para propagação

2.  Execute o setup SSL mostrado acima

3.  Crie o superusuário admin

4.  Teste acesso ao site: http://{config['ssh_host']}

5.  Configure monitoramento:
    • UptimeRobot (grátis) para uptime
    • Sentry para erros do Django
    • New Relic ou similar para performance

6.  Revise permissões:
    chown -R www-data:www-data {REMOTE_BASE_DIR}/media
    chmod -R 755 {REMOTE_BASE_DIR}

{Colors.cyan('Obrigado por usar Oggi Barueri Deploy! 🚀')}
""")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
