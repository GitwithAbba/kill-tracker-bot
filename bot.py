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
import traceback

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

# Register the persistent view *before* we log in*


class GenerateKeyView(discord.ui.View):
    def __init__(self):
        # make this view truly persistent
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Generate Key",
        style=discord.ButtonStyle.primary,
        emoji="🔑",
        custom_id="killtracker:generate_key",
    )
    async def generate_key(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        try:
            await interaction.response.defer(ephemeral=True)
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
            new_key = resp.json()["key"]
            await interaction.followup.send(
                f"🔑 **Your API key** has been generated:\n```\n{new_key}\n```",
                ephemeral=True,
            )
        except Exception as e:
            traceback.print_exc()
            await interaction.followup.send(
                f"❌ Something went wrong generating your key:\n```{e}```",
                ephemeral=True,
            )


@bot.event
async def on_ready():
    # register our persistent view
    bot.add_view(GenerateKeyView())

    # sync slash commands
    await bot.tree.sync()
    print(f"🗡️ Logged in as {bot.user} — slash commands synced.")

    # post the “Generate Key” card if it’s not already there...
    channel = bot.get_channel(KEY_CHANNEL_ID)
    if channel:
        async for msg in channel.history(limit=50):
            if msg.author.id == bot.user.id and msg.embeds:
                break
        else:
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
            await channel.send(embed=embed, view=GenerateKeyView())

    # prime last_kill_id so we don’t backfill
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/kills", headers={"Authorization": f"Bearer {API_KEY}"}
        )
        resp.raise_for_status()
        all_kills = resp.json()
    if all_kills:
        global last_kill_id
        last_kill_id = max(k["id"] for k in all_kills)

    # start your kill loop
    if not fetch_and_post_kills.is_running():
        fetch_and_post_kills.start()

    # **start your death loop** right here
    if not fetch_and_post_deaths.is_running():
        fetch_and_post_deaths.start()


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
        # make the killer’s name clickable
        profile_url = f"https://robertsspaceindustries.com/citizens/{player}"
        embed.set_author(name=player, url=profile_url)
        # if you have an avatar URL from your API, do:
        # embed.set_thumbnail(url=avatar_url)

        # victim as a link too
        victim_url = f"https://robertsspaceindustries.com/citizens/{victim}"
        embed.add_field(name="Victim", value=f"[{victim}]({victim_url})", inline=True)

        embed.add_field(name="Zone", value=zone, inline=True)
        embed.add_field(name="Weapon", value=weapon, inline=True)
        embed.add_field(name="Damage", value=damage_type, inline=True)

        # extra fields from your backend payload
        embed.add_field(name="Mode", value=mode, inline=True)
        embed.add_field(
            name="Ship", value=payload.get("killers_ship", "N/A"), inline=True
        )

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


@tasks.loop(seconds=10)
async def fetch_and_post_kills():
    global last_kill_id
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/kills", headers={"Authorization": f"Bearer {API_KEY}"}
        )
        resp.raise_for_status()
        kills = resp.json()

    for kill in sorted(kills, key=lambda e: e["id"]):
        if kill["id"] <= last_kill_id:
            continue

        # Decide which feed channel
        feed_id = PU_KILL_FEED_ID if kill["mode"] == "pu-kill" else AC_KILL_FEED_ID
        channel = bot.get_channel(feed_id)
        if not channel:
            continue

        # 1) Build separate URLs for killer vs. victim
        killer_url = f"https://robertsspaceindustries.com/citizens/{kill['player']}"
        victim_url = kill.get(
            "rsi_profile",
            f"https://robertsspaceindustries.com/citizens/{kill['victim']}",
        )

        # 2) Pull avatar (or fall back to your logo)
        avatar_url = kill.get(
            "avatar_url", "https://your.cdn/default_avatar_or_logo.png"
        )

        # 3) Pull organization (or fall back to “Unknown”)
        victim_org = kill.get("organization") or "Unknown"

        embed = discord.Embed(
            title="RRR Kill",
            color=discord.Color.red(),
            timestamp=discord.utils.parse_time(kill["time"]),
        )

        # Author block (clickable killer name + avatar)
        embed.set_author(
            name=kill["player"],
            url=killer_url,
            icon_url=avatar_url,
        )

        # Thumbnail (bigger version of avatar/logo)
        embed.set_thumbnail(url=avatar_url)

        # Victim as a markdown link
        embed.add_field(
            name="Victim",
            value=f"[{kill['victim']}]({victim_url})",
            inline=True,
        )

        # Standard fields
        embed.add_field(name="Zone", value=kill["zone"], inline=True)
        embed.add_field(name="Weapon", value=kill["weapon"], inline=True)
        embed.add_field(name="Damage", value=kill["damage_type"], inline=True)

        # Richer fields
        embed.add_field(name="Mode", value=kill.get("game_mode", "—"), inline=True)
        embed.add_field(
            name="Killer’s Ship", value=kill.get("killers_ship", "—"), inline=True
        )
        embed.add_field(name="Victim Organization", value=victim_org, inline=True)

        await channel.send(embed=embed)
        last_kill_id = kill["id"]


# Keep track of the last‑seen death time
last_death_id = ""  # or datetime, whichever you prefer


@tasks.loop(seconds=10)
async def fetch_and_post_deaths():
    global last_death_id

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/deaths", headers={"Authorization": f"Bearer {API_KEY}"}
        )
        resp.raise_for_status()
        deaths = resp.json()

    for death in sorted(deaths, key=lambda e: e["time"]):
        if death["time"] <= last_death_id:
            continue

        # choose feed channel (you can also pick a dedicated “deaths” channel)
        feed_id = PU_KILL_FEED_ID if "pu" in death["mode"].lower() else AC_KILL_FEED_ID
        channel = bot.get_channel(feed_id)
        if not channel:
            continue

        embed = discord.Embed(
            title="💀 You Died",
            color=discord.Color.dark_gray(),
            timestamp=discord.utils.parse_time(death["time"]),
        )

        # Author = who killed you
        embed.set_author(
            name=death["player"],  # the killer’s handle
            url=death.get("rsi_profile"),  # their RSI profile
        )

        # thumbnail their avatar if present
        if death.get("avatar_url"):
            embed.set_thumbnail(url=death["avatar_url"])

        # core fields
        embed.add_field(name="Victim (You)", value=death["victim"], inline=True)
        embed.add_field(name="Zone", value=death["zone"], inline=True)
        embed.add_field(name="Weapon", value=death["weapon"], inline=True)
        embed.add_field(name="Damage", value=death["damage_type"], inline=True)
        embed.add_field(name="Mode", value=death["mode"], inline=True)
        embed.add_field(name="Ship", value=death["killers_ship"], inline=True)

        # optional Org
        org = death.get("organization", {})
        org_name = org.get("name") or "Unknown"
        if org.get("url"):
            embed.add_field(
                name="Victim Organization",
                value=f"[{org_name}]({org['url']})",
                inline=False,
            )
        else:
            embed.add_field(name="Victim Organization", value=org_name, inline=False)

        await channel.send(embed=embed)
        last_death_id = death["time"]


bot.run(TOKEN)
