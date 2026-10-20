import sys, os, json
exec(open("test_network_page.py", encoding="utf-8").read().split("fake = FakeNM()")[0])
events = []; n.log = lambda m: events.append(m)
n.ALERT_FILE = os.path.join(tmp, "alerts.json")
n.PAUSE_FILE = os.path.join(tmp, "pause.json")
open(n.RTKBASE_SETTINGS, "w").write("[main]\ncom_port='ttyGNSS_TEST_ASSENTE'\n[ntrip_A]\nsvr_port_a='2101'\nmnt_name_a='ALTAMURA'\n")

assert n.sms_text("Città: ferma àèé — ok") == "Citta: ferma aee  ok"
assert len(n.sms_text("x" * 300)) == 160

sms = []
def fake_send(settings, number, text):
    sms.append((number, text)); return None
n.send_sms = fake_send
st = n.load_settings()
assert st["alerts"]["enabled"] and st["alerts"]["numbers"] == [] and st["alerts"]["down_minutes"] == 15
up = {"v": True}
n.transmission_up = lambda: up["v"]
n.socket.gethostname = lambda: "evonetrtkbase"

# nessun numero: niente SMS
up["v"] = False
n.check_transmission_alert(1000, st); n.check_transmission_alert(5000, st); assert not sms
st["alerts"]["numbers"] = ["+39 360 962958"]; n.save_settings(st); st = n.load_settings()
os.path.exists(n.ALERT_FILE) and os.remove(n.ALERT_FILE)
# ferma: avviso dopo 15 minuti, con il motivo
n.check_transmission_alert(10000, st); assert not sms
n.check_transmission_alert(10000 + 14 * 60, st); assert not sms
n.check_transmission_alert(10000 + 15 * 60, st)
assert len(sms) == 1 and "ALTAMURA FERMA da 15 minuti" in sms[0][1] and "ricevitore GNSS non collegato" in sms[0][1], sms
n.check_transmission_alert(10000 + 60 * 60, st); assert len(sms) == 1          # niente doppioni
n.check_transmission_alert(10000 + 15 * 60 + 12 * 3600, st); assert len(sms) == 2 # promemoria dopo 12 ore
# di nuovo in linea
up["v"] = True
n.check_transmission_alert(60000, st)
assert len(sms) == 3 and "DI NUOVO IN LINEA" in sms[-1][1], sms[-1]
n.check_transmission_alert(60100, st); assert len(sms) == 3
# fermo breve (sotto i 15 minuti): nessun SMS, nemmeno alla ripresa
up["v"] = False; n.check_transmission_alert(70000, st); n.check_transmission_alert(70000 + 600, st)
up["v"] = True; n.check_transmission_alert(70000 + 700, st); assert len(sms) == 3
# in pausa (misura HAS): niente avvisi
n.set_pause(7200, "misura"); up["v"] = False
n.check_transmission_alert(80000, st); n.check_transmission_alert(80000 + 3600, st); assert len(sms) == 3
n.clear_pause()
# avvisi disattivati
st["alerts"]["enabled"] = False
n.check_transmission_alert(90000, st); n.check_transmission_alert(99000, st); assert len(sms) == 3
st["alerts"]["enabled"] = True
# limite giornaliero
data = n.read_json(n.ALERT_FILE, {}); data.update(day=__import__("time").strftime("%Y-%m-%d"), sent_today=10)
n.write_json(n.ALERT_FILE, data)
assert "limite" in n.send_alert(st, "prova") and len(sms) == 3
print("AVVISI SMS OK")

from flask import Flask
from flask_login import LoginManager
import network_routes
app = Flask(__name__); app.secret_key = "x"; LoginManager(app).user_loader(lambda uid: None)
app.register_blueprint(network_routes.blueprint); c = app.test_client()
assert c.get("/api/network/alerts").status_code in (302, 401)
app.config["LOGIN_DISABLED"] = True
r = c.post("/api/network/alerts", json={"enabled": True, "numbers": "+39 360 962958, +39 333 1234567", "down_minutes": 20}).get_json()
assert r["numbers"] == ["+39 360 962958", "+39 333 1234567"] and r["down_minutes"] == 20
assert c.post("/api/network/alerts", json={"enabled": True, "numbers": "abc", "down_minutes": 20}).status_code == 400
assert c.post("/api/network/alerts", json={"enabled": True, "numbers": "", "down_minutes": 1}).status_code == 400
n.write_json(n.ALERT_FILE, {})
r = c.post("/api/network/alerts", json={"test": True}).get_json()
assert "inviato" in r["result"] and len(sms) == 5, (r, sms)
print("AVVISI ROUTE OK")

# criterio "in linea": il servizio NTRIP che riparte e si collega per pochi secondi non basta (20/10)
import importlib
n2 = n
real_up = n2.__class__ if False else None
svc = {"str2str_tcp.service": "activating", "str2str_ntrip_A.service": "active"}
def run3(args, timeout=15):
    if args[:2] == ["systemctl", "is-active"]:
        return svc.get(args[2], "inactive")
    if args[0] == "ss":
        return "ESTAB 0 0 192.168.10.2:1 45.129.248.45:2101"
    return ""
n.run = run3
import types
up_fn = n.__dict__.get("_transmission_up_real")
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "Install", "network_page.py"),
          encoding="utf-8").read().split("def transmission_up():")[1].split("\ndef down_reason")[0].join(["def _tu():", ""]), n.__dict__)
open(n.RTKBASE_SETTINGS, "w").write("[main]\ncom_port='ttyGNSS_TEST_ASSENTE'\n[ntrip_A]\nsvr_port_a='2101'\n")
assert n._tu() is False                                   # ricevitore non collegato
open(n.RTKBASE_SETTINGS, "w").write("[main]\ncom_port=''\n[ntrip_A]\nsvr_port_a='2101'\n")
assert n._tu() is False                                   # servizio del ricevitore che non parte
svc["str2str_tcp.service"] = "active"; n.RECEIVER_OUTPUT["silent_since"] = 123
assert n._tu() is False                                   # ricevitore muto
n.RECEIVER_OUTPUT["silent_since"] = None
assert n._tu() is True
print("CRITERIO IN LINEA OK")
