exec(open("test_network_page.py", encoding="utf-8").read().split("fake = FakeNM()")[0])
fake = FakeNM(); n.run_cmd = fake
clock = {"t": 1000.0, "loops": 0}
n.time.time = lambda: clock["t"]
events = []
script = {}   # loop -> azione
class Stop(Exception): pass
def sleep(s):
    clock["t"] += s; clock["loops"] += 1
    if clock["loops"] in script: script[clock["loops"]]()
    if clock["loops"] > 120: raise Stop
n.time.sleep = sleep
n.log = lambda m: events.append((clock["loops"], m))
n.lte_pin_check = lambda s, force=False: None
def offline():
    INTERNET["ok"] = False
    fake.devices["wlan0"]["state"]="disconnected"; fake.cons["preconfigured"]["dev"]=None; fake.devices["wlan0"]["con"]=None
script[3] = offline                          # al giro 3 si perde internet
script[60] = lambda: INTERNET.update(ok=True)   # al giro 60 torna (es. LTE)
try: n.watch()
except Stop: pass
for e in events: print(e)
starts = [l for l, m in events if "avviato" in m]; stops = [l for l, m in events if "fermato" in m]
assert starts and starts[0] >= 3 + 12, starts          # 120 s = 12 giri da 10 s
assert stops and stops[0] - starts[0] >= 30, stops     # 300 s senza client -> riprova
assert len(starts) >= 2                                # poi riparte
assert stops[-1] >= 60 and not n.hotspot_active()      # internet tornato -> spento
print("WATCH OK")
