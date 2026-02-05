from __future__ import annotations

import io
import json
import mimetypes
import os
import http.client
import urllib.error
import urllib.request
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

BTC_ADDRESS = "19Tf5K7eZY6umSpaCktKfaf5ZTWv7qQvw6"
BLOCKSTREAM_API = "https://blockstream.info/api"
WALLET_DIR = Path("wallet_folder")
STATIC_DIR = Path("static")
PAYMENT_STATE_FILE = Path("payment_state.json")


def sat_to_btc(sats: int) -> float:
    return sats / 100_000_000


def fetch_json(url: str):
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=15) as response:
        return response.read().decode("utf-8").strip()


def get_latest_incoming_transaction(address: str):
    txs = fetch_json(f"{BLOCKSTREAM_API}/address/{address}/txs")
    tip_height = None
    latest_incoming_tx = None

    for tx in txs:
        amount_sats = 0
        for vout in tx.get("vout", []):
            if vout.get("scriptpubkey_address") == address:
                amount_sats += int(vout.get("value", 0))

        if amount_sats <= 0:
            continue

        if latest_incoming_tx is None:
            latest_incoming_tx = tx

        status = tx.get("status", {})
        confirmations = 0
        if status.get("confirmed"):
            if tip_height is None:
                tip_height = int(fetch_text(f"{BLOCKSTREAM_API}/blocks/tip/height"))
            block_height = int(status.get("block_height", 0))
            confirmations = max(1, tip_height - block_height + 1)

        tx_info = {
            "txid": tx.get("txid"),
            "amount_sats": amount_sats,
            "amount_btc": sat_to_btc(amount_sats),
            "confirmations": confirmations,
            "required_confirmations": 1,
            "is_unlocked": confirmations >= 1,
        }

        if tx_info["is_unlocked"]:
            return tx_info

    if latest_incoming_tx:
        amount_sats = 0
        for vout in latest_incoming_tx.get("vout", []):
            if vout.get("scriptpubkey_address") == address:
                amount_sats += int(vout.get("value", 0))
        return {
            "txid": latest_incoming_tx.get("txid"),
            "amount_sats": amount_sats,
            "amount_btc": sat_to_btc(amount_sats),
            "confirmations": 0,
            "required_confirmations": 1,
            "is_unlocked": False,
        }

    return None


