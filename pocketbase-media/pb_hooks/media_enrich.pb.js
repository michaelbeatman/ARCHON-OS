/// <reference path="../pb_data/types.d.ts" />

onRecordCreate((e) => {
    if (!e.record.get("received_at")) {
        e.record.set("received_at", new Date().toISOString());
    }
    e.next();
}, "media_items");
