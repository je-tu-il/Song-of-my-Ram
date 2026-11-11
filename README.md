# 🎵 Song-of-my-Ram Studio

[![Windows](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-blue.svg?logo=windows)](https://github.com/je-tu-il/Song-of-my-Ram/releases)
[![Release](https://img.shields.io/github/v/release/je-tu-il/Song-of-my-Ram?color=success&include_prereleases)](https://github.com/je-tu-il/Song-of-my-Ram/releases/latest)
[![Python](https://img.shields.io/badge/Python-3.9%2B-brightgreen.svg?logo=python)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Transformez votre mémoire RAM en direct en Musique, Images Algorithmiques, Mots de Passe, Vidéos, Poésie et Modèles 3D !**  
> Une suite créative moderne à onglets avec **mode Simple** et **mode Avancé** sur chaque générateur, fonctionnant nativement sans dépendances lourdes (`psutil` + `Tkinter` + `WinMM`).

---

## ✨ Les 6 Onglets du Studio (Mode Simple & Avancé)

Chaque onglet propose une bascule instantanée **`⚡ Simple`** / **`⚙️ Avancé`** :

1. **🎵 Audio RAM**
   - **Simple** : Lecture / Stop + curseur Volume + choix Concerto MIDI ou Synthétiseur RAM.
   - **Avancé** : Formes d'onde temps réel (`sine`, `triangle`, `square`, `sawtooth`, `fm_pad`), gammes & toniques, progressions d'accords, tempo (BPM), quantification harmonique, réverbération, swing, humanisation, sample rate (`22050`/`44100`/`48000` Hz), mix de grain RAM brut, oscilloscope temps réel et export `.wav`.
2. **🖼️ Images RAM**
   - **Simple** : Génération instantanée **1 Image** ou **mode Continu** non-stop + export PNG.
   - **Avancé** : Générateurs algorithmiques (Plasma interférentiel, Fractale de Julia, Mandelbrot, Automate Cellulaire cyclique, Cristaux de Voronoi, Ondes & Réaction, Mosaïque Mémoire), palettes, symétries (kaléidoscope 8x), complexité, vitesse, résolution et auto-sauvegarde.
3. **🔐 Mots de Passe RAM**
   - **Simple** : Longueur + génération 1-clic + copie presse-papiers + jauge de robustesse.
   - **Avancé** : Modes Mot de passe, Passphrase, Clé Hex, Token Base64, PIN ; règles de caractères, exclusion des ambigus (`0O1lI|`), blanchiment cryptographique (`RAM + os.urandom` ou RAM pure déterministe), visualisation matricielle 256 octets et distribution d'entropie Shannon.
4. **🎬 Vidéo RAM**
   - **Simple** : Génération de clip (`MP4`, `GIF`, `AVI`) ou **Flux Continu** en direct avec aperçu.
   - **Avancé** : Shaders animés (`plasma_flow`, `julia_morph`, `voronoi_drift`, `cellular_life`, `wave_field`, `oscilloscope_spectrum`), FPS, durée, résolution jusqu'à `1280x720`, symétrie, bande-son synthétique RAM muxée (MP4/FFmpeg) et encodeurs natifs sans dépendance de secours (`AVI` / `GIF` pur Python).
5. **📜 Texte RAM**
   - **Simple** : Choix du style (Chaîne de Markov, Haïku 5-7-5, Poème structuré, Prose Mémoire, Pseudo-Code poétique), langue FR/EN, longueur, copie & export `.txt`.
   - **Avancé** : Température, ordre Markov (1 ou 2), pénalité de répétition, amorce textuelle, graine manuelle reproductible et corpus personnalisé.
6. **🧊 Modèle 3D RAM**
   - **Simple** : Topologies procédurales (`Supershape 3D`, `Terrain RAM`, `Géosphère`, `Tore Torsadé`, `Cristal Facetté`), génération **One-Shot** ou **Évolution Continue**, viewport **3D interactif** (glisser = rotation, molette = zoom) et export **`.obj` / `.stl`**.
   - **Avancé** : Modes de rendu (`Ombré + Arêtes`, `Solide Ombré`, `Fil de Fer`), thèmes couleur, subdivisions, amplitude, fréquence, torsion, lissage Laplacien, vitesse de morphing et export STL binaire/ASCII.

---

## 🛠️ Installation & Lancement

### Lancement rapide Windows
Double-cliquez sur **`Lancer_Projet.bat`** (crée/détecte automatiquement `venv` et lance le Studio).

### Ligne de commande
```bash
git clone https://github.com/je-tu-il/Song-of-my-Ram.git
cd Song-of-my-Ram
pip install -r requirements.txt
python main.py
```

*(Pour inspecter également les processus système protégés sous Windows : `python main.py --admin` ou cliquez sur **🛡️ Mode Admin** dans la barre supérieure. En mode standard, tous les processus utilisateur accessibles sont lus sans élévation.)*

### Dépendances optionnelles (accélération)
Le Studio fonctionne intégralement avec **`psutil`** seul. Pour accélérer les rendus haute résolution ou débloquer des encodeurs supplémentaires :
```bash
pip install numpy pillow opencv-python imageio
```
*(Avoir `ffmpeg` dans le `PATH` active en plus l'export MP4 H.264 avec mixage audio).*

---

## 🧪 Tests Automatisés

Exécutez `run_tests.bat` ou :
```bash
python -m unittest discover -s tests -v
```

---

## 🏗️ Structure du Projet

```text
Song-of-my-Ram/
├── main.py                  # Point d'entrée principal (--admin optionnel)
├── ram_audio.py / a.py      # Points d'entrée de compatibilité
├── ram_studio/
│   ├── ram_source.py        # Lecteur mémoire processus & pool d'entropie RAM
│   ├── codecs.py            # Codecs pur Python (PNG/GIF/AVI/WAV/WinMM PCM) + adaptateurs optionnels
│   ├── audio_engine.py      # Synthèse PCM temps réel & concerto MIDI
│   ├── image_engine.py      # Plasma, fractales, automates cellulaires, Voronoi, ondes
│   ├── password_engine.py   # Générateur mots de passe / passphrases & analytics entropie
│   ├── video_engine.py      # Clip MP4/GIF/AVI & flux continu
│   ├── text_engine.py       # Markov, Haïku, Poésie, Prose & Logs poétiques
│   ├── model3d_engine.py    # Maillages 3D procéduraux, projection interactive & export OBJ/STL
│   └── ui/                  # Interface moderne sombre à 6 onglets (Simple / Avancé)
├── tests/                   # Suite complète de tests unitaires & UI headless
├── Lancer_Projet.bat        # Lanceur Windows (venv auto)
└── run_tests.bat            # Lanceur de tests Windows
```

---

## 📄 Licence

Projet distribué sous licence MIT. Libre d'utilisation et de modification.