def load_payment_state() -> dict:
    if not PAYMENT_STATE_FILE.exists():
        return {}
    try:
        return json.loads(PAYMENT_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_payment_state(state: dict) -> None:
    PAYMENT_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def list_wallet_folder_contents() -> list[str]:
    if not WALLET_DIR.exists() or not WALLET_DIR.is_dir():
        return []
    return sorted(
        str(path.relative_to(WALLET_DIR)).replace("\\", "/")
        for path in WALLET_DIR.rglob("*")
        if path.is_file()
    )


def render_index_html() -> str:
    return f"""<!doctype html>
<html lang=\"fr\">
  <head>
    <meta charset=\"UTF-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
    <title>Plateforme Transaction BTC</title>
    <link rel=\"stylesheet\" href=\"/static/styles.css\" />
  </head>
  <body>
    <main class=\"container\">
      <section class=\"card\">
        <h1>Plateforme temporaire de transaction</h1>
        <p class=\"subtitle\">Paiement Bitcoin avec vérification automatique (1/1 confirmation)</p>

        <div class=\"info-grid\">
          <div>
            <span class=\"label\">Adresse BTC de réception</span>
            <code id=\"btc-address\">{BTC_ADDRESS}</code>
          </div>
          <div>
            <span class=\"label\">État de la transaction</span>
            <strong id=\"status-text\">En attente d'une transaction entrante...</strong>
          </div>
          <div>
            <span class=\"label\">Montant détecté</span>
            <strong id=\"amount-text\">-</strong>
          </div>
          <div>
            <span class=\"label\">Confirmations</span>
            <strong id=\"confirmations-text\">0 / 1</strong>
          </div>
          <div>
            <span class=\"label\">TXID complet (transaction entrante)</span>
            <code id=\"txid-text\">-</code>
          </div>
        </div>

        <a id=\"download-link\" class=\"btn hidden\" href=\"/download/wallet-folder\">Télécharger le dossier wallet_folder</a>

        <section class=\"preview-window\">
          <h2>Contenu de wallet_folder (aperçu)</h2>
          <p id=\"preview-status\" class=\"preview-status\">Contenu verrouillé jusqu'à la confirmation du paiement (1/1).</p>
          <pre id=\"folder-preview\">🔒 Paiement requis pour voir les fichiers.</pre>
        </section>

        <p id=\"error-text\" class=\"error\"></p>
      </section>
    </main>

    <script>
      async function refreshPaymentStatus() {{
        const statusText = document.getElementById('status-text');
        const amountText = document.getElementById('amount-text');
        const confirmationsText = document.getElementById('confirmations-text');
        const txidText = document.getElementById('txid-text');
        const downloadLink = document.getElementById('download-link');
        const previewStatus = document.getElementById('preview-status');
        const folderPreview = document.getElementById('folder-preview');
        const errorText = document.getElementById('error-text');

        try {{
          const response = await fetch('/api/payment-status');
          const data = await response.json();

          if (!response.ok || !data.ok) {{
            throw new Error(data.error || 'Erreur inconnue lors de la vérification.');
          }}

          errorText.textContent = '';

          if (!data.has_transaction) {{
            statusText.textContent = data.message;
            amountText.textContent = '-';
            confirmationsText.textContent = '0 / 1';
            txidText.textContent = '-';
            downloadLink.classList.add('hidden');
            previewStatus.textContent = "Contenu verrouillé jusqu'à la confirmation du paiement (1/1).";
            folderPreview.textContent = '🔒 Paiement requis pour voir les fichiers.';
            return;
          }}

          amountText.textContent = `${{data.amount_btc.toFixed(8)}} BTC`;
          confirmationsText.textContent = `${{Math.min(data.confirmations, 1)}} / 1`;
          txidText.textContent = data.txid || '-';

          if (data.is_unlocked) {{
            statusText.textContent = 'Transaction confirmée. Téléchargement disponible.';
            downloadLink.classList.remove('hidden');
            previewStatus.textContent = 'Paiement validé: fichiers disponibles en aperçu.';
            folderPreview.textContent = (data.folder_contents && data.folder_contents.length)
              ? data.folder_contents.join('\\n')
              : 'Aucun fichier trouvé dans wallet_folder.';
          }} else {{
            statusText.textContent = 'Transaction détectée. En attente de confirmation...';
            downloadLink.classList.add('hidden');
            previewStatus.textContent = "Contenu verrouillé jusqu'à la confirmation du paiement (1/1).";
            folderPreview.textContent = '🔒 Paiement requis pour voir les fichiers.';
          }}
        }} catch (error) {{
          errorText.textContent = `Impossible de vérifier le paiement: ${{error.message}}`;
        }}
      }}

      refreshPaymentStatus();
      setInterval(refreshPaymentStatus, 15000);
    </script>
  </body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, data: dict):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_text(self, status: int, text: str):
        payload = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            html = render_index_html().encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return

        if path.startswith("/static/"):
            relative = path.removeprefix("/static/")
            file_path = STATIC_DIR / relative
            if not file_path.exists() or not file_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            mime_type, _ = mimetypes.guess_type(str(file_path))
            content = file_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mime_type or "application/octet-stream")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if path == "/api/payment-status":
            state = load_payment_state()
            try:
                tx = get_latest_incoming_transaction(BTC_ADDRESS)
            except (urllib.error.URLError, TimeoutError, ValueError, http.client.RemoteDisconnected, OSError) as exc:
                if state.get("is_unlocked"):
                    self.send_json(
                        200,
                        {
                            "ok": True,
                            "has_transaction": True,
                            **state,
                            "message": f"Mode cache actif (API indisponible: {exc})",
                            "folder_contents": list_wallet_folder_contents(),
                        },
                    )
                    return
                self.send_json(503, {"ok": False, "error": f"API indisponible: {exc}"})
                return

            if tx and tx.get("is_unlocked"):
                state = {**tx, "is_unlocked": True}
                save_payment_state(state)
            elif state.get("is_unlocked"):
                tx = state

            if not tx:
                self.send_json(
                    200,
                    {
                        "ok": True,
                        "has_transaction": False,
                        "message": "Aucune transaction entrante détectée pour le moment.",
                    },
                )
                return

            self.send_json(
                200,
                {
                    "ok": True,
                    "has_transaction": True,
                    **tx,
                    "folder_contents": list_wallet_folder_contents() if tx.get("is_unlocked") else [],
                },
            )
            return

        if path == "/download/wallet-folder":
            state = load_payment_state()
            try:
                tx = get_latest_incoming_transaction(BTC_ADDRESS)
            except (urllib.error.URLError, TimeoutError, ValueError, http.client.RemoteDisconnected, OSError):
                tx = state if state.get("is_unlocked") else None

            if tx and tx.get("is_unlocked"):
                save_payment_state({**tx, "is_unlocked": True})
            elif state.get("is_unlocked"):
                tx = state

            if not tx or tx["confirmations"] < 1:
                self.send_text(403, "Téléchargement verrouillé: une confirmation est requise.")
                return

            if not WALLET_DIR.exists() or not WALLET_DIR.is_dir():
                self.send_text(404, "Le dossier wallet_folder est introuvable.")
                return

            in_memory_zip = io.BytesIO()
            with zipfile.ZipFile(in_memory_zip, "w", zipfile.ZIP_DEFLATED) as zip_file:
                for file_path in WALLET_DIR.rglob("*"):
                    if file_path.is_file():
                        zip_file.write(file_path, file_path.relative_to(WALLET_DIR.parent))
            payload = in_memory_zip.getvalue()

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", "attachment; filename=wallet_folder.zip")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        self.send_error(HTTPStatus.NOT_FOUND)


def run():
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Server running on http://0.0.0.0:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
