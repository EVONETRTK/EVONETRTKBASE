exec(open("test_network_page.py", encoding="utf-8").read().split("fake = FakeNM()")[0])
import socket as S, threading
n.TEMPS_FILE = os.path.join(tmp, "temps.json")
real_receiver_temperature = n.receiver_temperature
st = n.load_settings()
events = []
n.log = lambda m: events.append(m)

# 1) lettura HWSTATUSA reale, con la risposta mescolata a dati binari RTCM
srv = S.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1); port = srv.getsockname()[1]
def serve():
    c, _ = srv.accept(); c.recv(100)
    c.sendall(b"\xd3\x00\x13\x01\x02binario$command,HWSTATUSA,response: OK*14\r\n\xd3\x00\x05ab"
              b"#HWSTATUSA,97,GPS,FINE,2438,24440000,0,0,18,18;71035,0.902,1.020,1.805,1,-0.646,0.0,0x84,1,0x0370,0,0*537217fe\r\n")
    time.sleep(0.5); c.close()
threading.Thread(target=serve, daemon=True).start()
open(n.RTKBASE_SETTINGS, "w").write("[main]\nreceiver='Unicore_UM982'\ntcp_port='%d'\n" % port)
t = real_receiver_temperature()
print("HWSTATUSA ->", t)
assert t == 71.0
open(n.RTKBASE_SETTINGS, "w").write("[main]\nreceiver='u-blox_ZED-F9P'\ntcp_port='5015'\n")
assert real_receiver_temperature() is None               # non Unicore: non si interroga

# 2) avvisi con isteresi
vals = {"pi": 70.0, "rx": 71.0}
n.pi_temperature = lambda: vals["pi"]
n.receiver_temperature = lambda: vals["rx"]
n.modem_at = lambda s, c, timeout=5: (True, ["+CBC: 3864"])
n.LTE_RADIO["on"] = True
temps = {}
n.check_temperatures(st, temps, 0, True)
assert temps["pi"] == 70.0 and temps["receiver"] == 71.0 and temps["modem_mv"] == 3864 and not events, (temps, events)
vals["pi"] = 76.2; n.check_temperatures(st, temps, 30, False)
assert "Raspberry Pi alta" in events[-1]
n.check_temperatures(st, temps, 60, False); assert len(events) == 1           # nessun avviso ripetuto
vals["pi"] = 72.0; n.check_temperatures(st, temps, 90, False); assert len(events) == 1   # isteresi
vals["pi"] = 69.0; n.check_temperatures(st, temps, 120, False); assert "rientrata" in events[-1]
vals["rx"] = 82.0; n.check_temperatures(st, temps, 150, True); assert "ricevitore GNSS alta" in events[-1]
assert n.read_json(n.TEMPS_FILE, {})["receiver"] == 82.0
print(events)
print("TEMPERATURE OK")
