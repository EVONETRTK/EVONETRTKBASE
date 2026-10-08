""" Route Flask della pagina "Rete" di ELT_RTKBase (registrate in server.py come blueprint) """

import re
import json
import time
import socket
from flask import Blueprint, render_template, request, jsonify, redirect, Response
from flask_login import login_required

import network_page as net

blueprint = Blueprint("network", __name__)

SSID_MAX = 32
APN_RE = re.compile(r"[A-Za-z0-9._-]{0,63}")
PIN_RE = re.compile(r"[0-9]{4,8}")
AT_RE = re.compile(r"AT[ -~]{0,200}", re.IGNORECASE)

HOTSPOT_PREFIX = "10.42.0."        # rete dei client dell'hotspot (NetworkManager, modalita' shared)
HOTSPOT_URL = "http://10.42.0.1/network"

# Aggiornamento online: il pulsante "Check update" di Settings non usa piu' il repository ufficiale di
# ELT_RTKBase (installerebbe la versione senza pagina Rete) ma EVONETRTKBASE, con il canale scelto nella
# pagina Rete. Resta possibile caricare a mano un install.sh (Settings?update=manual).


def check_update_for_settings():
    """ Risposta nel formato atteso da settings.js ("new release"): {} = nessuna novita' """
    result = net.check_update()
    if result.get("error"):
        return {"error": result["error"]}
    if not result.get("available"):
        return {}
    return {"version": result["latest"], "new_release": result["new_release"],
            "comment": result["comment"] + "\r\n(canale " + result["channel"] + ", installata " +
            result["current_label"] + ")"}


def download_update(path):
    return net.download_update(path)


def before_update():
    net.backup_before_update()


def error(message, code=400):
    return jsonify({"ok": False, "error": message}), code


def started(ok):
    if not ok:
        return error("C'è già un'operazione in corso, attendi che finisca.", 409)
    return jsonify({"ok": True})


def psk_valid(password):
    return 8 <= len(password) <= 63 and all(32 <= ord(c) <= 126 for c in password)


@blueprint.before_app_request
def captive_portal():
    """ Chi e' collegato all'hotspot e apre un indirizzo qualsiasi (o il telefono che controlla la connessione)
        viene portato alla pagina Rete: il DNS dell'hotspot risponde 10.42.0.1 per ogni nome. """
    if not (request.remote_addr or "").startswith(HOTSPOT_PREFIX):
        return None
    if request.host.split(":")[0] == HOTSPOT_URL.split("/")[2]:
        return None
    return redirect(HOTSPOT_URL, code=302)


@blueprint.route("/network")
@login_required
def page():
    """ La pagina "Rete": stato e gestione di Ethernet, WiFi, LTE e hotspot """
    return render_template("network.html")


@blueprint.route("/api/network/status")
@login_required
def status():
    return jsonify(net.get_status())


@blueprint.route("/api/network/operation")
@login_required
def operation():
    return jsonify(net.get_operation())


@blueprint.route("/api/network/interfaces", methods=["POST"])
@login_required
def interfaces():
    data = request.get_json(silent=True) or {}
    enabled = data.get("enabled") or {}
    order = data.get("order") or []
    if sorted(order) != sorted(net.KINDS):
        return error("Ordine di priorità non valido.")
    if not any(enabled.get(k) for k in net.KINDS):
        return error("Almeno una connessione deve restare abilitata.")
    return started(net.start_operation("Connessioni", net.change_interfaces, enabled, order))


@blueprint.route("/api/network/wifi/scan")
@login_required
def wifi_scan():
    return jsonify({"networks": net.wifi_scan(), "hotspot": net.hotspot_active()})


@blueprint.route("/api/network/wifi/saved")
@login_required
def wifi_saved():
    return jsonify({"profiles": net.wifi_profiles()})


