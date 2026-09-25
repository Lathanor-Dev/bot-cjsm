import os
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Europe/Paris"))
AGENDA_CHANNEL_ID = int(os.getenv("AGENDA_CHANNEL_ID") or 0)
REMINDER_CHANNEL_ID = int(os.getenv("REMINDER_CHANNEL_ID") or 0)

DB_FILE = str(Path(__file__).resolve().parent / "agenda_jdr.db")

CRENEAUX = {
    "journee": ("🌞 Journée", 10),
    "apres_midi": ("☀️ Après-midi", 14),
    "soiree": ("🌙 Soirée", 20),
}

JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        channel_id INTEGER NOT NULL,
        message_id INTEGER,
        title TEXT NOT NULL,
        game TEXT,
        game_master_id INTEGER NOT NULL,
        event_date TEXT NOT NULL,
        slot TEXT NOT NULL,
        max_players INTEGER NOT NULL,
        cancelled INTEGER DEFAULT 0,
        reminder_7_sent INTEGER DEFAULT 0,
        reminder_1_sent INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS participants (
        event_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        status TEXT NOT NULL,
        joined_at TEXT NOT NULL,
        PRIMARY KEY(event_id, user_id)
    );
    """)
    conn.commit()
    conn.close()


def get_event(event_id: int):
    conn = db()
    row = conn.execute(
        "SELECT * FROM events WHERE id = ?", (event_id,)
    ).fetchone()
    conn.close()
    return row


def event_datetime(event):
    _, hour = CRENEAUX[event["slot"]]
    dt = datetime.strptime(event["event_date"], "%Y-%m-%d")
    return dt.replace(hour=hour, tzinfo=TIMEZONE)


def participant_counts(event_id):
    conn = db()
    rows = conn.execute("""
        SELECT status, COUNT(*) AS total
        FROM participants
        WHERE event_id = ?
        GROUP BY status
    """, (event_id,)).fetchall()
    conn.close()
    result = {"confirmed": 0, "waiting": 0}
    for row in rows:
        result[row["status"]] = row["total"]
    return result


def get_participants(event_id, status):
    conn = db()
    rows = conn.execute("""
        SELECT user_id FROM participants
        WHERE event_id = ? AND status = ?
        ORDER BY joined_at
    """, (event_id, status)).fetchall()
    conn.close()
    return [r["user_id"] for r in rows]


def build_embed(event):
    counts = participant_counts(event["id"])
    slot_name, _ = CRENEAUX[event["slot"]]
    dt = event_datetime(event)

    embed = discord.Embed(
        title=f"🎲 {event['title']}",
        description=(
            f"📅 **{JOURS[dt.weekday()].capitalize()} {dt.strftime('%d/%m/%Y')}**\n"
            f"{slot_name}\n"
            f"🎮 **Jeu :** {event['game'] or 'Non précisé'}"
        ),
        timestamp=dt,
    )

    embed.add_field(
        name="🎙️ MJ / Organisateur",
        value=f"<@{event['game_master_id']}>",
        inline=False,
    )
    embed.add_field(
        name="👥 Places",
        value=f"**{counts['confirmed']} / {event['max_players']}**",
        inline=True,
    )
    embed.add_field(
        name="⏳ Attente",
        value=str(counts["waiting"]),
        inline=True,
    )

    confirmed = get_participants(event["id"], "confirmed")
    waiting = get_participants(event["id"], "waiting")

    embed.add_field(
        name="✅ Participants",
        value="\n".join(f"<@{u}>" for u in confirmed) or "*Personne pour le moment*",
        inline=False,
    )
    if waiting:
        embed.add_field(
            name="⏳ Liste d'attente",
            value="\n".join(f"<@{u}>" for u in waiting),
            inline=False,
        )

    embed.set_footer(text=f"Partie #{event['id']} • Utilise les boutons ci-dessous")
    return embed


class EventView(discord.ui.View):
    def __init__(self, event_id: int):
        super().__init__(timeout=None)
        self.event_id = event_id

        join_button = discord.ui.Button(
            label="Je participe",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id=f"jdr_join_{event_id}",
        )
        leave_button = discord.ui.Button(
            label="Je me désinscris",
            emoji="❌",
            style=discord.ButtonStyle.secondary,
            custom_id=f"jdr_leave_{event_id}",
        )

        join_button.callback = self.join
        leave_button.callback = self.leave
        self.add_item(join_button)
        self.add_item(leave_button)

    async def refresh_message(self, interaction):
        event = get_event(self.event_id)
        if event and interaction.message:
            await interaction.message.edit(
                embed=build_embed(event),
                view=EventView(self.event_id),
            )

    async def join(self, interaction: discord.Interaction):
        event = get_event(self.event_id)

        if not event or event["cancelled"]:
            await interaction.response.send_message(
                "❌ Cette séance n'existe plus ou a été annulée.",
                ephemeral=True,
            )
            return

        if event_datetime(event) < datetime.now(TIMEZONE):
            await interaction.response.send_message(
                "❌ Cette séance est déjà passée.",
                ephemeral=True,
            )
            return

        conn = db()
        existing = conn.execute("""
            SELECT status FROM participants
            WHERE event_id = ? AND user_id = ?
        """, (self.event_id, interaction.user.id)).fetchone()

        if existing:
            conn.close()
            await interaction.response.send_message(
                "ℹ️ Tu es déjà inscrit à cette séance.",
                ephemeral=True,
            )
            return

        confirmed = conn.execute("""
            SELECT COUNT(*) AS total FROM participants
            WHERE event_id = ? AND status = 'confirmed'
        """, (self.event_id,)).fetchone()["total"]

        status = "confirmed" if confirmed < event["max_players"] else "waiting"

        conn.execute("""
            INSERT INTO participants(event_id, user_id, status, joined_at)
            VALUES (?, ?, ?, ?)
        """, (
            self.event_id,
            interaction.user.id,
            status,
            datetime.now(TIMEZONE).isoformat(),
        ))
        conn.commit()
        conn.close()

        await interaction.response.send_message(
            "✅ Inscription confirmée !" if status == "confirmed"
            else "⏳ La partie est complète : tu es ajouté à la liste d'attente.",
            ephemeral=True,
        )
        await self.refresh_message(interaction)

    async def leave(self, interaction: discord.Interaction):
        event = get_event(self.event_id)
        if not event:
            await interaction.response.send_message(
                "❌ Cette séance n'existe plus.",
                ephemeral=True,
            )
            return

        conn = db()
        existing = conn.execute("""
            SELECT status FROM participants
            WHERE event_id = ? AND user_id = ?
        """, (self.event_id, interaction.user.id)).fetchone()

        if not existing:
            conn.close()
            await interaction.response.send_message(
                "ℹ️ Tu n'es pas inscrit à cette séance.",
                ephemeral=True,
            )
            return

        was_confirmed = existing["status"] == "confirmed"

        conn.execute("""
            DELETE FROM participants
            WHERE event_id = ? AND user_id = ?
        """, (self.event_id, interaction.user.id))

        promoted = None
        if was_confirmed:
            waiting = conn.execute("""
                SELECT user_id FROM participants
                WHERE event_id = ? AND status = 'waiting'
                ORDER BY joined_at
                LIMIT 1
            """, (self.event_id,)).fetchone()

            if waiting:
                promoted = waiting["user_id"]
                conn.execute("""
                    UPDATE participants
                    SET status = 'confirmed'
                    WHERE event_id = ? AND user_id = ?
                """, (self.event_id, promoted))

        conn.commit()
        conn.close()

        message = "✅ Tu es désinscrit."
        if promoted:
            message += f" Une personne de la liste d'attente est promue."

        await interaction.response.send_message(message, ephemeral=True)

        if promoted and interaction.guild:
            member = interaction.guild.get_member(promoted)
            if member:
                try:
                    await member.send(
                        f"🎉 Une place s'est libérée pour **{event['title']}** ! "
                        "Tu es maintenant confirmé."
                    )
                except discord.Forbidden:
                    pass

        await self.refresh_message(interaction)


class AgendaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        init_db()

        # Les vues persistantes permettent aux boutons de survivre à un redémarrage.
        conn = db()
        events = conn.execute("""
            SELECT id FROM events WHERE cancelled = 0
        """).fetchall()
        conn.close()

        for event in events:
            self.add_view(EventView(event["id"]))

        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

        reminder_loop.start()


bot = AgendaBot()


def can_manage(interaction: discord.Interaction):
    return (
        interaction.user.guild_permissions.manage_guild
        or interaction.user.guild_permissions.administrator
    )


@bot.tree.command(name="agenda", description="Affiche les prochaines séances JDR")
async def agenda(interaction: discord.Interaction):
    conn = db()
    rows = conn.execute("""
        SELECT * FROM events
        WHERE guild_id = ?
          AND cancelled = 0
          AND event_date >= ?
        ORDER BY event_date, slot
        LIMIT 20
    """, (interaction.guild_id, datetime.now(TIMEZONE).date().isoformat())).fetchall()
    conn.close()

    if not rows:
        await interaction.response.send_message(
            "📭 Aucune séance JDR à venir.",
            ephemeral=True,
        )
        return

    embed = discord.Embed(title="📅 Agenda JDR — prochaines séances")

    for event in rows:
        counts = participant_counts(event["id"])
        slot_name, _ = CRENEAUX[event["slot"]]
        dt = event_datetime(event)

        embed.add_field(
            name=f"🎲 #{event['id']} — {event['title']}",
            value=(
                f"📅 {dt.strftime('%d/%m/%Y')} — {slot_name}\n"
                f"🎮 {event['game'] or 'Jeu non précisé'}\n"
                f"👥 {counts['confirmed']}/{event['max_players']} "
                f"• ⏳ {counts['waiting']} attente"
            ),
            inline=False,
        )

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="partie_creer", description="Crée une nouvelle séance JDR")
@app_commands.describe(
    titre="Nom de la partie ou de la campagne",
    date="Date au format JJ/MM/AAAA",
    creneau="Journée, après-midi ou soirée",
    jeu="Jeu de rôle",
    places="Nombre maximum de joueurs",
)
@app_commands.choices(creneau=[
    app_commands.Choice(name="🌞 Journée", value="journee"),
    app_commands.Choice(name="☀️ Après-midi", value="apres_midi"),
    app_commands.Choice(name="🌙 Soirée", value="soiree"),
])
async def partie_creer(
    interaction: discord.Interaction,
    titre: str,
    date: str,
    creneau: app_commands.Choice[str],
    jeu: str,
    places: app_commands.Range[int, 1, 30],
):
    if not can_manage(interaction):
        await interaction.response.send_message(
            "⛔ Seuls les organisateurs peuvent créer une séance.",
            ephemeral=True,
        )
        return

    try:
        event_date = datetime.strptime(date, "%d/%m/%Y").date()
    except ValueError:
        await interaction.response.send_message(
            "❌ Format de date invalide. Utilise **JJ/MM/AAAA**.",
            ephemeral=True,
        )
        return

    if event_date < datetime.now(TIMEZONE).date():
        await interaction.response.send_message(
            "❌ Impossible de créer une séance dans le passé.",
            ephemeral=True,
        )
        return

    channel_id = AGENDA_CHANNEL_ID or interaction.channel_id

    conn = db()
    cursor = conn.execute("""
        INSERT INTO events(
            guild_id, channel_id, title, game, game_master_id,
            event_date, slot, max_players, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        interaction.guild_id,
        channel_id,
        titre,
        jeu,
        interaction.user.id,
        event_date.isoformat(),
        creneau.value,
        places,
        datetime.now(TIMEZONE).isoformat(),
    ))
    event_id = cursor.lastrowid
    conn.commit()
    conn.close()

    event = get_event(event_id)
    target_channel = bot.get_channel(channel_id) or interaction.channel

    message = await target_channel.send(
        embed=build_embed(event),
        view=EventView(event_id),
    )

    conn = db()
    conn.execute(
        "UPDATE events SET message_id = ? WHERE id = ?",
        (message.id, event_id),
    )
    conn.commit()
    conn.close()

    await interaction.response.send_message(
        f"✅ Séance **#{event_id}** créée et publiée dans {target_channel.mention}.",
        ephemeral=True,
    )


