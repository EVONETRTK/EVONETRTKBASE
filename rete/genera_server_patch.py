""" Rigenera Install/server_py_network.patch: le modifiche della pagina Rete a web_app/server.py.

    Il punto di partenza e' rete/riferimento/server_elt.py = server.py di RTKBase 2.7.0 con gia' applicata
    la patch ufficiale di ELT (server_py.patch). Se ELT cambia server.py, aggiornare prima quel file.
    Uso:  python rete/genera_server_patch.py
"""
import os
import difflib

RETE = os.path.dirname(os.path.abspath(__file__))
INSTALL = os.path.join(RETE, "..", "Install")
s = open(os.path.join(RETE, "riferimento", "server_elt.py"), encoding="utf-8").read()
original = s


def rep(old, new):
    global s
    assert s.count(old) == 1, old
    s = s.replace(old, new, 1)


rep("import network_infos\n", "import network_infos\nimport network_routes\n")
rep("login.login_view = 'login_page'\n",
    "login.login_view = 'login_page'\napp.register_blueprint(network_routes.blueprint)  # pagina \"Rete\"\n")

# Check update: dal repository EVONETRTKBASE (canale scelto nella pagina Rete) invece che da quello di ELT
rep('''    print("Check update ELT started. branch:", branch)
''', '''    print("Check update ELT started. branch:", branch)
    # EVONETRTKBASE: versioni dal nostro repository, canale scelto nella pagina Rete (il ramo ricevuto e' ignorato)
    new_release = network_routes.check_update_for_settings()
    socketio.emit("new release", json.dumps(new_release), namespace="/test")
    return new_release
''')

# Update: install.sh dal nostro repository con impronta SHA-256 verificata, copia di sicurezza prima
rep('''    if update_file is None:
        #Download update
        #update_archive = download_update(update_url)
        try:
            response = requests.get(update_url)
            if response.ok:
                with open(update_archive, "wb") as f:
                    f.write(response.content)
                print("update downloaded in",update_archive)
            else:
                error = update_url + " not downloded, error " + str(response.status_code)
                socketio.emit("downloading_update", json.dumps({"result": 'false', "error" : error}), namespace="/test")
                return
        except Exception as e:
            error = "Error: Can't download update - " + repr(e)
            print(error)
            socketio.emit("downloading_update", json.dumps({"result": 'false', "error" : error}), namespace="/test")
            return
    else:
        #update from file
        update_file.save(update_archive)
        print("update stored in",update_archive)

    os.chmod(update_archive,0o755)
''', '''    if update_file is None:
        # EVONETRTKBASE: install.sh dal nostro repository, impronta SHA-256 verificata prima di eseguirlo
        error = network_routes.download_update(update_archive)
        if error:
            print(error)
            socketio.emit("downloading_update", json.dumps({"result": 'false', "error" : error}), namespace="/test")
            return
        print("update downloaded in",update_archive)
    else:
        #update from file
        update_file.save(update_archive)
        print("update stored in",update_archive)

    network_routes.before_update()   # copia di sicurezza di pannello e impostazioni
    os.chmod(update_archive,0o755)
''')

diff = difflib.unified_diff(original.splitlines(keepends=True), s.splitlines(keepends=True),
                            "a/web_app/server.py", "b/web_app/server.py")
out = "".join(diff)
with open(os.path.join(INSTALL, "server_py_network.patch"), "w", encoding="utf-8", newline="\n") as f:
    f.write(out)
print(out)
