#!/usr/bin/python3
""" Modulo per la pagina "Rete" di ELT_RTKBase.

    Gestisce Ethernet, WiFi e LTE tramite NetworkManager (nmcli):
      - stato delle interfacce
      - abilitazione e priorita' (metrica delle rotte) di ogni tipo di rete
      - scansione, connessione e rimozione delle reti WiFi
      - hotspot WiFi di emergenza quando la base non ha internet
      - modem LTE (APN, PIN, stato) tramite comandi AT sulla porta seriale del modem
      - controllo di internet su ogni interfaccia: una connessione "collegata ma senza internet"
        viene scavalcata e, se e' l'LTE, recuperata (riconnessione, riaggancio, reset del modem)
      - LTE su richiesta: radio del modem spenta finche' WiFi/Ethernet hanno internet
      - traffico LTE giornaliero/mensile con soglia di avviso
      - registro eventi di rete

    Usa solo la libreria standard: viene importato dal server web (root) e
    lanciato come servizio con --watch (rtkbase_network_watch.service).
"""

import os
import re
import sys
import glob
import json
import time
import socket
import select
import string
import hashlib
import copy
import secrets
import argparse
import threading
import subprocess
from contextlib import contextmanager

NMCLI = "nmcli"
TIMEOUT = 15

SETTINGS_FILE = "/usr/local/rtkbase/network_page.json"
RTKBASE_SETTINGS = "/usr/local/rtkbase/rtkbase/settings.conf"
GNSS_RULE = "/etc/udev/rules.d/92-elt-gnss-port.rules"
GNSS_LINK = "ttyGNSS"
SCAN_CACHE = "/run/rtkbase_network_scan.json"
PIN_STATE = "/run/rtkbase_network_pin.json"
ACTIVATION_STATE = "/run/rtkbase_network_activation.json"
OP_LOCK = "/run/rtkbase_network_op.lock"
AT_LOCK = "/run/rtkbase_network_at.lock"
EVENTS_FILE = "/usr/local/rtkbase/network_events.log"
TRAFFIC_FILE = "/usr/local/rtkbase/network_traffic.json"
HEALTH_FILE = "/run/rtkbase_network_health.json"
LTE_STATE_FILE = "/run/rtkbase_network_lte.json"
TEMPS_FILE = "/run/rtkbase_network_temps.json"
AUTO_REBOOT_FILE = "/usr/local/rtkbase/network_auto_reboot.json"

KINDS = ("ethernet", "wifi", "lte")
METRICS = (100, 200, 300)          # metrica per la 1a, 2a e 3a rete in ordine di priorita'
PROFILE_PREFIX = {"ethernet": "Rete-Ethernet-", "lte": "Rete-LTE-"}
PROFILE_PRIORITY = "100"           # i nostri profili vincono su quelli creati in automatico
HOTSPOT_CON = "Rete-Hotspot"
WIFI_DEVICE = "wlan0"

CHECK_DELAY = 30                   # secondi prima di verificare internet dopo una modifica
LTE_CHECK_DELAY = 60
HOTSPOT_RETRY = 300                # hotspot senza client per 5 minuti -> riprova le reti WiFi salvate
WATCH_PERIOD = 10
APPLY_PERIOD = 600
ACTIVATION_DELAY = 60               # modem senza interfaccia di rete da 60 s -> comando di attivazione
HEALTH_PERIOD = 30                 # ogni quanto si prova internet su ogni interfaccia
HEALTH_FAIL = 60                   # senza internet da 60 s -> la connessione viene scavalcata
HEALTH_RECOVER = 60                # di nuovo ok da 60 s -> torna alla sua priorita'
DEGRADE_METRIC = 1000              # metrica aggiunta a una connessione senza internet
LTE_RECOVERY = ((300, "reconnect"), (600, "reattach"), (900, "reset"))   # secondi senza internet -> azione
LTE_RECOVERY_RESTART = 1800        # finito il ciclo, ricomincia dopo 30 minuti
TRAFFIC_SAVE = 300
LTE_WAKE_AFTER = 60                # LTE su richiesta: altre connessioni senza internet da 60 s -> radio accesa
LTE_IDLE_AFTER = 300               # altre connessioni di nuovo ok da 5 minuti -> radio spenta
RECEIVER_TEMP_PERIOD = 300         # temperatura del ricevitore (HWSTATUSA) ogni 5 minuti: con 60 s (03-04/10)
                                   # l'UM982 restava muto per minuti ("serial inactive") e ALTAMURA si fermava
TEMP_LIMITS = {"pi": 75.0, "receiver": 80.0, "modem": 80.0}   # sopra: avviso; rientro sotto limite - TEMP_HYSTERESIS
                                                               # (Air780E: max 85 gradi)
TEMP_HYSTERESIS = 5.0
# chip WiFi bloccato (driver brcmfmac che inonda il kernel di errori SDIO, visto con il Pi surriscaldato)
WIFI_HANG_PATTERN = re.compile(r"brcmf_sdio_(htclk|readframes|bus_rxctl|txpkt|dpc).*error|brcmf_sdio_\w+: .*failed")
WIFI_HANG_LINES = 200              # ultimi messaggi del kernel esaminati
WIFI_HANG_MIN_ERRORS = 50          # errori del chip fra quei messaggi per dire "bloccato"
WIFI_HANG_DELAY = 120              # bloccato da 2 minuti -> riavvio (il driver bloccato non si scarica:
                                   # "modprobe -r brcmfmac" resta appeso per ore, visto il 28/09)
AUTO_REBOOT_MIN_INTERVAL = 6 * 3600  # al massimo un riavvio automatico ogni 6 ore
# chip WiFi bloccato "in silenzio" (visto il 30/09: pochi errori, poi il chip non risponde piu'):
# WiFi abilitato ma scollegato da WIFI_DEAD_AFTER e la scansione fallisce con -110 (timeout) per
# WIFI_DEAD_PROBES volte di fila. Un chip sano senza reti intorno (base in campo) scansiona senza errori.
WIFI_DEAD_AFTER = 300
WIFI_DEAD_PROBE_EVERY = 60
WIFI_DEAD_PROBES = 2
WIFI_DEAD_PROBES_BUSY = 3          # scansione "occupata" (-16) di fila: 01/10 WiFi giu' 1 h 30 min
EVENTS_MAX = 500
# 1.1.1.1 per ultimo: sulla rete WindTre/Very non risponde
INTERNET_TARGETS = (("8.8.8.8", 53), ("9.9.9.9", 443), ("1.1.1.1", 443))
PASSWORD_CHARS = "abcdefghjkmnpqrstuvwxyz23456789"
# trasmissioni verso l'esterno da far ripartire quando cambia la connessione che porta internet:
# altrimenti restano su un collegamento morto (es. WiFi sparito) finche' il TCP non va in timeout
OUTGOING_SERVICES = ["str2str_ntrip_%s.service" % x for x in "ABCDE"] + ["str2str_rtcm_client.service"]
# servizi della base da tenere accesi se abilitati: in ELT quando str2str_tcp si riavvia le trasmissioni
# NTRIP si fermano e non ripartono da sole (ALTAMURA spenta per ore il 28/09)
GUARDED_SERVICES = ["str2str_tcp.service"] + OUTGOING_SERVICES
GUARD_DELAY = 60                   # abilitato ma fermo da 60 s -> riavvio
GUARD_PERIOD = 60                  # controllo dei servizi ogni 60 s
SLOW_PERIOD = 60                   # segnale LTE, temperature, chip WiFi: ogni 60 s
SLOW_LAST = {"time": 0}
GUARD_LAST = {"time": 0}

# interfacce che non sono reti "utente" (es. ricevitore Septentrio via USB-Ethernet)
IGNORED_DEVICES = ("lo", "septentrio")
IGNORED_PREFIXES = ("docker", "veth", "p2p-dev", "tailscale")
LTE_DRIVERS = ("rndis_host", "cdc_ether", "cdc_ncm", "cdc_mbim", "qmi_wwan", "option")
MODEM_USB_NAMES = re.compile(r"air7|airm2m|eigencomm|luat|asr|quectel|simcom|mobile|lte|4g", re.IGNORECASE)
# produttori USB di modem LTE (EigenComm/AirM2M, Quectel, SIMCom, Huawei, ZTE, Fibocom, Sierra, Telit)
MODEM_VENDORS = ("19d1", "2c7c", "1e0e", "12d1", "19d2", "2cb7", "1199", "1bc7")
# modem di cui si usa solo la prima porta seriale (AT): sull'Air780E interrogare ttyACM1/2 blocca il modem e il Pi
FIRST_PORT_ONLY = ("19d1",)

DEFAULT_SETTINGS = {
    "enabled": {"ethernet": True, "wifi": True, "lte": True},
    "order": ["ethernet", "wifi", "lte"],
    "hotspot": {"enabled": True, "ssid": "", "password": "", "delay": 120},
    "lte": {"apn": "", "pin": "", "at_port": "", "activation_command": "", "monthly_limit_mb": 0,
            "on_demand": True, "phone": ""},       # phone: numero della SIM, inserito a mano (non e' sulla SIM)
    # note di accesso (credenziali di prova ecc.) mostrate nella pagina, da cancellare prima del campo
    "access_notes": "",
    # aggiornamenti online dal repository EVONETRTKBASE: canale "stabile" (ramo main) o "prova"
    "update": {"channel": "stabile"},
}


#### comandi di sistema ####

def run_cmd(args, timeout=TIMEOUT):
    """ Esegue un comando e ritorna (ok, stdout, stderr) """
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout, result.stderr.strip()
    except (OSError, subprocess.SubprocessError) as e:
        return False, "", str(e)


def run(args, timeout=TIMEOUT):
    """ Esegue un comando e ritorna lo stdout ("" in caso di errore) """
    ok, out, _ = run_cmd(args, timeout)
    return out if ok else ""


# Nel servizio watch lo stato di NetworkManager si legge una volta per giro (ogni nmcli costa
# 50-150 ms di CPU su un Pi Zero): cache di pochi secondi, svuotata a ogni modifica fatta con nm().
_CACHE = {"enabled": False, "data": {}}
CACHE_TTL = 5


def cached(key, fn):
    if not _CACHE["enabled"]:
        return fn()
    now = time.time()
    hit = _CACHE["data"].get(key)
    if hit and 0 <= now - hit[0] < CACHE_TTL:
        return copy.deepcopy(hit[1])
    value = fn()
    _CACHE["data"][key] = (now, value)
    return copy.deepcopy(value)


def invalidate_cache():
    _CACHE["data"].clear()


def nm(*args, timeout=TIMEOUT):
    """ nmcli con risultato (ok, messaggio di errore) """
    ok, out, err = run_cmd([NMCLI] + list(args), timeout)
    invalidate_cache()
    return ok, err or out.strip()


def split_terse(line):
    """ Divide una riga di "nmcli -t" sui ':' non preceduti da '\\' """
    fields = []
    current = ""
    escaped = False
    for char in line:
        if escaped:
            current += char
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append(current)
            current = ""
        else:
            current += char
    fields.append(current)
    return fields


def nm_get(field, connection):
    """ Valore di un campo di un profilo NetworkManager (uuid o nome) """
    out = run([NMCLI, "-s", "-g", field, "connection", "show", connection])
    return split_terse(out.rstrip("\n"))[0] if out else ""


@contextmanager
def file_lock(path, timeout=30):
    """ Lock tra processi (server web e servizio watch) con attesa massima """
    import fcntl
    handle = open(path, "a")
    deadline = time.time() + timeout
    try:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() > deadline:
                    raise TimeoutError("risorsa occupata, riprova tra poco")
                time.sleep(0.5)
        yield
    finally:
        handle.close()


def is_locked(path):
    """ True se un'altra operazione sta usando il lock """
    try:
        with file_lock(path, timeout=0):
            return False
    except TimeoutError:
        return True


#### impostazioni ####

def normalize_settings(saved):
    """ Impostazioni complete: valori salvati sopra i valori predefiniti, chiavi sconosciute ignorate """
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))
    for key, value in (saved or {}).items():
        if isinstance(value, dict) and isinstance(settings.get(key), dict):
            settings[key].update({k: v for k, v in value.items() if k in settings[key]})
        elif key in settings and not isinstance(settings[key], dict):
            settings[key] = value
    if not isinstance(settings["order"], list) or sorted(settings["order"]) != sorted(KINDS):
        settings["order"] = list(DEFAULT_SETTINGS["order"])
    return settings


def load_settings():
    try:
        with open(SETTINGS_FILE) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = {}
    settings = normalize_settings(saved)
    if not settings["hotspot"]["password"]:
        # password dell'hotspot diversa per ogni base, generata al primo avvio
        settings["hotspot"]["password"] = "".join(secrets.choice(PASSWORD_CHARS) for _ in range(10))
        try:
            save_settings(settings)
            log("generata la password dell'hotspot di emergenza")
        except OSError:
            pass
    return settings


