#!/bin/bash
# Pubblica una versione di EVONETRTKBASE sul repository GitHub (aggiornamento online delle basi).
#
#   rete/rilascia.sh prova "novita' 1" "novita' 2" ...   test, nuova revisione, install.sh, Description.json,
#                                                       commit e push sul ramo "prova" (base di test)
#   rete/rilascia.sh promuovi                           porta su "main" (canale stabile, basi in campo)
#                                                       l'ultima versione del ramo "prova", gia' provata
#   rete/rilascia.sh stato                              versioni pubblicate sui due canali
#
# Variabili: PYTHON (python con flask per i test), REMOTE (nome del remote git, default "evonet").
# Le basi non installano mai da sole: avvisano nella pagina Rete, si installa da Settings, Check update.

set -u

REPO=EVONETRTK/EVONETRTKBASE
REMOTE=${REMOTE:-evonet}
RAW=https://raw.githubusercontent.com/${REPO}/refs/heads
ROOT=$(cd "$(dirname "${0}")/.." && pwd)
INSTALLER=${ROOT}/Install/install_script.sh

fail(){
   echo "ERRORE: ${1}" >&2
   exit 1
}

remote_version(){        # versione pubblicata su un ramo (0 se non c'e')
   local v
   v=$(curl -fsS -m 20 "${RAW}/${1}/Description.json?$(date +%s)" 2>/dev/null | grep -o '"version": *"[0-9]*"' | grep -o '[0-9][0-9]*')
   echo "${v:-0}"
}

label(){                 # 19801 -> 1.9.8-01
   echo "${1}" | sed 's/^\(.\)\(.\)\(.\)$/\1.\2.\3/;t;s/^\(.\)\(.\)\(.\)\(..*\)$/\1.\2.\3-\4/'
}

cd "${ROOT}" || fail "cartella ${ROOT}"
git remote get-url "${REMOTE}" >/dev/null 2>&1 || fail "manca il remote git ${REMOTE}: git remote add ${REMOTE} https://github.com/${REPO}.git"

case "${1:-}" in
stato)
   echo "stabile (main): $(label "$(remote_version main)")"
   echo "prova:          $(label "$(remote_version prova)")"
   exit 0
   ;;
promuovi)
   git fetch -q "${REMOTE}" || fail "git fetch"
   v=$(remote_version prova)
   [[ "${v}" != 0 ]] || fail "nessuna versione sul ramo prova"
   echo "Porto su stabile (main) la versione $(label "${v}") gia' pubblicata su prova"
   git push "${REMOTE}" "${REMOTE}/prova:refs/heads/main" || fail "push su main (main ha commit che prova non ha?)"
   echo "Fatto: le basi sul canale stabile vedranno la $(label "${v}") entro 12 ore (o con Controlla adesso)."
   exit 0
   ;;
prova)
   shift
   [[ $# -gt 0 ]] || fail "indicare almeno una novita': rete/rilascia.sh prova \"cosa cambia\""
   ;;
*)
   sed -n '2,12p' "${0}"
   exit 1
   ;;
esac

echo "== 1. test"
rete/test/esegui_test.sh "${PYTHON:-python3}" || fail "test falliti: niente rilascio"

echo "== 2. patch rigenerate"
"${PYTHON:-python3}" rete/genera_server_patch.py >/dev/null || fail "genera_server_patch.py"
rete/aggiorna_da_elt.sh prepara >/dev/null 2>&1 || fail "aggiorna_da_elt.sh prepara"

echo "== 3. numero di versione"
current=$(sed -n 's/^NEW_VERSION=\([0-9]*\)$/\1/p' "${INSTALLER}")
published=$(( $(remote_version prova) > $(remote_version main) ? $(remote_version prova) : $(remote_version main) ))
version=${current}
if [[ ${version} -le ${published} ]]; then
   version=$((published + 1))
fi
[[ ${#version} -eq 5 ]] || fail "versione ${version} non nel formato ELT(3 cifre)+revisione(2 cifre)"
sed -i "s/^NEW_VERSION=${current}$/NEW_VERSION=${version}/" "${INSTALLER}"
echo "   $(label "${published}") pubblicata -> nuova $(label "${version}")"
rete/aggiorna_da_elt.sh prepara >/dev/null 2>&1 || fail "aggiorna_da_elt.sh prepara"

echo "== 4. install.sh"
(cd Install && bash create_release.sh >/dev/null) || fail "create_release.sh"
[[ -s install.sh ]] || fail "install.sh non creato"
sha=$(sha256sum install.sh | cut -d' ' -f1)

echo "== 5. Description.json"
comment=$(printf '%s\\r\\n' "$@" | sed 's/"/\\"/g; s/\\r\\n$//')
cat > Description.json <<EOF
{
  "version": "${version}",
  "new_release": "EVONETRTKBASE $(label "${version}")",
  "comment": "${comment}",
  "sha256": "${sha}"
}
EOF

echo "== 6. commit e pubblicazione sul ramo prova"
git add -A . || fail "git add"
git update-index --chmod=+x rete/*.sh rete/test/esegui_test.sh install.sh || fail "git update-index"
git commit -q -m "EVONETRTKBASE $(label "${version}")" -m "$(printf '%s\n' "$@")" ${COMMIT_TRAILER:+-m "${COMMIT_TRAILER}"} || fail "git commit"
git push "${REMOTE}" "HEAD:refs/heads/prova" || fail "git push"
echo "Pubblicata EVONETRTKBASE $(label "${version}") sul canale prova (sha256 ${sha})."
echo "Dopo qualche giorno senza problemi sulla base di prova: rete/rilascia.sh promuovi"
