import os
import datetime
import httpx
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
API_BASE = os.getenv("BACKEND_URL").rstrip("/")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


# sync our slash commands on startup
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"🗡️ Logged in as {bot.user} — synced slash commands.")


# /reportkill
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
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{API_BASE}/reportKill", json=payload, timeout=10.0
            )
        resp.raise_for_status()
    except Exception as e:
        return await interaction.followup.send(f"❌ Failed to report kill:\n```{e}```")
    await interaction.followup.send(
        f"✅ Kill recorded for **{player}** vs **{victim}** at `{time}`."
    )


# /kills
@bot.tree.command(name="kills", description="Show the most recent kills")
async def kills(interaction: discord.Interaction):
    # tell Discord “I’m working on it…”
    await interaction.response.defer()

    # fetch from your FastAPI backend
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{API_BASE}/kills", timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        # send the error so the user knows something went wrong
        return await interaction.followup.send(f"❌ Could not fetch kills:\n```{e}```")

    if not data:
        return await interaction.followup.send("📭 No kills recorded yet.")

    # build a neat list (up to the last 5 kills)
    lines = []
    for e in data[-5:]:
        lines.append(
            f"**{e['id']}** • {e['player']} ➔ {e['victim']} • {e['time']} "
            f"({e['zone']}, {e['weapon']})"
        )

    # finally send back to Discord
    await interaction.followup.send("\n".join(lines))


# run
bot.run(TOKEN)
