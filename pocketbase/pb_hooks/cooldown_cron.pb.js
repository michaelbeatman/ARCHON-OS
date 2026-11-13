// pb_hooks/cooldown_cron.pb.js
// PocketBase JS Hook für automatischen 1-Jahres-Cooldown und Einladungs-Stempel

// 1. Cronjob: Läuft täglich um 00:00 Uhr ("0 0 * * *")
cronAdd("cooldown_1jahr_check", "0 0 * * *", (e) => {
    let cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - 365);
    let cutoffStr = cutoff.toISOString().replace("T", " ").substring(0, 19);

    let records = $app.findRecordsByFilter(
        "kontakte",
        "status = 'Gesperrt_1Jahr' && einladung_zurueckgezogen_am != '' && einladung_zurueckgezogen_am <= {:cutoffDate}",
        "-created",
        1000,
        0,
        { cutoffDate: cutoffStr }
    );

    for (let record of records) {
        record.set("status", "Parkposition");
        let currentComment = record.get("kommentar") || "";
        let logEntry = "<p><em>[Auto-Cooldown]: 1-Jahres-Sperre abgelaufen. Status auf Parkposition gesetzt.</em></p>";
        record.set("kommentar", currentComment ? currentComment + logEntry : logEntry);
        $app.save(record);
    }
});

// 2. Request-Hooks: Automatischen Zeitstempel bei 'Gesperrt_1Jahr' setzen
onRecordCreateRequest((e) => {
    let status = e.record.get("status");
    let dateVal = e.record.get("einladung_zurueckgezogen_am");
    if (status === "Gesperrt_1Jahr" && (!dateVal || dateVal === "")) {
        e.record.set("einladung_zurueckgezogen_am", new DateTime().string());
    }
    return e.next();
}, "kontakte");

onRecordUpdateRequest((e) => {
    let status = e.record.get("status");
    let dateVal = e.record.get("einladung_zurueckgezogen_am");
    if (status === "Gesperrt_1Jahr" && (!dateVal || dateVal === "")) {
        e.record.set("einladung_zurueckgezogen_am", new DateTime().string());
    }
    return e.next();
}, "kontakte");
