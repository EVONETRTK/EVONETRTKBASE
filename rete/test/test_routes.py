import sys, os, json, time, threading
exec(open("test_network_page.py", encoding="utf-8").read().split("fake = FakeNM()")[0])
fake = FakeNM(); n.run_cmd = fake
n.lte_status = lambda: {"found": False, "apn_saved": "", "pin_saved": False}
from flask import Flask, g
from flask_login import LoginManager
from flask_bootstrap import Bootstrap4
import network_routes

app = Flask(__name__, template_folder="flaskapp/templates", static_folder="flaskapp/static")
app.secret_key = "x"
login = LoginManager(app)
login.login_view = "login_page"
login.user_loader(lambda uid: None)


@app.route("/login")
def login_page():
    return "login"


for ep in ("status_page", "settings_page", "logs_page"):
    app.add_url_rule("/" + ep, ep, lambda: "x")
app.register_blueprint(network_routes.blueprint)
Bootstrap4(app)


@app.before_request
def inject():
    g.version = "2.7.0"; g.station_name = "TEST"; g.elt_version = "1.9.8"; g.sbc_model = "pi"


c = app.test_client()
r = c.get("/network"); assert r.status_code == 302, r.status_code            # senza login -> login
r = c.get("/api/network/status"); assert r.status_code == 302
app.config["LOGIN_DISABLED"] = True
r = c.get("/network"); html = r.get_data(as_text=True)
assert r.status_code == 200 and "Hotspot di emergenza" in html and "network.js" in html
i = html.index('href="/network"')
print(" ".join(html[i-120:i+40].split()))
assert "active" in html[i-120:i]
st = c.get("/api/network/status").get_json()
assert st["interfaces"] and st["order"] == ["ethernet", "wifi", "lte"]

# validazioni
assert c.post("/api/network/interfaces", json={"enabled": {}, "order": ["ethernet", "wifi", "lte"]}).status_code == 400
assert c.post("/api/network/interfaces", json={"enabled": {"wifi": True}, "order": ["wifi"]}).status_code == 400
assert c.post("/api/network/wifi/connect", json={"ssid": "Casa", "password": "corta"}).status_code == 400
assert c.post("/api/network/hotspot", json={"ssid": "X", "password": "1234567", "delay": 60}).status_code == 400
assert c.post("/api/network/lte", json={"apn": 'a"; AT+X', "pin": ""}).status_code == 400
assert c.post("/api/network/lte", json={"apn": "ok.it", "pin": "12"}).status_code == 400
assert c.post("/api/network/lte/at", json={"command": "reboot"}).get_json()["ok"] is False

# operazione in background + blocco della seconda
r = c.post("/api/network/wifi/connect", json={"ssid": "Ufficio", "password": "ufficio123", "security": "WPA3"})
assert r.get_json() == {"ok": True}, r.get_json()
for _ in range(100):
    op = c.get("/api/network/operation").get_json()
    if not op["running"]:
        break
    threading.Event().wait(0.05)
print(op)
assert op["result"] == "ok" and fake.devices["wlan0"]["con"] == "Ufficio"

print(c.get("/api/network/wifi/scan").get_json()["networks"][0])
print(c.get("/api/network/wifi/saved").get_json())
print(c.get("/api/network/hotspot").get_json())
print("ROUTES OK")

# --- hotspot: reindirizzamento alla pagina Rete
r = c.get("/generate_204", headers={"Host": "connectivitycheck.gstatic.com"}, environ_base={"REMOTE_ADDR": "10.42.0.23"})
assert r.status_code == 302 and r.headers["Location"] == "http://10.42.0.1/network", (r.status_code, r.headers.get("Location"))
r = c.get("/network", headers={"Host": "10.42.0.1"}, environ_base={"REMOTE_ADDR": "10.42.0.23"})
assert r.status_code == 200
r = c.get("/generate_204", headers={"Host": "connectivitycheck.gstatic.com"}, environ_base={"REMOTE_ADDR": "192.168.1.20"})
assert r.status_code == 404          # fuori dall'hotspot nessun reindirizzamento

# --- soglia, eventi, esporta, importa
assert c.post("/api/network/lte/limit", json={"monthly_limit_mb": "abc"}).status_code == 400
assert c.post("/api/network/lte/limit", json={"monthly_limit_mb": 3000}).get_json() == {"ok": True}
assert n.load_settings()["lte"]["monthly_limit_mb"] == 3000
assert "traffic" in c.get("/api/network/status").get_json()
assert isinstance(c.get("/api/network/events").get_json()["events"], list)
r = c.get("/api/network/export")
assert "attachment; filename=rete-" in r.headers["Content-Disposition"]
exported = r.get_json()
assert exported["lte"]["monthly_limit_mb"] == 3000 and len(exported["hotspot"]["password"]) == 10
assert c.post("/api/network/import", json={"foo": 1}).status_code == 400
assert c.post("/api/network/import", json={"enabled": {"ethernet": False, "wifi": False, "lte": False}}).status_code == 400
assert c.post("/api/network/import", json={"hotspot": {"password": "corta"}}).status_code == 400
exported["order"] = ["wifi", "lte", "ethernet"]
assert c.post("/api/network/import", json=exported).get_json() == {"ok": True}
for _ in range(100):
    op = c.get("/api/network/operation").get_json()
    if not op["running"]:
        break
    threading.Event().wait(0.05)
assert op["result"] == "ok" and n.load_settings()["order"] == ["wifi", "lte", "ethernet"], op
print("ROUTES NUOVE OK")
assert c.post("/api/network/access_notes", json={"text": "x" * 5000}).status_code == 400
assert c.post("/api/network/access_notes", json={"text": "nota di prova"}).get_json() == {"ok": True}
assert n.load_settings()["access_notes"] == "nota di prova"
print("NOTE OK")
