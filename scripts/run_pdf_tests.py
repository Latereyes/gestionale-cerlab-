import sys
import os
import json
import urllib.request
import urllib.error
from pathlib import Path

# Assicura working directory
BASE_DIR = Path(__file__).resolve().parent.parent
os.chdir(BASE_DIR)

SERVER_URL = "http://127.0.0.1:5001"
DATA_PREV_DIR = BASE_DIR / "data" / "preventivi"

def make_request(path):
    url = f"{SERVER_URL}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "TestClient/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            content_type = resp.headers.get("Content-Type", "")
            data = resp.read().decode("utf-8")
            return resp.status, data, content_type
    except urllib.error.HTTPError as e:
        data = e.read().decode("utf-8")
        return e.code, data, e.headers.get("Content-Type", "")
    except Exception as e:
        return 0, str(e), ""

def run_tests():
    print("=== INIZIO TEST SUITE PDF GESTIONALE ===")
    
    # 1. Verifica disponibilità del server
    status, data, _ = make_request("/")
    if status != 200:
        print(f"[-] Server non raggiungibile su {SERVER_URL} (status: {status}). Assicurarsi che sia attivo.")
        sys.exit(1)
    print(f"[+] Server attivo e raggiungibile su {SERVER_URL} (status: {status})")

    # 2. Test Error Handling: Preventivo inesistente
    print("\n--- Test 1: Preventivo inesistente ---")
    status, data, _ = make_request("/generate-pdf-task/PREVENTIVO_INESISTENTE_9999")
    print(f"Status: {status} (atteso: 404)")
    assert status == 404, f"Atteso 404, ottenuto {status}"
    json_data = json.loads(data)
    assert "error" in json_data, f"Risposta JSON non contiene 'error': {json_data}"
    print(f"[+] Ricevuto errore atteso: {json_data['error']}")

    # 3. Test Error Handling: Preventivo in stato 'Bozza'
    print("\n--- Test 2: Preventivo in stato Bozza ---")
    status, data, _ = make_request("/generate-pdf-task/PREV-CF-04AG2609A19")
    print(f"Status: {status} (atteso: 400)")
    assert status == 400, f"Atteso 400, ottenuto {status}"
    json_data = json.loads(data)
    assert "error" in json_data, f"Risposta JSON non contiene 'error': {json_data}"
    print(f"[+] Bloccato preventivo in bozza come previsto: {json_data['error']}")

    # 4. Creazione Preventivo di Test
    test_quote_id = "PREV-TEST-PDF-001"
    test_quote_file = DATA_PREV_DIR / f"{test_quote_id}.json"
    
    test_quote_data = {
        "numero": test_quote_id,
        "data": "2026-09-09",
        "stato": "Inviato",
        "id_cliente": "CLI-TEST",
        "cliente": "CLIENTE TEST SRL",
        "tipo_preventivo": "standard",
        "totale": "1.250,00",
        "totale_imponibile": "1.250,00",
        "totale_iva": "275,00",
        "totale_ivato": "1.525,00",
        "righe": [
            {
                "descrizione": "Servizio di test generazione PDF robusta",
                "quantita": "1",
                "um": "pz",
                "prezzo_unitario": "1.250,00",
                "totale": "1.250,00",
                "stato": "In Bolla"
            }
        ],
        "bolle": [
            {
                "id": "BOLLA-2026-TEST",
                "numero_progressivo": "TEST-1",
                "data": "2026-09-09",
                "vettore": "Mittente",
                "causale": "Vendita",
                "indici_righe": [0]
            }
        ]
    }
    
    with open(test_quote_file, "w", encoding="utf-8") as f:
        json.dump(test_quote_data, f, indent=2)
    print(f"\n[+] Creato preventivo di test temporaneo: {test_quote_file.name}")

    generated_files = []

    try:
        # 5. Test Pagina Loading Preventivo
        print("\n--- Test 3: Pagina /export-pdf/<quote_id> ---")
        status, html, _ = make_request(f"/export-pdf/{test_quote_id}")
        assert status == 200, f"Atteso 200 per export-pdf, ottenuto {status}"
        assert "Generazione del PDF in corso..." in html, "Testo del titolo mancante in loading.html"
        assert "progress-bar" in html, "Progress bar mancante in loading.html"
        assert "generate-pdf-task" in html, "Chiamata a generate-pdf-task mancante in loading.html"
        print("[+] Pagina loading.html renderizzata correttamente con progress bar e script")

        # 6. Test Generazione PDF Preventivo (Standard)
        print("\n--- Test 4: Task generazione PDF Preventivo (Standard) ---")
        status, data, _ = make_request(f"/generate-pdf-task/{test_quote_id}?template=standard")
        print(f"Status: {status} (atteso: 200)")
        assert status == 200, f"Atteso 200, ottenuto {status}: {data}"
        res = json.loads(data)
        assert "pdf_url" in res, f"pdf_url mancante nella risposta: {res}"
        pdf_url = res["pdf_url"]
        pdf_filename = pdf_url.split("/")[-1]
        pdf_path = DATA_PREV_DIR / pdf_filename
        generated_files.append(pdf_path)
        print(f"[+] PDF Preventivo generato: {pdf_filename}")
        assert pdf_path.exists(), f"File PDF non trovato su disco: {pdf_path}"
        pdf_size = pdf_path.stat().st_size
        print(f"[+] Dimensione file PDF: {pdf_size} bytes (> 1000 byte)")
        assert pdf_size > 1000, f"File PDF troppo piccolo: {pdf_size} bytes"

        # 7. Test Generazione PDF Preventivo (Semplice)
        print("\n--- Test 5: Task generazione PDF Preventivo (Semplice) ---")
        status, data, _ = make_request(f"/generate-pdf-task/{test_quote_id}?template=semplice")
        print(f"Status: {status} (atteso: 200)")
        assert status == 200, f"Atteso 200, ottenuto {status}: {data}"
        res = json.loads(data)
        pdf_url = res["pdf_url"]
        pdf_filename = pdf_url.split("/")[-1]
        pdf_path = DATA_PREV_DIR / pdf_filename
        generated_files.append(pdf_path)
        print(f"[+] PDF Preventivo Semplice generato: {pdf_filename} ({pdf_path.stat().st_size} bytes)")

        # 8. Test Pagina Loading Bolla
        print("\n--- Test 6: Pagina /export-bolla-pdf/<quote_id>/<bolla_id> ---")
        status, html, _ = make_request(f"/export-bolla-pdf/{test_quote_id}/BOLLA-2026-TEST")
        assert status == 200, f"Atteso 200 per export-bolla-pdf, ottenuto {status}"
        assert "Generazione della Bolla in corso..." in html
        assert "progress-bar" in html
        print("[+] Pagina loading_bolla.html renderizzata correttamente")

        # 9. Test Generazione PDF Bolla
        print("\n--- Test 7: Task generazione PDF Bolla ---")
        status, data, _ = make_request(f"/generate-bolla-task/{test_quote_id}/BOLLA-2026-TEST")
        print(f"Status: {status} (atteso: 200)")
        assert status == 200, f"Atteso 200, ottenuto {status}: {data}"
        res = json.loads(data)
        assert "pdf_url" in res, f"pdf_url mancante nella risposta: {res}"
        bolla_pdf_url = res["pdf_url"]
        bolla_pdf_filename = bolla_pdf_url.split("/")[-1]
        bolla_pdf_path = DATA_PREV_DIR / bolla_pdf_filename
        generated_files.append(bolla_pdf_path)
        print(f"[+] PDF Bolla generato: {bolla_pdf_filename}")
        assert bolla_pdf_path.exists(), f"File PDF bolla non trovato: {bolla_pdf_path}"
        bolla_size = bolla_pdf_path.stat().st_size
        print(f"[+] Dimensione file PDF Bolla: {bolla_size} bytes")
        assert bolla_size > 1000, f"File PDF bolla troppo piccolo: {bolla_size} bytes"

        # 10. Test Rigenerazione Bolla (Endpoint /rigenera-bolla-pdf)
        print("\n--- Test 8: Pagina /rigenera-bolla-pdf/<quote_id>/<bolla_id> ---")
        status, html, _ = make_request(f"/rigenera-bolla-pdf/{test_quote_id}/BOLLA-2026-TEST")
        assert status == 200, f"Atteso 200 per rigenera-bolla-pdf, ottenuto {status}"
        print("[+] Endpoint rigenera-bolla-pdf risponde con 200 OK")

        # 11. Test Error Handling Bolla inesistente
        print("\n--- Test 9: Bolla inesistente ---")
        status, data, _ = make_request(f"/generate-bolla-task/{test_quote_id}/BOLLA_NON_ESISTE")
        print(f"Status: {status} (atteso: 404)")
        assert status == 404, f"Atteso 404, ottenuto {status}"
        print("[+] Bolla inesistente gestita correttamente con 404")

        # 12. Verifica log eventi PDF
        print("\n--- Test 10: Verifica file di log ---")
        log_file = BASE_DIR / "data" / "pdf_generation.log"
        if log_file.exists():
            with open(log_file, "r", encoding="utf-8") as lf:
                log_content = lf.read()
            assert test_quote_id in log_content, f"Quote id {test_quote_id} non trovato nei log"
            print(f"[+] Eventi registrati regolarmente nel file di log per {test_quote_id}")

        print("\n=========================================")
        print(">>> TUTTI I 10 TEST SUPERATI CON SUCCESSO! <<<")
        print("=========================================")

    finally:
        # Pulizia file temporanei
        print("\n--- Pulizia file di test ---")
        if test_quote_file.exists():
            test_quote_file.unlink()
            print(f"[+] Rimosso {test_quote_file.name}")
        for gf in generated_files:
            if gf.exists():
                gf.unlink()
                print(f"[+] Rimosso file generato {gf.name}")

if __name__ == "__main__":
    run_tests()
