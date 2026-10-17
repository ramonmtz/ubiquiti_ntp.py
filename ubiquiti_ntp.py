#!/usr/bin/env python3
"""Configura NTP en equipos airOS autorizados desde Termux con OpenSSH."""
import csv
import getpass
import ipaddress
import os
import re
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

PRINT_LOCK = threading.Lock()

def log(message):
    with PRINT_LOCK:
        print(message, flush=True)

def ask_ip(label):
    while True:
        raw = input(label).strip()
        try:
            address = ipaddress.IPv4Address(raw)
            if not address.is_private:
                print('Introduce una IP privada de tu red de administración.')
                continue
            return address
        except ipaddress.AddressValueError:
            print('Dirección IPv4 inválida.')

def ask_threads():
    while True:
        raw = input('Hilos simultáneos [10, máximo 16]: ').strip() or '10'
        if raw.isdigit() and 1 <= int(raw) <= 16:
            return int(raw)
        print('Introduce un número de 1 a 16.')

def run_one(ip, username, password, ntp_server, known_hosts):
    # Password via inherited FD, never argv/environment. Unique pipe per worker.
    read_fd, write_fd = os.pipe()
    os.set_inheritable(read_fd, True)
    try:
        os.write(write_fd, (password + '\n').encode('utf-8'))
    finally:
        os.close(write_fd)
    remote = r'''set -eu
CFG=/tmp/system.cfg
[ -f "$CFG" ] || { echo 'ERROR: no existe /tmp/system.cfg'; exit 21; }
command -v cfgmtd >/dev/null 2>&1 || { echo 'ERROR: cfgmtd no disponible'; exit 22; }
command -v ntpd >/dev/null 2>&1 || { echo 'ERROR: ntpd no disponible'; exit 23; }
cp "$CFG" /tmp/system.cfg.ntp-backup
# Only modify keys that already exist; do not assume other airOS versions.
grep -q '^ntpclient.status=' "$CFG" || { echo 'ERROR: ntpclient.status no existe'; exit 24; }
grep -q '^ntpclient.1.status=' "$CFG" || { echo 'ERROR: ntpclient.1.status no existe'; exit 25; }
if grep -Eq '^ntpclient(\.1)?\.status=disabled$' "$CFG"; then
  sed -i 's/^ntpclient\.status=disabled$/ntpclient.status=enabled/; s/^ntpclient\.1\.status=disabled$/ntpclient.1.status=enabled/' "$CFG"
fi
grep -q '^ntpclient.status=enabled$' "$CFG" || { echo 'ERROR: estado NTP principal inesperado'; exit 26; }
grep -q '^ntpclient.1.status=enabled$' "$CFG" || { echo 'ERROR: estado NTP servidor inesperado'; exit 27; }
if ! cmp -s "$CFG" /tmp/system.cfg.ntp-backup; then
  cfgmtd -w -p /etc/ >/dev/null || { echo 'ERROR: fallo al guardar'; exit 28; }
  echo 'CONFIG=actualizada_y_guardada'
else
  echo 'CONFIG=ya_habilitada'
fi
SERVER='__SERVER__'
# One-shot only; it does NOT start the periodic service.
if ntpd -n -q -p "$SERVER" >/tmp/ntp-batch-last.log 2>&1; then
  echo 'SYNC=correcta'
else
  echo 'SYNC=fallida'
  tail -n 3 /tmp/ntp-batch-last.log
  exit 29
fi
echo "DATE=$(date -u)"
'''.replace('__SERVER__', ntp_server)
    cmd = [
        'sshpass', '-d', str(read_fd), 'ssh', '-T',
        '-o', 'BatchMode=no',
        '-o', 'PreferredAuthentications=password,keyboard-interactive',
        '-o', 'PubkeyAuthentication=no',
        '-o', 'HostKeyAlgorithms=+ssh-rsa',
        '-o', 'StrictHostKeyChecking=accept-new',
        '-o', f'UserKnownHostsFile={known_hosts}',
        '-o', 'ConnectTimeout=7',
        '-o', 'ConnectionAttempts=1',
        '-o', 'ServerAliveInterval=5',
        '-o', 'ServerAliveCountMax=2',
        f'{username}@{ip}', 'sh', '-s',
    ]
    try:
        result = subprocess.run(cmd, input=remote, text=True, capture_output=True,
                                timeout=55, pass_fds=(read_fd,))
        output = (result.stdout + '\n' + result.stderr).strip()
        if result.returncode == 0 and 'SYNC=correcta' in output:
            status = 'OK'
        elif 'REMOTE HOST IDENTIFICATION HAS CHANGED' in output:
            status = 'CLAVE_SSH_CAMBIADA'
        elif 'Permission denied' in output:
            status = 'AUTENTICACION_FALLIDA'
        elif result.returncode == 255:
            status = 'SSH_NO_DISPONIBLE'
        else:
            status = 'ERROR'
        details = ' | '.join(line.strip() for line in output.splitlines() if line.strip())
        return str(ip), status, details[:1200]
    except subprocess.TimeoutExpired:
        return str(ip), 'TIMEOUT', 'Se agotó el límite de 55 segundos de SSH/sincronización; la configuración puede haberse guardado, verificar en equipo'
    except Exception as exc:
        return str(ip), 'ERROR', str(exc)
    finally:
        os.close(read_fd)