def save_settings(settings):
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(settings, f, indent=2)
    os.chmod(tmp, 0o600)          # contiene PIN e password dell'hotspot
    os.replace(tmp, SETTINGS_FILE)


def metric_for(settings, kind):
    return METRICS[settings["order"].index(kind)]


#### stato ####

def get_driver(device):
    try:
        return os.path.basename(os.readlink("/sys/class/net/%s/device/driver" % device))
    except OSError:
        return None


def device_kind(device, nm_type, driver=None):
    """ Classifica un device come 'ethernet', 'wifi' o 'lte' (None se da ignorare) """
    if device in IGNORED_DEVICES or device.startswith(IGNORED_PREFIXES):
        return None
    if nm_type == "wifi":
        return "wifi"
    if nm_type == "gsm" or device == "mobile" or device.startswith("wwan") or driver in LTE_DRIVERS:
        return "lte"
    if nm_type == "ethernet":
        return "lte" if driver is None and device.startswith("usb") else "ethernet"
    return None


def list_devices():
    """ Lista di dict {device, kind, type, state, connection} delle interfacce gestite """
    return cached("devices", _list_devices)


def _list_devices():
    """ Lista di dict {device, kind, type, state, connection} delle interfacce gestite """
    devices = []
    output = run([NMCLI, "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"])
    for line in output.splitlines():
        fields = split_terse(line)
        if len(fields) < 4:
            continue
        device, nm_type, state, connection = fields[:4]
        kind = device_kind(device, nm_type, get_driver(device))
        if kind is None:
            continue
        devices.append({
            "device": device,
            "kind": kind,
            "type": nm_type,
            "state": state.split(" ")[0],
            "connection": connection if connection and connection != "--" else None,
        })
    return devices


def get_default_routes():
    """ Ritorna {device: metrica} delle rotte di default """
    routes = {}
    for line in run(["ip", "-4", "route", "show", "default"]).splitlines():
        parts = line.split()
        if "dev" not in parts:
            continue
        device = parts[parts.index("dev") + 1]
        metric = int(parts[parts.index("metric") + 1]) if "metric" in parts else 0
        if device not in routes or metric < routes[device]:
            routes[device] = metric
    return routes


def get_device_details(device):
    """ Indirizzi IPv4, gateway, DNS e MAC di un device """
    details = {"ipv4": [], "gateway": None, "dns": [], "hwaddr": None}
    output = run([NMCLI, "-t", "-f", "IP4.ADDRESS,IP4.GATEWAY,IP4.DNS,GENERAL.HWADDR", "device", "show", device])
    for line in output.splitlines():
        key, _, value = line.partition(":")
        value = value.replace("\\:", ":")
        if not value or value == "--":
            continue
        if key.startswith("IP4.ADDRESS"):
            details["ipv4"].append(value)
        elif key == "IP4.GATEWAY":
            details["gateway"] = value
        elif key.startswith("IP4.DNS"):
            details["dns"].append(value)
        elif key == "GENERAL.HWADDR":
            details["hwaddr"] = value
    return details


def get_wifi_active():
    """ SSID e segnale (%) della rete WiFi attiva, se c'e' """
    output = run([NMCLI, "-t", "-f", "ACTIVE,SSID,SIGNAL", "device", "wifi", "list", "--rescan", "no"])
    for line in output.splitlines():
        fields = split_terse(line)
        if len(fields) >= 3 and fields[0] == "yes":
            return {"ssid": fields[1], "signal": int(fields[2]) if fields[2].isdigit() else None}
    return None


def get_radio_wifi():
    """ True se la radio WiFi e' accesa """
    return cached("radio_wifi", _get_radio_wifi)


def _get_radio_wifi():
    return run([NMCLI, "radio", "wifi"]).strip() == "enabled"


_internet_cache = {"time": 0, "value": False}


def internet_ok(max_age=0):
    """ True se almeno un server noto e' raggiungibile (non dipende dal controllo di NetworkManager) """
    if max_age and time.time() - _internet_cache["time"] < max_age:
        return _internet_cache["value"]
    value = False
    for host, port in INTERNET_TARGETS:
        try:
            socket.create_connection((host, port), timeout=3).close()
            value = True
            break
        except OSError:
            pass
    _internet_cache.update(time=time.time(), value=value)
    return value


def internet_via(device):
    """ True se internet e' raggiungibile uscendo da una interfaccia precisa (SO_BINDTODEVICE, serve root) """
    for host, port in INTERNET_TARGETS:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        try:
            sock.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_BINDTODEVICE", 25), device.encode())
            sock.connect((host, port))
            return True
        except OSError:
            pass
        finally:
            sock.close()
    return False


def read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def connectivity_rank():
    """ 2 = internet, 1 = almeno una rotta di default, 0 = niente """
    if internet_ok():
        return 2
    return 1 if get_default_routes() else 0


def get_status():
    """ Stato completo della rete per la pagina "Rete" """
    settings = load_settings()
    routes = get_default_routes()
    internet_device = min(routes, key=routes.get) if routes else None

    health = read_json(HEALTH_FILE, {})
    interfaces = []
    for info in list_devices():
        info["metric"] = routes.get(info["device"])
        info["internet"] = info["device"] == internet_device
        if info["device"] in health:
            info["health"] = {k: health[info["device"]][k] for k in ("ok", "degraded")}
        if info["state"] == "connected":
            info.update(get_device_details(info["device"]))
            if info["kind"] == "wifi" and info["connection"] != HOTSPOT_CON:
                info["wifi"] = get_wifi_active()
        interfaces.append(info)

    interfaces.sort(key=lambda i: (KINDS.index(i["kind"]), i["device"]))

    return {
        "interfaces": interfaces,
        "internet_device": internet_device,
        "internet": internet_ok(max_age=10),
        "wifi_radio": get_radio_wifi(),
        "lte_serial_only": modem_without_network(),
        "receiver": receiver_port_status(),
        "traffic": traffic_summary(settings),
        "lte_radio": read_json(LTE_STATE_FILE, {}),
        "temps": read_json(TEMPS_FILE, {}),
        "sim": sim_info(settings),
        "access": access_info(settings, interfaces),
        "enabled": settings["enabled"],
        "order": settings["order"],
        "hotspot": {
            "active": hotspot_active(),
            "enabled": settings["hotspot"]["enabled"],
            "ssid": hotspot_ssid(settings),
            "delay": settings["hotspot"]["delay"],
        },
    }


#### come raggiungere la base ####

_access_cache = {"time": 0, "tailscale": None}


def tailscale_info():
    """ IP e nome Tailscale della base (letti al massimo ogni 60 s), o None se Tailscale non c'e' """
    if time.time() - _access_cache["time"] < 60:
        return _access_cache["tailscale"]
    info = None
    out = run(["tailscale", "status", "--json"], timeout=8)
    if out:
        try:
            data = json.loads(out)
            me = data.get("Self") or {}
            ips = [ip for ip in me.get("TailscaleIPs") or [] if "." in ip]
            account = (data.get("User") or {}).get(str(me.get("UserID")), {}).get("LoginName")
            info = {"ip": ips[0] if ips else None,
                    "name": (me.get("DNSName") or "").rstrip(".") or None,
                    "online": data.get("BackendState") == "Running" and bool(me.get("Online", True)),
                    "account": account}
        except ValueError:
            info = None
    _access_cache.update(time=time.time(), tailscale=info)
    return info


def access_info(settings, interfaces):
    """ Indirizzi per raggiungere il pannello: in locale, da fuori (Tailscale), dall'hotspot """
    port = re.search(r"^web_port\s*=\s*'?(\d+)", read_sys(RTKBASE_SETTINGS), re.MULTILINE)
    port = port.group(1) if port else "80"
    local = []
    for i in interfaces:
        if i["kind"] == "lte" or i.get("connection") == HOTSPOT_CON or i["state"] != "connected":
            continue                                    # l'IP verso il modem LTE non serve da fuori
        for addr in i.get("ipv4") or []:
            local.append({"kind": i["kind"], "device": i["device"], "ip": addr.split("/")[0]})
    return {"hostname": socket.gethostname(), "port": port, "local": local,
            "tailscale": tailscale_info(), "hotspot_ip": "10.42.0.1",
            "hotspot_ssid": hotspot_ssid(settings), "hotspot_password": settings["hotspot"]["password"],
            "notes": settings.get("access_notes") or "",
            "web_default_password": web_password_is_default()}


def web_password_is_default():
    """ True se la password del pannello e' ancora quella di fabbrica di RTKBase ("admin") """
    match = re.search(r"^web_password_hash\s*=\s*'?([^'\s]+)", read_sys(RTKBASE_SETTINGS), re.MULTILINE)
    if not match:
        return None
    try:
        from werkzeug.security import check_password_hash
    except ImportError:
        return None
    try:
        return check_password_hash(match.group(1), "admin")
    except (ValueError, TypeError):
        return None


#### aggiornamenti online (repository EVONETRTKBASE) ####
# Stesso meccanismo di ELT_RTKBase (Description.json + install.sh su GitHub, poi exec_update.sh), ma dal
# nostro repository: quello ufficiale installerebbe ELT senza la pagina Rete. In piu': canale stabile/prova
# scelto sulla base, impronta SHA-256 dell'install.sh verificata prima di eseguirlo, copia di sicurezza.

UPDATE_REPO = "EVONETRTK/EVONETRTKBASE"
UPDATE_CHANNELS = {"stabile": "main", "prova": "prova"}
VERSION_FILE = "/usr/local/rtkbase/version.txt"     # scritto dall'installer (es. 19801 = ELT 1.9.8, revisione 01)
UPDATE_STATE_FILE = "/usr/local/rtkbase/network_update.json"
UPDATE_CHECK_PERIOD = 12 * 3600                    # controllo automatico (solo avviso, mai installazione)
UPDATE_MAX_SIZE = 50 * 1024 * 1024
BACKUP_DIR = "/usr/local/rtkbase/backup"
BACKUP_KEEP = 3


def version_label(version):
    """ 19801 -> "1.9.8-01", 198 -> "1.9.8" (versioni ELT ufficiali), 0 -> "sconosciuta" """
    text = str(version or "")
    if not text.isdigit() or int(text) == 0:
        return "sconosciuta"
    if len(text) >= 5:
        return "%s.%s.%s-%s" % (text[0], text[1], text[2], text[3:])
    return ".".join(text)


def installed_version():
    value = read_sys(VERSION_FILE)
    return int(value) if value.isdigit() else 0


def update_raw_url(settings, name):
    branch = UPDATE_CHANNELS.get(settings["update"]["channel"], "main")
    return "https://raw.githubusercontent.com/%s/refs/heads/%s/%s" % (UPDATE_REPO, branch, name)


def http_get(url, timeout=30, limit=1024 * 1024):
    """ Scarica un URL (contenuto in bytes). Solleva OSError/ValueError in caso di errore. """
    import urllib.request
    request = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "EVONETRTKBASE"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("file troppo grande")
    return data


def fetch_release(settings):
    """ Description.json del canale scelto: {version (int), new_release, comment, sha256} """
    data = json.loads(http_get(update_raw_url(settings, "Description.json")).decode("utf-8"))
    version = str(data.get("version", ""))
    if not version.isdigit():
        raise ValueError("Description.json senza numero di versione")
    data["version"] = int(version)
    return data


def check_update(settings=None):
    """ Confronta la versione installata con quella del canale scelto e salva l'esito """
    settings = settings or load_settings()
    current = installed_version()
    result = {"time": int(time.time()), "channel": settings["update"]["channel"],
              "current": current, "current_label": version_label(current)}
    try:
        release = fetch_release(settings)
        result.update(latest=release["version"], latest_label=version_label(release["version"]),
                      new_release=release.get("new_release") or version_label(release["version"]),
                      comment=release.get("comment") or "", available=release["version"] > current)
    except (OSError, ValueError) as e:
        result.update(error="Impossibile leggere la versione disponibile: %s" % e, available=False)
    try:
        write_json(UPDATE_STATE_FILE, result)
    except OSError:
        pass
    return result


def update_status():
    settings = load_settings()
    state = read_json(UPDATE_STATE_FILE, {})
    current = installed_version()
    state.update(current=current, current_label=version_label(current), channel=settings["update"]["channel"],
                 channels=list(UPDATE_CHANNELS), repo=UPDATE_REPO)
    if "latest" in state:
        state["available"] = state["latest"] > current
    return state


def set_update_channel(channel):
    if channel not in UPDATE_CHANNELS:
        raise ValueError("canale sconosciuto")
    settings = load_settings()
    settings["update"]["channel"] = channel
    save_settings(settings)
    try:
        os.remove(UPDATE_STATE_FILE)               # l'esito del controllo era dell'altro canale
    except OSError:
        pass


