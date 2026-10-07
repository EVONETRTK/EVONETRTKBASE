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

# reset automatico dopo 10 minuti di silenzio, al massimo uno all'ora
n.RECEIVER_RESET_FILE = os.path.join(tmp, "rxreset.json")
sent, runs = [], []
def session2(command=None, tag=None, listen=0.0):
    if command:
        sent.append(command)
        return 0, (b"$command,RESET,response: OK*7a" if command == b"RESET" else line)
    return state["heard"], None
n.receiver_session = session2
n.run = lambda args, timeout=15: runs.append(args) or ""
line = b'#BESTNAVA,97,GPS,FINE,2439,1,0,0,18,8;SOL_COMPUTED,FIXEDPOS,40.83,16.54,490.99,0.0,WGS84,0,0,0,"1",0.000,11.000,11,3,3,0,1*00'
n.RECEIVER_OUTPUT.update(silent_since=None, reset_at=None, restart_at=None)
events.clear(); state["heard"] = 0
n.check_receiver_output(1000, temps, False)                       # inizio silenzio
n.check_receiver_output(1170, temps, False); assert b"RESET" not in sent   # meno di 3 minuti: ancora niente
n.check_receiver_output(1600, temps, False)                       # oltre 3 minuti: reset
assert b"RESET" in sent and "inviato RESET (confermato)" in events[-1], events
n.check_receiver_output(1630, temps, False)                       # 30 s dopo: riavvio del servizio
assert ["systemctl", "restart", "str2str_tcp.service"] in runs and "riavviato dopo il reset" in events[-1]
sent.clear()
n.check_receiver_output(1690, temps, False); assert b"RESET" not in sent   # un solo reset per silenzio
state["heard"] = 700
n.check_receiver_output(1750, temps, False)
assert "di nuovo con dati dopo 12 minuti, 2 minuti dopo il reset" in events[-1], events
# nuovo silenzio entro un'ora: niente secondo reset
state["heard"] = 0; sent.clear()
for t in (2000, 2200, 2500):
    n.check_receiver_output(t, temps, False)
assert b"RESET" not in sent
n.check_receiver_output(3000, temps, False)                       # passati 20 minuti: reset
assert b"RESET" in sent
print("RESET RICEVITORE OK")
