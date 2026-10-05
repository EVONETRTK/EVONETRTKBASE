#!/bin/bash
# Porta la versione modificata di ELT_RTKBase (pagina "Rete") su una nuova versione ufficiale di ELT_RTKBase.
#
#   ./rete/aggiorna_da_elt.sh prepara            salva le nostre modifiche all'installer in rete/installer.patch
#                                                (da rilanciare ogni volta che si modificano install_script.sh,
#                                                create_release.sh, uninstall.sh o .gitattributes)
#   ./rete/aggiorna_da_elt.sh aggiorna [branch] [cartella]  scarica ELT_RTKBase ufficiale (branch "main" se non indicato)
#                                                in una cartella NUOVA accanto a questa, ci rimette le nostre
#                                                modifiche, controlla le patch e genera install.sh
#
# La cartella attuale non viene mai modificata da "aggiorna".

set -u

REPO_URL=https://github.com/GNSSOEM/ELT_RTKBase.git
SCRIPT_DIR=$(cd "$(dirname "${0}")" && pwd)
OUR_ROOT=$(dirname "${SCRIPT_DIR}")
OUR_INSTALL=${OUR_ROOT}/Install
INSTALLER_PATCH=${SCRIPT_DIR}/installer.patch
BASE_COMMIT=${SCRIPT_DIR}/base_elt_commit.txt

# file nuovi della pagina Rete (copiati cosi' come sono)
NEW_FILES="network_page.py network_routes.py network.html network.js network_access.html qrcode.min.js
           90-rtkbase-network.conf 90-rtkbase-journald.conf
           rtkbase_network_watch.service rtkbase_hotspot_dns.conf
           server_py_network.patch base_html_network.patch"
# file di ELT che modifichiamo (le modifiche stanno in installer.patch)
INSTALLER_FILES="Install/install_script.sh Install/create_release.sh Install/uninstall.sh Install/UnicoreConfigure.sh Install/UM980_RTCM3_OUT.txt Install/UM982_RTCM3_OUT.txt .gitattributes"

ERRORS=0

fail(){
   echo "ERRORE: ${1}" >&2
   exit 1
}

problem(){
   echo "  PROBLEMA: ${1}"
   ERRORS=$((ERRORS + 1))
}

prepara(){
   cd "${OUR_ROOT}" || fail "cartella ${OUR_ROOT} non trovata"
   git rev-parse HEAD >/dev/null 2>&1 || fail "${OUR_ROOT} non e' un clone git di ELT_RTKBase"
   git diff HEAD -- ${INSTALLER_FILES} > "${INSTALLER_PATCH}" || fail "git diff non riuscito"
   git rev-parse HEAD > "${BASE_COMMIT}"
   echo "Salvate in rete/installer.patch le modifiche a: ${INSTALLER_FILES}"
   echo "Versione ELT di partenza: $(cat "${BASE_COMMIT}")"
}

check_web_patches(){
   # Applica, come fa l'installer, le patch di ELT e poi le nostre al RTKBase contenuto in rtkbase_install.sh
   local install_dir=${1}
   local tmp
   tmp=$(mktemp -d)
   local line
   line=$(awk '/^__ARCHIVE__/ {print NR + 1; exit 0; }' "${install_dir}/rtkbase_install.sh")
   if [[ -z "${line}" ]] || ! tail -n+"${line}" "${install_dir}/rtkbase_install.sh" | tar xJf - -C "${tmp}" 2>/dev/null; then
      problem "impossibile estrarre RTKBase da rtkbase_install.sh (serve tar con supporto xz)"
      rm -rf "${tmp}"
      return
   fi
   local web=${tmp}/rtkbase/web_app
   echo "  RTKBase contenuto: $(grep '^version=' "${tmp}/rtkbase/settings.conf.default" | cut -d= -f2)"

   patch -s -f "${web}/server.py" "${install_dir}/server_py.patch" >/dev/null \
      || problem "la patch server_py.patch di ELT non si applica (controllare la nuova versione di ELT)"
   patch -s -f "${web}/templates/base.html" "${install_dir}/base_html.patch" >/dev/null \
      || problem "la patch base_html.patch di ELT non si applica (controllare la nuova versione di ELT)"

   if patch -s -f "${web}/server.py" "${install_dir}/server_py_network.patch"; then
      echo "  server_py_network.patch: OK"
      if python3 -c "" >/dev/null 2>&1; then      # su Windows "python3" puo' essere solo l'alias dello Store
         python3 -m py_compile "${web}/server.py" 2>/dev/null || problem "server.py con le nostre modifiche non compila"
      fi
   else
      problem "server_py_network.patch non si applica: va rifatta sul nuovo server.py"
   fi
   if patch -s -f "${web}/templates/base.html" "${install_dir}/base_html_network.patch"; then
      echo "  base_html_network.patch: OK"
   else
      problem "base_html_network.patch non si applica: va rifatta sul nuovo base.html"
   fi
   rm -rf "${tmp}"
}

