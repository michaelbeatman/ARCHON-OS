import os
import sys
import time

sys.path.insert(0, os.path.abspath("."))
from utils.batch_library_importer import process_document

SOURCE_DIR = r"C:\Users\User\Downloads\extracted\PDF-Import 20260904"
VAULT_DIR = r"./obsidian_vault"

# Saubere thematische Zuordnung für Titel, die sonst unter 04_Allgemein landen würden
CUSTOM_CATEGORY_MAP = {
    "buchfuehrung_1_datev_kontenrahmen_2018": "07_Betriebswirtschaft_Finanzen",
    "jahresabschluesse_und_jahresabschlussanalysa": "07_Betriebswirtschaft_Finanzen",
    "schnelleinstieg_finanzbuchhaltung": "07_Betriebswirtschaft_Finanzen",
    "erfolgreiche_vertriebsstrategien_in_banken": "03_Strategie_Markt",
    "smart_banking": "03_Strategie_Markt",
    "corporate_sicial_responsibility": "03_Strategie_Markt",
    "csr_und_diversity_management": "03_Strategie_Markt",
    "csr_und_social_media": "03_Strategie_Markt",
    "csr_und_compliance": "02_Recht_Steuern",
    "handbuch_kartelrecht_im_unternehmen_vvcnvg_fv": "02_Recht_Steuern",
    "ki_und_recht": "02_Recht_Steuern",
    "leitfaden_projektmanagement_fuer_bauherren": "08_Projektmanagement_Organisation",
    "dienstleistungsmanagement": "08_Projektmanagement_Organisation",
    "durchsetzungsstark_verhandeln": "08_Projektmanagement_Organisation",
    "verhandlen_hart_aber_herzlich": "08_Projektmanagement_Organisation",
    "seminare_trainings_und_workshops_lebendig_gestalten": "08_Projektmanagement_Organisation",
    "problemloeseprozesse_selbsstaendigkeitsorienteirt_begleiten": "08_Projektmanagement_Organisation",
    "hacking_security_das_umfassende_handbuch": "09_Tech_Software_KI",
    "mikrocontroller_esp32_das_umfassendes_handbuch_uber_700_seiten_komplett_in_farbe_mit_fritzing_schalts": "09_Tech_Software_KI",
    "ki_in_der_medizinischen_forschung_ein_einblick_in_regulation_ethische_fragen_und_computergestuetzte_verf": "09_Tech_Software_KI",
    "schimmepilze_in_wohnung": "01_Immobilien_Modulbau",
    "medizinisches_cannabis_und_cbd_in_der_psychischen_gesundheitsversorgung": "06_Cannabis_Wirtschaft_Medizin",
    "der_placebo_effekt": "10_Medizin_Gesundheit",
    "monika_engelhardt_heike_reinhardt_roland_mertelsmann_justus_duyster_hrsg_das_blaue_buch": "10_Medizin_Gesundheit",
    "ineke_eilers_selbst_und_co_regulation": "10_Medizin_Gesundheit",
    "matthias_karmasin_rainer_ribing_die_gestaltung_wissenschaftlicher_arbeiten_9_auflage": "04_Allgemein",
    "einfuehrung_in_die_soziologie": "04_Allgemein",
    "future_model": "03_Strategie_Markt",
    "globalisierung_und_digitalisierung": "03_Strategie_Markt",
    "kommunikationssteuerung": "03_Strategie_Markt"
}

def main():
    files = sorted([f for f in os.listdir(SOURCE_DIR) if f.lower().endswith((".pdf", ".epub"))])
    total = len(files)
    print(f"=== BATCH-INGEST TRANCHE START: {total} Werke ===", flush=True)

    success_count = 0
    fail_count = 0

    for idx, filename in enumerate(files, 1):
        fpath = os.path.join(SOURCE_DIR, filename)
        fsize_mb = os.path.getsize(fpath) / (1024 * 1024)
        
        # Ermittle Kategorie
        base = os.path.splitext(filename)[0]
        from utils.batch_library_importer import slugify
        slug = slugify(base)
        cat = CUSTOM_CATEGORY_MAP.get(slug, "auto")

        print(f"[{idx}/{total}] [{cat}] '{filename}' ({fsize_mb:.1f} MB)...", flush=True)
        t0 = time.time()
        try:
            res = process_document(fpath, VAULT_DIR, cat)
            dt = time.time() - t0
            pages = res.get("total_pages", 0)
            status = res.get("status", "ok")
            print(f"    -> Fertig in {dt:.1f}s | Seiten: {pages} | Status: {status}", flush=True)
            success_count += 1
        except Exception as e:
            dt = time.time() - t0
            print(f"    -> FEHLER nach {dt:.1f}s: {e}", flush=True)
            fail_count += 1

    print(f"\n=== TRANCHE BEENDET ===", flush=True)
    print(f"Erfolgreich: {success_count} | Fehler: {fail_count} | Gesamt: {total}", flush=True)

if __name__ == "__main__":
    main()