def main():
    for name in ('ssh', 'sshpass'):
        if not shutil.which(name):
            sys.exit(f'Falta {name}. Instala con: pkg install openssh sshpass -y')
    print('=== CONFIGURADOR NTP UBIQUITI airOS ===')
    start = ask_ip('IP inicial: ')
    end = ask_ip('IP final: ')
    if int(end) < int(start):
        sys.exit('La IP final debe ser igual o mayor que la inicial.')
    count = int(end) - int(start) + 1
    if count > 1024:
        sys.exit('Máximo 1024 direcciones por ejecución.')
    username = input('Usuario SSH [ubnt]: ').strip() or 'ubnt'
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', username):
        sys.exit('Usuario SSH no válido.')
    password = getpass.getpass('Contraseña SSH: ')
    if not password:
        sys.exit('La contraseña no puede estar vacía.')
    server = input('Servidor NTP [0.ubnt.pool.ntp.org]: ').strip() or '0.ubnt.pool.ntp.org'
    if not re.fullmatch(r'[A-Za-z0-9.-]+', server) or len(server) > 253 or server.startswith('-'):
        sys.exit('Nombre de servidor NTP no válido.')
    threads = ask_threads()
    print(f'\nSe procesarán {count} IP con {threads} hilos.')
    print('Las claves SSH nuevas se aceptarán automáticamente (TOFU).')
    print('Las claves cambiadas serán rechazadas. No se reiniciarán las antenas.')
    if input('Escribe SI para comenzar: ').strip() != 'SI':
        sys.exit('Cancelado.')
    # Shared known_hosts is used by OpenSSH; changed keys are not silently accepted.
    ssh_dir = Path.home() / '.ssh'
    ssh_dir.mkdir(mode=0o700, exist_ok=True)
    known_hosts = str(ssh_dir / 'known_hosts')
    results = []
    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(run_one, ipaddress.IPv4Address(i), username, password, server, known_hosts)
                   for i in range(int(start), int(end) + 1)]
        for future in as_completed(futures):
            ip, status, details = future.result()
            results.append((ip, status, details))
            log(f'[{ip}] {status}: {details[:170]}')
    filename = f'ubiquiti_ntp_resultados_{datetime.now():%Y%m%d_%H%M%S}.csv'
    with open(filename, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(['ip', 'estado', 'detalle'])
        writer.writerows(sorted(results, key=lambda r: int(ipaddress.IPv4Address(r[0]))))
    successes = sum(status == 'OK' for _, status, _ in results)
    print(f'\nFinalizado: {successes}/{len(results)} correctos. Reporte: {filename}')
    print('NOTA: sincronización puntual; no verifica servicio NTP periódico.')

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nInterrumpido por el usuario.')
        sys.exit(130)
