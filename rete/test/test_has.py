import sys, os, json, math
exec(open("test_network_page.py", encoding="utf-8").read().split("fake = FakeNM()")[0])
events = []; n.log = lambda m: events.append(m)
n.HAS_FILE = os.path.join(tmp, "has.json")
n.PAUSE_FILE = os.path.join(tmp, "pause.json")
open(n.RTKBASE_SETTINGS, "w").write("[main]\nposition='0.00 0.00 0.00'\nreceiver='Unicore_UM982'\ntcp_port='5015'\n")

# --- conversione ITRF2020 -> ETRF2000: in Italia ~1 m verso sud-ovest nel 2026, quota quasi uguale
lat, lon, h = 40.8337500, 16.5482000, 500.0
elat, elon, eh = n.itrf2020_to_etrf2000(lat, lon, h, 2026.77)
dn = (elat - lat) * 111132.0
de = (elon - lon) * 111320.0 * math.cos(math.radians(lat))
assert -0.9 < dn < -0.3 and -0.9 < de < -0.2 and abs(eh - h) < 0.15, (dn, de, eh - h)
assert 0.6 < math.hypot(dn, de) < 1.1, math.hypot(dn, de)
lat2, lon2, h2 = n._ecef_to_geo(*n._geo_to_ecef(lat, lon, h))          # andata e ritorno
assert abs(lat2 - lat) < 1e-10 and abs(lon2 - lon) < 1e-10 and abs(h2 - h) < 1e-4
assert abs(n.decimal_year(1791373161) - 2026.766) < 0.002            # 07/10/2026
print("ETRF2000 OK (spostamento %.2f m a sud, %.2f m a ovest)" % (-dn, -de))

# --- soluzione PPPNAVA (riga vera del 07/10)
line = (b'#PPPNAVA,97,GPS,FINE,2439,1,0,0,18,9;SOL_COMPUTED,PPP_CONVERGING,40.83375422815,16.54815297192,'
        b'513.8647,0.0000,WGS84,0.6740,1.6391,1.7348,"9901",11.000,0.000,20,14,14,13,1,00*00')
s = n.parse_pppnav(line)
assert s == {"type": "PPP_CONVERGING", "lat": 40.83375422815, "lon": 16.54815297192, "h": 513.8647,
             "slat": 0.674, "slon": 1.6391, "sh": 1.7348, "sv": 20, "used": 14}, s
assert n.parse_pppnav(None) is None and n.parse_pppnav(b"#PPPNAVA,1;SOL") is None

# --- media: solo le soluzioni convergenti, altrimenti la coda in convergenza sotto 1 m
conv = [[1791373161 + i * 30, "PPP_CONVERGING", 40.8, 16.5, 500.0, 2.0, 2.0, 3.0, 10] for i in range(30)]
good = [[1791374161 + i * 30, "PPP", 40.83375 + (i % 3 - 1) * 1e-7, 16.5482, 500.1, 0.12, 0.15, 0.3, 14]
        for i in range(30)]
r = n.has_result(conv + good, 0)
assert r["samples"] == 30 and r["kind"] == "convergente" and abs(r["itrf2020"]["lat"] - 40.83375) < 1e-7
assert r["spread"]["lat_m"] < 0.02 and abs(r["sigma"]["lat_m"] - 0.12) < 1e-9 and r["minutes"] in (14, 15)
assert n.has_result(conv, 0) is None                       # precisione troppo scarsa: niente risultato
tail = [[1791373161 + i * 30, "PPP_CONVERGING", 40.8, 16.5, 500.0, 0.4, 0.8, 1.2, 12] for i in range(80)]
assert n.has_result(tail, 0)["kind"].startswith("in convergenza")
print("MEDIA OK")

# --- ricevitore simulato
rx = {"mode": "MODE BASE 1 TIME 60 0 0 1", "has_ok": True, "ppp": line, "silent": False}
sent, runs = [], []
def commands(cmds, wait=1.5):
    sent.extend(cmds)
    out = []
    for c in cmds:
        if c == "CONFIG PPP ENABLE E6-HAS" and not rx["has_ok"]:
            out.append("$command,CONFIG PPP ENABLE E6-HAS,response: PARSING FAILED GRAMMAR ERROR*2A")
        else:
            out.append("$command,%s,response: OK*00" % c)
        if c.startswith("MODE ROVER"):
            rx["mode"] = "MODE ROVER SURVEY"
        if c == "CONFIG SIGNALGROUP 7 0":
            rx["mode"] = rx.get("mode_after_restore", "MODE BASE 1 TIME 60 0 0 1")
        if c == "RESET":
            rx["mode"] = "MODE BASE 1 TIME 60 0 0 1"
    return out
