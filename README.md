# 🎵 Song-of-my-Ram — RAM Synthesis & Audio Engine

[![Windows](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-blue.svg?logo=windows)](https://github.com/je-tu-il/Song-of-my-Ram/releases)
[![Release](https://img.shields.io/github/v/release/je-tu-il/Song-of-my-Ram?color=success&include_prereleases)](https://github.com/je-tu-il/Song-of-my-Ram/releases/latest)
[![Python](https://img.shields.io/badge/Python-3.9%2B-brightgreen.svg?logo=python)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Écoutez littéralement votre mémoire RAM !**  
> Une application graphique qui inspecte en temps réel la mémoire vive de vos processus Windows en cours d'exécution et la transcrit sous forme de concerto symphonique MIDI ou de synthèse sonore brute.

---

## ⚡ Téléchargement Rapide (Pour les Utilisateurs)

Vous n'avez **pas besoin d'installer Python ni aucune bibliothèque**.

👉 **[Télécharger Song-of-my-Ram.exe (Dernière Version)](https://github.com/je-tu-il/Song-of-my-Ram/releases/latest)**

1. Téléchargez le fichier `Song-of-my-Ram.exe` (ou le fichier `.zip` portable).
2. Double-cliquez pour exécuter l'application.
3. Acceptez la demande d'élévation Administrateur *(nécessaire sous Windows pour permettre la lecture inter-processus en mémoire vive)*.
4. Cliquez sur **▶ Démarrer la Lecture** et profitez de la symphonie de vos applications !

---

## 🎹 Fonctionnalités

- 🎼 **Mode Concerto MIDI (Recommandé & Natif)** :
  - Assigne automatiquement chaque processus majeur (navigateur, éditeur, explorer...) à un instrument spécifique (Violoncelle, Piano Électrique, Saxophone Alto, Marimba, Glockenspiel, Guitare, Basse Synth...).
  - Mappe les octets de mémoire sur des gammes harmoniques (basses, accords, arpèges, mélodies) à un tempo réglable (BPM).
  - Utilise le synthétiseur MIDI matériel natif de Windows (`winmm`) : **aucun lag, aucun pilote à installer**.
- ⚡ **Mode Électronique (Raw PCM direct)** :
  - Écoute brute des octets de la RAM sous forme de flux audio direct.
- 🔄 **Détection Automatique & Rafraîchissement** :
  - Sélectionne dynamiquement les processus les plus actifs en mémoire vive avec affichage des PID et de la mémoire consommée en Mo.
- 🎚️ **Contrôle du Tempo** :
  - Ajustez le tempo en direct de 20 à 200 BPM avec le curseur fluide.

---

## 🛠️ Lancement pour Développeurs (Code Source)

Si vous souhaitez exécuter ou modifier le code source Python :

### Prérequis
- Windows 10 ou 11 (64-bit)
- Python 3.9 ou supérieur

### Installation
```bash
git clone https://github.com/je-tu-il/Song-of-my-Ram.git
cd Song-of-my-Ram
pip install -r requirements.txt
```

### Lancement
```bash
python main.py
```

*(Note : Si vous souhaitez également utiliser le mode expérimental Raw PCM, installez `pip install pyaudio`).*

---

## 🧠 Fonctionnement Technique

L'application exploite l'API Win32 bas niveau pour parcourir la mémoire vive sans impacter la stabilité du système :
1. **Énumération** : `psutil` et `OpenProcess` scannent les processus utilisateur ayant les plus gros ensembles de travail (`RSS`).
2. **Filtrage Mémoire** : `VirtualQueryEx` identifie les pages mémoires allouées (`MEM_COMMIT`) tout en excluant systématiquement les pages protégées (`PAGE_GUARD`, `PAGE_NOACCESS`) pour prévenir toute violation d'accès.
3. **Lecture sécurisée** : `ReadProcessMemory` extrait les octets par pas d'échantillonnage réguliers.
4. **Restitution Audio** :
   - Mode MIDI : Les octets modulent la hauteur des notes (`midiOutShortMsg`) selon des tables de quantification modale.
   - Mode PCM : Écriture séquentielle dans un buffer audio 44.1 kHz.

---

## 📄 Licence

Projet distribué sous licence MIT. Libre d'utilisation et de modification.
