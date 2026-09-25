# Bot Discord — Agenda JDR

Première version fonctionnelle d'un agenda JDR autonome pour Discord.

## Fonctionnalités

- Création de séances avec `/partie_creer`
- Créneaux : `journée`, `après-midi`, `soirée`
- Inscription par boutons
- Désinscription
- Liste d'attente automatique
- Consultation avec `/agenda`
- Annulation avec `/partie_annuler`
- Rappels automatiques à J-7 et J-1
- Base SQLite locale (`agenda_jdr.db`)
- Interface en français

## Installation

### 1. Créer une application Discord

Dans le Discord Developer Portal :

1. Crée une application.
2. Onglet **Bot** → crée le bot.
3. Copie son token.
4. Dans **OAuth2 → URL Generator**, sélectionne :
   - `bot`
   - `applications.commands`
5. Permissions recommandées :
   - View Channels
   - Send Messages
   - Embed Links
   - Read Message History

Invite le bot sur ton serveur.

### 2. Installer Python et les dépendances

```bash
python -m venv .venv
```

Windows :

```bash
.venv\Scripts\activate
pip install -r requirements.txt
```

Linux/macOS :

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configuration

Copie `.env.example` vers `.env`.

Renseigne :

- `DISCORD_TOKEN`
- `GUILD_ID`

Les IDs de salons sont optionnels.

Pour récupérer un ID Discord, active le **mode développeur** dans Discord.

### 4. Lancer

```bash
python bot.py
```

## Commandes

- `/agenda` — affiche les prochaines séances
- `/partie_creer` — crée une séance
- `/partie_annuler` — annule une séance

## Droits

Par défaut, seuls les membres disposant de la permission Discord
`Manage Guild` peuvent créer ou annuler des séances.

## Hébergement

Le projet fonctionne très bien :

- sur un PC Windows/Linux ;
- un Raspberry Pi ;
- un NAS ;
- un VPS.

La base SQLite reste locale et aucun Google Agenda ou autre calendrier externe n'est utilisé.
