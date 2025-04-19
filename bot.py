import os
import datetime
import logging
import asyncio
from discord.ext import tasks
import httpx
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from discord import ui, ButtonStyle, Embed
from discord.ui import View

# ─── Load & validate env ─────────────────────────────────────────────────────────
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
API_BASE = os.getenv("BACKEND_URL", "").rstrip("/")
API_KEY = os.getenv("BACKEND_KEY")
KEY_CHANNEL_ID = int(
    os.getenv("KEY_CHANNEL_ID")
)  # put your #kill-tracker-key channel’s ID here
PU_KILL_FEED_ID = int(os.getenv("PU_KILL_FEED"))
AC_KILL_FEED_ID = int(os.getenv("AC_KILL_FEED"))

if not TOKEN or not API_BASE or not API_KEY:
    logging.critical(
        "Missing configuration. "
        "Ensure DISCORD_TOKEN, BACKEND_URL, and BACKEND_KEY are set."
    )
    raise SystemExit(1)

# ─── Bot setup ────────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


class GenerateKeyView(discord.ui.View):
    """Persistent view that sits in #🔑-kill-tracker-key forever."""

    def __init__(self):
        super().__init__(timeout=None)  # never time out

    @discord.ui.button(
        label="Generate Key",
        style=discord.ButtonStyle.primary,
        emoji="🔑",
    )
    async def generate_key(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        # show the “thinking…” indicator (ephemeral so only they see it)
        await interaction.response.defer(ephemeral=True)

        # call your backend to mint a new key
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{API_BASE}/keys",
                    headers={
                        "Authorization": f"Bearer {API_KEY}",
                        "X-Discord-ID": str(interaction.user.id),
                    },
                    timeout=10.0,
                )
            resp.raise_for_status()
            data = resp.json()
            new_key = data["key"]
        except Exception as e:
            return await interaction.followup.send(
                f"❌ Could not generate key:\n```{e}```",
                ephemeral=True,
            )

        # DM them back their new key
        await interaction.followup.send(
            f"🔑 **Your API key** has been generated:\n```\n{new_key}\n```",
            ephemeral=True,
        )


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"🗡️ Logged in as {bot.user} — slash commands synced.")

    # send the “generate key” embed + button once, if it’s not already there
    channel = bot.get_channel(KEY_CHANNEL_ID)
    if channel:
        embed = discord.Embed(
            title="Generate BlightVeil Kill Tracker Key",
            description=(
                "Click the button below to generate a unique key for the "
                "BlightVeil Kill Tracker. Use this key in your kill tracker "
                "client to post your kills in the #💀-pu-kill-feed and/or "
                "#💀-ac-kill-feed.\n\n"
                "Each key is valid for 72 hours. You may generate a new key at any time.\n\n"
                "[Download BV KillTracker](https://example.com/download)\n"
            ),
            color=discord.Color.dark_gray(),
        )
        # attach our persistent view
        await channel.send(embed=embed, view=GenerateKeyView())


