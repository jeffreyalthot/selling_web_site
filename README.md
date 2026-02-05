# selling_web_site

Mini site web professionnel pour une transaction Bitcoin temporaire.

## Fonctionnalités
- Affiche l'adresse BTC de paiement: `19Tf5K7eZY6umSpaCktKfaf5ZTWv7qQvw6`.
- Interroge périodiquement l'API publique Blockstream pour détecter la dernière transaction entrante.
- Affiche le montant entrant et l'état de confirmation `0/1` puis `1/1`.
- Rend visible un lien de téléchargement seulement quand la transaction est confirmée à `1/1`.
- Permet de télécharger le contenu du dossier `wallet_folder` au format ZIP après confirmation.

## Lancer le site
```bash
python3 app.py
```
Puis ouvrir `http://localhost:8000`.
