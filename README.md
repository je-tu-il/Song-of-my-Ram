# Lecteur RAM Audio

Interface graphique permettant de lire la mémoire virtuelle d'un processus Windows cible et de la restituer sous forme de flux audio PCM en temps réel.

## Prérequis

- Système d'exploitation : Windows
- Python 3.x
- Bibliothèque `pyaudio`

## Installation

Installer la dépendance requise :
```bash
pip install pyaudio
```

## Utilisation

1. Exécuter le script avec des privilèges Administrateur (obligatoire pour la lecture inter-processus) :
   ```bash
   python ram_audio.py
   ```
2. L'interface affiche l'état de la lecture.
3. Quatre options sont disponibles pour modifier la source dynamiquement :
   - Lire `explorer.exe`
   - Lire `notepad.exe`
   - Lire `cmd.exe`
   - Lire un Custom PID (nécessite la saisie de l'identifiant du processus dans le champ dédié)
4. Le bouton "Pause" stoppe la lecture en cours.

## Fonctionnement technique

Le script utilise l'API Win32 (`OpenProcess`, `VirtualQueryEx`, `ReadProcessMemory`) pour identifier les pages mémoire allouées (`MEM_COMMIT`) et accessibles. Les blocs d'octets sont extraits et envoyés directement dans le tampon audio via `pyaudio`. Le résultat acoustique est un bruit numérique aléatoire dépendant des structures de données en mémoire.
