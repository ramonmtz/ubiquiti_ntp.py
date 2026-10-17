# Ubiquiti NTP Manager

Script interactivo en Python para habilitar y sincronizar NTP en múltiples equipos **Ubiquiti airOS** mediante SSH, con ejecución paralela y reporte CSV.

## Características

- Solicita **IP inicial y final**, usuario SSH, contraseña, servidor NTP y cantidad de hilos.
- Procesa hasta **1024 direcciones IP privadas** por ejecución.
- Utiliza `ThreadPoolExecutor` para trabajar en paralelo (**10 hilos** predeterminados; de 1 a 16).
- Se conecta con **OpenSSH y sshpass**; no necesita Paramiko.
- Acepta automáticamente claves SSH **nuevas**, pero **rechaza claves que hayan cambiado**.
- Habilita las opciones NTP de la configuración nativa de airOS y guarda los cambios.
- Ejecuta una sincronización puntual de la hora, sin reiniciar las antenas.
- Genera un archivo CSV con los resultados por IP.

## Requisitos

- Python 3.
- Cliente OpenSSH (`ssh`).
- `sshpass`.
- Acceso SSH a los equipos Ubiquiti y credenciales con permisos suficientes.
- Conectividad desde las antenas hacia el servidor NTP seleccionado.

### Instalación en Debian/Ubuntu

```bash
sudo apt update
sudo apt install -y python3 openssh-client sshpass
```

### Instalación en Termux (Android)

```bash
pkg update
pkg install python openssh sshpass
```

> La disponibilidad de `sshpass` puede depender de los repositorios habilitados en tu instalación de Termux.

## Uso

Coloca `ubiquiti_ntp.py` en tu directorio de trabajo y ejecútalo:

```bash
python3 ubiquiti_ntp.py
```

El programa solicita los datos de forma interactiva:

```text
IP inicial: 192.168.110.1
IP final: 192.168.110.254
Usuario SSH [ubnt]: ubnt
Contraseña SSH: ********
Servidor NTP [0.ubnt.pool.ntp.org]: 0.ubnt.pool.ntp.org
Hilos simultáneos [10]: 10
```

Antes de empezar, solicita confirmar la operación escribiendo `SI`.

## ¿Qué hace en cada antena?

1. Establece una conexión SSH.
2. Crea una copia de respaldo temporal de `/tmp/system.cfg` en `/tmp/system.cfg.ntp-backup`.
3. Habilita `ntpclient.status` y `ntpclient.1.status` en la configuración del equipo.
4. Guarda la configuración mediante `cfgmtd -w -p /etc/`.
5. Realiza una sincronización puntual usando `ntpd -n -q -p SERVIDOR_NTP`.
6. Consulta la fecha y hora y registra el resultado.

**Importante:** el script **no instala un demonio NTP adicional, no configura crontab y no reinicia las antenas**. La sincronización periódica posterior depende del cliente NTP nativo de airOS y del comportamiento de la versión de firmware instalada. En los equipos probados, la configuración se mantuvo después de reiniciar.

## Reporte de resultados

Al finalizar, genera un archivo similar a:

```text
ubiquiti_ntp_resultados_20261017_075200.csv
```

Columnas:

| ip | estado | detalle |
|---|---|---|
| 192.168.110.10 | OK | Operación completada |
| 192.168.110.11 | SSH_NO_DISPONIBLE | No se pudo establecer conexión |

Entre los estados posibles están `OK`, `CLAVE_SSH_CAMBIADA`, `AUTENTICACION_FALLIDA`, `SSH_NO_DISPONIBLE`, `TIMEOUT` y `ERROR`.

## Seguridad SSH

- Usa `~/.ssh/known_hosts` para registrar y comprobar la identidad de los equipos.
- `StrictHostKeyChecking=accept-new` acepta una clave de host desconocida en la primera conexión, pero rechaza cambios posteriores.
- Incluye compatibilidad con `ssh-rsa` para determinados equipos antiguos.
- La contraseña se solicita de forma oculta y se entrega a `sshpass` mediante un descriptor de archivo, en lugar de incluirla directamente como argumento visible en la línea de comandos.

**Advertencia:** aceptar automáticamente una clave SSH nueva no verifica por sí solo que el equipo sea legítimo. Comprueba las huellas digitales de los dispositivos cuando sea posible. No publiques credenciales, inventarios privados ni reportes con información sensible.

## Consideraciones y limitaciones

- Diseñado para equipos **Ubiquiti airOS** compatibles con los comandos y claves de configuración utilizados; no se garantiza compatibilidad con UniFi, airOS 8 u otras variantes sin validación previa.
- Es recomendable probar primero con **una sola antena** antes de ejecutar sobre un rango completo.
- El respaldo de `system.cfg` se guarda en `/tmp` del equipo: **no es una copia permanente** y puede perderse al reiniciar.
- El estado `OK` indica que el procedimiento del script terminó correctamente; **no garantiza por sí solo que el servicio NTP periódico siga sincronizando indefinidamente**. Conviene verificarlo después de un reinicio y transcurrido cierto tiempo.
- La conexión SSH tiene un tiempo de espera y los equipos inaccesibles se reportan sin detener el procesamiento del resto.

## Archivo principal

```text
ubiquiti_ntp.py
```

## Licencia

No se ha definido una licencia para este proyecto. Si deseas permitir su reutilización y distribución, agrega un archivo `LICENSE` con la licencia que elijas.