def download_update(path):
    """ Scarica l'install.sh del canale scelto in `path` dopo averne verificato l'impronta SHA-256
        indicata in Description.json. Ritorna None se tutto va bene, altrimenti il messaggio di errore. """
    settings = load_settings()
    try:
        release = fetch_release(settings)
    except (OSError, ValueError) as e:
        return "Impossibile leggere Description.json: %s" % e
    expected = str(release.get("sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        return "Description.json non contiene l'impronta SHA-256 di install.sh: aggiornamento annullato."
    if release["version"] <= installed_version():
        return "Nessuna versione piu' recente sul canale %s." % settings["update"]["channel"]
    try:
        data = http_get(update_raw_url(settings, "install.sh"), timeout=300, limit=UPDATE_MAX_SIZE)
    except (OSError, ValueError) as e:
        return "Download di install.sh non riuscito: %s" % e
    if hashlib.sha256(data).hexdigest() != expected:
        return "install.sh scaricato non corrisponde all'impronta attesa (download incompleto?): aggiornamento annullato."
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    log("scaricato l'aggiornamento %s (canale %s), impronta verificata"
        % (version_label(release["version"]), settings["update"]["channel"]))
    return None


def backup_before_update():
    """ Copia di sicurezza (pannello, impostazioni, versione) prima di un aggiornamento; tiene le ultime
        BACKUP_KEEP. Per tornare indietro: tar -xzf <file> -C / e riavviare. Ritorna il file o None. """
    import tarfile
    paths = [os.path.dirname(os.path.abspath(__file__)), RTKBASE_SETTINGS, SETTINGS_FILE, VERSION_FILE]
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        name = os.path.join(BACKUP_DIR, "prima_di_aggiornare_%s_v%s.tar.gz"
                            % (time.strftime("%Y%m%d-%H%M%S"), version_label(installed_version())))
        with tarfile.open(name, "w:gz") as tar:
            for p in paths:
                if os.path.exists(p):
                    tar.add(p, filter=lambda info: None if "__pycache__" in info.name else info)
        os.chmod(name, 0o600)                       # contiene password
        old = sorted(glob.glob(os.path.join(BACKUP_DIR, "prima_di_aggiornare_*.tar.gz")))
        for f in old[:-BACKUP_KEEP]:
            os.remove(f)
        log("copia di sicurezza prima dell'aggiornamento: %s" % name)
        return name
    except (OSError, tarfile.TarError) as e:
        log("copia di sicurezza prima dell'aggiornamento non riuscita: %s" % e)
        return None


def check_update_periodically(now, settings):
    """ Nel servizio watch: ogni UPDATE_CHECK_PERIOD (con internet) controlla se c'e' una versione nuova
        e lo scrive nel registro eventi una volta sola. Non installa mai niente da solo. """
    state = read_json(UPDATE_STATE_FILE, {})
    if now - state.get("time", 0) < UPDATE_CHECK_PERIOD or not internet_ok(max_age=60):
        return
    result = check_update(settings)
    if result.get("available") and state.get("latest") != result.get("latest"):
        log("disponibile l'aggiornamento EVONETRTKBASE %s (canale %s): installalo da Settings, Check update"
            % (result["latest_label"], result["channel"]))


#### scheda di accesso stampabile ####

def rtkbase_conf(key):
    """ Valore di una chiave di settings.conf di RTKBase (senza apici), o "" """
    match = re.search(r"^%s\s*=\s*'?([^'\n]*)'?\s*$" % re.escape(key), read_sys(RTKBASE_SETTINGS), re.MULTILINE)
    return match.group(1).strip() if match else ""


def web_password_ok(given):
    """ True se `given` e' la password del pannello (stesso controllo del login di RTKBase) """
    match = re.search(r"^web_password_hash\s*=\s*'?([^'\s]+)", read_sys(RTKBASE_SETTINGS), re.MULTILINE)
    if not match or not given:
        return False
    try:
        from werkzeug.security import check_password_hash
        return check_password_hash(match.group(1), given)
    except (ImportError, ValueError, TypeError):
        return False


def login_users():
    """ Utenti con cui si entra in SSH (uid >= 1000 con una shell vera) """
    import pwd
    return [u.pw_name for u in pwd.getpwall()
            if 1000 <= u.pw_uid < 60000 and not u.pw_shell.endswith(("nologin", "false"))]


def rpi_connect_status():
    """ "collegato", "non registrato", "spento" oppure None se Raspberry Pi Connect non e' installato.
        E' un servizio dell'utente: si interroga come quell'utente. """
    import pwd
    if not os.path.exists("/usr/bin/rpi-connect"):
        return None
    for uid in sorted(os.listdir("/run/user")) if os.path.isdir("/run/user") else []:
        try:
            user = pwd.getpwuid(int(uid)).pw_name
        except (KeyError, ValueError):
            continue
        out = run(["runuser", "-u", user, "--", "env", "XDG_RUNTIME_DIR=/run/user/" + uid,
                   "rpi-connect", "status"], timeout=10)
        if "Signed in: yes" in out:
            return "collegato"
        if "Signed in: no" in out:
            return "non registrato"
    return "spento"


def usb_vendor_present(vendor):
    for path in glob.glob("/sys/bus/usb/devices/*/idVendor"):
        if read_sys(path) == vendor:
            return True
    return False


def access_card():
    """ Dati della scheda di accesso stampabile, senza password (quelle con access_secrets) """
    settings = load_settings()
    status = get_status()
    access = dict(status["access"])
    access.pop("hotspot_password", None)
    access.pop("notes", None)
    if access.get("tailscale"):                  # l'account Tailscale solo con le password
        access["tailscale"] = {k: v for k, v in access["tailscale"].items() if k != "account"}
    position = rtkbase_conf("position")
    try:
        fixed = any(abs(float(x)) > 0 for x in position.split())
    except ValueError:
        fixed = False
    return {
        "access": access,
        "elt_version": rtkbase_conf("elt_version"),
        "rtkbase_version": rtkbase_conf("version"),
        "board": read_sys("/proc/device-tree/model").strip("\x00 \n"),
        "receiver": rtkbase_conf("receiver").replace("_", " "),
        "receiver_port": rtkbase_conf("com_port"),
        "modem": "Air780E (LTE)" if usb_vendor_present("19d1") else None,
        "apn": settings["lte"]["apn"],
        "sim": sim_info(settings),
        "caster": {"host": rtkbase_conf("svr_addr_a"), "port": rtkbase_conf("svr_port_a") or "2101",
                   "mountpoint": rtkbase_conf("mnt_name_a"),
                   "active": run(["systemctl", "is-active", "str2str_ntrip_A"]).strip() == "active"},
        "position": position if fixed else None,
        "ssh_users": login_users(),
        "rpi_connect": rpi_connect_status(),
        "internet_device": status["internet_device"],
        "satellites": status["temps"].get("satellites"),
        "hotspot_enabled": settings["hotspot"]["enabled"],
        "hotspot_delay": settings["hotspot"]["delay"],
    }


def access_secrets():
    """ Password leggibili sulla base per la scheda di accesso. Quelle del pannello e degli utenti
        sono salvate cifrate (non si possono leggere): nella scheda restano da scrivere a mano. """
    settings = load_settings()
    wifi = []
    for profile in wifi_profiles():
        psk = run([NMCLI, "-s", "-g", "802-11-wireless-security.psk", "connection", "show", profile["uuid"]])
        wifi.append({"ssid": profile["ssid"], "password": psk.strip()})
    return {
        "hotspot_password": settings["hotspot"]["password"],
        "wifi": wifi,
        "caster_password": rtkbase_conf("svr_pwd_a"),
        "caster_user": rtkbase_conf("svr_user_a"),
        "sim_pin": settings["lte"].get("pin") or "",
        "notes": settings.get("access_notes") or "",
        "web_default_password": web_password_is_default(),
        "tailscale_account": (tailscale_info() or {}).get("account") or "",
    }


#### abilitazione e priorita' ####

def connection_names():
    return set(run([NMCLI, "-g", "NAME", "connection", "show"]).splitlines())


def metric_args(metric):
    """ Priorita' di rotte e DNS insieme: con un LTE senza dati i suoi DNS non devono bloccare il WiFi """
    metric = str(metric)
    return ["ipv4.route-metric", metric, "ipv6.route-metric", metric,
            "ipv4.dns-priority", metric, "ipv6.dns-priority", metric]


def set_metric(connection, metric):
    """ Imposta la metrica di un profilo solo se diversa (evita scritture inutili) """
    if nm_get("ipv4.route-metric", connection) == str(metric) and nm_get("ipv4.dns-priority", connection) == str(metric):
        return False
    nm("connection", "modify", connection, *metric_args(metric))
    return True


def ensure_profile(kind, device, metric, enabled, nm_type="ethernet", apn=""):
    """ Crea/aggiorna il nostro profilo per un device Ethernet o LTE.
        Modem in modalita' RNDIS/ECM = profilo ethernet (DHCP); modem gestito da ModemManager = profilo gsm con APN.
        Alla creazione copia l'eventuale IP statico del profilo attivo, per non perderlo. """
    name = PROFILE_PREFIX[kind] + device
    if name not in connection_names():
        args = ["connection", "add", "type", "gsm" if nm_type == "gsm" else "ethernet", "con-name", name,
                "ifname", device, "connection.autoconnect-priority", PROFILE_PRIORITY]
        if nm_type == "gsm":
            args += ["gsm.apn", apn]
        active = next((d["connection"] for d in list_devices() if d["device"] == device and d["connection"]), None)
        if kind == "ethernet" and active and nm_get("ipv4.method", active) == "manual":
            args += ["ipv4.method", "manual", "ipv4.addresses", nm_get("ipv4.addresses", active)]
            for field in ("ipv4.gateway", "ipv4.dns"):
                value = nm_get(field, active)
                if value:
                    args += [field, value]
        nm(*args)
    wanted = "yes" if enabled else "no"
    if nm_get("connection.autoconnect", name) != wanted:       # scrive il profilo solo se cambia (SD)
        nm("connection", "modify", name, "connection.autoconnect", wanted)
    set_metric(name, metric)
    return name


def wifi_profiles():
    """ Profili WiFi client salvati: [{name, uuid, ssid, active}] (escluso l'hotspot) """
    profiles = []
    output = run([NMCLI, "-t", "-f", "NAME,UUID,TYPE,ACTIVE", "connection", "show"])
    for line in output.splitlines():
        fields = split_terse(line)
        if len(fields) < 4 or fields[2] != "802-11-wireless" or fields[0] == HOTSPOT_CON:
            continue
        if nm_get("802-11-wireless.mode", fields[1]) == "ap":
            continue
        profiles.append({
            "name": fields[0],
            "uuid": fields[1],
            "ssid": nm_get("802-11-wireless.ssid", fields[1]),
            "active": fields[3] == "yes",
        })
    return profiles


def apply_interfaces(settings, report=None):
    """ Applica abilitazioni e priorita' a tutte le interfacce presenti """
    report = report or (lambda msg: None)
    routes = get_default_routes()
    hotspot_on = hotspot_active()

    # WiFi: radio accesa/spenta (se l'hotspot e' attivo ci pensa il watch) e metrica sui profili salvati
    wifi_on = settings["enabled"]["wifi"]
    if not hotspot_on and get_radio_wifi() != wifi_on:
        nm("radio", "wifi", "on" if wifi_on else "off")
        report("WiFi " + ("acceso" if wifi_on else "spento"))
    wifi_metric = metric_for(settings, "wifi")
    for profile in wifi_profiles():
        set_metric(profile["uuid"], wifi_metric)

    for dev in list_devices():
        kind, device = dev["kind"], dev["device"]
        metric = metric_for(settings, kind)
        enabled = settings["enabled"][kind]
        if kind == "wifi":
            if dev["state"] == "connected" and routes.get(device) not in (None, metric) and not hotspot_on \
                    and device not in DEGRADED:
                nm("device", "reapply", device)
            continue

        name = ensure_profile(kind, device, metric, enabled, dev["type"], settings["lte"]["apn"])
        if enabled:
            nm("device", "set", device, "autoconnect", "yes")
            if dev["state"] == "disconnected":      # "unavailable" = senza cavo/segnale: ci pensa NetworkManager
                ok, _ = nm("--wait", "30", "connection", "up", name, timeout=40)
                report("%s (%s): %s" % (kind.upper(), device, "connessa" if ok else "non connessa (cavo/SIM assente?)"))
            elif dev["state"] != "connected" or not dev["connection"]:
                continue
            elif dev["connection"] != name:
                # connesso con un altro profilo: gli diamo la stessa metrica senza staccarlo
                set_metric(dev["connection"], metric)
                if routes.get(device) not in (None, metric) and device not in DEGRADED:
                    nm("device", "reapply", device)
            elif routes.get(device) not in (None, metric) and device not in DEGRADED:
                nm("device", "reapply", device)
        else:
            nm("device", "set", device, "autoconnect", "no")
            if dev["state"] == "connected":
                nm("device", "disconnect", device)
                report("%s (%s): disattivata" % (kind.upper(), device))


def change_interfaces(enabled, order, report):
    """ Operazione: salva abilitazioni/priorita' con ripristino automatico se si perde internet """
    old = load_settings()
    new = json.loads(json.dumps(old))
    new["enabled"] = {k: bool(enabled.get(k)) for k in KINDS}
    new["order"] = list(order)
    before = connectivity_rank()

    save_settings(new)
    report("Applico le nuove impostazioni...")
    apply_interfaces(new, report)
    report("Verifico la connessione tra %d secondi..." % CHECK_DELAY)
    time.sleep(CHECK_DELAY)

    if connectivity_rank() >= before:
        report("Fatto: connessione verificata.")
        return True
    report("Connessione persa: ripristino le impostazioni precedenti.")
    save_settings(old)
    apply_interfaces(old, report)
    return False


#### WiFi ####

def wifi_scan(rescan=True):
    """ Reti WiFi visibili [{ssid, signal, security, in_use}] ordinate per segnale.
        Con l'hotspot attivo non si puo' scansionare: ritorna l'ultima scansione salvata. """
    if hotspot_active():
        try:
            with open(SCAN_CACHE) as f:
                return json.load(f)
        except (OSError, ValueError):
            return []
    output = run([NMCLI, "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                  "--rescan", "yes" if rescan else "auto"], timeout=40)
    networks = {}
    for line in output.splitlines():
        fields = split_terse(line)
        if len(fields) < 4 or not fields[1]:
            continue
        signal = int(fields[2]) if fields[2].isdigit() else 0
        ssid = fields[1]
        if ssid not in networks or signal > networks[ssid]["signal"]:
            networks[ssid] = {"ssid": ssid, "signal": signal,
                              "security": fields[3] if fields[3] != "--" else "",
                              "in_use": fields[0] == "*"}
    result = sorted(networks.values(), key=lambda n: -n["signal"])
    try:
        with open(SCAN_CACHE, "w") as f:
            json.dump(result, f)
    except OSError:
        pass
    return result


def wifi_key_mgmt(security):
    """ key-mgmt NetworkManager dalla colonna SECURITY della scansione """
    if "WPA3" in security and "WPA2" not in security and "WPA1" not in security:
        return "sae"
    return "wpa-psk"


def active_on(device):
    """ Profilo attivo su un device (uuid) o None """
    output = run([NMCLI, "-t", "-f", "UUID,DEVICE", "connection", "show", "--active"])
    for line in output.splitlines():
        fields = split_terse(line)
        if len(fields) >= 2 and fields[1] == device:
            return fields[0]
    return None


def wifi_connect(ssid, password, hidden, security, report):
    """ Operazione: connette a una rete WiFi; se fallisce o si perde internet torna alla rete precedente """
    settings = load_settings()
    if not settings["enabled"]["wifi"]:
        settings["enabled"]["wifi"] = True
        save_settings(settings)
    before = connectivity_rank()
    previous = active_on(WIFI_DEVICE)
    existing = next((p for p in wifi_profiles() if p["ssid"] == ssid), None)
    old_psk = nm_get("802-11-wireless-security.psk", existing["uuid"]) if existing else ""

    sec_args = []
    if password:
        sec_args = ["wifi-sec.key-mgmt", wifi_key_mgmt(security or ""), "wifi-sec.psk", password]
    metric = str(metric_for(settings, "wifi"))

    if not get_radio_wifi():
        nm("radio", "wifi", "on")
        time.sleep(3)

    if existing:
        uuid = existing["uuid"]
        if sec_args:
            nm("connection", "modify", uuid, *sec_args)
        nm("connection", "modify", uuid, "connection.autoconnect", "yes")
    else:
        args = ["connection", "add", "type", "wifi", "con-name", ssid, "ifname", WIFI_DEVICE, "ssid", ssid,
                "connection.autoconnect", "yes"] + metric_args(metric)
        if hidden:
            args += ["802-11-wireless.hidden", "yes"]
        ok, msg = nm(*(args + sec_args))
        match = re.search(r"\(([0-9a-f-]{36})\)", msg)
        if not ok or not match:
            report("Errore nella creazione della rete: " + msg)
            return False
        uuid = match.group(1)

    report("Connessione a \"%s\" in corso..." % ssid)
    ok, msg = nm("--wait", "45", "connection", "up", uuid, "ifname", WIFI_DEVICE, timeout=60)
    if ok:
        report("Connessa. Verifico internet tra %d secondi..." % CHECK_DELAY)
        time.sleep(CHECK_DELAY)
        if connectivity_rank() >= max(before, 1):
            report("Fatto: base connessa a \"%s\"." % ssid)
            return True
        report("La rete \"%s\" non porta internet." % ssid)
    else:
        report("Connessione fallita (password errata o rete non raggiungibile).")

    # ripristino
    if existing:
        if sec_args and old_psk:
            nm("connection", "modify", uuid, "wifi-sec.psk", old_psk)
    else:
        nm("connection", "delete", uuid)
    if previous and previous != uuid:
        report("Torno alla connessione precedente...")
        nm("--wait", "45", "connection", "up", previous, timeout=60)
    return False


def wifi_forget(uuid):
    if uuid not in [p["uuid"] for p in wifi_profiles()]:
        return False, "rete non trovata"
    return nm("connection", "delete", uuid)


#### hotspot di emergenza ####

def hotspot_ssid(settings):
    if settings["hotspot"]["ssid"]:
        return settings["hotspot"]["ssid"]
    try:
        with open("/sys/class/net/%s/address" % WIFI_DEVICE) as f:
            suffix = f.read().strip().replace(":", "")[-4:].upper()
    except OSError:
        suffix = "0000"
    return "ELT-RTKBase-" + suffix


def hotspot_active():
    return cached("hotspot_active", _hotspot_active)


def _hotspot_active():
    # ricavato dallo stato delle interfacce (gia' letto), senza un'altra chiamata a nmcli
    return any(d["device"] == WIFI_DEVICE and d["connection"] == HOTSPOT_CON for d in list_devices())


def hotspot_profile(settings):
    """ (Ri)crea il profilo dell'hotspot: WPA2, IP 10.42.0.1, DHCP per i client """
    if HOTSPOT_CON in connection_names():
        nm("connection", "delete", HOTSPOT_CON)
    return nm("connection", "add", "type", "wifi", "con-name", HOTSPOT_CON, "ifname", WIFI_DEVICE,
              "ssid", hotspot_ssid(settings), "connection.autoconnect", "no",
              "802-11-wireless.mode", "ap", "802-11-wireless.band", "bg",
              "ipv4.method", "shared", "ipv6.method", "disabled",
              "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.proto", "rsn",
              "wifi-sec.pairwise", "ccmp", "wifi-sec.group", "ccmp",
              "wifi-sec.psk", settings["hotspot"]["password"])


def hotspot_start(settings):
    wifi_scan()                        # salva le reti visibili: con l'hotspot attivo non si puo' scansionare
    nm("radio", "wifi", "on")
    if HOTSPOT_CON not in connection_names():
        hotspot_profile(settings)
    ok, msg = nm("--wait", "30", "connection", "up", HOTSPOT_CON, timeout=40)
    log("hotspot %s avviato: %s" % (hotspot_ssid(settings), "ok" if ok else msg))
    return ok


def hotspot_stop(settings):
    nm("connection", "down", HOTSPOT_CON)
    if not settings["enabled"]["wifi"]:
        nm("radio", "wifi", "off")
    log("hotspot fermato")


def hotspot_clients():
    """ Numero di dispositivi collegati all'hotspot """
    ok, out, _ = run_cmd(["iw", "dev", WIFI_DEVICE, "station", "dump"])
    if ok:
        return out.count("Station ")
    out = run(["ip", "neigh", "show", "dev", WIFI_DEVICE])
    return len([l for l in out.splitlines() if "REACHABLE" in l or "DELAY" in l or "STALE" in l])


def change_hotspot(enabled, ssid, password, delay, report):
    """ Operazione: salva le impostazioni dell'hotspot e ricrea il profilo """
    settings = load_settings()
    settings["hotspot"].update(enabled=enabled, ssid=ssid, password=password, delay=delay)
    save_settings(settings)
    was_active = hotspot_active()
    ok, msg = hotspot_profile(settings)
    if not ok:
        report("Errore nella creazione dell'hotspot: " + msg)
        return False
    if was_active and enabled:
        report("Riavvio l'hotspot con le nuove impostazioni...")
        nm("--wait", "30", "connection", "up", HOTSPOT_CON, timeout=40)
    elif was_active:
        hotspot_stop(settings)
    report("Impostazioni hotspot salvate.")
    return True


#### modem LTE (comandi AT) ####

def usb_device_dir(sys_path):
    """ Risale da un device di /sys al dispositivo USB (la cartella con idVendor) """
    path = os.path.realpath(sys_path)
    while path and os.path.dirname(path) != path:      # si ferma alla radice ("/" o "C:\")
        if os.path.exists(os.path.join(path, "idVendor")):
            return path
        path = os.path.dirname(path)
    return None


def read_sys(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def rtkbase_com_port():
    """ Porta del ricevitore scelta in RTKBase/ELT (senza /dev/), "" se non impostata """
    match = re.search(r"^com_port\s*=\s*'?([^'\n]*)", read_sys(RTKBASE_SETTINGS), re.MULTILINE)
    return match.group(1).strip() if match else ""


def tty_usb_device(tty):
    return usb_device_dir("/sys/class/tty/%s/device" % tty)


def lte_usb_devices():
    """ Dispositivi USB che hanno un'interfaccia di rete LTE """
    devices = set()
    for dev in list_devices():
        if dev["kind"] == "lte":
            usb = usb_device_dir("/sys/class/net/%s/device" % dev["device"])
            if usb:
                devices.add(usb)
    return devices


def is_modem_usb(usb, lte_usb):
    if usb in lte_usb or read_sys(os.path.join(usb, "idVendor")) in MODEM_VENDORS:
        return True
    names = read_sys(os.path.join(usb, "manufacturer")) + " " + read_sys(os.path.join(usb, "product"))
    return bool(MODEM_USB_NAMES.search(names))


def receiver_usb_devices():
    """ Dispositivi USB del ricevitore GNSS (com_port di RTKBase e /dev/ttyGNSS): non vanno mai interrogati con comandi AT """
    ports = ["/dev/ttyGNSS", "/dev/ttyGNSS_CTRL"]
    if rtkbase_com_port():
        ports.append("/dev/" + rtkbase_com_port())
    devices = set()
    for port in ports:
        if os.path.exists(port):
            usb = usb_device_dir("/sys/class/tty/%s/device" % os.path.basename(os.path.realpath(port)))
            if usb:
                devices.add(usb)
    return devices


def udev_properties(tty):
    """ Proprieta' udev di una porta seriale (ID_SERIAL, ID_USB_INTERFACE_NUM, ...) """
    props = {}
    for line in run(["udevadm", "info", "-q", "property", "-n", "/dev/" + tty]).splitlines():
        key, _, value = line.partition("=")
        props[key] = value
    return props


def pin_receiver_port():
    """ Crea la regola udev che da' al ricevitore il nome fisso /dev/ttyGNSS.
        Parte dalla porta rilevata da ELT (com_port, es. ttyUSB3), qualunque sia il tipo di ricevitore,
        e la identifica con numero di serie USB + interfaccia, che non cambiano tra un avvio e l'altro. """
    port = rtkbase_com_port()
    if not re.fullmatch(r"tty(USB|ACM)[0-9]+", port) or not os.path.exists("/dev/" + port):
        return None                                  # gia' ttyGNSS, UART (serial0/ttyAMA) o porta assente
    usb = tty_usb_device(port)
    if not usb or is_modem_usb(usb, lte_usb_devices()):
        return None                                  # com_port punta al modem: non la fisso
    if os.path.exists("/dev/" + GNSS_LINK) and os.path.realpath("/dev/" + GNSS_LINK) != os.path.realpath("/dev/" + port):
        return None                                  # ttyGNSS esiste gia' per un altro dispositivo
    props = udev_properties(port)
    serial, interface = props.get("ID_SERIAL", ""), props.get("ID_USB_INTERFACE_NUM", "")
    if not re.fullmatch(r"[\w.+-]+", serial) or not re.fullmatch(r"[0-9a-fA-F]{0,2}", interface):
        return None
    rule = 'SUBSYSTEM=="tty", ENV{ID_SERIAL}=="%s"' % serial
    if interface:
        rule += ', ENV{ID_USB_INTERFACE_NUM}=="%s"' % interface
    rule += ', SYMLINK+="%s", GROUP="dialout"' % GNSS_LINK
    content = "# Creato dalla pagina Rete di ELT_RTKBase: nome fisso del ricevitore GNSS (%s)\n%s" % (port, rule)
    if read_sys(GNSS_RULE) == content:
        return GNSS_LINK
    with open(GNSS_RULE, "w") as f:
        f.write(content + "\n")
    run(["udevadm", "control", "--reload-rules"])
    run(["udevadm", "trigger", "--action=add", "/sys/class/tty/" + port])
    log("ricevitore %s (%s) fissato come /dev/%s" % (port, serial, GNSS_LINK))
    return GNSS_LINK


def receiver_port_status():
    """ Stato della porta del ricevitore per la pagina: numerata (puo' cambiare) o fissa """
    port = rtkbase_com_port()
    numbered = bool(re.fullmatch(r"tty(USB|ACM)[0-9]+", port))
    link_ready = (numbered and os.path.exists("/dev/" + GNSS_LINK)
                  and os.path.realpath("/dev/" + GNSS_LINK) == os.path.realpath("/dev/" + port))
    return {"com_port": port, "numbered": numbered, "link_ready": link_ready}


def modem_port_candidates():
    """ Porte seriali che appartengono al modem: stesso dispositivo USB dell'interfaccia LTE
        oppure dispositivi USB con nome da modem (Air780, Luat, ...) """
    lte_usb = lte_usb_devices()
    receiver_usb = receiver_usb_devices() - lte_usb
    candidates = []
    used_first = set()
    try:
        ttys = sorted((t for t in os.listdir("/sys/class/tty") if t.startswith(("ttyUSB", "ttyACM"))),
                      key=lambda t: (t[:6], int(t[6:]) if t[6:].isdigit() else 0))
    except OSError:
        ttys = []
    for tty in ttys:
        usb = tty_usb_device(tty)
        if not usb or usb in receiver_usb or not is_modem_usb(usb, lte_usb):
            continue
        if read_sys(os.path.join(usb, "idVendor")) in FIRST_PORT_ONLY:
            if usb in used_first:
                continue
            used_first.add(usb)
        candidates.append("/dev/" + tty)
    return candidates


def at_command(port, command, timeout=5):
    """ Invia un comando AT e ritorna (ok, righe di risposta) """
    import termios
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        attrs = termios.tcgetattr(fd)
        attrs[0] = 0                                               # iflag
        attrs[1] = 0                                               # oflag
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL    # cflag
        attrs[3] = 0                                               # lflag
        attrs[4] = attrs[5] = termios.B115200
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        termios.tcflush(fd, termios.TCIOFLUSH)
        os.write(fd, (command + "\r").encode())

        buffer = b""
        deadline = time.time() + timeout
        while time.time() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.2)
            if not ready:
                continue
            try:
                buffer += os.read(fd, 1024)
            except BlockingIOError:
                continue
            lines = [l.strip() for l in buffer.decode(errors="replace").splitlines() if l.strip()]
            if lines and (lines[-1] in ("OK", "ERROR") or lines[-1].startswith(("+CME ERROR", "+CMS ERROR"))):
                lines = [l for l in lines if l != command]           # toglie l'eco
                return lines[-1] == "OK", lines[:-1] if lines[-1] == "OK" else lines
        return False, ["nessuna risposta dal modem"]
    finally:
        os.close(fd)


_modem_port = {"port": None}


def find_at_port(settings):
    """ Porta AT del modem: quella impostata a mano, oppure la prima candidata che risponde "OK" """
    if settings["lte"]["at_port"]:
        return settings["lte"]["at_port"]
    cached = _modem_port["port"]
    if cached and os.path.exists(cached):
        return cached
    for port in modem_port_candidates():
        try:
            ok, _ = at_command(port, "AT", timeout=1)
        except OSError:
            continue
        if ok:
            _modem_port["port"] = port
            return port
    return None


def modem_at(settings, command, timeout=5):
    """ Comando AT con lock tra processi. Ritorna (ok, righe) """
    with file_lock(AT_LOCK, timeout=15):
        port = find_at_port(settings)
        if not port:
            return False, ["porta AT del modem non trovata"]
        return at_command(port, command, timeout)


def at_value(lines, prefix):
    """ Valore dopo "+XXX: " nella prima riga che inizia con il prefisso """
    for line in lines:
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return None


REGISTRATION = {"0": "non registrato", "1": "registrato (rete di casa)", "2": "ricerca rete...",
                "3": "registrazione rifiutata", "4": "sconosciuto", "5": "registrato (roaming)"}
ACCESS_TECH = {"0": "2G", "1": "2G", "2": "3G", "3": "2G (EDGE)", "4": "3G (HSDPA)", "5": "3G (HSUPA)",
               "6": "3G (HSPA)", "7": "4G", "8": "2G", "9": "4G (NB-IoT)", "10": "4G", "11": "5G", "12": "5G",
               "13": "5G", "14": "4G/5G"}
# gestori italiani (MCC-MNC) quando la rete non trasmette il nome
OPERATORS_IT = {"22201": "TIM", "22202": "Elsacom", "22206": "Vodafone", "22208": "Fastweb", "22210": "Vodafone",
                "22233": "Poste Mobile", "22234": "BT Italia", "22235": "Lycamobile", "22237": "WindTre",
                "22238": "Linkem", "22239": "SMS Italia", "22243": "TIM", "22248": "TIM", "22250": "Iliad",
                "22253": "CoopVoce", "22254": "Plintron", "22256": "Spusu", "22288": "WindTre", "22299": "WindTre"}


def operator_name(value):
    """ Nome del gestore da +COPS (nome o codice MCC-MNC) """
    value = (value or "").strip().strip('"')
    if value.isdigit():
        return OPERATORS_IT.get(value, value)
    return value or None


#### SIM: ICCID (letto dal modem e memorizzato) e numero di telefono (inserito a mano) ####

SIM_FILE = "/usr/local/rtkbase/network_sim.json"
SIM_CHECK_PERIOD = 3600            # ICCID riletto ogni ora con l'LTE acceso (SIM cambiata?)
SIM_LAST = {"time": 0}
PHONE_RE = re.compile(r"\+?[0-9][0-9 ]{5,19}")


def parse_iccid(lines):
    """ ICCID dalla risposta del modem: "+ICCID: 8939...F" (Air780E), "+CCID:", "+QCCID:" o solo cifre """
    for line in lines:
        value = line
        for prefix in ("+ICCID:", "+CCID:", "+QCCID:"):
            if line.startswith(prefix):
                value = line[len(prefix):]
        digits = re.sub(r"[^0-9]", "", value.strip().strip('"').rstrip("Ff"))
        if 18 <= len(digits) <= 22:
            return digits
    return None


def remember_iccid(iccid, now=None):
    """ Memorizza l'ICCID letto. Se e' diverso da quello salvato la SIM e' stata cambiata: evento nel
        registro e avviso nella pagina finche' non viene confermato; il numero di telefono salvato era
        della SIM vecchia, quindi viene tolto (e ricordato nell'avviso) per inserire quello nuovo """
    if not iccid:
        return
    now = int(now or time.time())
    data = read_json(SIM_FILE, {})
    if data.get("iccid") and data["iccid"] != iccid:
        settings = load_settings()
        old_phone = settings["lte"]["phone"]
        log("SIM CAMBIATA: ICCID %s (prima %s%s). Controllare numero di telefono, APN e PIN nella pagina Rete"
            % (iccid, data["iccid"], ", numero " + old_phone if old_phone else ""))
        data["changed"] = {"time": now, "old_iccid": data["iccid"], "new_iccid": iccid, "old_phone": old_phone}
        if old_phone:
            settings["lte"]["phone"] = ""
            save_settings(settings)
    elif not data.get("iccid"):
        log("SIM letta: ICCID %s" % iccid)
    data.update(iccid=iccid, time=now)
    try:
        write_json(SIM_FILE, data)
    except OSError:
        pass


def parse_imei(lines):
    """ IMEI del modem da AT+CGSN: "868909078545780" (Air780E) o "+CGSN: "868..."" -> 15 cifre """
    for line in lines:
        digits = re.sub(r"[^0-9]", "", line.split(":", 1)[-1])
        if len(digits) == 15:
            return digits
    return None


def remember_imei(imei, now=None):
    """ Memorizza l'IMEI del modem; se cambia (modem sostituito) lo scrive nel registro eventi """
    if not imei:
        return
    data = read_json(SIM_FILE, {})
    if data.get("imei") == imei:
        return
    if data.get("imei"):
        log("MODEM CAMBIATO: IMEI %s (prima %s)" % (imei, data["imei"]))
    else:
        log("modem letto: IMEI %s" % imei)
    data.update(imei=imei, imei_time=int(now or time.time()))
    try:
        write_json(SIM_FILE, data)
    except OSError:
        pass


def acknowledge_sim_change():
    data = read_json(SIM_FILE, {})
    if data.pop("changed", None):
        write_json(SIM_FILE, data)


def read_iccid(settings):
    for command in ("AT+ICCID", "AT+CCID"):
        ok, lines = modem_at(settings, command)
        iccid = parse_iccid(lines) if ok else None
        if iccid:
            return iccid
    return None


def check_sim(settings, now):
    """ Nel servizio watch: rilegge l'ICCID all'avvio (la SIM si cambia a base spenta) e poi ogni
        SIM_CHECK_PERIOD, anche con l'LTE su richiesta spento (l'ICCID si legge con la radio spenta) """
    if not settings["enabled"]["lte"] or now - SIM_LAST["time"] < SIM_CHECK_PERIOD:
        return
    SIM_LAST["time"] = now
    try:
        remember_iccid(read_iccid(settings), now)
        ok, lines = modem_at(settings, "AT+CGSN")
        remember_imei(parse_imei(lines) if ok else None, now)
    except (OSError, TimeoutError):
        pass


def sim_info(settings=None):
    settings = settings or load_settings()
    data = read_json(SIM_FILE, {})
    return {"iccid": data.get("iccid"), "iccid_read_at": data.get("time"), "phone": settings["lte"]["phone"],
            "imei": data.get("imei"), "changed": data.get("changed")}


def set_sim_phone(phone):
    phone = " ".join(str(phone or "").split())
    if phone and not PHONE_RE.fullmatch(phone):
        raise ValueError("numero di telefono non valido (cifre, spazi, + iniziale)")
    settings = load_settings()
    settings["lte"]["phone"] = phone
    save_settings(settings)
    return phone


def lte_status():
    """ Stato del modem letto con comandi AT, piu' le impostazioni LTE salvate """
    status = modem_status()
    status["activation_command"] = load_settings()["lte"]["activation_command"]
    status["serial_only"] = modem_without_network()
    status["sim_info"] = sim_info()
    return status


def modem_status():
    settings = load_settings()
    try:
        with file_lock(AT_LOCK, timeout=15):
            port = find_at_port(settings)
            if not port:
                return {"found": False, "apn_saved": settings["lte"]["apn"], "pin_saved": bool(settings["lte"]["pin"])}

            def ask(command):
                ok, lines = at_command(port, command)
                return lines if ok else []

            status = {"found": True, "port": port,
                      "apn_saved": settings["lte"]["apn"], "pin_saved": bool(settings["lte"]["pin"])}
            model = [at_value([l], "+CGMM:") or l for l in ask("AT+CGMM")]      # "Air780E" o +CGMM: "Air780E"
            status["model"] = model[0].strip('"') if model else None
            status["imei"] = parse_imei(ask("AT+CGSN"))
            remember_imei(status["imei"])

            cfun = at_value(ask("AT+CFUN?"), "+CFUN:")
            status["radio"] = None if cfun is None else cfun.split(",")[0].strip() != "0"

            ok, lines = at_command(port, "AT+CPIN?")
            cpin = at_value(lines, "+CPIN:")
            if ok and cpin:
                status["sim"] = cpin
                iccid = parse_iccid(ask("AT+ICCID")) or parse_iccid(ask("AT+CCID"))
                remember_iccid(iccid)
            elif status["radio"] is False:
                status["sim"] = "non leggibile con la radio spenta"
            else:
                status["sim"] = "SIM assente o non leggibile"

            csq = at_value(ask("AT+CSQ"), "+CSQ:")
            if csq and csq.split(",")[0].isdigit() and int(csq.split(",")[0]) != 99:
                rssi = int(csq.split(",")[0])
                status["signal_dbm"] = -113 + 2 * rssi
                status["signal"] = min(100, round(rssi * 100 / 31))

            ask("AT+COPS=3,2")                             # codice MCC-MNC (il nome non tutti i modem lo danno)
            cops = at_value(ask("AT+COPS?"), "+COPS:")
            if cops:
                parts = cops.split(",")
                status["operator"] = operator_name(parts[2]) if len(parts) > 2 else None
                status["technology"] = ACCESS_TECH.get(parts[3].strip()) if len(parts) > 3 else None

            reg = at_value(ask("AT+CEREG?"), "+CEREG:") or at_value(ask("AT+CREG?"), "+CREG:")
            if reg and len(reg.split(",")) > 1:
                status["registration"] = REGISTRATION.get(reg.split(",")[1], reg)

            for line in ask("AT+CGDCONT?"):
                if line.startswith("+CGDCONT: 1,"):
                    parts = line.split(",")
                    status["apn"] = parts[2].strip('"') if len(parts) > 2 else None
            return status
    except (OSError, TimeoutError) as e:
        return {"found": False, "error": str(e), "apn_saved": settings["lte"]["apn"], "pin_saved": bool(settings["lte"]["pin"])}


def pin_hash(pin):
    return hashlib.sha256(pin.encode()).hexdigest()


def lte_pin_check(settings, force=False):
    """ Se la SIM chiede il PIN lo inserisce UNA sola volta per valore di PIN
        (con un PIN errato non riprova, per non bloccare la SIM con il PUK) """
    pin = settings["lte"]["pin"]
    if not pin:
        return None
    try:
        with open(PIN_STATE) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    if not force and state.get("hash") == pin_hash(pin) and not state.get("ok"):
        return "PIN errato: correggilo nella pagina Rete"
    try:
        ok, lines = modem_at(settings, "AT+CPIN?")
        if not ok or "SIM PIN" not in (at_value(lines, "+CPIN:") or ""):
            return None
        ok, lines = modem_at(settings, 'AT+CPIN="%s"' % pin)
    except (OSError, TimeoutError):
        return None
    with open(PIN_STATE, "w") as f:
        json.dump({"hash": pin_hash(pin), "ok": ok}, f)
    log("PIN SIM inserito: %s" % ("ok" if ok else "ERRATO"))
    return None if ok else "PIN errato: correggilo nella pagina Rete"


def lte_reattach(settings, apn, report):
    """ Imposta l'APN nel modem e fa riagganciare la rete.
        Air780E (AirM2M/EigenComm): AT+CPNETAPN, che salva l'APN, disattiva la scelta automatica (AUTOAPN,
        che altrimenti ignora AT+CGDCONT) e riavvia da solo la sessione dati usata dalla scheda di rete.
        Altri modem: AT+CGDCONT e riaggancio con AT+CFUN. """
    ok, _ = modem_at(settings, 'AT+CPNETAPN=2,"%s","","",0' % apn, timeout=20)
    if ok:
        report("APN impostato e salvato nel modem. Riaggancio della rete in corso...")
        return True
    ok, lines = modem_at(settings, 'AT+CGDCONT=1,"IP","%s"' % apn)
    if not ok:
        report("Il modem ha rifiutato l'APN: " + " ".join(lines))
        return False
    report("APN impostato. Riaggancio la rete mobile...")
    modem_at(settings, "AT+CFUN=0", timeout=15)
    time.sleep(3)
    modem_at(settings, "AT+CFUN=1", timeout=15)
    return True


def lte_gsm_profiles():
    """ Nostri profili gsm (modem gestiti da ModemManager) """
    return [PROFILE_PREFIX["lte"] + d["device"] for d in list_devices() if d["kind"] == "lte" and d["type"] == "gsm"]


def lte_apply_apn(settings, apn, report):
    """ Imposta l'APN: nel profilo gsm se il modem e' gestito da ModemManager, altrimenti con i comandi AT """
    profiles = lte_gsm_profiles()
    if not profiles:
        return lte_reattach(settings, apn, report)
    for name in profiles:
        nm("connection", "modify", name, "gsm.apn", apn)
        report("APN impostato. Riconnetto %s..." % name)
        nm("--wait", "60", "connection", "up", name, timeout=70)
    return True


def modem_without_network():
    """ True se c'e' un modem sulle porte seriali ma nessuna interfaccia LTE (modem non in modalita' RNDIS/ECM) """
    if any(d["kind"] == "lte" for d in list_devices()):
        return False
    return bool(modem_port_candidates())


def lte_activate(settings, force=False):
    """ Invia (una volta per avvio) il comando che mette il modem in modalita' rete RNDIS/ECM """
    command = settings["lte"]["activation_command"]
    if not command:
        return None
    try:
        with open(ACTIVATION_STATE) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    if not force and state.get("command") == command:
        return None
    try:
        ok, lines = modem_at(settings, command, timeout=15)
    except (OSError, TimeoutError) as e:
        ok, lines = False, [str(e)]
    with open(ACTIVATION_STATE, "w") as f:
        json.dump({"command": command, "ok": ok}, f)
    log("comando di attivazione modem %s: %s %s" % (command, "ok" if ok else "ERRORE", " ".join(lines)))
    return ok


def change_lte(apn, pin, report, activation_command=None):
    """ Operazione: salva APN/PIN, li invia al modem, ripristina l'APN precedente se si perde internet """
    settings = load_settings()
    old_apn = settings["lte"]["apn"]
    before = connectivity_rank()
    pin_changed = pin is not None and pin != settings["lte"]["pin"]
    activation_changed = activation_command is not None and activation_command != settings["lte"]["activation_command"]
    settings["lte"]["apn"] = apn
    if activation_command is not None:
        settings["lte"]["activation_command"] = activation_command
    if pin is not None:
        settings["lte"]["pin"] = pin
    save_settings(settings)

    if activation_changed and activation_command and modem_without_network():
        report("Invio al modem il comando di attivazione %s..." % activation_command)
        if not lte_activate(settings, force=True):
            report("Il modem ha rifiutato il comando di attivazione.")
            return False
        report("Comando accettato: il modem dovrebbe ricomparire come interfaccia di rete entro un minuto.")

    if pin_changed and pin:
        report("Invio il PIN alla SIM (se richiesto)...")
        error = lte_pin_check(settings, force=True)
        if error:
            report(error)
            return False

    if apn == old_apn:
        report("Impostazioni LTE salvate.")
        return True
    if not apn:
        report("APN rimosso dalle impostazioni (il modem mantiene quello attuale).")
        return True
    if not lte_apply_apn(settings, apn, report):
        return False

    report("Verifico la connessione tra %d secondi..." % LTE_CHECK_DELAY)
    time.sleep(LTE_CHECK_DELAY)
    if connectivity_rank() >= before:
        report("Fatto: APN \"%s\" attivo." % apn)
        return True
    report("Connessione persa: ripristino l'APN precedente.")
    settings["lte"]["apn"] = old_apn
    save_settings(settings)
    if old_apn:
        lte_apply_apn(settings, old_apn, report)
    return False


def lte_manual_at(command):
    """ Comando AT libero dalla pagina (solo una riga che inizia con AT) """
    command = command.strip()
    if not re.fullmatch(r"AT[\x20-\x7E]{0,200}", command, re.IGNORECASE):
        return False, ["comando non valido: deve iniziare con AT"]
    try:
        return modem_at(load_settings(), command, timeout=15)
    except (OSError, TimeoutError) as e:
        return False, [str(e)]


#### operazioni in background (server web) ####

_operation = {"id": 0, "title": None, "running": False, "result": None, "messages": []}
_operation_lock = threading.Lock()


def start_operation(title, func, *args):
    """ Lancia un'operazione lunga in background: la pagina ne legge l'avanzamento con get_operation() """
    with _operation_lock:
        if _operation["running"]:
            return False
        _operation.update(id=_operation["id"] + 1, title=title, running=True, result=None, messages=[])

    def report(message):
        _operation["messages"].append({"time": time.strftime("%H:%M:%S"), "text": message})

    def target():
        result = "error"
        try:
            with file_lock(OP_LOCK, timeout=60):
                result = "ok" if func(*args, report=report) else "error"
        except Exception as e:
            report("Errore: %s" % e)
        finally:
            _operation.update(running=False, result=result)
            last = _operation["messages"][-1]["text"] if _operation["messages"] else ""
            log("pagina Rete, %s: %s" % (title, last or result))

    threading.Thread(target=target, daemon=True).start()
    return True


def get_operation():
    return {k: (list(v) if isinstance(v, list) else v) for k, v in _operation.items()}


#### servizio watch ####

def log(message):
    """ Messaggio nel journal del servizio e nel registro eventi mostrato dalla pagina """
    print(message, flush=True)
    try:
        with open(EVENTS_FILE, "a") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), message))
        if os.path.getsize(EVENTS_FILE) > EVENTS_MAX * 200:
            with open(EVENTS_FILE) as f:
                lines = f.readlines()[-EVENTS_MAX:]
            with open(EVENTS_FILE, "w") as f:
                f.writelines(lines)
    except OSError:
        pass


def read_events(limit=100):
    """ Ultimi eventi, dal piu' recente """
    try:
        with open(EVENTS_FILE) as f:
            lines = f.readlines()[-limit:]
    except OSError:
        return []
    events = []
    for line in reversed(lines):
        stamp, _, text = line.rstrip("\n").partition(" ")
        clock, _, text = text.partition(" ")
        events.append({"time": stamp + " " + clock, "text": text})
    return events


#### controllo di internet per interfaccia e recupero LTE ####

DEGRADED = set()      # interfacce scavalcate perche' collegate ma senza internet


def set_runtime_metric(device, metric):
    """ Cambia la metrica solo sulla connessione attiva (non tocca il profilo salvato) """
    nm("device", "modify", device, *metric_args(metric))


def check_health(settings, health, now):
    """ Prova internet su ogni interfaccia collegata. Una connessione senza internet da HEALTH_FAIL secondi
        viene messa in fondo alla priorita' (cosi' il traffico passa dalla successiva); quando torna ok
        riprende la sua priorita'. L'LTE senza internet viene anche recuperato. """
    routes = get_default_routes()
    seen = set()
    for dev in list_devices():
        device = dev["device"]
        if dev["state"] != "connected" or device not in routes or dev["connection"] == HOTSPOT_CON:
            continue
        if dev["kind"] == "lte" and LTE_RADIO["on"] is False:
            continue                                    # radio spenta di proposito (su richiesta o disabilitato)
        seen.add(device)
        ok = internet_via(device)
        h = health.setdefault(device, {"kind": dev["kind"], "ok": ok, "since": now, "degraded": False, "recovery": 0})
        if ok != h["ok"]:
            h.update(ok=ok, since=now)
        base = metric_for(settings, dev["kind"])
        if not ok and not h["degraded"] and now - h["since"] >= HEALTH_FAIL:
            set_runtime_metric(device, base + DEGRADE_METRIC)
            h["degraded"] = True
            log("%s (%s) collegata ma senza internet: uso la connessione successiva" % (dev["kind"].upper(), device))
        elif not ok and h["degraded"] and routes[device] < base + DEGRADE_METRIC:
            set_runtime_metric(device, base + DEGRADE_METRIC)    # riconnessa: NetworkManager ha rimesso la metrica
        elif ok and h["degraded"] and now - h["since"] >= HEALTH_RECOVER:
            set_runtime_metric(device, base)
            h.update(degraded=False, recovery=0)
            log("%s (%s) di nuovo con internet: torna alla sua priorita'" % (dev["kind"].upper(), device))
        if dev["kind"] == "lte" and not ok and settings["enabled"]["lte"]:
            lte_recover(settings, device, h, now)
    for device in list(health):
        if device not in seen:
            del health[device]
    DEGRADED.clear()
    DEGRADED.update(d for d, h in health.items() if h["degraded"])
    try:
        write_json(HEALTH_FILE, health)
    except OSError:
        pass


LTE_RADIO = {"on": None, "bad_since": None, "good_since": None, "signal": None, "dbm": None, "tech": None,
             "operator": None, "cops_format": False}


def lte_manage(settings, health, now):
    """ Radio del modem accesa o spenta:
        - LTE disabilitato -> spenta
        - LTE su richiesta -> spenta finche' un'altra connessione ha internet, accesa se nessuna ce l'ha
          da LTE_WAKE_AFTER secondi; rispenta quando le altre sono di nuovo ok da LTE_IDLE_AFTER secondi
        - altrimenti -> accesa """
    if not any(d["kind"] == "lte" for d in list_devices()) and not modem_port_candidates():
        return
    st = LTE_RADIO
    if st["on"] is None:                                # stato reale della radio (all'avvio del servizio)
        try:
            ok, lines = modem_at(settings, "AT+CFUN?")
            value = at_value(lines, "+CFUN:") if ok else None
            st["on"] = None if value is None else value.split(",")[0].strip() != "0"
        except (OSError, TimeoutError):
            st["on"] = None
        if st["on"] is None:
            return                                      # modem non raggiungibile: riprovo al giro dopo

    if not settings["enabled"]["lte"]:
        want = False
    elif not settings["lte"].get("on_demand") or settings["order"][0] == "lte":
        want = True                                     # sempre accesa, o LTE e' la connessione principale
    else:
        other_ok = any(h["ok"] for h in health.values() if h["kind"] != "lte")
        if other_ok:
            st["bad_since"] = None
            st["good_since"] = st["good_since"] or now
            want = st["on"] and now - st["good_since"] < LTE_IDLE_AFTER
        else:
            st["good_since"] = None
            st["bad_since"] = st["bad_since"] or now
            # nessun'altra connessione proprio collegata (es. WiFi sparito): radio subito;
            # collegata ma senza internet: si aspetta LTE_WAKE_AFTER (un router che si riavvia non accende il modem)
            other_connected = any(h["kind"] != "lte" for h in health.values())
            want = st["on"] or not other_connected or now - st["bad_since"] >= LTE_WAKE_AFTER

    if want == st["on"]:
        write_lte_state(settings)
        return
    try:
        ok, _ = modem_at(settings, "AT+CFUN=1" if want else "AT+CFUN=0", timeout=15)
    except (OSError, TimeoutError):
        ok = False
    if ok:
        st["on"] = want
        if want and settings["lte"].get("on_demand") and settings["enabled"]["lte"]:
            log("nessuna altra connessione ha internet: accendo la radio LTE")
        elif not want and settings["enabled"]["lte"]:
            log("WiFi/Ethernet con internet: LTE in attesa (radio spenta)")
        else:
            log("radio LTE %s" % ("accesa" if want else "spenta"))
    write_lte_state(settings)


def lte_read_signal(settings):
    """ Segnale LTE per le barre della pagina (letto dal servizio, non a ogni aggiornamento della pagina) """
    st = LTE_RADIO
    st.update(signal=None, dbm=None, tech=None, operator=None)
    if not st["on"]:
        return
    try:
        ok, lines = modem_at(settings, "AT+CSQ")
        csq = at_value(lines, "+CSQ:") if ok else None
        if csq and csq.split(",")[0].strip().isdigit():
            rssi = int(csq.split(",")[0])
            if rssi != 99:
                st.update(signal=min(100, round(rssi * 100 / 31)), dbm=-113 + 2 * rssi)
        if not st["cops_format"]:
            st["cops_format"] = modem_at(settings, "AT+COPS=3,2")[0]     # codice MCC-MNC -> nome con OPERATORS_IT
        ok, lines = modem_at(settings, "AT+COPS?")
        cops = at_value(lines, "+COPS:") if ok else None
        parts = cops.split(",") if cops else []
        if len(parts) > 2:
            st["operator"] = operator_name(parts[2])
        if len(parts) > 3:
            st["tech"] = ACCESS_TECH.get(parts[3].strip())
    except (OSError, TimeoutError):
        pass


def write_lte_state(settings):
    idle = settings["enabled"]["lte"] and bool(settings["lte"].get("on_demand")) and LTE_RADIO["on"] is False
    try:
        write_json(LTE_STATE_FILE, {"on": LTE_RADIO["on"], "idle": idle,
                                    "on_demand": bool(settings["lte"].get("on_demand")),
                                    "signal": LTE_RADIO["signal"], "dbm": LTE_RADIO["dbm"],
                                    "tech": LTE_RADIO["tech"], "operator": LTE_RADIO["operator"]})
    except OSError:
        pass


#### temperature ####

def pi_temperature():
    """ Temperatura della CPU del Raspberry Pi in gradi, o None """
    value = read_sys("/sys/class/thermal/thermal_zone0/temp")
    return round(int(value) / 1000.0, 1) if value.isdigit() else None


def unicore_tcp_port():
    """ Porta TCP del flusso del ricevitore se e' un Unicore, altrimenti None """
    conf = read_sys(RTKBASE_SETTINGS)
    if not re.search(r"^receiver\s*=\s*'?Unicore", conf, re.MULTILINE):
        return None
    port = re.search(r"^tcp_port\s*=\s*'?(\d+)", conf, re.MULTILINE)
    return int(port.group(1)) if port else 5015


def receiver_session(command=None, tag=None, listen=0.0):
    """ Sul flusso del ricevitore (str2str -b 1 inoltra i comandi al ricevitore: nessuna interruzione):
        ascolta per `listen` secondi contando i byte, poi manda `command` e aspetta la riga che inizia
        con `tag`. Ritorna (byte ascoltati, riga) oppure (None, None) se il servizio non risponde. """
    port = unicore_tcp_port()
    if port is None:
        return None, None
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    except OSError:
        return None, None
    sock.settimeout(0.3)
    heard, data = 0, b""
    try:
        end = time.time() + listen
        while time.time() < end:
            try:
                heard += len(sock.recv(8192))
            except socket.timeout:
                pass
        if command:
            sock.sendall(command + b"\r\n")
            end = time.time() + 5
            while time.time() < end and not re.search(re.escape(tag) + rb"[^\r\n]*\n", data):
                try:
                    data += sock.recv(8192)
                except socket.timeout:
                    pass
    except OSError:
        return None, None
    finally:
        sock.close()
    match = re.search(re.escape(tag) + rb"[^\r\n]*", data) if command else None
    return heard, (match.group(0) if match else None)


def receiver_temperature():
    """ Temperatura di un ricevitore Unicore (log HWSTATUSA, campo temp1 in millesimi di grado), o None """
    _, line = receiver_session(b"HWSTATUSA", b"#HWSTATUSA")
    match = re.search(rb"^#HWSTATUSA[^;]*;(-?\d+),", line or b"")
    return round(int(match.group(1)) / 1000.0, 1) if match else None


def receiver_satellites():
    """ {"tracked", "used", "solution"} dal log BESTNAVA del ricevitore Unicore (risposta singola), o None.
        Campi dopo ';': stato, tipo soluzione, ..., 14o satelliti tracciati, 15o satelliti usati. """
    _, line = receiver_session(b"BESTNAVA", b"#BESTNAVA")
    if not line or b";" not in line:
        return None
    fields = line.split(b";", 1)[1].decode(errors="replace").split(",")
    if len(fields) < 15 or not fields[13].isdigit() or not fields[14].isdigit():
        return None
    return {"tracked": int(fields[13]), "used": int(fields[14]), "solution": fields[1]}


RECEIVER_OUTPUT = {"silent_since": None, "reset_at": None, "restart_at": None}
RECEIVER_LISTEN = 3                # nessun byte dal ricevitore in 3 s = muto (normalmente ~800 byte/s)
RECEIVER_RESET_AFTER = 180         # muto da 3 minuti -> reset del ricevitore (comando RESET di Unicore): il 06/10
                                   # ha sbloccato l'UM982 6 volte su 6, dati ripresi ~2 minuti dopo
RECEIVER_RESET_MIN_INTERVAL = 1200 # al massimo un reset ogni 20 minuti
RECEIVER_RESTART_DELAY = 30        # dopo il reset: riavvio del servizio, che rimanda la configurazione da base
RECEIVER_RESET_FILE = "/usr/local/rtkbase/network_receiver_reset.json"


def describe_satellites(sats):
    if not sats:
        return "satelliti non disponibili"
    return "%d satelliti tracciati, %d usati (%s)" % (sats["tracked"], sats["used"], sats["solution"])


def check_receiver_output(now, temps, read_satellites):
    """ Ricevitore acceso ma senza dati (03-05/10: muto per minuti, poi riparte da solo, mentre ai
        comandi risponde): registra quando succede e quanti satelliti vede, per capire se e' l'antenna """
    st = RECEIVER_OUTPUT
    if st["restart_at"] is not None and now >= st["restart_at"]:
        # dopo il RESET il ricevitore riparte con la configurazione salvata: il riavvio del servizio gli
        # rimanda quella da base (UnicoreSetBasePos.sh) e fa ripartire anche le trasmissioni NTRIP
        st["restart_at"] = None
        run(["systemctl", "restart", "str2str_tcp.service"], timeout=60)
        log("ricevitore GNSS: servizio str2str_tcp riavviato dopo il reset")
        return
    heard, _ = receiver_session(listen=RECEIVER_LISTEN)
    if heard is None:                  # servizio in riavvio o ricevitore non Unicore: si riprova dopo
        return
    silent = heard == 0
    if silent and st["silent_since"] is None:
        st["silent_since"] = now
        sats = receiver_satellites()
        temps["satellites"] = sats
        log("ricevitore GNSS senza dati: %s" % describe_satellites(sats))
    elif silent and now - st["silent_since"] >= RECEIVER_RESET_AFTER and st["reset_at"] is None:
        last = read_json(RECEIVER_RESET_FILE, {}).get("time")
        if last is not None and 0 <= now - last < RECEIVER_RESET_MIN_INTERVAL:
            return
        sats = receiver_satellites()
        _, answer = receiver_session(b"RESET", b"$command,RESET")
        st.update(reset_at=now, restart_at=now + RECEIVER_RESTART_DELAY)
        try:
            write_json(RECEIVER_RESET_FILE, {"time": now})
        except OSError:
            pass
        log("ricevitore GNSS senza dati da %d minuti (%s): inviato RESET (%s)"
            % ((now - st["silent_since"]) // 60, describe_satellites(sats),
               "confermato" if answer and b"OK" in answer else "nessuna conferma"))
    elif not silent and st["silent_since"] is not None:
        sats = receiver_satellites()
        temps["satellites"] = sats
        after_reset = (", %d minuti dopo il reset" % ((now - st["reset_at"]) // 60)) if st["reset_at"] else ""
        log("ricevitore GNSS di nuovo con dati dopo %d minuti%s: %s" %
            ((now - st["silent_since"]) // 60, after_reset, describe_satellites(sats)))
        st.update(silent_since=None, reset_at=None)
    elif read_satellites:
        temps["satellites"] = receiver_satellites()


MODEM_TEMP = {"supported": True}


def modem_temperature(settings):
    """ Temperatura del modem in gradi, o None. Air780E (chip EigenComm EC618): AT+ECADC="TEMP"
        risponde "+ECADC: TEMP, 60" (verificato 04/10); i comandi standard (AT+CPMUTEMP ecc.) danno ERROR.
        Se il modem non lo conosce non si riprova fino al riavvio del servizio. """
    if not MODEM_TEMP["supported"]:
        return None
    ok, lines = modem_at(settings, 'AT+ECADC="TEMP"')
    value = at_value(lines, "+ECADC:") if ok else None
    number = value.split(",")[-1].strip() if value else ""
    if not number.lstrip("-").isdigit():
        if any("ERROR" in line for line in lines):
            MODEM_TEMP["supported"] = False
        return None
    return float(number)


def check_temperatures(settings, temps, now, read_receiver):
    """ Aggiorna le temperature e scrive un evento quando superano il limite o rientrano """
    temps["pi"] = pi_temperature()
    if read_receiver:
        temps["receiver"] = receiver_temperature()
        temps["receiver_time"] = now
    if LTE_RADIO.get("on"):
        try:
            ok, lines = modem_at(settings, "AT+CBC")
            value = at_value(lines, "+CBC:") if ok else None
            temps["modem_mv"] = int(value.split(",")[-1]) if value and value.split(",")[-1].strip().isdigit() else None
            temps["modem"] = modem_temperature(settings)
        except (OSError, TimeoutError):
            pass
    else:
        temps["modem"] = None
    names = {"pi": "Raspberry Pi", "receiver": "ricevitore GNSS", "modem": "modem LTE"}
    alarms = temps.setdefault("alarms", {})
    for key, limit in TEMP_LIMITS.items():
        value = temps.get(key)
        if value is None:
            continue
        if not alarms.get(key) and value >= limit:
            alarms[key] = True
            log("temperatura %s alta: %.1f gradi (limite %.0f)" % (names[key], value, limit))
        elif alarms.get(key) and value <= limit - TEMP_HYSTERESIS:
            alarms[key] = False
            log("temperatura %s rientrata: %.1f gradi" % (names[key], value))
    temps["limits"] = TEMP_LIMITS
    try:
        write_json(TEMPS_FILE, temps)
    except OSError:
        pass


#### chip WiFi bloccato ####

WIFI_HANG = {"since": None, "warned": False, "down_since": None, "last_probe": 0, "probe_fails": 0,
             "probe_busy": False}


def wifi_scan_failure():
    """ Esito della scansione WiFi: "timeout" (-110, il chip non risponde), "busy" (-16, una
        scansione precedente non finisce mai, visto il 01/10) oppure None (anche "nessuna rete trovata") """
    ok, out, err = run_cmd(["iw", "dev", WIFI_DEVICE, "scan"], timeout=30)
    text = out + err
    if "(-110)" in text:
        return "timeout"
    if "(-16)" in text:
        return "busy"
    return None


def wifi_chip_silent_dead(now, settings):
    """ Chip WiFi bloccato senza errori a raffica: WiFi abilitato, scollegato da WIFI_DEAD_AFTER
        e scansioni che falliscono WIFI_DEAD_PROBES volte di fila (WIFI_DEAD_PROBES_BUSY se fra
        gli errori c'e' "occupato", che puo' capitare anche con una scansione normale in corso) """
    st = WIFI_HANG
    dev = next((d for d in list_devices() if d["device"] == WIFI_DEVICE), None)
    if (not settings["enabled"]["wifi"] or dev is None or dev["state"] == "connected"
            or not get_radio_wifi() or hotspot_active()):
        st.update(down_since=None, probe_fails=0, probe_busy=False)
        return False
    st["down_since"] = st["down_since"] or now
    if now - st["down_since"] < WIFI_DEAD_AFTER:
        return False
    if now - st["last_probe"] >= WIFI_DEAD_PROBE_EVERY:
        st["last_probe"] = now
        failure = wifi_scan_failure()
        if failure:
            st["probe_fails"] += 1
            st["probe_busy"] = st["probe_busy"] or failure == "busy"
        else:
            st.update(probe_fails=0, probe_busy=False)
    return st["probe_fails"] >= (WIFI_DEAD_PROBES_BUSY if st["probe_busy"] else WIFI_DEAD_PROBES)


def wifi_chip_hung():
    """ True se fra gli ultimi messaggi del kernel ci sono molti errori SDIO del chip WiFi """
    out = run(["dmesg"], timeout=10)
    lines = out.splitlines()[-WIFI_HANG_LINES:]
    return sum(1 for line in lines if WIFI_HANG_PATTERN.search(line)) >= WIFI_HANG_MIN_ERRORS


def check_wifi_chip(now, settings=None):
    """ Chip WiFi bloccato da WIFI_HANG_DELAY: riavvia la base (al massimo una volta ogni
        AUTO_REBOOT_MIN_INTERVAL, per non entrare in un ciclo di riavvii). Niente ricarica del driver:
        con il chip bloccato "modprobe -r" resta appeso e bloccherebbe anche questo servizio. """
    st = WIFI_HANG
    flood = wifi_chip_hung()
    silent = not flood and settings is not None and wifi_chip_silent_dead(now, settings)
    if not flood and not silent:
        if st["since"] is not None:
            log("chip WiFi di nuovo regolare")
        st.update(since=None, warned=False)
        return
    st["since"] = st["since"] or now
    if flood and now - st["since"] < WIFI_HANG_DELAY:
        return
    last = read_json(AUTO_REBOOT_FILE, {}).get("time")
    if last is not None and now - last < AUTO_REBOOT_MIN_INTERVAL:
        if not st["warned"]:
            st["warned"] = True
            log("chip WiFi ancora bloccato, ma la base e' gia' stata riavviata da meno di 6 ore: "
                "nessun nuovo riavvio automatico (controllare temperatura e alimentazione)")
        return
    if flood:
        log("chip WiFi bloccato da %d minuti (errori del driver a raffica): riavvio la base" %
            ((now - st["since"]) // 60))
    else:
        log("chip WiFi bloccato (WiFi scollegato da %d minuti, scansioni in timeout%s): riavvio la base" %
            ((now - st["down_since"]) // 60, " o bloccate" if st["probe_busy"] else ""))
    try:
        write_json(AUTO_REBOOT_FILE, {"time": now, "reason": "chip WiFi bloccato"})
    except OSError:
        pass
    run(["sync"], timeout=30)
    # riavvio forzato: uno normale resta minuti ad aspettare il driver bloccato allo spegnimento
    subprocess.Popen(["systemctl", "reboot", "--force"], start_new_session=True)


#### guardiano dei servizi della base ####

GUARD = {}      # servizio -> istante in cui e' stato visto fermo


def services_state(units):
    """ {unit: {UnitFileState, ActiveState}} con una sola chiamata a systemctl
        (un blocco per unita', anche per quelle che non esistono) """
    ok, out, _ = run_cmd(["systemctl", "show", "--property=Id,UnitFileState,ActiveState"] + list(units), timeout=20)
    states = {}
    for block in out.strip().split("\n\n"):
        values = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        if values.get("Id"):
            states[values["Id"]] = values
    return states


def guard_services(now):
    """ Riavvia i servizi della base abilitati ma fermi da GUARD_DELAY secondi """
    states = services_state(GUARDED_SERVICES)
    for service in GUARDED_SERVICES:
        state = states.get(service, {})
        if state.get("UnitFileState") != "enabled":
            GUARD.pop(service, None)
            continue
        if state.get("ActiveState") in ("active", "activating", "reloading"):
            GUARD.pop(service, None)
            continue
        GUARD[service] = GUARD.get(service) or now
        if now - GUARD[service] >= GUARD_DELAY:
            log("%s abilitato ma fermo: lo riavvio" % service.replace(".service", ""))
            run(["systemctl", "start", service], timeout=60)
            GUARD.pop(service, None)


def internet_device():
    """ Interfaccia della rotta di default preferita (quella che porta internet), o None """
    routes = get_default_routes()
    return min(routes, key=routes.get) if routes else None


def reconnect_outgoing(old, new):
    """ La connessione a internet e' cambiata: le trasmissioni NTRIP attive ripartono sulla strada nuova """
    log("connessione a internet passata da %s a %s: riconnetto le trasmissioni NTRIP" % (old, new))
    run(["systemctl", "try-restart"] + OUTGOING_SERVICES, timeout=60)


def lte_recover(settings, device, h, now):
    """ LTE collegato ma senza internet: riconnessione, poi riaggancio alla rete, poi reset del modem """
    bad_for = now - h["since"]
    step = h["recovery"]
    if step < len(LTE_RECOVERY):
        delay, action = LTE_RECOVERY[step]
        if bad_for < delay:
            return
        h["recovery"] = step + 1
        log("LTE (%s) senza internet da %d minuti: %s" % (device, bad_for // 60, {
            "reconnect": "riconnetto l'interfaccia", "reattach": "riaggancio la rete mobile",
            "reset": "riavvio il modem"}[action]))
        try:
            if action == "reconnect":
                nm("device", "disconnect", device)
                nm("--wait", "30", "device", "connect", device, timeout=40)
            elif action == "reattach":
                modem_at(settings, "AT+CFUN=0", timeout=15)
                time.sleep(3)
                modem_at(settings, "AT+CFUN=1", timeout=15)
            else:
                modem_at(settings, "AT+CFUN=1,1", timeout=15)
        except (OSError, TimeoutError) as e:
            log("recupero LTE non riuscito: %s" % e)
    elif bad_for >= LTE_RECOVERY[-1][0] + LTE_RECOVERY_RESTART:
        h.update(since=now, recovery=0)


#### traffico LTE ####

def lte_counters():
    """ Byte totali (ricevuti + inviati) per ogni interfaccia LTE presente """
    counters = {}
    for dev in list_devices():
        if dev["kind"] != "lte":
            continue
        base = "/sys/class/net/%s/statistics/" % dev["device"]
        try:
            counters[dev["device"]] = int(read_sys(base + "rx_bytes")) + int(read_sys(base + "tx_bytes"))
        except ValueError:
            pass
    return counters


def traffic_update(state, settings):
    """ Aggiorna i totali giornaliero/mensile (i contatori del kernel ripartono se l'interfaccia ricompare) """
    day, month = time.strftime("%Y-%m-%d"), time.strftime("%Y-%m")
    if state.get("month") != month:
        state.update(month=month, month_bytes=0, warned=[])
    if state.get("day") != day:
        state.update(day=day, day_bytes=0)
    last = state.setdefault("last", {})
    for device, value in lte_counters().items():
        delta = value - last[device] if device in last and value >= last[device] else value if device in last else 0
        last[device] = value
        state["day_bytes"] += delta
        state["month_bytes"] += delta

    limit = int(settings["lte"].get("monthly_limit_mb") or 0) * 1024 * 1024
    if limit:
        for percent in (80, 100):
            if state["month_bytes"] >= limit * percent / 100 and percent not in state["warned"]:
                state["warned"].append(percent)
                log("traffico LTE del mese al %d%% della soglia (%d MB su %d MB)" %
                    (percent, state["month_bytes"] // 1048576, limit // 1048576))
    return state


def traffic_summary(settings):
    state = read_json(TRAFFIC_FILE, {})
    limit = int(settings["lte"].get("monthly_limit_mb") or 0)
    month_mb = round(state.get("month_bytes", 0) / 1048576, 1) if state.get("month") == time.strftime("%Y-%m") else 0
    day_mb = round(state.get("day_bytes", 0) / 1048576, 1) if state.get("day") == time.strftime("%Y-%m-%d") else 0
    return {"day_mb": day_mb, "month_mb": month_mb, "limit_mb": limit,
            "percent": round(month_mb * 100 / limit) if limit else None}


#### esporta / importa impostazioni ####

def import_settings(data, report):
    """ Operazione: importa le impostazioni (da un'altra base o da un backup) con ripristino se si perde internet """
    old = load_settings()
    new = normalize_settings(data)
    if not new["hotspot"]["password"]:
        new["hotspot"]["password"] = old["hotspot"]["password"]
    before = connectivity_rank()
    save_settings(new)
    report("Impostazioni importate. Le applico...")
    apply_interfaces(new, report)
    hotspot_profile(new)
    report("Verifico la connessione tra %d secondi..." % CHECK_DELAY)
    time.sleep(CHECK_DELAY)
    if connectivity_rank() >= before:
        report("Fatto: impostazioni importate e connessione verificata.")
        return True
    report("Connessione persa: ripristino le impostazioni precedenti.")
    save_settings(old)
    apply_interfaces(old, report)
    hotspot_profile(old)
    return False


def watch():
    """ Ciclo del servizio rtkbase_network_watch: applica le impostazioni, gestisce hotspot e PIN """
    _CACHE["enabled"] = True
    settings = load_settings()
    with file_lock(OP_LOCK, timeout=120):
        apply_interfaces(settings, log)
    last_apply = time.time()
    last_devices = sorted((d["device"], d["kind"]) for d in list_devices())
    last_pin = 0
    serial_only_since = None
    offline_since = None
    hotspot_since = time.time() if hotspot_active() else None
    health = {}
    last_health = 0
    traffic = read_json(TRAFFIC_FILE, {})
    last_traffic_save = time.time()
    last_route = internet_device()
    temps = {}
    last_receiver_temp = 0

    while True:
        time.sleep(WATCH_PERIOD)
        if is_locked(OP_LOCK):             # la pagina sta facendo una modifica
            continue
        settings = load_settings()
        now = time.time()

        # nuove interfacce (es. modem che si avvia dopo il Pi) o riapplicazione periodica
        devices = sorted((d["device"], d["kind"]) for d in list_devices())
        if devices != last_devices or now - last_apply > APPLY_PERIOD:
            try:
                with file_lock(OP_LOCK, timeout=5):
                    apply_interfaces(settings, log)
                last_devices, last_apply = devices, now
            except TimeoutError:
                continue

        if now - last_pin > 60:
            lte_pin_check(settings)
            last_pin = now
            if modem_without_network():
                serial_only_since = serial_only_since or now
                if now - serial_only_since >= ACTIVATION_DELAY:
                    lte_activate(settings)
            else:
                serial_only_since = None
            pin_receiver_port()

        traffic_update(traffic, settings)
        if now - last_traffic_save >= TRAFFIC_SAVE or traffic.get("_saved_day") != traffic.get("day"):
            traffic["_saved_day"] = traffic.get("day")
            try:
                write_json(TRAFFIC_FILE, traffic)
            except OSError:
                pass
            last_traffic_save = now

        if now - last_health >= HEALTH_PERIOD:
            check_health(settings, health, now)
            lte_manage(settings, health, now)
            slow = now - SLOW_LAST["time"] >= SLOW_PERIOD     # controlli che cambiano lentamente
            if slow:
                lte_read_signal(settings)
            write_lte_state(settings)
            read_receiver = now - last_receiver_temp >= RECEIVER_TEMP_PERIOD
            if slow:
                check_receiver_output(now, temps, read_receiver)
            if slow or read_receiver:
                check_temperatures(settings, temps, now, read_receiver)
            if read_receiver:
                last_receiver_temp = now
            if slow:
                check_wifi_chip(now, settings)
                check_update_periodically(now, settings)
                check_sim(settings, now)
                SLOW_LAST["time"] = now
            if now - GUARD_LAST["time"] >= GUARD_PERIOD:
                guard_services(now)
                GUARD_LAST["time"] = now
            last_health = now

        route = internet_device()
        if route and route != last_route:
            if last_route is not None:
                reconnect_outgoing(last_route, route)
            last_route = route

        online = internet_ok()
        if hotspot_active():
            hotspot_since = hotspot_since or now
            if not settings["hotspot"]["enabled"] or online:
                hotspot_stop(settings)
                hotspot_since, offline_since = None, None
            elif now - hotspot_since > HOTSPOT_RETRY and hotspot_clients() == 0:
                # nessuno collegato: riprovo le reti WiFi salvate, poi eventualmente riparto
                hotspot_stop(settings)
                hotspot_since, offline_since = None, now
            continue

        hotspot_since = None
        if online:
            offline_since = None
            continue
        offline_since = offline_since or now
        if settings["hotspot"]["enabled"] and now - offline_since >= int(settings["hotspot"]["delay"]):
            if hotspot_start(settings):
                hotspot_since = now


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="network_page", description="Gestione rete di ELT_RTKBase")
    parser.add_argument("--watch", action="store_true", help="servizio: applica impostazioni, hotspot e PIN")
    parser.add_argument("--apply", action="store_true", help="applica abilitazioni e priorita' e termina")
    parser.add_argument("--lte", action="store_true", help="stampa lo stato del modem LTE")
    args = parser.parse_args()
    if args.watch:
        watch()
    elif args.apply:
        apply_interfaces(load_settings(), log)
    elif args.lte:
        print(json.dumps(lte_status(), indent=2))
    else:
        print(json.dumps(get_status(), indent=2))
    sys.exit(0)