@blueprint.route("/api/network/wifi/connect", methods=["POST"])
@login_required
def wifi_connect():
    data = request.get_json(silent=True) or {}
    ssid = str(data.get("ssid") or "")
    password = str(data.get("password") or "")
    if not ssid or len(ssid.encode()) > SSID_MAX:
        return error("Nome della rete non valido.")
    if password and not psk_valid(password):
        return error("La password WiFi deve avere da 8 a 63 caratteri.")
    return started(net.start_operation("WiFi", net.wifi_connect, ssid, password,
                                       bool(data.get("hidden")), str(data.get("security") or "")))


@blueprint.route("/api/network/wifi/forget", methods=["POST"])
@login_required
def wifi_forget():
    data = request.get_json(silent=True) or {}
    ok, message = net.wifi_forget(str(data.get("uuid") or ""))
    return jsonify({"ok": ok, "error": None if ok else message})


@blueprint.route("/api/network/hotspot", methods=["GET", "POST"])
@login_required
def hotspot():
    if request.method == "GET":
        settings = net.load_settings()
        return jsonify({"enabled": settings["hotspot"]["enabled"],
                        "ssid": net.hotspot_ssid(settings),
                        "password": settings["hotspot"]["password"],
                        "delay": settings["hotspot"]["delay"],
                        "active": net.hotspot_active()})
    data = request.get_json(silent=True) or {}
    ssid = str(data.get("ssid") or "").strip()
    password = str(data.get("password") or "")
    try:
        delay = int(data.get("delay"))
    except (TypeError, ValueError):
        return error("Ritardo non valido.")
    if not ssid or len(ssid.encode()) > SSID_MAX:
        return error("Nome dell'hotspot non valido.")
    if not psk_valid(password):
        return error("La password dell'hotspot deve avere da 8 a 63 caratteri.")
    if not 30 <= delay <= 3600:
        return error("Il ritardo deve essere tra 30 e 3600 secondi.")
    return started(net.start_operation("Hotspot", net.change_hotspot, bool(data.get("enabled")),
                                       ssid, password, delay))


@blueprint.route("/api/network/lte", methods=["GET", "POST"])
@login_required
def lte():
    if request.method == "GET":
        return jsonify(net.lte_status())
    data = request.get_json(silent=True) or {}
    apn = str(data.get("apn") or "").strip()
    pin = data.get("pin")
    activation = data.get("activation_command")
    if activation is not None:
        activation = str(activation).strip()
        if activation and not AT_RE.fullmatch(activation):
            return error("Il comando di attivazione deve essere un comando AT su una riga.")
    if not APN_RE.fullmatch(apn):
        return error("APN non valido (solo lettere, numeri, punto, trattino).")
    if pin is not None:
        pin = str(pin).strip()
        if pin and not PIN_RE.fullmatch(pin):
            return error("Il PIN deve avere da 4 a 8 cifre.")
    return started(net.start_operation("LTE", net.change_lte, apn, pin, activation))


@blueprint.route("/api/network/sim", methods=["GET", "POST"])
@login_required
def sim():
    """ ICCID (letto dal modem) e numero di telefono della SIM; POST {phone} salva il numero
        senza toccare la connessione LTE (vuoto = da inserire in seguito) """
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        if data.get("acknowledge"):              # "Ho capito" sull'avviso di SIM cambiata
            net.acknowledge_sim_change()
        if "phone" in data:
            try:
                net.set_sim_phone(data.get("phone"))
            except ValueError as e:
                return error(str(e))
    return jsonify(net.sim_info())


@blueprint.route("/api/network/has", methods=["GET", "POST"])
@login_required
def has():
    """ Misura della posizione della base con Galileo HAS. POST {action: start, hours} | cancel | apply | undo """
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        action = data.get("action")
        try:
            if action == "start":
                net.has_start(int(data.get("hours") or 0))
            elif action == "cancel":
                net.has_cancel()
            elif action in ("apply", "undo"):
                net.has_request(action)
            else:
                return error("Azione non valida.")
        except (ValueError, TypeError) as e:
            return error(str(e))
    return jsonify(net.has_status())


