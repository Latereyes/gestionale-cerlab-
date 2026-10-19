import sys
import os
import unittest
import tempfile
import sqlite3

# Aggiungi la cartella padre di quella del file a sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import catalogo_auto as ca


def _make_db(db_path):
    """Crea il DB con lo schema vero del modulo."""
    return ca.apri(db_path)


def _make_preventivo(numero="PREV-T-1", stato="Inviato", tipo="standard", righe=None):
    if righe is None:
        righe = [
            {
                "articolo": "Pavimento X",
                "unt": "PZ",
                "qt": "2",
                "prezzo_catalogo": "100",
                "s1": "50",
                "s2": "10",
                "s3": "",
                "costo_trasporto": "10",
                "spese_incasso": "",
                "ricarico_pct": "30",
                "tot_prezzo_unitario": "80",
            }
        ]
    return {
        "numero": numero,
        "data": "2026-10-01",
        "stato": stato,
        "tipo_preventivo": tipo,
        "righe": righe,
    }


class TestCatalogoAuto(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "test.db")
        self.conn = _make_db(self.db_path)

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def test_1_num_vari_formati(self):
        self.assertEqual(ca.num("1.234,50"), 1234.5)
        self.assertEqual(ca.num("12,5%"), 12.5)
        self.assertIsNone(ca.num(""))

    def test_2_costo_righe(self):
        # Caso 1: PZ, listino 100, s1 50, s2 10, trasporto 10, qt 2, spese 0
        # costo = 100*(1-0.5)*(1-0.1) + 10/2 + 0 = 45 + 5 = 50.0
        riga1 = {
            "articolo": "Articolo A",
            "unt": "PZ",
            "qt": "2",
            "prezzo_catalogo": "100",
            "s1": "50",
            "s2": "10",
            "s3": "",
            "costo_trasporto": "10",
            "spese_incasso": "",
            "ricarico_pct": "30",
            "tot_prezzo_unitario": "80",
        }
        p1 = _make_preventivo(numero="PREV-COSTO-1", righe=[riga1])
        ca.aggiorna_da_preventivo(self.db_path, p1)

        cur = self.conn.cursor()
        cur.execute("SELECT costo FROM righe WHERE preventivo = ?", ("PREV-COSTO-1",))
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row[0], 50.0, places=2)

        # Caso 2: MQ, listino 20, sconti vuoti, trasporto 3, qt 10, spese "20"
        # costo = 20*(1)*(1)*(1) + 3 + 20/10 = 20 + 3 + 2 = 25.0
        riga2 = {
            "articolo": "Articolo B",
            "unt": "MQ",
            "qt": "10",
            "prezzo_catalogo": "20",
            "s1": "",
            "s2": "",
            "s3": "",
            "costo_trasporto": "3",
            "spese_incasso": "20",
            "ricarico_pct": "30",
            "tot_prezzo_unitario": "80",
        }
        p2 = _make_preventivo(numero="PREV-COSTO-2", righe=[riga2])
        ca.aggiorna_da_preventivo(self.db_path, p2)

        cur.execute("SELECT costo FROM righe WHERE preventivo = ?", ("PREV-COSTO-2",))
        row2 = cur.fetchone()
        self.assertIsNotNone(row2)
        self.assertAlmostEqual(row2[0], 25.0, places=2)

    def test_3_doppio_salvataggio(self):
        p = _make_preventivo(numero="PREV-DUP-1")
        ca.aggiorna_da_preventivo(self.db_path, p)

        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM righe WHERE preventivo = ?", ("PREV-DUP-1",))
        count1 = cur.fetchone()[0]

        ca.aggiorna_da_preventivo(self.db_path, p)
        cur.execute("SELECT COUNT(*) FROM righe WHERE preventivo = ?", ("PREV-DUP-1",))
        count2 = cur.fetchone()[0]

        self.assertEqual(count1, count2)

    def test_4_stesso_articolo_maiuscole_diverse(self):
        riga1 = {
            "articolo": "Pavimento X",
            "unt": "PZ",
            "qt": "1",
            "prezzo_catalogo": "100",
            "s1": "",
            "s2": "",
            "s3": "",
            "costo_trasporto": "",
            "spese_incasso": "",
            "ricarico_pct": "30",
            "tot_prezzo_unitario": "80",
        }
        p1 = _make_preventivo(numero="PREV-ART-1", righe=[riga1])
        ca.aggiorna_da_preventivo(self.db_path, p1)

        riga2 = {
            "articolo": "pavimento x",
            "unt": "PZ",
            "qt": "1",
            "prezzo_catalogo": "100",
            "s1": "",
            "s2": "",
            "s3": "",
            "costo_trasporto": "",
            "spese_incasso": "",
            "ricarico_pct": "30",
            "tot_prezzo_unitario": "80",
        }
        p2 = _make_preventivo(numero="PREV-ART-2", righe=[riga2])
        ca.aggiorna_da_preventivo(self.db_path, p2)

        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM articoli WHERE LOWER(nome) = 'pavimento x'")
        n_articoli = cur.fetchone()[0]
        self.assertEqual(n_articoli, 1)

        cur.execute("SELECT n_preventivi FROM articoli WHERE LOWER(nome) = 'pavimento x'")
        n_prev = cur.fetchone()[0]
        self.assertEqual(n_prev, 2)

    def test_5_stato_chiuso_e_inviato(self):
        # Stato Chiuso -> n_vendite 1, prezzo_vendita_mediano 80
        riga_chiusa = {
            "articolo": "Articolo Chiuso",
            "unt": "PZ",
            "qt": "1",
            "prezzo_catalogo": "100",
            "s1": "",
            "s2": "",
            "s3": "",
            "costo_trasporto": "",
            "spese_incasso": "",
            "ricarico_pct": "30",
            "tot_prezzo_unitario": "80",
        }
        p_chiuso = _make_preventivo(numero="PREV-CHIUSO", stato="Chiuso", righe=[riga_chiusa])
        ca.aggiorna_da_preventivo(self.db_path, p_chiuso)

        cur = self.conn.cursor()
        cur.execute("SELECT n_vendite, prezzo_vendita_mediano FROM articoli WHERE LOWER(nome) = 'articolo chiuso'")
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 1)
        self.assertAlmostEqual(row[1], 80.0, places=2)

        # Stato Inviato -> n_vendite 0
        riga_inviata = {
            "articolo": "Articolo Inviato",
            "unt": "PZ",
            "qt": "1",
            "prezzo_catalogo": "100",
            "s1": "",
            "s2": "",
            "s3": "",
            "costo_trasporto": "",
            "spese_incasso": "",
            "ricarico_pct": "30",
            "tot_prezzo_unitario": "80",
        }
        p_inviato = _make_preventivo(numero="PREV-INVIATO", stato="Inviato", righe=[riga_inviata])
        ca.aggiorna_da_preventivo(self.db_path, p_inviato)

        cur.execute("SELECT n_vendite FROM articoli WHERE LOWER(nome) = 'articolo inviato'")
        row2 = cur.fetchone()
        self.assertIsNotNone(row2)
        self.assertEqual(row2[0], 0)

    def test_6_marca_da_alias(self):
        # Primo salvataggio per creare le tabelle
        p_init = _make_preventivo(numero="PREV-INIT")
        ca.aggiorna_da_preventivo(self.db_path, p_init)

        # Inserisci l'alias
        cur = self.conn.cursor()
        cur.execute("INSERT INTO marche_alias (alias, marca) VALUES (?, ?)", ("mirage", "Mirage"))
        self.conn.commit()

        # Salva un preventivo con "Gres MIRAGE 60x60"
        riga = {
            "articolo": "Gres MIRAGE 60x60",
            "unt": "PZ",
            "qt": "1",
            "prezzo_catalogo": "100",
            "s1": "",
            "s2": "",
            "s3": "",
            "costo_trasporto": "",
            "spese_incasso": "",
            "ricarico_pct": "30",
            "tot_prezzo_unitario": "80",
        }
        p = _make_preventivo(numero="PREV-ALIAS", righe=[riga])
        ca.aggiorna_da_preventivo(self.db_path, p)

        cur.execute("SELECT marca FROM articoli WHERE LOWER(nome) = 'gres mirage 60x60'")
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "Mirage")

        cur.execute("SELECT COUNT(*) FROM condizioni_marca WHERE marca = ?", ("Mirage",))
        n_cond = cur.fetchone()[0]
        self.assertGreaterEqual(n_cond, 1)

    def test_7_preventivo_edile(self):
        p = _make_preventivo(numero="PREV-EDILE", tipo="edile")
        n_righe = ca.aggiorna_da_preventivo(self.db_path, p)
        self.assertEqual(n_righe, 0)

    def test_8_togliere_riga_e_risalvare(self):
        riga1 = {
            "articolo": "Articolo Da Togliere",
            "unt": "PZ",
            "qt": "1",
            "prezzo_catalogo": "100",
            "s1": "",
            "s2": "",
            "s3": "",
            "costo_trasporto": "",
            "spese_incasso": "",
            "ricarico_pct": "30",
            "tot_prezzo_unitario": "80",
        }
        p1 = _make_preventivo(numero="PREV-TOGLI", righe=[riga1])
        ca.aggiorna_da_preventivo(self.db_path, p1)

        cur = self.conn.cursor()
        cur.execute("SELECT n_preventivi FROM articoli WHERE LOWER(nome) = 'articolo da togliere'")
        n_prev_1 = cur.fetchone()[0]
        self.assertEqual(n_prev_1, 1)

        # Risalva lo stesso preventivo senza righe
        p2 = _make_preventivo(numero="PREV-TOGLI", righe=[])
        ca.aggiorna_da_preventivo(self.db_path, p2)

        cur.execute("SELECT COUNT(*) FROM righe WHERE preventivo = ?", ("PREV-TOGLI",))
        n_righe = cur.fetchone()[0]
        self.assertEqual(n_righe, 0)

        cur.execute("SELECT n_preventivi FROM articoli WHERE LOWER(nome) = 'articolo da togliere'")
        n_prev_2 = cur.fetchone()[0]
        self.assertEqual(n_prev_2, 0)

    def test_9_costo_da_magazzino(self):
        riga = {
            "articolo": "Articolo Magazzino",
            "unt": "PZ",
            "qt": "1",
            "prezzo_catalogo": "100",
            "s1": "",
            "s2": "",
            "s3": "",
            "costo_trasporto": "0",
            "spese_incasso": "0",
            "ricarico_pct": "30",
            "tot_prezzo_unitario": "80",
            "id_articolo_magazzino": "7",
        }
        p = _make_preventivo(numero="PREV-MAG", righe=[riga])
        ca.aggiorna_da_preventivo(self.db_path, p, costi_magazzino={7: 12.0})

        cur = self.conn.cursor()
        cur.execute("SELECT costo FROM righe WHERE preventivo = ?", ("PREV-MAG",))
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row[0], 12.0, places=2)


if __name__ == "__main__":
    unittest.main()