def session(command=None, tag=None, listen=0.0):
    if rx["silent"]:
        return 0, None
    if command == b"PPPNAVA":
        return 0, rx["ppp"]
    if command == b"MODE":
        return 900, ("#MODE,97,GPS,FINE,1,2,0,0,18,1;%s,*00" % rx["mode"]).encode()
    return 900, None
n.receiver_commands = commands
n.receiver_session = session
n.run = lambda args, timeout=15: runs.append(args) or ""

def tick_until(status, t, step=10, limit=10000):
    for _ in range(limit):
        n.has_tick(t)
        if n.has_state()["status"] == status:
            return t
        t += step
    raise SystemExit("stato %s non raggiunto: %s" % (status, n.has_state()))

st = n.has_start(1)
assert st["status"] == "starting" and n.pause_info() and n.pause_info()["until"] > 0
try:
    n.has_start(1); raise SystemExit("seconda misura accettata")
except ValueError:
    pass
t = 1791373161
n.has_tick(t)
assert ["systemctl", "stop", "str2str_ntrip_A.service"] in runs and "CONFIG SIGNALGROUP 3 6" in sent
assert n.has_state()["status"] == "switching"
n.has_tick(t + 5); assert n.has_state()["status"] == "switching"           # aspetta che il ricevitore riparta
t = tick_until("measuring", t + 10)
assert all(c in sent for c in n.HAS_SETUP)
# ricevitore che riparte da solo a meta' misura: nessuna risposta -> riconfigurazione, poi si continua
t += 30; n.has_tick(t)
rx["silent"] = True
for i in range(n.HAS_MAX_MISSES):
    t += 30; n.has_tick(t)
assert n.has_state()["status"] == "starting" and any("riconfiguro" in e for e in events)
rx["silent"] = False
sent.clear()
t = tick_until("measuring", t + 10)
assert "CONFIG SIGNALGROUP 3 6" in sent
# soluzioni convergenti fino alla fine
rx["ppp"] = line.replace(b"PPP_CONVERGING", b"PPP").replace(b"0.6740,1.6391,1.7348", b"0.1200,0.1500,0.3000")
t = tick_until("verifying", t + 10, step=30)
st = n.has_state()
assert st["result"] and st["result"]["kind"] == "convergente" and "CONFIG SIGNALGROUP 7 0" in sent
runs.clear()
t = tick_until("done", t + 10)
assert ["systemctl", "start", "str2str_ntrip_A.service"] in runs and n.pause_info() is None
print("MISURA OK (%d soluzioni)" % n.has_state()["result"]["samples"])

# --- usa la posizione e torna indietro (eseguiti dal servizio watch)
os.chmod(n.RTKBASE_SETTINGS, 0o644)
n.has_request("apply"); runs.clear()
n.has_tick(t + 100)
conf = open(n.RTKBASE_SETTINGS).read()
etrf = n.has_state()["result"]["etrf2000"]
assert "position='%.9f %.9f %.4f'" % (etrf["lat"], etrf["lon"], etrf["h"]) in conf, conf
assert ["systemctl", "restart", "rtkbase_web.service"] in runs and ["systemctl", "restart", "str2str_tcp.service"] in runs
assert n.has_state()["applied"]["old_position"] == "0.00 0.00 0.00"
n.has_request("undo"); n.has_tick(t + 200)
assert "position='0.00 0.00 0.00'" in open(n.RTKBASE_SETTINGS).read() and "applied" not in n.has_state()
try:
    n.has_request("undo"); raise SystemExit("undo senza posizione precedente")
except ValueError:
    pass
print("APPLICA/RIPRISTINA OK")

