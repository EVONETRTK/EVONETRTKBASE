""" Test: controllo internet per interfaccia, recupero LTE, traffico, eventi, password hotspot, importazione """
exec(open("test_network_page.py", encoding="utf-8").read().split("fake = FakeNM()")[0])
fake = FakeNM()
n.run_cmd = fake
events = []
real_log = n.log
n.log = lambda m: (events.append(m), real_log(m))

# --- password dell'hotspot generata una volta, diversa per ogni base
s1 = n.load_settings()
pw = s1["hotspot"]["password"]
assert len(pw) == 10 and all(c in n.PASSWORD_CHARS for c in pw)
assert n.load_settings()["hotspot"]["password"] == pw          # non cambia a ogni lettura
os.remove(n.SETTINGS_FILE)
assert n.load_settings()["hotspot"]["password"] != pw          # un'altra base -> un'altra password
print("password hotspot OK")

# --- WiFi collegato ma senza internet, LTE ok -> WiFi scavalcato, poi ripristinato
n.apply_interfaces(n.load_settings())
st = n.load_settings()
assert n.get_status()["internet_device"] == "wlan0"
VIA.update({"wlan0": False, "usb0": True})
health = {}
t = 1000
n.check_health(st, health, t)                       # primo fallimento: si aspetta HEALTH_FAIL
assert fake.devices["wlan0"].get("rt_metric") is None
n.check_health(st, health, t + 60)
assert fake.devices["wlan0"]["rt_metric"] == 200 + n.DEGRADE_METRIC
assert n.get_status()["internet_device"] == "usb0" and "wlan0" in n.DEGRADED
s = n.get_status()
w = [i for i in s["interfaces"] if i["device"] == "wlan0"][0]
assert w["health"] == {"ok": False, "degraded": True}
# la riapplicazione periodica non deve annullare lo scavalcamento
n.apply_interfaces(st)
assert fake.devices["wlan0"]["rt_metric"] == 200 + n.DEGRADE_METRIC
# internet torna sul WiFi
VIA["wlan0"] = True
n.check_health(st, health, t + 90)
assert fake.devices["wlan0"]["rt_metric"] == 200 + n.DEGRADE_METRIC   # si aspetta HEALTH_RECOVER
n.check_health(st, health, t + 150)
assert fake.devices["wlan0"]["rt_metric"] == 200 and "wlan0" not in n.DEGRADED
assert n.get_status()["internet_device"] == "wlan0"
print("scavalcamento OK")

# --- LTE senza internet: riconnessione, riaggancio, reset del modem
sent = []
n.find_at_port = lambda settings: "/dev/ttyUSB2"
n.at_command = lambda port, cmd, timeout=5: (sent.append(cmd), (True, []))[1]
VIA.update({"wlan0": True, "usb0": False})
health = {}
fake.log.clear()
for dt in range(0, 1000, 30):
    n.check_health(st, health, 5000 + dt)
assert any(a[1:3] == ["device", "disconnect"] and a[3] == "usb0" for a in fake.log)
assert fake.devices["usb0"]["rt_metric"] == 300 + n.DEGRADE_METRIC   # dopo la riconnessione resta scavalcata
assert sent == ["AT+CFUN=0", "AT+CFUN=1", "AT+CFUN=1,1"], sent
assert any("riavvio il modem" in e for e in events)
# dopo il ciclo ricomincia solo dopo LTE_RECOVERY_RESTART
before = len(sent)
for dt in range(1000, 2600, 30):
    n.check_health(st, health, 5000 + dt)
assert len(sent) == before
n.check_health(st, health, 5000 + 900 + n.LTE_RECOVERY_RESTART)
n.check_health(st, health, 5000 + 900 + n.LTE_RECOVERY_RESTART + 300)
assert any(a[1:3] == ["device", "disconnect"] for a in fake.log[-10:])
print("recupero LTE OK")

# --- traffico LTE: giorno/mese, contatori che ripartono, soglia
counters = {"usb0": 0}
n.lte_counters = lambda: dict(counters)
st = n.load_settings()
st["lte"]["monthly_limit_mb"] = 100
state = {}
n.traffic_update(state, st)                  # prima lettura: base
counters["usb0"] = 50 * 1048576
n.traffic_update(state, st)
assert state["month_bytes"] == 50 * 1048576
counters["usb0"] = 85 * 1048576
n.traffic_update(state, st)
assert 80 in state["warned"] and any("80%" in e for e in events)
counters["usb0"] = 10 * 1048576               # interfaccia ricomparsa: contatore ripartito
n.traffic_update(state, st)
assert state["month_bytes"] == 95 * 1048576
counters["usb0"] = 20 * 1048576
n.traffic_update(state, st)
assert state["month_bytes"] == 105 * 1048576 and 100 in state["warned"]
n.write_json(n.TRAFFIC_FILE, state)
settings = n.load_settings()
settings["lte"]["monthly_limit_mb"] = 100
n.save_settings(settings)
tr = n.get_status()["traffic"]
assert tr["month_mb"] == 105.0 and tr["percent"] == 105, tr
state["month"] = "2000-01"                    # cambio mese
n.traffic_update(state, st)
assert state["month_bytes"] == 0 and state["warned"] == []
print("traffico OK")

# --- registro eventi
ev = n.read_events()
assert ev and ev[0]["text"].startswith("traffico LTE") and len(ev[0]["time"]) == 19
print("eventi OK")

# --- importazione con ripristino
VIA.clear()
INTERNET["ok"] = True
data = {"enabled": {"ethernet": True, "wifi": True, "lte": True}, "order": ["lte", "wifi", "ethernet"],
        "hotspot": {"ssid": "BASE-2", "password": "altrabase99"}, "lte": {"apn": "ibox.tim.it"}, "sconosciuto": 1}
assert n.import_settings(data, print)
imp = n.load_settings()
assert imp["order"] == ["lte", "wifi", "ethernet"] and imp["hotspot"]["ssid"] == "BASE-2" and "sconosciuto" not in imp
assert fake.cons["Rete-Hotspot"]["s"]["802-11-wireless.ssid"] == "BASE-2"
print("importazione OK")

print("\nFUNZIONI NUOVE OK")
