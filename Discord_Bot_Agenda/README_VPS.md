# Installation sur le VPS Ubuntu (compte du développeur)

**Sécurité :** le jeton présent dans l’archive d’origine a été retiré. Réinitialiser ce jeton dans le portail développeur Discord avant d’installer cette version. Ne jamais transmettre le nouveau jeton dans un chat ou une archive.

## Préparer le VPS (administrateur, une seule fois)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip unzip
sudo loginctl enable-linger NOM_DU_COMPTE
```

Remplacer `NOM_DU_COMPTE` par le compte Linux du développeur. Le linger permet au service utilisateur de rester actif après sa déconnexion et de redémarrer avec le VPS. Installer sous son propre compte, séparément du bot Banque Van Horn.

## Installer (connecté avec le compte du développeur)

Copier l’archive sur le VPS avec SFTP, puis :

```bash
unzip Discord_Bot_Agenda_VPS.zip
cd Discord_Bot_Agenda
bash installer.sh
```

Le script demande le **nouveau** jeton et l’identifiant du serveur Discord. Il crée un environnement Python isolé et un service `systemd --user`. Les salons peuvent être configurés ensuite dans `.env` avec leurs identifiants (`AGENDA_CHANNEL_ID` et `REMINDER_CHANNEL_ID`), puis `systemctl --user restart agenda-jdr.service`.

## Vérifier

```bash
systemctl --user status agenda-jdr.service
journalctl --user -u agenda-jdr.service -n 80 --no-pager
```

La base `agenda_jdr.db` sera créée dans le dossier du bot. Sauvegarder ce fichier avant toute réinstallation. Ne pas exécuter deux copies du même bot avec la même base.

Le bot doit avoir été invité au serveur Discord avec les scopes `bot` et `applications.commands` et les permissions de lecture/écriture du salon. Les commandes prévues sont `/agenda`, `/partie_creer` et `/partie_annuler`. Les deux dernières demandent la permission Discord « Gérer le serveur ».