# --- annullamento
n.has_start(2); t = tick_until("measuring", t + 1000)
n.has_cancel(); t = tick_until("cancelled", t + 10)
assert n.pause_info() is None and n.has_state()["message"]
# --- ricevitore che rifiuta HAS: errore, ripristino comunque
rx["has_ok"] = False
n.has_start(1); t = tick_until("error", t + 1000)
assert "non accetta Galileo HAS" in n.has_state()["message"] and "CONFIG SIGNALGROUP 7 0" in sent
rx["has_ok"] = True
# --- ripristino difficile: il ricevitore non torna da base -> RESET
rx["mode_after_restore"] = "MODE ROVER SURVEY"; sent.clear()
n.has_start(1); t = tick_until("measuring", t + 1000)
n.has_cancel(); t = tick_until("cancelled", t + 10, step=30)
assert "RESET" in sent
print("ANNULLA/ERRORI/RESET OK")

# --- pausa: il guardiano non riavvia ALTAMURA, nessun reset del ricevitore
n.set_pause(3600, "prova")
svc_state = {"str2str_tcp.service": ("enabled", "active"), "str2str_ntrip_A.service": ("enabled", "inactive")}
def show(args, timeout=15):
    if args[:2] == ["systemctl", "show"]:
        return True, "\n\n".join("Id=%s\nUnitFileState=%s\nActiveState=%s" % (u, *svc_state.get(u, ("disabled", "inactive")))
                                 for u in args[3:]) + "\n", ""
    return True, "", ""
n.run_cmd = show; runs.clear()
n.guard_services(10000); n.guard_services(10100)
assert not any(a[:2] == ["systemctl", "start"] for a in runs)
n.RECEIVER_OUTPUT.update(silent_since=1, reset_at=None, restart_at=None)
n.check_receiver_output(20000, {}, False); assert n.RECEIVER_OUTPUT["silent_since"] is None
n.clear_pause(); n.guard_services(20000); n.guard_services(20100)
assert ["systemctl", "start", "str2str_ntrip_A.service"] in runs
print("PAUSA OK")

# --- route
from flask import Flask
from flask_login import LoginManager
import network_routes
app = Flask(__name__); app.secret_key = "x"; LoginManager(app).user_loader(lambda uid: None)
app.register_blueprint(network_routes.blueprint); c = app.test_client()
assert c.get("/api/network/has").status_code in (302, 401)
app.config["LOGIN_DISABLED"] = True
s = c.get("/api/network/has").get_json()
assert s["unicore"] and s["status"] == "cancelled" and "samples" not in s and s["hours_choices"]
assert c.post("/api/network/has", json={"action": "start", "hours": 3}).status_code == 400
assert c.post("/api/network/has", json={"action": "boh"}).status_code == 400
assert c.post("/api/network/has", json={"action": "start", "hours": 1}).get_json()["status"] == "starting"
assert c.post("/api/network/has", json={"action": "start", "hours": 1}).status_code == 400
assert c.post("/api/network/has", json={"action": "apply"}).status_code == 400   # misura in corso
print("HAS ROUTE OK")

# --- misura non affidabile (08/10, 6 ore dal balcone): dispersione di metri -> non utilizzabile
import random
random.seed(1)
noisy = [[1791373161 + i * 30, "PPP", 40.83375 + random.uniform(-2e-5, 2e-5), 16.5482 + random.uniform(-4e-5, 4e-5),
          494.5 + random.uniform(-2, 2), 0.19, 0.6, 0.76, 18] for i in range(40)]
r = n.has_result(noisy, 0)
assert not r["usable"] and any("orizzontale" in p for p in r["problems"]), r["problems"]
assert n.has_result(good, 0)["usable"]
assert not n.has_result(tail, 0)["usable"]                       # mai convergente
st = n.has_state(); st["status"] = "done"; st["result"] = r; n._has_save(st)
try:
    n.has_request("apply"); raise SystemExit("misura non affidabile accettata")
except ValueError as e:
    assert "non affidabile" in str(e)
st["result"] = {k: v for k, v in n.has_result(good, 0).items() if k not in ("usable", "problems")}   # versione vecchia
n._has_save(st)
try:
    n.has_request("apply"); raise SystemExit("risultato senza verifica accettato")
except ValueError:
    pass
print("MISURA NON AFFIDABILE BLOCCATA OK")