# ─── /reportkill ─────────────────────────────────────────────────────────────────
@bot.tree.command(name="reportkill", description="Report a new kill")
@app_commands.describe(
    player="Name of the killer",
    victim="Name of the victim",
    zone="Where it happened",
    weapon="Weapon used",
    damage_type="Type of damage",
    time="ISO timestamp (defaults to now)",
    mode="Which mode: PU or AC",
)
@app_commands.choices(
    mode=[
        app_commands.Choice(name="Public Universe", value="pu-kill"),
        app_commands.Choice(name="Arena Commander", value="ac-kill"),
    ]
)
async def reportkill(
    interaction: discord.Interaction,
    player: str,
    victim: str,
    zone: str,
    weapon: str,
    damage_type: str,
    time: str = None,
    mode: str = "pu-kill",
):
    # 1) defer & prepare
    await interaction.response.defer(ephemeral=True)
    time = time or datetime.datetime.utcnow().isoformat()
    payload = {
        "player": player,
        "victim": victim,
        "zone": zone,
        "weapon": weapon,
        "damage_type": damage_type,
        "time": time,
        "mode": mode,
    }
    headers = {"Authorization": f"Bearer {API_KEY}"}

    # 2) send to backend
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{API_BASE}/reportKill",
                json=payload,
                headers=headers,
                timeout=10.0,
            )
        resp.raise_for_status()
    except Exception as e:
        return await interaction.followup.send(
            f"❌ Could not record kill:\n```{e}```", ephemeral=True
        )

    # 3) confirm to the user
    await interaction.followup.send(
        f"✅ Kill recorded for **{player}** vs **{victim}** at `{time}`.",
        ephemeral=True,
    )

    # 4) mirror to the proper feed channel
    feed_id = PU_KILL_FEED_ID if mode == "pu-kill" else AC_KILL_FEED_ID
    channel = interaction.client.get_channel(feed_id)
    if channel:
        embed = discord.Embed(
            title="BlightVeil Kill",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Killer", value=player, inline=True)
        embed.add_field(name="Victim", value=victim, inline=True)
        embed.add_field(name="Zone", value=zone, inline=True)
        embed.add_field(name="Weapon", value=weapon, inline=True)
        embed.add_field(name="Damage", value=damage_type, inline=True)
        embed.add_field(name="Time", value=time, inline=False)
        await channel.send(embed=embed)


# ─── /kills ──────────────────────────────────────────────────────────────────────
@bot.tree.command(name="kills", description="Show the most recent kills")
async def kills(interaction: discord.Interaction):
    await interaction.response.defer()
    headers = {"Authorization": f"Bearer {API_KEY}"}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{API_BASE}/kills", headers=headers, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError:
        body = resp.text
        return await interaction.followup.send(
            f"❌ ListKills failed [{resp.status_code}]:\n```{body}```"
        )
    except Exception as e:
        return await interaction.followup.send(f"❌ Error: `{e}`")

    if not data:
        return await interaction.followup.send("📭 No kills recorded yet.")

    lines = [
        f"**{e['id']}** • {e['player']} ➔ {e['victim']} • {e['time']} "
        f"({e['zone']}, {e['weapon']})"
        for e in data[-5:]
    ]
    await interaction.followup.send("\n".join(lines))


# Keep track of the highest kill ID we've posted so far
last_kill_id = 0


@tasks.loop(seconds=10)  # run every 10 seconds (tune as you like)
async def fetch_and_post_kills():
    global last_kill_id

    headers = {"Authorization": f"Bearer {API_KEY}"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_BASE}/kills", headers=headers, timeout=10.0)
    resp.raise_for_status()
    kills = resp.json()

    # Sort oldest → newest
    kills.sort(key=lambda e: e["id"])

    for kill in kills:
        if kill["id"] <= last_kill_id:
            continue

        # choose feed channel
        feed_id = PU_KILL_FEED_ID if kill["mode"] == "pu-kill" else AC_KILL_FEED_ID
        channel = bot.get_channel(feed_id)
        if not channel:
            continue

        embed = discord.Embed(
            title="BlightVeil Kill",
            color=discord.Color.red(),
            timestamp=discord.utils.parse_time(kill["time"]),
        )
        embed.add_field(name="Killer", value=kill["player"], inline=True)
        embed.add_field(name="Victim", value=kill["victim"], inline=True)
        embed.add_field(name="Zone", value=kill["zone"], inline=True)
        embed.add_field(name="Weapon", value=kill["weapon"], inline=True)
        embed.add_field(name="Damage", value=kill["damage_type"], inline=True)
        embed.add_field(name="Time", value=kill["time"], inline=False)

        await channel.send(embed=embed)
        last_kill_id = kill["id"]


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"🗡️ Logged in as {bot.user} — slash commands synced.")

    # send your GenerateKeyView here…
    # …

    # start our polling loop if not already running
    if not fetch_and_post_kills.is_running():
        fetch_and_post_kills.start()


bot.run(TOKEN)
