import os
import datetime
import logging

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

if not TOKEN or not API_BASE or not API_KEY:
    logging.critical(
        "Missing configuration. "
        "Ensure DISCORD_TOKEN, BACKEND_URL, and BACKEND_KEY are set."
    )
    raise SystemExit(1)

# ─── Bot setup ────────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


class GenerateKeyView(View):
    """Persistent view that sits in #🔑-kill-tracker-key forever."""

    def __init__(self):
        super().__init__(timeout=None)  # never time out

    @discord.ui.button(
        label="Generate Key",
        style=discord.ButtonStyle.primary,
        emoji="🔑",
    )
    async def generate(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        """User clicked: POST /keys and DM them the key."""
        # call your backend
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{API_BASE}/keys",
                    headers={"X-Discord-ID": str(interaction.user.id)},
                    timeout=10.0,
                )
            resp.raise_for_status()
            data = resp.json()
            new_key = data["key"]
        except Exception as e:
            return await interaction.response.send_message(
                f"❌ Could not generate key:\n```{e}```",
                ephemeral=True,
            )

        embed = discord.Embed(
            title="Your API key has been generated:",
            description=f"`{new_key}`",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Usage",
            value=(
                "Use this key in your kill‑tracker client to post kills in "
                "#💀-pu-kill-feed and/or #💀-ac-kill-feed."
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


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