aggiorna(){
   local branch=${1:-main}
   [[ -s "${INSTALLER_PATCH}" ]] || fail "manca rete/installer.patch: lancia prima \"${0} prepara\""
   for f in ${NEW_FILES}; do
      [[ -f "${OUR_INSTALL}/${f}" ]] || fail "manca ${OUR_INSTALL}/${f}"
   done

   local work
   work=$(mktemp -d)
   echo "Scarico ELT_RTKBase ufficiale (branch ${branch})..."
   git clone -q --depth 1 --branch "${branch}" "${REPO_URL}" "${work}/elt" || fail "download da ${REPO_URL} non riuscito"

   local version
   version=$(grep -o '"version"[^,}]*' "${work}/elt/Description.json" | grep -o '[0-9]\+' | head -n 1)
   local dest
   dest=${2:-"$(dirname "${OUR_ROOT}")/ELT_RTKBase_rete_v${version:-nuova}"}
   if [[ -d "${dest}" ]] && [[ -z "$(ls -A "${dest}")" ]]; then
      # cartella vuota rimasta (es. bloccata da un editor aperto): la riuso
      (shopt -s dotglob; mv "${work}/elt/"* "${dest}/") || fail "impossibile spostare i file in ${dest}"
   else
      [[ -e "${dest}" ]] && fail "la cartella ${dest} esiste gia': rinominala o cancellala e riprova"
      mv "${work}/elt" "${dest}" || fail "impossibile creare ${dest}"
   fi
   rm -rf "${work}"
   echo "Nuova versione ELT: ${version:-?}  ->  ${dest}"
   if [[ -f "${BASE_COMMIT}" ]]; then
      echo "Versione ELT di partenza delle nostre modifiche: $(cut -c1-12 "${BASE_COMMIT}"), nuova: $(git -C "${dest}" rev-parse --short=12 HEAD)"
   fi

   echo "1) Copio i file della pagina Rete"
   for f in ${NEW_FILES}; do
      cp "${OUR_INSTALL}/${f}" "${dest}/Install/" || problem "copia di ${f} non riuscita"
   done
   cp -r "${SCRIPT_DIR}" "${dest}/rete"

   echo "2) Applico le modifiche all'installer"
   if (cd "${dest}" && patch -p1 -f --no-backup-if-mismatch < "${INSTALLER_PATCH}" >/dev/null); then
      echo "  installer.patch: OK"
   else
      problem "installer.patch non si applica del tutto: vedi i file .rej in ${dest}"
      (cd "${dest}" && find . -name "*.rej" -print | sed 's/^/    /')
   fi
   for f in install_script.sh create_release.sh uninstall.sh; do
      bash -n "${dest}/Install/${f}" 2>/dev/null || problem "${f} ha errori di sintassi dopo le modifiche"
   done

   echo "3) Controllo le patch sul RTKBase contenuto nella nuova versione"
   check_web_patches "${dest}/Install"

   if [[ ${ERRORS} -ne 0 ]]; then
      echo
      echo "FINITO CON ${ERRORS} PROBLEMI: install.sh NON generato. Correggi in ${dest} e poi lancia"
      echo "  cd \"${dest}/Install\" && ./create_release.sh"
      exit 2
   fi

   echo "4) Genero install.sh"
   if (cd "${dest}/Install" && ./create_release.sh >/dev/null) && [[ -s "${dest}/install.sh" ]]; then
      echo "  ${dest}/install.sh pronto"
   else
      echo "  create_release.sh non riuscito qui (serve tar con xz, meglio su Linux/Raspberry):"
      echo "  cd \"${dest}/Install\" && ./create_release.sh"
   fi
   echo
   echo "TUTTO OK. Prima di aggiornare le basi, provalo su una base di test:"
   echo "  Settings con ?update=manual in fondo all'indirizzo -> Check update -> carica install.sh"
}

case "${1:-}" in
   prepara)  prepara ;;
   aggiorna) aggiorna "${2:-main}" "${3:-}" ;;
   *)        sed -n '2,13p' "${0}" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
