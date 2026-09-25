#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null || ! python3 -m venv --help >/dev/null 2>&1; then
  echo "Python 3 et python3-venv sont requis. Demande à l’administrateur du VPS de les installer." >&2
  exit 1
fi
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
if [[ ! -f .env ]]; then
  read -r -s -p "Nouveau token Discord (rien ne s’affiche) : " token
  echo
  if [[ -z "$token" ]]; then echo "Token vide : installation arrêtée." >&2; exit 1; fi
  read -r -p "ID du serveur Discord (GUILD_ID) : " guild
  if [[ ! "$guild" =~ ^[0-9]+$ ]] || [[ "$guild" == 0 ]]; then echo "ID invalide." >&2; exit 1; fi
  umask 077
  {
    printf 'DISCORD_TOKEN=%s\n' "$token"
    printf 'GUILD_ID=%s\n' "$guild"
    printf 'TIMEZONE=Europe/Brussels\nAGENDA_CHANNEL_ID=\nREMINDER_CHANNEL_ID=\n'
  } > .env
fi
chmod 600 .env
if ! command -v systemctl >/dev/null; then
  echo "Dépendances installées. Démarre avec : .venv/bin/python bot.py"
  exit 0
fi
unit_dir="$HOME/.config/systemd/user"
mkdir -p "$unit_dir"
cat > "$unit_dir/agenda-jdr.service" <<EOF
[Unit]
Description=Bot Discord Agenda JDR
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/.venv/bin/python $(pwd)/bot.py
Restart=on-failure
RestartSec=10
[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now agenda-jdr.service
echo "Bot installé. État : systemctl --user status agenda-jdr.service"
echo "Journaux : journalctl --user -u agenda-jdr.service -f"
echo "Pour démarrer après un redémarrage sans connexion SSH, l’administrateur doit exécuter : sudo loginctl enable-linger $(whoami)"
