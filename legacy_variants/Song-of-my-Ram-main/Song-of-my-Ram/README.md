# Song of my RAM

Deux expériences Windows qui transforment la mémoire de processus en matière artistique : une orchestration MIDI et une série d'images cohérentes.

## Prérequis

- Système d'exploitation : Windows
- Python 3.x
- Bibliothèques Python `pyaudio`, `psutil` et `Pillow`, ainsi que FFmpeg dans le `PATH`

## Installation

Installer la dépendance requise :
```bash
pip install pyaudio psutil Pillow
```

## Utilisation

1. Exécuter le script avec des privilèges Administrateur (obligatoire pour la lecture inter-processus) :
   ```bash
   python a.py
   ```
2. L'interface affiche l'état de la lecture.
3. Quatre options sont disponibles pour modifier la source dynamiquement :
   - Lire `explorer.exe`
   - Lire `notepad.exe`
   - Lire `cmd.exe`
   - Lire un Custom PID (nécessite la saisie de l'identifiant du processus dans le champ dédié)
4. Le bouton "Pause" stoppe la lecture en cours.

## Fonctionnement technique

Le script utilise l'API Win32 (`OpenProcess`, `VirtualQueryEx`, `ReadProcessMemory`) pour lire des octets dans les pages mémoire accessibles. En mode MIDI, les valeurs sont lissées puis quantifiées dans une progression commune, avec des rôles rythmiques différents.

## Video coherente

Lancer :
```bash
python ram_images.py
```

Le générateur conserve une palette, une graine liée aux processus et des formes persistantes pendant toute la vidéo. Chaque frame varie avec l'énergie moyenne de la mémoire et est encodée dans un MP4 16:9 enregistré dans `ram_images/`. L'option de bande-son RAM crée une piste harmonique à partir des mêmes échantillons mémoire et l'ajoute au MP4. Les réglages sont `FPS`, puis `Duree (s)`. FFmpeg doit être installé et accessible depuis le `PATH`.
