import sys, os, json, time, types
from collections import namedtuple
P = namedtuple("P", "pw_name pw_uid pw_shell")
users = [P("root", 0, "/bin/bash"), P("filippo", 1000, "/bin/bash"), P("rtkbase", 1001, "/usr/sbin/nologin"),
         P("nobody", 65534, "/usr/sbin/nologin")]
fake_pwd = types.ModuleType("pwd")
fake_pwd.getpwall = lambda: users
fake_pwd.getpwuid = lambda uid: next(u for u in users if u.pw_uid == uid)
sys.modules["pwd"] = fake_pwd
exec(open("test_network_page.py", encoding="utf-8").read().split("fake = FakeNM()")[0])
fake = FakeNM(); n.run_cmd = fake
n.lte_status = lambda: {"found": False, "apn_saved": "", "pin_saved": False}
from werkzeug.security import generate_password_hash
open(n.RTKBASE_SETTINGS, "w").write(
    "[general]\nversion=2.7.0\nelt_version='1.9.8'\nweb_port=80\nweb_password_hash=%s\n[main]\n"
    "position='0.00 0.00 0.00'\ncom_port='ttyGNSS'\nreceiver='Unicore_UM982'\n[ntrip_A]\n"
    "svr_addr_a='rtk.evo-net.it'\nsvr_port_a='2101'\nsvr_pwd_a='segreta'\nmnt_name_a='ALTAMURA'\n"
    % generate_password_hash("pannello1"))
assert n.rtkbase_conf("mnt_name_a") == "ALTAMURA" and n.rtkbase_conf("version") == "2.7.0"
assert n.rtkbase_conf("elt_version") == "1.9.8" and n.rtkbase_conf("assente") == ""
assert n.web_password_ok("pannello1") and not n.web_password_ok("admin") and not n.web_password_ok("")
st = n.load_settings(); st["access_notes"] = "SSH filippo / prova"; st["lte"]["apn"] = "internet.it"; n.save_settings(st)
card = n.access_card()
text = json.dumps(card)
assert "segreta" not in text and "SSH filippo" not in text and "hotspot_password" not in text, text
assert card["caster"]["mountpoint"] == "ALTAMURA" and card["receiver"] == "Unicore UM982" and card["position"] is None
assert card["apn"] == "internet.it" and card["access"]["hotspot_ssid"]
assert card["ssh_users"] == ["filippo"], card["ssh_users"]
sec = n.access_secrets()
assert sec["caster_password"] == "segreta" and sec["notes"] == "SSH filippo / prova" and sec["hotspot_password"]
assert isinstance(sec["wifi"], list)
open(n.RTKBASE_SETTINGS, "w").write("[main]\nposition='40.83 16.54 490.9'\n")
assert n.access_card()["position"] == "40.83 16.54 490.9"
print("SCHEDA DATI OK")

from flask import Flask
from flask_login import LoginManager
import network_routes
network_routes.time.sleep = lambda s: None
app = Flask(__name__, template_folder="flaskapp/templates", static_folder="flaskapp/static")
app.secret_key = "x"
LoginManager(app).user_loader(lambda uid: None)
app.register_blueprint(network_routes.blueprint)
c = app.test_client()
assert c.get("/network/access").status_code in (302, 401)
assert c.post("/api/network/access_secrets", json={"password": "x"}).status_code in (302, 401)
app.config["LOGIN_DISABLED"] = True
open(n.RTKBASE_SETTINGS, "w").write("[general]\nweb_password_hash=%s\n[ntrip_A]\nsvr_pwd_a='segreta'\n"
                                    % generate_password_hash("pannello1"))
html = c.get("/network/access").get_data(as_text=True)
assert "Scheda di accesso" in html and "qrcode.min.js" in html and "raw %}" not in html and "const pw = val" in html
assert "segreta" not in c.get("/api/network/access_card").get_data(as_text=True)
assert c.post("/api/network/access_secrets", json={"password": "sbagliata"}).status_code == 403
r = c.post("/api/network/access_secrets", json={"password": "pannello1"})
assert r.status_code == 200 and r.get_json()["caster_password"] == "segreta" and r.headers["Cache-Control"] == "no-store"
print("SCHEDA ROUTE OK")