@blueprint.route("/api/network/lte/limit", methods=["POST"])
@login_required
def lte_limit():
    data = request.get_json(silent=True) or {}
    try:
        limit = int(data.get("monthly_limit_mb") or 0)
    except (TypeError, ValueError):
        return error("Soglia non valida.")
    if not 0 <= limit <= 10000000:
        return error("Soglia non valida.")
    settings = net.load_settings()
    settings["lte"]["monthly_limit_mb"] = limit
    if "on_demand" in data:
        settings["lte"]["on_demand"] = bool(data.get("on_demand"))
    net.save_settings(settings)
    return jsonify({"ok": True})


@blueprint.route("/api/network/access_notes", methods=["POST"])
@login_required
def access_notes():
    data = request.get_json(silent=True) or {}
    text = str(data.get("text") or "")
    if len(text) > 4000:
        return error("Note troppo lunghe (massimo 4000 caratteri).")
    settings = net.load_settings()
    settings["access_notes"] = text
    net.save_settings(settings)
    return jsonify({"ok": True})


@blueprint.route("/network/access")
@login_required
def access_page():
    """ Scheda di accesso stampabile: indirizzi, utenti, password e istruzioni della base """
    return render_template("network_access.html")


@blueprint.route("/api/network/access_card")
@login_required
def access_card():
    return jsonify(net.access_card())


@blueprint.route("/api/network/access_secrets", methods=["POST"])
@login_required
def access_secrets():
    """ Password per la scheda di accesso: solo reinserendo la password del pannello
        (non basta una sessione rimasta aperta su un PC qualunque) """
    data = request.get_json(silent=True) or {}
    if not net.web_password_ok(str(data.get("password") or "")):
        time.sleep(1)                               # rallenta i tentativi a caso
        return error("Password errata.", 403)
    response = jsonify(net.access_secrets())
    response.headers["Cache-Control"] = "no-store"
    return response


@blueprint.route("/api/network/update", methods=["GET", "POST"])
@login_required
def update():
    """ GET: versione installata, canale ed esito dell'ultimo controllo. POST {channel}: cambia canale,
        POST {check: true}: controlla adesso. L'installazione si avvia da Settings, Check update. """
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        if "channel" in data:
            try:
                net.set_update_channel(str(data["channel"]))
            except ValueError as e:
                return error(str(e))
        if data.get("check"):
            net.check_update()
    return jsonify(net.update_status())


@blueprint.route("/api/network/events")
@login_required
def events():
    return jsonify({"events": net.read_events()})


@blueprint.route("/api/network/export")
@login_required
def export_settings():
    """ Scarica le impostazioni della pagina Rete (contengono PIN e password: trattale come riservate) """
    name = "rete-%s.json" % re.sub(r"[^\w.-]", "_", socket.gethostname())
    return Response(json.dumps(net.load_settings(), indent=2), mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=%s" % name})


@blueprint.route("/api/network/import", methods=["POST"])
@login_required
def import_settings():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not any(k in data for k in ("enabled", "order", "hotspot", "lte")):
        return error("Il file non contiene impostazioni della pagina Rete.")
    settings = net.normalize_settings(data)
    if settings["hotspot"]["password"] and not psk_valid(settings["hotspot"]["password"]):
        return error("Nel file la password dell'hotspot non è valida.")
    if not any(settings["enabled"].values()):
        return error("Nel file tutte le connessioni sono disabilitate.")
    return started(net.start_operation("Importa impostazioni", net.import_settings, data))


@blueprint.route("/api/network/lte/at", methods=["POST"])
@login_required
def lte_at():
    data = request.get_json(silent=True) or {}
    ok, lines = net.lte_manual_at(str(data.get("command") or ""))
    return jsonify({"ok": ok, "lines": lines})
