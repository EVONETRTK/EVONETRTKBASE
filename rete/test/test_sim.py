import sys, os, json
exec(open("test_network_page.py", encoding="utf-8").read().split("fake = FakeNM()")[0])
events = []; n.log = lambda m: events.append(m)
n.SIM_FILE = os.path.join(tmp, "sim.json")
assert n.parse_iccid(["+ICCID: 8939880841024179213F"]) == "8939880841024179213"     # Air780E
assert n.parse_iccid(['+CCID: "89390100001234567890"']) == "89390100001234567890"
assert n.parse_iccid(["+QCCID: 8939010000123456789F"]) == "8939010000123456789"
assert n.parse_iccid(["8939010000123456789"]) == "8939010000123456789"
assert n.parse_iccid(["ERROR"]) is None and n.parse_iccid([]) is None
# memorizzazione e cambio SIM
n.remember_iccid("8939880841024179213", 100)
assert "SIM letta" in events[-1] and n.sim_info()["iccid"] == "8939880841024179213"
k = len(events); n.remember_iccid("8939880841024179213", 200); assert len(events) == k   # stessa SIM: niente
st = n.load_settings(); st["lte"]["phone"] = "+39 350 1111111"; n.save_settings(st)
n.remember_iccid("8939010000123456789", 300)
assert "SIM CAMBIATA" in events[-1] and "prima 8939880841024179213" in events[-1] and "+39 350 1111111" in events[-1], events[-1]
ch = n.sim_info()["changed"]
assert ch == {"time": 300, "old_iccid": "8939880841024179213", "new_iccid": "8939010000123456789", "old_phone": "+39 350 1111111"}, ch
assert n.sim_info()["phone"] == ""                       # il numero era della SIM vecchia
n.remember_iccid("8939010000123456789", 400); assert n.sim_info()["changed"]["time"] == 300   # resta finche' non confermato
n.acknowledge_sim_change(); assert n.sim_info()["changed"] is None
n.remember_iccid(None); assert n.sim_info()["iccid"] == "8939010000123456789"
# numero di telefono: vuoto ammesso, poi inserito in seguito
assert n.sim_info()["phone"] == ""
assert n.set_sim_phone("  +39 351   1234567 ") == "+39 351 1234567" and n.sim_info()["phone"] == "+39 351 1234567"
assert n.set_sim_phone("") == "" and n.sim_info()["phone"] == ""
for bad in ("abc", "+39-351", "12", "+39 351 1234567 1234567 99"):
    try:
        n.set_sim_phone(bad); raise SystemExit("accettato: %r" % bad)
    except ValueError:
        pass
# controllo periodico: solo con LTE acceso, ogni ora
calls = []
n.read_iccid = lambda st: calls.append(1) or "8939010000123456789"
st = n.load_settings(); st["enabled"]["lte"] = False; n.save_settings(st)
n.check_sim(n.load_settings(), 5000); assert not calls                 # LTE disabilitato: niente
st["enabled"]["lte"] = True; n.save_settings(st)
n.LTE_RADIO["on"] = False; n.check_sim(n.load_settings(), 5000); assert len(calls) == 1   # anche con la radio spenta
n.check_sim(n.load_settings(), 5000 + 600); assert len(calls) == 1
n.check_sim(n.load_settings(), 5000 + 3600); assert len(calls) == 2
# IMEI del modem
assert n.parse_imei(["868909078545780"]) == "868909078545780"            # Air780E, AT+CGSN
assert n.parse_imei(['+CGSN: "868909078545780"']) == "868909078545780"
assert n.parse_imei(["ERROR"]) is None and n.parse_imei(["12345"]) is None
events.clear()
n.remember_imei("868909078545780", 10); assert "modem letto: IMEI 868909078545780" in events[-1]
n.remember_imei("868909078545780", 20); assert len(events) == 1
n.remember_imei("861234567890123", 30); assert "MODEM CAMBIATO" in events[-1] and "prima 868909078545780" in events[-1]
assert n.sim_info()["imei"] == "861234567890123" and n.sim_info()["iccid"]   # ICCID conservato
n.remember_iccid(n.sim_info()["iccid"], 40); assert n.sim_info()["imei"] == "861234567890123"  # e viceversa
print("SIM DATI OK")

from flask import Flask
from flask_login import LoginManager
import network_routes
app = Flask(__name__); app.secret_key = "x"; LoginManager(app).user_loader(lambda uid: None)
app.register_blueprint(network_routes.blueprint); c = app.test_client()
assert c.get("/api/network/sim").status_code in (302, 401)
app.config["LOGIN_DISABLED"] = True
assert c.post("/api/network/sim", json={"phone": "+39 351 7654321"}).get_json()["phone"] == "+39 351 7654321"
assert c.post("/api/network/sim", json={"phone": "x1"}).status_code == 400
assert c.get("/api/network/sim").get_json()["iccid"] == "8939010000123456789"
n.remember_iccid("8939880841024179213", 9000); assert c.get("/api/network/sim").get_json()["changed"]
r = c.post("/api/network/sim", json={"acknowledge": True}).get_json()
assert r["changed"] is None and r["phone"] == ""
print("SIM ROUTE OK")
