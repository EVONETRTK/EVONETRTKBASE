exec(open("test_network_page.py", encoding="utf-8").read().split("fake = FakeNM()")[0])
events = []; n.log = lambda m: events.append(m)
line = b'#BESTNAVA,97,GPS,FINE,2439,156894000,0,0,18,8;SOL_COMPUTED,FIXEDPOS,40.83,16.54,490.99,0.0,WGS84,0,0,0,"1",0.000,11.000,13,7,7,0,1,02,14,41,SOL_COMPUTED,DOPPLER_VELOCITY*d2972844'
state = {"heard": 800}
def session(command=None, tag=None, listen=0.0):
    if command == b"BESTNAVA": return 0, line
    return state["heard"], None
n.receiver_session = session
assert n.receiver_satellites() == {"tracked": 13, "used": 7, "solution": "FIXEDPOS"}
temps = {}
n.check_receiver_output(0, temps, False); assert not events and "satellites" not in temps
n.check_receiver_output(60, temps, True); assert temps["satellites"]["tracked"] == 13 and not events
state["heard"] = 0
n.check_receiver_output(120, temps, False)
assert "senza dati: 13 satelliti tracciati, 7 usati (FIXEDPOS)" in events[-1], events
n.check_receiver_output(180, temps, False); assert len(events) == 1          # un solo avviso
state["heard"] = None                                                          # servizio in riavvio
n.check_receiver_output(240, temps, False); assert len(events) == 1
state["heard"] = 900
n.check_receiver_output(720, temps, False)
assert "di nuovo con dati dopo 10 minuti" in events[-1], events
# risposta assente / formato inatteso
line = None; assert n.receiver_satellites() is None
line = b"#BESTNAVA,1;SOL,X"; assert n.receiver_satellites() is None
print("SILENZIO RICEVITORE OK")
