import sys
import os

# Permet d'importer app.py qui se trouve à la racine du projet,
# un dossier au-dessus de ce fichier (api/index.py).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
