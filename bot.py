import os
import datetime
import logging

import httpx
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# ─── Load & validate env ─────────────────────────────────────────────────────────
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
API_BASE = os.getenv("BACKEND_URL", "").rstrip("/")
API_KEY = os.getenv("BACKEND_KEY")

if not TOKEN or not API_BASE or not API_KEY:
    logging.critical(
        "Missing configuration. "
        "Ensure DISCORD_TOKEN, BACKEND_URL, and BACKEND_KEY are set."
    )
    raise SystemExit(1)

# ─── Bot setup ────────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"🗡️ Logged in as {bot.user} — slash commands synced.")


# ─── /reportkill ─────────────────────────────────────────────────────────────────
@bot.tree.command(name="reportkill", description="Report a new kill")
@app_commands.describe(
    player="Name of the killer",
    victim="Name of the victim",
    zone="Where it happened",
    weapon="Weapon used",
    damage_type="Type of damage",
    time="ISO timestamp (defaults to now)",
)
async def reportkill(
    interaction: discord.Interaction,
    player: str,
    victim: str,
    zone: str,
    weapon: str,
    damage_type: str,
    time: str = None,
):
    await interaction.response.defer()
    if time is None:
        time = datetime.datetime.utcnow().isoformat()

    payload = {
        "player": player,
        "victim": victim,
        "zone": zone,
        "weapon": weapon,
        "damage_type": damage_type,
        "time": time,
        "mode": "pu-kill",
    }
    headers = {"Authorization": f"Bearer {API_KEY}"}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{API_BASE}/reportKill",
                json=payload,
                headers=headers,
                timeout=10.0,
            )
        resp.raise_for_status()
    except httpx.HTTPStatusError as http_err:
        # bubble up the response body for debugging
        text = await resp.aread()
        return await interaction.followup.send(
            f"❌ Failed to report kill (status {resp.status_code}):\n```{text}```"
        )
    except Exception as e:
        return await interaction.followup.send(f"❌ Failed to report kill:\n```{e}```")

    await interaction.followup.send(
        f"✅ Kill recorded for **{player}** vs **{victim}** at `{time}`."
    )


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
    except httpx.HTTPStatusError as http_err:
        text = await resp.aread()
        return await interaction.followup.send(
            f"❌ Could not fetch kills (status {resp.status_code}):\n```{text}```"
        )
    except Exception as e:
        return await interaction.followup.send(f"❌ Could not fetch kills:\n```{e}```")

    if not data:
        return await interaction.followup.send("📭 No kills recorded yet.")

    # show up to the last 5
    lines = [
        f"**{e['id']}** • {e['player']} ➔ {e['victim']} • {e['time']} "
        f"({e['zone']}, {e['weapon']})"
        for e in data[-5:]
    ]
    await interaction.followup.send("\n".join(lines))


# ─── Run ─────────────────────────────────────────────────────────────────────────
bot.run(TOKEN)
