import sys, os
exec(open("test_network_page.py", encoding="utf-8").read().split("fake = FakeNM()")[0])
events = []; n.log = lambda m: events.append(m)
n.PAUSE_FILE = os.path.join(tmp, "pause.json")
open(n.RTKBASE_SETTINGS, "w").write("[main]\ncom_port='ttyGNSS'\n")
state = {"service": "activating", "opens": False, "name": "1-1.3"}
resets, runs = [], []
n.run = lambda args, timeout=15: (runs.append(args), state["service"] if args[:2] == ["systemctl", "is-active"] else "")[1]
n.port_opens = lambda path: state["opens"]
n.receiver_usb_name = lambda port: state["name"]
def fake_reset(name):
    resets.append(name); state["opens"] = True
n.reset_usb_device = fake_reset
# ricevitore sano: ricorda il dispositivo USB
state.update(service="active"); n.check_receiver_port(1000); assert n.RECEIVER_PORT["usb"] == "1-1.3" and not resets
# porta bloccata e servizio che non parte: dopo 3 minuti reset, poi restart del servizio
state.update(service="activating", opens=False, name=None)
n.check_receiver_port(2000); n.check_receiver_port(2120); assert not resets
n.check_receiver_port(2180)
assert resets == ["1-1.3"] and ["systemctl", "restart", "str2str_tcp.service"] in runs
assert "bloccata da 3 minuti" in events[-2] and "di nuovo disponibile" in events[-1], events
# ancora bloccata subito dopo: niente secondo reset prima di 15 minuti
state["opens"] = False
for t in (2400, 2700, 3000):
    n.check_receiver_port(t)
assert len(resets) == 1
n.check_receiver_port(2180 + 900); assert len(resets) == 2
# servizio fermo ma porta che si apre (es. arresto voluto): niente reset
resets.clear(); n.RECEIVER_PORT.update(bad_since=None, last_reset=0)
state["opens"] = True
for t in range(10000, 11000, 60):
    n.check_receiver_port(t)
assert not resets
# in pausa (misura HAS): niente reset
state["opens"] = False; n.set_pause(3600, "prova")
for t in range(20000, 21000, 60):
    n.check_receiver_port(t)
assert not resets
n.clear_pause()
# dispositivo non trovato: solo avviso
n.RECEIVER_PORT.update(bad_since=None, last_reset=0, usb=None); state["name"] = None
for t in range(30000, 30300, 60):
    n.check_receiver_port(t)
assert not resets and "controllare il cavo" in events[-1]
print("PORTA USB RICEVITORE OK")
