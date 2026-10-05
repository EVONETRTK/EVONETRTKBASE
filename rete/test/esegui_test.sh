#!/bin/bash
# Esegue tutti i test della pagina Rete. Serve Python 3 con flask, flask-login e werkzeug:
#   python -m venv venv && venv/bin/pip install flask flask-login werkzeug   (su Windows: venv\Scripts\pip)
# Uso: rete/test/esegui_test.sh [python]
cd "$(dirname "$0")"
PY=${1:-${PYTHON:-python3}}
INSTALL=../../Install
cp "$INSTALL/network.html" "$INSTALL/network_access.html" flaskapp/templates/
cp "$INSTALL/network.js" "$INSTALL/qrcode.min.js" flaskapp/static/
failed=0
for t in test_*.py; do
   result=$("$PY" "$t" 2>&1 | tail -1)
   if [[ "$result" == *OK* ]]; then
      echo "ok      $t: $result"
   else
      echo "FALLITO $t: $result"
      failed=1
   fi
done
exit $failed
