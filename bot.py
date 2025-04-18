import os
import datetime
import logging

import httpx
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from discord import ui, ButtonStyle, Embed

# ─── Load & validate env ─────────────────────────────────────────────────────────
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
API_BASE = os.getenv("BACKEND_URL", "").rstrip("/")
API_KEY = os.getenv("BACKEND_KEY")
KEY_CHANNEL_ID = int(
    os.getenv("KEY_CHANNEL_ID")
)  # put your #kill-tracker-key channel’s ID here

if not TOKEN or not API_BASE or not API_KEY:
    logging.critical(
        "Missing configuration. "
        "Ensure DISCORD_TOKEN, BACKEND_URL, and BACKEND_KEY are set."
    )
    raise SystemExit(1)

# ─── Bot setup ────────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


class GenerateKeyView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Generate Key", style=ButtonStyle.primary, emoji="🔑")
    async def generate_key(self, button: ui.Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # call your FastAPI /keys endpoint
        discord_id = str(interaction.user.id)
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{API_BASE}/keys",
                    headers={"X-Discord-ID": discord_id},
                    timeout=10.0,
                )
            resp.raise_for_status()
            key = resp.json()["key"]
        except Exception as e:
            return await interaction.followup.send(
                f"❌ Could not generate key:\n```{e}```", ephemeral=True
            )

        embed = Embed(
            title="🔑 Your Kill‑Tracker API Key",
            description=f"```{key}```\nUse this key in your BeowulfHunter client. Valid for 72 hours.",
            color=discord.Color.blue(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"🗡️ Logged in as {bot.user} — slash commands synced.")

    # post (or re‑post) the Generate Key prompt in your key channel
    channel = bot.get_channel(KEY_CHANNEL_ID)
    if channel:
        view = GenerateKeyView()
        embed = Embed(
            title="Generate BlightVeil Kill Tracker Key",
            description=(
                "Click the button below to generate a unique key for the BlightVeil Kill‑Tracker.\n\n"
                "Each key is valid for 72 hours. You may generate a new one at any time."
            ),
            color=discord.Color.dark_gray(),
        )
        embed.set_footer(
            text="Use this key in your client to post kills to #💀‑pu‑kill‑feed and/or #💀‑ac‑kill‑feed."
        )
        # you might want to delete any previous prompt messages here,
        # or check that you only send it once.
        await channel.send(embed=embed, view=view)


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
    time = time or datetime.datetime.utcnow().isoformat()
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
    except httpx.HTTPStatusError:
        body = resp.text
        return await interaction.followup.send(
            f"❌ ReportKill failed [{resp.status_code}]:\n```{body}```"
        )
    except Exception as e:
        return await interaction.followup.send(f"❌ Error: `{e}`")

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


bot.run(TOKEN)