@bot.tree.command(name="partie_modifier", description="Modifie une séance que tu as créée")
@app_commands.describe(
    numero="Numéro de la partie (visible dans le message)",
    titre="Nouveau titre (facultatif)",
    date="Nouvelle date au format JJ/MM/AAAA (facultatif)",
    creneau="Nouveau créneau (facultatif)",
    jeu="Nouveau jeu (facultatif)",
    places="Nouveau nombre de places (facultatif)",
)
@app_commands.choices(creneau=[
    app_commands.Choice(name="🌞 Journée", value="journee"),
    app_commands.Choice(name="☀️ Après-midi", value="apres_midi"),
    app_commands.Choice(name="🌙 Soirée", value="soiree"),
])
async def partie_modifier(
    interaction: discord.Interaction,
    numero: int,
    titre: str | None = None,
    date: str | None = None,
    creneau: app_commands.Choice[str] | None = None,
    jeu: str | None = None,
    places: app_commands.Range[int, 1, 30] | None = None,
):
    event = get_event(numero)
    if not event or event["guild_id"] != interaction.guild_id or event["cancelled"]:
        await interaction.response.send_message("❌ Partie introuvable ou annulée.", ephemeral=True)
        return

    if interaction.user.id != event["game_master_id"]:
        await interaction.response.send_message(
            "⛔ Seule la personne qui a créé cette partie peut la modifier.", ephemeral=True
        )
        return

    if all(value is None for value in (titre, date, creneau, jeu, places)):
        await interaction.response.send_message("❌ Indique au moins un champ à modifier.", ephemeral=True)
        return

    if titre is not None and not titre.strip():
        await interaction.response.send_message("❌ Le titre ne peut pas être vide.", ephemeral=True)
        return

    if jeu is not None and not jeu.strip():
        await interaction.response.send_message("❌ Le jeu ne peut pas être vide.", ephemeral=True)
        return

    try:
        new_date = datetime.strptime(date, "%d/%m/%Y").date().isoformat() if date else event["event_date"]
    except ValueError:
        await interaction.response.send_message("❌ Format de date invalide. Utilise JJ/MM/AAAA.", ephemeral=True)
        return

    new_slot = creneau.value if creneau else event["slot"]
    proposed = {"event_date": new_date, "slot": new_slot}
    if event_datetime(proposed) <= datetime.now(TIMEZONE):
        await interaction.response.send_message("❌ La séance doit être dans le futur.", ephemeral=True)
        return

    new_places = places if places is not None else event["max_players"]
    confirmed = participant_counts(numero)["confirmed"]
    if new_places < confirmed:
        await interaction.response.send_message(
            f"❌ Il y a déjà {confirmed} personnes inscrites : impossible de réduire à {new_places} places.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)
    schedule_changed = new_date != event["event_date"] or new_slot != event["slot"]
    conn = db()
    conn.execute("""
        UPDATE events SET title = ?, game = ?, event_date = ?, slot = ?,
            max_players = ?, reminder_7_sent = ?, reminder_1_sent = ?
        WHERE id = ? AND guild_id = ? AND game_master_id = ? AND cancelled = 0
    """, (
        titre.strip() if titre is not None else event["title"],
        jeu.strip() if jeu is not None else event["game"],
        new_date, new_slot, new_places,
        0 if schedule_changed else event["reminder_7_sent"],
        0 if schedule_changed else event["reminder_1_sent"],
        numero, interaction.guild_id, interaction.user.id,
    ))
    conn.commit()
    conn.close()

    if not event["message_id"]:
        await interaction.followup.send(
            "✅ Partie modifiée dans l'agenda, mais son message Discord est introuvable.", ephemeral=True
        )
        return

    try:
        channel = bot.get_channel(event["channel_id"]) or await bot.fetch_channel(event["channel_id"])
        message = await channel.fetch_message(event["message_id"])
        await message.edit(embed=build_embed(get_event(numero)), view=EventView(numero))
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        await interaction.followup.send(
            "✅ Partie modifiée dans l'agenda, mais le message Discord n'a pas pu être actualisé. Vérifie le salon et les permissions du bot.",
            ephemeral=True,
        )
        return

    await interaction.followup.send(f"✅ La partie **#{numero}** a été modifiée.", ephemeral=True)


@bot.tree.command(name="partie_annuler", description="Annule une séance")
@app_commands.describe(numero="Numéro de la partie")
async def partie_annuler(interaction: discord.Interaction, numero: int):
    if not can_manage(interaction):
        await interaction.response.send_message(
            "⛔ Seuls les organisateurs peuvent annuler une séance.",
            ephemeral=True,
        )
        return

    event = get_event(numero)
    if not event or event["guild_id"] != interaction.guild_id:
        await interaction.response.send_message(
            "❌ Partie introuvable.",
            ephemeral=True,
        )
        return

    conn = db()
    conn.execute("UPDATE events SET cancelled = 1 WHERE id = ?", (numero,))
    conn.commit()
    conn.close()

    try:
        channel = bot.get_channel(event["channel_id"])
        if channel and event["message_id"]:
            message = await channel.fetch_message(event["message_id"])
            embed = discord.Embed(
                title=f"❌ ANNULÉ — {event['title']}",
                description="Cette séance a été annulée.",
            )
            await message.edit(embed=embed, view=None)
    except (discord.NotFound, discord.Forbidden):
        pass

    await interaction.response.send_message(
        f"❌ La partie **#{numero}** est annulée.",
        ephemeral=True,
    )


@tasks.loop(minutes=30)
async def reminder_loop():
    now = datetime.now(TIMEZONE)

    conn = db()
    events = conn.execute("""
        SELECT * FROM events
        WHERE cancelled = 0
          AND event_date >= ?
    """, (now.date().isoformat(),)).fetchall()
    conn.close()

    for event in events:
        dt = event_datetime(event)
        delta = dt - now

        reminder_type = None
        field = None

        # Fenêtre volontairement large car la tâche tourne toutes les 30 minutes.
        if timedelta(days=6, hours=23) <= delta <= timedelta(days=7, hours=1):
            reminder_type = "📅 Dans une semaine"
            field = "reminder_7_sent"
        elif timedelta(hours=23) <= delta <= timedelta(days=1, hours=1):
            reminder_type = "⏰ Demain"
            field = "reminder_1_sent"

        if not field or event[field]:
            continue

        channel_id = REMINDER_CHANNEL_ID or event["channel_id"]
        channel = bot.get_channel(channel_id)

        if channel:
            counts = participant_counts(event["id"])
            await channel.send(
                f"{reminder_type} : **🎲 {event['title']}**\n"
                f"📅 {dt.strftime('%d/%m/%Y')} — {CRENEAUX[event['slot']][0]}\n"
                f"👥 {counts['confirmed']}/{event['max_players']} joueurs inscrits"
            )

        else:
            continue

        conn = db()
        conn.execute(
            f"UPDATE events SET {field} = 1 WHERE id = ?",
            (event["id"],),
        )
        conn.commit()
        conn.close()


@reminder_loop.before_loop
async def before_reminder_loop():
    await bot.wait_until_ready()


if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN est absent. Crée un fichier .env à partir de .env.example."
    )

bot.run(TOKEN)
