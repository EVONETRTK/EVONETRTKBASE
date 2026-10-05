""" Test: LTE su richiesta """
exec(open("test_network_page.py", encoding="utf-8").read().split("fake = FakeNM()")[0])
n.LTE_STATE_FILE = os.path.join(tmp, "lte.json")
fake = FakeNM()
n.run_cmd = fake
n.log = print

radio = {"on": True}
sent = []


def fake_at(settings, cmd, timeout=5):
    sent.append(cmd)
    if cmd == "AT+CFUN?":
        return True, ["+CFUN: %d" % (1 if radio["on"] else 0)]
    if cmd == "AT+CFUN=1":
        radio["on"] = True
    if cmd == "AT+CFUN=0":
        radio["on"] = False
    return True, []


n.modem_at = fake_at
n.modem_port_candidates = lambda: ["/dev/ttyACM0"]
n.apply_interfaces(n.load_settings())
st = n.load_settings()
assert st["lte"]["on_demand"] is True

health = {}
VIA.update({"wlan0": True, "usb0": False})
t = 1000
# WiFi ok: la radio resta accesa per LTE_IDLE_AFTER, poi si spegne
for dt in range(0, 330, 30):
    n.check_health(st, health, t + dt)
    n.lte_manage(st, health, t + dt)
    if dt < 300:
        assert radio["on"], dt
assert not radio["on"] and n.read_json(n.LTE_STATE_FILE, {})["idle"]
assert n.get_status()["lte_radio"]["idle"]
print("radio spenta con WiFi ok: OK")

# con la radio spenta l'LTE non viene controllato ne' recuperato
sent.clear()
for dt in range(330, 1500, 30):
    n.check_health(st, health, t + dt)
    n.lte_manage(st, health, t + dt)
assert "usb0" not in health and not any(c in ("AT+CFUN=1", "AT+CFUN=1,1") for c in sent), sent
print("nessun recupero LTE mentre e' in attesa: OK")

# WiFi senza internet: dopo LTE_WAKE_AFTER la radio si riaccende
VIA.update({"wlan0": False, "usb0": True})
t2 = t + 1500
n.check_health(st, health, t2)
n.lte_manage(st, health, t2)
assert not radio["on"]                      # WiFi collegato ma senza internet: aspetta
n.check_health(st, health, t2 + 60)
n.lte_manage(st, health, t2 + 60)
assert radio["on"] and not n.read_json(n.LTE_STATE_FILE, {})["idle"]
print("radio accesa quando il WiFi perde internet: OK")

# WiFi torna: resta accesa 5 minuti, poi si spegne
VIA.update({"wlan0": True})
for dt in range(90, 420, 30):
    n.check_health(st, health, t2 + dt)
    n.lte_manage(st, health, t2 + dt)
assert not radio["on"]
print("rispenta dopo il ritorno del WiFi: OK")

# LTE disabilitato -> radio spenta; su richiesta disattivato -> radio accesa
radio["on"] = True
n.LTE_RADIO.update(on=None, bad_since=None, good_since=None)
st["enabled"]["lte"] = False
n.lte_manage(st, health, t2 + 1000)
assert not radio["on"]
st["enabled"]["lte"] = True
st["lte"]["on_demand"] = False
n.lte_manage(st, health, t2 + 1030)
assert radio["on"]
print("disabilitato/sempre acceso: OK")

# servizio riavviato con radio gia' spenta e WiFi ok: resta spenta
radio["on"] = False
n.LTE_RADIO.update(on=None, bad_since=None, good_since=None)
st["lte"]["on_demand"] = True
sent.clear()
n.lte_manage(st, health, t2 + 2000)
assert not radio["on"] and "AT+CFUN=1" not in sent
print("riavvio del servizio con radio spenta: OK")
print("\nLTE SU RICHIESTA OK")

# segnale LTE per le barre
def at_sig(settings, cmd, timeout=5):
    if cmd == "AT+CSQ": return True, ["+CSQ: 22,0"]
    if cmd == "AT+COPS?": return True, ['+COPS: 0,2,"22288",7']
    return fake_at(settings, cmd, timeout)
n.modem_at = at_sig
n.LTE_RADIO["on"] = True
n.lte_read_signal(st); n.write_lte_state(st)
r = n.read_json(n.LTE_STATE_FILE, {})
assert r["signal"] == 71 and r["dbm"] == -69 and r["tech"] == "4G" and r["operator"] == "WindTre", r
n.LTE_RADIO["on"] = False
n.lte_read_signal(st); n.write_lte_state(st)
assert n.read_json(n.LTE_STATE_FILE, {})["signal"] is None
assert n.operator_name('"I TIM"') == "I TIM" and n.operator_name("22210") == "Vodafone" and n.operator_name("99999") == "99999"
print("SEGNALE LTE OK")
