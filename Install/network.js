// Pagina "Rete" di ELT_RTKBase: stato e gestione di Ethernet, WiFi, LTE e hotspot

$(document).ready(function () {

    const REFRESH_MS = 5000;
    const OPERATION_MS = 2000;

    const TITLES = {
        ethernet: "Ethernet",
        wifi: "WiFi",
        lte: "LTE"
    };

    const STATES = {
        connected:    ["Connessa", "badge-success"],
        connecting:   ["In connessione", "badge-warning"],
        disconnected: ["Non connessa", "badge-secondary"],
        unavailable:  ["Non disponibile", "badge-secondary"],
        unmanaged:    ["Non gestita", "badge-secondary"]
    };

    let lastStatus = null;
    let ifaceDraft = null;          // modifiche non ancora salvate a abilitazioni/priorità
    let operationId = null;
    let operationTimer = null;
    let savedProfiles = [];

    function escapeHtml(text) {
        return $("<div>").text(text === null || text === undefined ? "" : String(text)).html();
    }

    function showError(message) {
        if (message) {
            $("#net-error").removeClass("d-none").text(message);
        } else {
            $("#net-error").addClass("d-none");
        }
    }

    function postJson(url, data) {
        return $.ajax({url: url, type: "POST", contentType: "application/json", data: JSON.stringify(data), dataType: "json"});
    }

    function requestFailed(xhr) {
        let message = xhr.responseJSON && xhr.responseJSON.error ? xhr.responseJSON.error : "Richiesta non riuscita.";
        showError(message);
    }

    //### Stato ###

    // barre del segnale (0-4) da una percentuale; null = nessun segnale/non disponibile
    function bars(percent, title) {
        let level = 0;
        if (percent !== null && percent !== undefined) {
            level = percent >= 75 ? 4 : percent >= 50 ? 3 : percent >= 25 ? 2 : percent > 0 ? 1 : 0;
        }
        return '<span class="sig l' + level + '" title="' + escapeHtml(title || "") + '"><i></i><i></i><i></i><i></i></span>';
    }

    function wifiSignal(data) {
        let w = data.interfaces.find(function (i) { return i.kind === "wifi" && i.wifi; });
        return w ? w.wifi.signal : null;
    }

    function lteSignalTitle(r) {
        if (!r || r.on === false) {
            return r && r.idle ? "LTE in attesa (radio spenta)" : "radio LTE spenta";
        }
        return r.signal === null || r.signal === undefined ? "nessun segnale LTE"
            : r.signal + " % (" + r.dbm + " dBm)" + (r.tech ? " " + r.tech : "");
    }

    // "4G · WindTre" (vuoto con la radio spenta)
    function lteNetwork(r) {
        if (!r || !r.on) {
            return r && r.idle ? "in attesa" : "";
        }
        return [r.tech, r.operator].filter(function (x) { return x; }).join(" · ");
    }

    function row(label, value) {
        if (value === null || value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) {
            return "";
        }
        if (Array.isArray(value)) {
            value = value.join(", ");
        }
        return '<dt class="col-5">' + label + '</dt><dd class="col-7">' + escapeHtml(value) + '</dd>';
    }

    function renderCard(kind, interfaces, data) {
        let html = '<div class="card net-card h-100"><div class="card-header font-weight-bold">' + TITLES[kind];
        if (kind === "wifi") {
            let ws = wifiSignal(data);
            html += ' <span class="ml-2">' + bars(ws, ws !== null ? ws + " %" : "WiFi non collegato") + '</span>';
        } else if (kind === "lte" && data.lte_radio) {
            html += ' <span class="ml-2">' + bars(data.lte_radio.signal, lteSignalTitle(data.lte_radio)) + '</span>' +
                ' <span class="small text-muted font-weight-normal">' + escapeHtml(lteNetwork(data.lte_radio)) + '</span>';
        }
        if (!data.enabled[kind]) {
            html += ' <span class="badge badge-dark float-right">Disabilitata</span>';
        }
        html += '</div><div class="card-body">';

        if (interfaces.length === 0) {
            let msg = kind === "lte" ? "Nessun modem LTE rilevato" : "Interfaccia non presente";
            if (kind === "lte" && data.lte_serial_only) {
                msg = "Modem trovato ma non in modalità rete";
            }
            html += '<span class="badge badge-secondary">' + msg + '</span>';
            if (kind === "lte" && data.lte_serial_only) {
                html += '<p class="small text-muted mt-2 mb-0">Imposta il comando di attivazione nella sezione Modem LTE.</p>';
            }
        }

        interfaces.forEach(function (iface, index) {
            if (index > 0) {
                html += "<hr>";
            }
            let state = STATES[iface.state] || [iface.state, "badge-secondary"];
            if (kind === "wifi" && iface.connection === "Rete-Hotspot") {
                state = ["Hotspot attivo", "badge-warning"];
            }
            html += '<span class="badge ' + state[1] + '">' + escapeHtml(state[0]) + '</span> ';
            if (iface.internet) {
                html += '<span class="badge badge-primary">Usata per internet</span> ';
            }
            if (iface.health && iface.health.degraded) {
                html += '<span class="badge badge-danger">Senza internet: scavalcata</span>';
            } else if (iface.health && !iface.health.ok) {
                html += '<span class="badge badge-warning">Senza internet</span>';
            }
            html += '<dl class="row mt-2 mb-0 small">';
            html += row("Interfaccia", iface.device);
            html += row("Connessione", iface.connection);
            if (iface.wifi) {
                html += row("Rete WiFi", iface.wifi.ssid);
                html += row("Segnale", iface.wifi.signal !== null ? iface.wifi.signal + " %" : null);
            }
            html += row("Indirizzo IP", iface.ipv4);
            html += row("Gateway", iface.gateway);
            html += row("DNS", iface.dns);
            if (kind === "lte" && data.lte_radio && data.lte_radio.on) {
                html += row("Gestore", data.lte_radio.operator);
                html += row("Tipo di rete", data.lte_radio.tech);
                html += row("Segnale LTE", lteSignalTitle(data.lte_radio));
            }
            html += row("MAC", iface.hwaddr);
            html += '</dl>';
        });

        if (kind === "lte" && data.lte_radio && data.lte_radio.idle) {
            html += '<div class="mt-2"><span class="badge badge-info">In attesa (radio spenta, LTE su richiesta)</span></div>';
        }

        if (kind === "wifi" && !data.wifi_radio) {
            html += '<div class="mt-2"><span class="badge badge-secondary">Radio WiFi spenta</span></div>';
        }

        html += '</div></div>';
        $("#card-" + kind).html(html);
    }

    function renderStatus(data) {
        lastStatus = data;
        let ws = wifiSignal(data);
        $("#sig-wifi").html(bars(ws, ws !== null ? "WiFi " + ws + " %" : "WiFi non collegato"));
        $("#sig-lte").html(bars(data.lte_radio ? data.lte_radio.signal : null, lteSignalTitle(data.lte_radio)));
        $("#sig-lte-info").text(lteNetwork(data.lte_radio));
        $("#net-internet").removeClass().addClass("badge p-2 ml-2 " + (data.internet ? "badge-success" : "badge-danger"))
            .text(data.internet ? "Internet: OK" : "Internet: assente");

        ["ethernet", "wifi", "lte"].forEach(function (kind) {
            renderCard(kind, data.interfaces.filter(function (i) { return i.kind === kind; }), data);
        });

        if (data.hotspot.active) {
            $("#hotspot-banner").removeClass("d-none").html(
                "Hotspot di emergenza attivo (<b>" + escapeHtml(data.hotspot.ssid) + "</b>): la base non ha trovato internet. " +
                "Scegli una rete WiFi qui sotto.");
        } else {
            $("#hotspot-banner").addClass("d-none");
        }

        renderTraffic(data.traffic);
        renderTemps(data.temps);
        renderAccess(data.access);
        if (data.lte_radio && !$("#lte-on-demand").data("touched")) {
            $("#lte-on-demand").prop("checked", data.lte_radio.on_demand !== false);
        }

        let rx = data.receiver;
        if (rx && rx.numbered) {
            let text = "Il ricevitore GNSS usa la porta <b>" + escapeHtml(rx.com_port) + "</b>, il cui numero può cambiare dopo un riavvio " +
                "(anche il modem LTE crea porte seriali). ";
            text += rx.link_ready
                ? 'È pronto il nome fisso <b>ttyGNSS</b>: in <a href="/settings">Settings</a> scrivi <b>ttyGNSS</b> nel campo Com port e salva.'
                : "Il nome fisso ttyGNSS verrà creato automaticamente entro un minuto.";
            $("#receiver-banner").removeClass("d-none").html(text);
        } else {
            $("#receiver-banner").addClass("d-none");
        }

        if (ifaceDraft === null) {
            renderIfaceList(data.enabled, data.order);
        }
    }

    function refreshStatus() {
        $.getJSON("/api/network/status")
            .done(function (data) {
                if ($("#net-error").text().indexOf("stato della rete") >= 0) {
                    showError(null);
                }
                renderStatus(data);
            })
            .fail(function () {
                showError("Impossibile leggere lo stato della rete dalla base.");
            })
            .always(function () {
                setTimeout(refreshStatus, REFRESH_MS);
            });
    }

    function renderAccess(a) {
        if (!a) {
            return;
        }
        let port = a.port && a.port !== "80" ? ":" + a.port : "";
        let link = function (host) {
            let url = "http://" + host + port;
            return '<a href="' + escapeHtml(url) + '" target="_blank">' + escapeHtml(url) + '</a>';
        };
        let html = '<dl class="row mb-0">';
        html += '<dt class="col-sm-3">In locale<br><span class="font-weight-normal text-muted">stessa rete WiFi/LAN</span></dt><dd class="col-sm-9">' +
            link(a.hostname + ".local");
        a.local.forEach(function (l) {
            html += '<br>' + link(l.ip) + ' <span class="text-muted">(' + (l.kind === "wifi" ? "WiFi" : "Ethernet") + ')</span>';
        });
        if (a.local.length === 0) {
            html += '<br><span class="text-muted">nessuna rete locale collegata (solo LTE)</span>';
        }
        html += '</dd>';
        html += '<dt class="col-sm-3">Da fuori<br><span class="font-weight-normal text-muted">con Tailscale acceso</span></dt><dd class="col-sm-9">';
        if (a.tailscale && a.tailscale.ip) {
            html += link(a.hostname) + '<br>' + link(a.tailscale.ip);
            if (a.tailscale.name) {
                html += '<br>' + link(a.tailscale.name);
            }
            html += a.tailscale.online ? ' <span class="badge badge-success">collegata</span>'
                                       : ' <span class="badge badge-warning">Tailscale non collegato</span>';
            html += '<br><span class="text-muted">Serve Tailscale sul PC o sul telefono, con lo stesso account della base. ' +
                'Dalla rete mobile la base non si raggiunge direttamente.</span>';
        } else {
            html += '<span class="text-muted">Tailscale non configurato su questa base: da fuori non è raggiungibile.</span>';
        }
        html += '</dd>';
        html += '<dt class="col-sm-3">Hotspot di emergenza<br><span class="font-weight-normal text-muted">base senza internet</span></dt><dd class="col-sm-9">' +
            'collegati alla rete WiFi <b>' + escapeHtml(a.hotspot_ssid) + '</b>, poi ' + link(a.hotspot_ip) + '</dd>';
        html += '<dt class="col-sm-3">Terminale (SSH)</dt><dd class="col-sm-9"><code>ssh &lt;utente&gt;@' + escapeHtml(a.hostname) +
            '.local</code> in locale, <code>ssh &lt;utente&gt;@' + escapeHtml(a.tailscale && a.tailscale.ip ? a.tailscale.ip : a.hostname) +
            '</code> da fuori</dd>';
        html += '</dl>';
        html += '<a class="btn btn-sm btn-primary mt-2" href="/network/access" target="_blank" rel="noopener">' +
            '🖨️ Scheda di accesso stampabile</a> <span class="text-muted">indirizzi, utenti, password e cosa fare se la base non risponde</span>';

        // credenziali: sempre evidenziate come da cancellare/cambiare
        html += '<div class="alert alert-warning mt-3 mb-0"><b>⚠️ Credenziali — DA CANCELLARE e CAMBIARE prima del campo</b><ul class="mb-2 mt-2">';
        if (a.web_default_password === true) {
            html += '<li>Password del pannello: <b>admin</b> (quella di fabbrica: cambiala in Settings)</li>';
        } else if (a.web_default_password === false) {
            html += '<li>Password del pannello: personalizzata (non è più quella di fabbrica)</li>';
        }
        html += '<li>Hotspot di emergenza: rete <b>' + escapeHtml(a.hotspot_ssid) + '</b>, password <b>' +
            escapeHtml(a.hotspot_password) + '</b></li></ul>';
        html += '<div class="font-weight-bold">Note di accesso</div>';
        html += a.notes ? '<pre class="mb-2" style="white-space: pre-wrap;">' + escapeHtml(a.notes) + '</pre>'
                        : '<div class="text-muted mb-2">nessuna nota</div>';
        html += '<button type="button" class="btn btn-sm btn-outline-dark" id="notes-edit">Modifica note</button> ';
        if (a.notes) {
            html += '<button type="button" class="btn btn-sm btn-outline-danger" id="notes-clear">Cancella note</button>';
        }
        html += '<div class="d-none mt-2" id="notes-editor"><textarea class="form-control form-control-sm" id="notes-text" rows="6" maxlength="4000"></textarea>' +
            '<button type="button" class="btn btn-sm btn-primary mt-1" id="notes-save">Salva note</button></div>';
        html += '</div>';
        if (!$("#notes-editor").is(":visible")) {           // non ridisegnare mentre si scrive
            $("#access-info").html(html).data("notes", a.notes);
        }
    }

    $("#access-info").on("click", "#notes-edit", function () {
        $("#notes-text").val($("#access-info").data("notes") || "");
        $("#notes-editor").removeClass("d-none");
    });

    function saveNotes(text) {
        postJson("/api/network/access_notes", {text: text})
            .done(function () {
                $("#notes-editor").addClass("d-none");
                refreshStatusOnce();
            })
            .fail(requestFailed);
    }

    $("#access-info").on("click", "#notes-save", function () {
        saveNotes($("#notes-text").val());
    });

    $("#access-info").on("click", "#notes-clear", function () {
        if (confirm("Cancellare le note di accesso?")) {
            saveNotes("");
        }
    });

    function refreshStatusOnce() {
        $.getJSON("/api/network/status").done(renderStatus);
    }

    function renderTemps(t) {
        if (!t || (t.pi === undefined && t.receiver === undefined)) {
            $("#temp-line").html("");
            return;
        }
        let limits = t.limits || {pi: 75, receiver: 80, modem: 80};
        let parts = [], hot = [];
        [["pi", "Raspberry Pi"], ["receiver", "Ricevitore"], ["modem", "Modem LTE"]].forEach(function (p) {
            let v = t[p[0]];
            if (v === null || v === undefined) {
                return;
            }
            let color = v >= limits[p[0]] ? "text-danger" : (v >= 65 ? "text-warning" : "text-success");
            parts.push(p[1] + ' <b class="' + color + '">' + v.toFixed(1) + ' &deg;C</b>');
            if (v >= limits[p[0]]) {
                hot.push(p[1] + " " + v.toFixed(1) + " °C");
            }
        });
        if (t.modem_mv) {
            parts.push('Modem <b>' + (t.modem_mv / 1000).toFixed(2) + ' V</b>');
        }
        if (t.satellites) {
            parts.push('Satelliti <b>' + t.satellites.tracked + '</b> (' + t.satellites.used + ' usati)');
        }
        $("#temp-line").html('<span class="text-muted">Temperature:</span> ' + parts.join(" &middot; "));
        if (hot.length) {
            $("#temp-banner").removeClass("d-none").text("Temperatura alta: " + hot.join(", ") +
                ". Controlla ventilazione e ombra del contenitore.");
        } else {
            $("#temp-banner").addClass("d-none");
        }
    }

    function renderTraffic(t) {
        if (!t) {
            return;
        }
        let text = "oggi " + t.day_mb + " MB, questo mese " + t.month_mb + " MB";
        if (t.limit_mb) {
            text += " su " + t.limit_mb + " MB (" + t.percent + "%)";
        }
        $("#traffic-text").text(text);
        if (!$("#lte-limit").is(":focus") && !$("#lte-limit").data("touched")) {
            $("#lte-limit").val(t.limit_mb);
        }
        if (t.limit_mb && t.percent >= 80) {
            $("#traffic-banner").removeClass("d-none").text(
                "Traffico LTE del mese al " + t.percent + "% della soglia (" + t.month_mb + " MB su " + t.limit_mb + " MB).");
        } else {
            $("#traffic-banner").addClass("d-none");
        }
    }

    $("#lte-limit, #lte-on-demand").on("input change", function () {
        $(this).data("touched", true);
    });

    $("#lte-limit-save").click(function () {
        postJson("/api/network/lte/limit", {monthly_limit_mb: parseInt($("#lte-limit").val() || "0", 10),
                                            on_demand: $("#lte-on-demand").is(":checked")})
            .done(function () {
                $("#lte-limit, #lte-on-demand").data("touched", false);
                showError(null);
            })
            .fail(requestFailed);
    });

    //### Registro eventi ###

    function loadEvents() {
        $.getJSON("/api/network/events").done(function (data) {
            if (data.events.length === 0) {
                $("#events-list").html('<span class="text-muted">Nessun evento registrato.</span>');
                return;
            }
            $("#events-list").html(data.events.map(function (e) {
                return '<div><span class="text-muted">' + escapeHtml(e.time) + '</span> ' + escapeHtml(e.text) + '</div>';
            }).join(""));
        });
    }

    //### Esporta / importa ###

    $("#import-file").change(function () {
        let file = this.files[0];
        this.value = "";
        if (!file) {
            return;
        }
        let reader = new FileReader();
        reader.onload = function () {
            let data;
            try {
                data = JSON.parse(reader.result);
            } catch (e) {
                showError("Il file scelto non è un file di impostazioni valido.");
                return;
            }
            if (!confirm("Importare le impostazioni dal file " + file.name + "? Quelle attuali verranno sostituite " +
                         "(se la base perde internet, torna alle impostazioni attuali).")) {
                return;
            }
            ifaceDraft = null;
            postJson("/api/network/import", data).done(startOperationPolling).fail(requestFailed);
        };
        reader.readAsText(file);
    });

    //### Connessioni: abilitazione e priorità ###

    function renderIfaceList(enabled, order) {
        let html = "";
        order.forEach(function (kind, index) {
            html += '<li class="list-group-item d-flex align-items-center" data-kind="' + kind + '">' +
                '<span class="badge badge-light mr-3">' + (index + 1) + '</span>' +
                '<div class="custom-control custom-switch flex-grow-1">' +
                '<input type="checkbox" class="custom-control-input iface-enabled" id="en-' + kind + '"' + (enabled[kind] ? " checked" : "") + '>' +
                '<label class="custom-control-label" for="en-' + kind + '">' + TITLES[kind] + '</label></div>' +
                '<button type="button" class="btn btn-sm btn-outline-secondary iface-up mr-1"' + (index === 0 ? " disabled" : "") + '>&uarr;</button>' +
                '<button type="button" class="btn btn-sm btn-outline-secondary iface-down"' + (index === order.length - 1 ? " disabled" : "") + '>&darr;</button>' +
                '</li>';
        });
        $("#iface-list").html(html);
        $("#iface-save, #iface-reset").prop("disabled", ifaceDraft === null);
    }

    function readIfaceList() {
        let enabled = {};
        let order = [];
        $("#iface-list li").each(function () {
            let kind = $(this).data("kind");
            order.push(kind);
            enabled[kind] = $(this).find(".iface-enabled").is(":checked");
        });
        return {enabled: enabled, order: order};
    }

    $("#iface-list").on("change", ".iface-enabled", function () {
        ifaceDraft = readIfaceList();
        renderIfaceList(ifaceDraft.enabled, ifaceDraft.order);
    });

    $("#iface-list").on("click", ".iface-up, .iface-down", function () {
        let current = readIfaceList();
        let kind = $(this).closest("li").data("kind");
        let index = current.order.indexOf(kind);
        let target = $(this).hasClass("iface-up") ? index - 1 : index + 1;
        current.order.splice(index, 1);
        current.order.splice(target, 0, kind);
        ifaceDraft = current;
        renderIfaceList(ifaceDraft.enabled, ifaceDraft.order);
    });

    $("#iface-reset").click(function () {
        ifaceDraft = null;
        if (lastStatus) {
            renderIfaceList(lastStatus.enabled, lastStatus.order);
        }
    });

    $("#iface-save").click(function () {
        let data = readIfaceList();
        if (!confirm("Applicare le nuove impostazioni? Se la connessione che stai usando viene disattivata, questa pagina potrebbe non rispondere per qualche secondo.")) {
            return;
        }
        postJson("/api/network/interfaces", data)
            .done(function () {
                ifaceDraft = null;
                startOperationPolling();
            })
            .fail(requestFailed);
    });

    //### WiFi ###

    function signalBar(signal) {
        let color = signal >= 60 ? "#28a745" : (signal >= 35 ? "#ffc107" : "#dc3545");
        return '<span class="signal-bar"><span style="width:' + signal + '%;background:' + color + '"></span></span> ' +
            '<span class="small text-muted">' + signal + '%</span>';
    }

    function renderNetworks(networks, fromCache) {
        if (networks.length === 0) {
            $("#wifi-networks").html('<tr><td colspan="4" class="text-muted small">Nessuna rete trovata.</td></tr>');
            return;
        }
        let html = "";
        networks.forEach(function (net, index) {
            let saved = savedProfiles.some(function (p) { return p.ssid === net.ssid; });
            html += '<tr><td>' + escapeHtml(net.ssid) +
                (net.in_use ? ' <span class="badge badge-success">connessa</span>' : '') +
                (saved ? ' <span class="badge badge-light">salvata</span>' : '') + '</td>' +
                '<td>' + signalBar(net.signal) + '</td>' +
                '<td class="small">' + (net.security ? escapeHtml(net.security) : "aperta") + '</td>' +
                '<td class="text-right"><button type="button" class="btn btn-sm btn-primary wifi-connect" data-index="' + index + '"' +
                (net.in_use ? " disabled" : "") + '>Connetti</button></td></tr>';
        });
        $("#wifi-networks").html(html).data("networks", networks);
        $("#wifi-scan-msg").text(fromCache ? "Hotspot attivo: reti dell'ultima scansione." : "");
    }

    function scanWifi() {
        $("#wifi-scan").prop("disabled", true);
        $("#wifi-scan-msg").text("Ricerca in corso...");
        $.getJSON("/api/network/wifi/scan")
            .done(function (data) {
                renderNetworks(data.networks, data.hotspot);
            })
            .fail(function () {
                $("#wifi-scan-msg").text("Ricerca non riuscita.");
            })
            .always(function () {
                $("#wifi-scan").prop("disabled", false);
            });
    }

    function loadSaved() {
        $.getJSON("/api/network/wifi/saved").done(function (data) {
            savedProfiles = data.profiles;
            if (savedProfiles.length === 0) {
                $("#wifi-saved").html('<li class="list-group-item text-muted small">Nessuna rete salvata.</li>');
                return;
            }
            let html = "";
            savedProfiles.forEach(function (p) {
                html += '<li class="list-group-item d-flex align-items-center">' +
                    '<span class="flex-grow-1">' + escapeHtml(p.ssid || p.name) +
                    (p.active ? ' <span class="badge badge-success">in uso</span>' : '') + '</span>' +
                    '<button type="button" class="btn btn-sm btn-outline-danger wifi-forget" data-uuid="' + escapeHtml(p.uuid) +
                    '" data-ssid="' + escapeHtml(p.ssid || p.name) + '">Dimentica</button></li>';
            });
            $("#wifi-saved").html(html);
        });
    }

    function openWifiModal(ssid, security, hidden) {
        let saved = savedProfiles.some(function (p) { return p.ssid === ssid; });
        $("#wifi-ssid").val(ssid).prop("readonly", !hidden);
        $("#wifi-password").val("").attr("type", "password");
        $("#wifi-show-password").prop("checked", false);
        $("#wifi-password-group").toggle(hidden || security !== "");
        $("#wifi-saved-help").text(saved ? "Rete già salvata: lascia vuoto per usare la password salvata." : "");
        $("#wifi-form").data({security: security, hidden: hidden});
        let warning = "La base si collegherà alla nuova rete. Se non riesce o la rete non ha internet, entro circa un minuto torna alla connessione precedente.";
        if (lastStatus && lastStatus.hotspot.active) {
            warning = "Sei collegato all'hotspot della base: connettendosi alla nuova rete l'hotspot si spegne e questa pagina non sarà più raggiungibile a questo indirizzo. " +
                "Se la connessione fallisce, l'hotspot si riaccende.";
        }
        $("#wifi-warning").text(warning);
        $("#wifiModal").modal("show");
    }

    $("#wifi-scan").click(scanWifi);

    $("#wifi-hidden").click(function () {
        openWifiModal("", "WPA2", true);
    });

    $("#wifi-networks").on("click", ".wifi-connect", function () {
        let net = $("#wifi-networks").data("networks")[$(this).data("index")];
        openWifiModal(net.ssid, net.security, false);
    });

    $("#wifi-show-password").change(function () {
        $("#wifi-password").attr("type", this.checked ? "text" : "password");
    });

    $("#wifi-form").submit(function (event) {
        event.preventDefault();
        let options = $(this).data();
        let password = $("#wifi-password").val();
        let ssid = $("#wifi-ssid").val();
        let saved = savedProfiles.some(function (p) { return p.ssid === ssid; });
        if (options.security !== "" && !saved && password.length < 8 && !options.hidden) {
            alert("La password WiFi deve avere almeno 8 caratteri.");
            return;
        }
        postJson("/api/network/wifi/connect", {ssid: ssid, password: password, hidden: options.hidden, security: options.security})
            .done(function () {
                $("#wifiModal").modal("hide");
                startOperationPolling();
            })
            .fail(function (xhr) {
                $("#wifiModal").modal("hide");
                requestFailed(xhr);
            });
    });

    $("#wifi-saved").on("click", ".wifi-forget", function () {
        let ssid = $(this).data("ssid");
        if (!confirm('Dimenticare la rete "' + ssid + '"? Se è quella in uso, la base si disconnette dal WiFi.')) {
            return;
        }
        postJson("/api/network/wifi/forget", {uuid: $(this).data("uuid")})
            .done(function (data) {
                if (!data.ok) {
                    showError("Impossibile dimenticare la rete: " + data.error);
                }
                loadSaved();
            })
            .fail(requestFailed);
    });

    //### Hotspot ###

    function loadHotspot() {
        $.getJSON("/api/network/hotspot").done(function (data) {
            $("#hotspot-enabled").prop("checked", data.enabled);
            $("#hotspot-ssid").val(data.ssid);
            $("#hotspot-password").val(data.password);
            $("#hotspot-delay").val(data.delay);
            $("#hotspot-state").html(data.active ? '<span class="badge badge-warning">Hotspot attivo ora</span>' : "");
        });
    }

    $("#hotspot-form").submit(function (event) {
        event.preventDefault();
        postJson("/api/network/hotspot", {
            enabled: $("#hotspot-enabled").is(":checked"),
            ssid: $("#hotspot-ssid").val(),
            password: $("#hotspot-password").val(),
            delay: parseInt($("#hotspot-delay").val(), 10)
        }).done(startOperationPolling).fail(requestFailed);
    });

    //### Modem LTE ###

    function renderLte(data) {
        let html = "";
        if (!data.found) {
            html = '<dt class="col-sm-3">Modem</dt><dd class="col-sm-9">non trovato' +
                (data.error ? " (" + escapeHtml(data.error) + ")" : "") + '</dd>';
        } else {
            html += row("Modem", data.model);
            if (data.radio === false) {
                html += row("Radio", "spenta (LTE disabilitato o in attesa)");
            }
            html += row("Porta AT", data.port);
            html += row("SIM", data.sim);
            html += row("Operatore", data.operator ? data.operator + (data.technology ? " (" + data.technology + ")" : "") : null);
            html += row("Registrazione", data.registration);
            html += row("Segnale", data.signal !== undefined ? data.signal + " % (" + data.signal_dbm + " dBm)" : null);
            html += row("APN nel modem", data.apn);
        }
        $("#lte-status").html(html);
        if (!$("#lte-apn").is(":focus") && !$("#lte-apn").data("touched")) {
            $("#lte-apn").val(data.apn_saved || "");
        }
        if (!$("#lte-activation").is(":focus") && !$("#lte-activation").data("touched")) {
            $("#lte-activation").val(data.activation_command || "");
        }
        if (data.serial_only) {
            html = '<dt class="col-5">Attenzione</dt><dd class="col-7">modem non in modalità rete: serve il comando di attivazione</dd>' + html;
            $("#lte-status").html(html);
        }
        $("#lte-pin").attr("placeholder", data.pin_saved ? "PIN salvato (lascia vuoto per non cambiarlo)" : "");
        $("#lte-pin-help").text(data.pin_saved ? "C'è un PIN salvato." : "Lascia vuoto se la SIM non ha il PIN.");
        $("#lte-pin-remove-box").toggleClass("d-none", !data.pin_saved);
    }

    function renderSim(sim) {
        if (!sim) {
            return;
        }
        $("#sim-phone").html(sim.phone ? escapeHtml(sim.phone) : '<span class="text-muted">da inserire</span>');
        if (!$("#sim-phone-input").is(":focus")) {
            $("#sim-phone-input").val(sim.phone || "");
        }
        $("#sim-iccid").html(sim.iccid ? escapeHtml(sim.iccid) : '<span class="text-muted">non ancora letto</span>');
        $("#sim-iccid-copy").toggleClass("d-none", !sim.iccid).data("iccid", sim.iccid || "");
        $("#sim-iccid-time").text(sim.iccid_read_at ? "letto dal modem il " +
            new Date(sim.iccid_read_at * 1000).toLocaleString("it-IT") : "si legge con il modem acceso");
    }

    function loadSim() {
        $.getJSON("/api/network/sim", renderSim);
    }

    $("#sim-phone-save").on("click", function () {
        postJson("/api/network/sim", {phone: $("#sim-phone-input").val().trim()})
            .done(function (sim) {
                renderSim(sim);
                showError(null);
            })
            .fail(requestFailed);
    });

    $("#sim-iccid-copy").on("click", function () {
        let iccid = $(this).data("iccid");
        if (!iccid) {
            return;
        }
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(iccid);
        } else {                                   // pannello in http: niente API clipboard
            let area = $("<textarea>").val(iccid).css({position: "fixed", opacity: 0}).appendTo("body");
            area[0].select();
            document.execCommand("copy");
            area.remove();
        }
        $(this).text("Copiato");
        setTimeout(function () { $("#sim-iccid-copy").text("Copia"); }, 1500);
    });

    function loadLte() {
        $("#lte-loading").removeClass("d-none");
        $.getJSON("/api/network/lte")
            .done(function (data) {
                renderLte(data);
                renderSim(data.sim_info);
            })
            .always(function () {
                $("#lte-loading").addClass("d-none");
            });
    }

    $("#lte-refresh").click(loadLte);

    $("#lte-apn, #lte-activation").on("input", function () {
        $(this).data("touched", true);
    });

    $("#lte-form").submit(function (event) {
        event.preventDefault();
        let data = {apn: $("#lte-apn").val().trim(), activation_command: $("#lte-activation").val().trim()};
        let pin = $("#lte-pin").val().trim();
        if ($("#lte-pin-remove").is(":checked")) {
            data.pin = "";
        } else if (pin !== "") {
            data.pin = pin;
        }
        postJson("/api/network/lte", data)
            .done(function () {
                $("#lte-pin").val("");
                $("#lte-pin-remove").prop("checked", false);
                $("#lte-apn, #lte-activation").data("touched", false);
                startOperationPolling();
            })
            .fail(requestFailed);
    });

    $("#at-form").submit(function (event) {
        event.preventDefault();
        let command = $("#at-command").val().trim();
        if (command === "") {
            return;
        }
        $("#at-output").removeClass("d-none").text("> " + command + "\n...");
        postJson("/api/network/lte/at", {command: command})
            .done(function (data) {
                $("#at-output").text("> " + command + "\n" + data.lines.join("\n") + "\n" + (data.ok ? "OK" : "(errore)"));
            })
            .fail(function () {
                $("#at-output").text("> " + command + "\nrichiesta non riuscita");
            });
    });

    //### Operazioni in corso ###

    function renderOperation(op) {
        if (op.id === 0) {
            return;
        }
        let css = op.running ? "alert-info" : (op.result === "ok" ? "alert-success" : "alert-danger");
        $("#op-box").removeClass("d-none alert-info alert-success alert-danger").addClass(css);
        $("#op-title").text(op.title + (op.running ? ": in corso" : (op.result === "ok" ? ": completato" : ": non riuscito")));
        $("#op-spinner").toggleClass("d-none", !op.running);
        $("#op-messages").html(op.messages.map(function (m) {
            return '<div><span class="text-muted">' + m.time + '</span> ' + escapeHtml(m.text) + '</div>';
        }).join(""));
    }

    function pollOperation() {
        $.getJSON("/api/network/operation")
            .done(function (op) {
                renderOperation(op);
                if (op.running) {
                    operationTimer = setTimeout(pollOperation, OPERATION_MS);
                    return;
                }
                operationTimer = null;
                if (operationId !== op.id) {
                    operationId = op.id;
                    loadSaved();
                    loadHotspot();
                    loadEvents();
                }
            })
            .fail(function () {
                // durante un cambio di rete la pagina può non rispondere: riprovo
                operationTimer = setTimeout(pollOperation, OPERATION_MS * 2);
            });
    }

    function startOperationPolling() {
        showError(null);
        operationId = null;
        if (operationTimer === null) {
            pollOperation();
        }
    }

    //### Aggiornamenti ###

    function renderUpdate(u) {
        let html = 'Versione installata: <b>EVONETRTKBASE ' + escapeHtml(u.current_label) + '</b>';
        if (u.error) {
            html += '<div class="text-danger small">' + escapeHtml(u.error) + '</div>';
        } else if (u.latest_label) {
            html += u.available
                ? ' &mdash; <span class="badge badge-warning">disponibile la ' + escapeHtml(u.latest_label) + '</span>'
                : ' &mdash; <span class="badge badge-success">aggiornata</span>';
            if (u.available && u.comment) {
                html += '<pre class="small mt-1 mb-0" style="white-space: pre-wrap;">' + escapeHtml(u.comment) + '</pre>';
            }
        }
        if (u.time) {
            html += '<div class="small text-muted">ultimo controllo ' + new Date(u.time * 1000).toLocaleString("it-IT") +
                ' (canale ' + escapeHtml(u.channel) + ')</div>';
        }
        $("#update-info").html(html);
        $("#update-channel").val(u.channel);
    }

    function loadUpdate() {
        $.getJSON("/api/network/update", renderUpdate);
    }

    $("#update-channel").on("change", function () {
        postJson("/api/network/update", {channel: $(this).val(), check: true}).done(renderUpdate).fail(requestFailed);
    });

    $("#update-check").on("click", function () {
        let button = $(this).prop("disabled", true);
        postJson("/api/network/update", {check: true}).done(renderUpdate).fail(requestFailed)
            .always(function () { button.prop("disabled", false); });
    });

    //### Avvio ###

    refreshStatus();
    loadSaved();
    loadHotspot();
    loadSim();
    loadLte();
    loadEvents();
    loadUpdate();
    setInterval(loadEvents, 30000);
    pollOperation();
});
