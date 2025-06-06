import os
import datetime as dt
import logging
import asyncio
from discord.ext import tasks
import httpx
import discord
from discord import app_commands, Interaction, Embed, Color
from discord.ext import commands
from dotenv import load_dotenv
from discord import ui, ButtonStyle, Embed
from discord.ui import View
import traceback
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo
from aiohttp import web
import os
import logging
import threading
from discord.app_commands import Choice


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

# ─── Timezone setup ────────────────────────────────────────────────────────────────────
EST = ZoneInfo("America/New_York")

# ─── Guild ID setup ────────────────────────────────────────────────────────────────────
GUILD_ID = int(os.getenv("GUILD_ID"))

# ─── ignore these NPCs ────────────────────────────────────────────────────────────
IGNORED_VICTIM_PREFIX = ("vlk_juvenile_sentry_", "Quasigrazer")

# ─── weapon name translations ─────────────────────────────────────────────────────
WEAPON_NAME_MAP: dict[str, str] = {
    ##FPS WEAPONS
    "behr_rifle_ballistic_01": "P4-AR Rifle",
    "behr_rifle_ballistic_02": "P8-AR Rifle",
    "klwe_rifle_energy_01": "Gallant Rifle",
    "behr_sniper_ballistic_01": "P6-LR Sniper Rifle",
    "gmni_lmg_ballistic_01": "F55 LMG",
    "gmni_rifle_ballistic_01": "S71 Rifle",
    "behr_lmg_ballistic_01": "FS-9 LMG",
    "behr_smg_ballistic_01": "P8-SC SMG",
    "none_shotgun_ballistic_01": "DEADRIG Shotgun",
    "utfl_melee_01_red01_gungame": "FSK-8 BLOODLINE(GR FIRE KNIFE) Knife",
    "klwe_lmg_energy_01": "Demeco LMG",
    "ksar_rifle_energy_01": "Karna Rifle",
    "gmni_smg_ballistic_01": "C54 SMG",
    "ksar_shotgun_energy_01": "Devastator Shotgun",
    "ksar_sniper_ballistic_01": "Scalpel Sniper Rifle",
    "ksar_shotgun_ballistic_01": "Ravager-212 Shotgun",
    "gmni_shotgun_ballistic_01": "R97 Shotgun",
    "ksar_pistol_ballistic_01": "Coda Pistol",
    "klwe_smg_energy_01": "Lumin V SMG",
    "ksar_smg_energy_01": "Custodian SMG",
    "gmni_pistol_ballistic_01": "LH86 Pistol",
    "apar_special_ballistic_01": "Railgun",
    "gmni_sniper_ballistic_01": "A03 Sniper Rifle",
    "behr_shotgun_ballistic_01": "BR-2 Shotgun",
    "behr_pistol_ballistic_01": "S-38 Pistol",
    "lbco_pistol_energy_01": "Yubarev Pistol",
    ##SHIPS
    "MISC_Reliant_": "Reliant",
    "AEGS_Gladius_": "Gladius",
    "CNOU_Mustang_Alpha": "Mustang Alpha",
    "MISC_Razor_EX": "Razor EX",
    "ANVL_Hornet_F7A_Mk2_Exec": "F7A MK2 EXEC",
    "ANVL_Hornet_F7A_Mk2": "F7A MK2",
    "RSI_Aurora_MR": "Aurora MR",
    "ANVL_C8R_Pisces": "C8R Pisces",
    "MRCK_S03_AEGS_Sabre_Firebird": "Sabre Firebird",
    "ANVL_Arrow": "Arrow",
    "AMRS_LaserCannon_S4": "Scorpius",
    "AEGS_Sabre_Comet": "Sabre Comet",
    "CNOU_Nomad": "Nomad",
    "ANVL_Hornet_F7CM": "F7C-M Super Hornet",
    "CRUS_Starfighter_Inferno": "Ares Star Fighter Inferno",
    "CRUS_Starlifter_C2": "C2 Hercules Starlifter",
    "DRAK_Corsair": "Corsair",
    "DRAK_Corsair_Exec": "Corsair EXEC",
    ##SHIP WEAPONS
    "KLWE_LaserRepeater_S3": "CF-337 Panther Repeater",
    "MXOX_NeutronRepeater_S3": "NDB-30 Repeater",
    "AMRS_LaserCannon_S4": "Omnisky XII Cannon",
    "KLWE_LaserRepeater_S4": "CF-447 Rhino Repeater",
    "POWR_AEGS_S01_Regulus_SCitem_": "Thunderbolt III Missile",
    ##LOCATIONS
    "util_a_orbital_001_occu": "LAMINA OLP",
}


def format_weapon(raw: str) -> str:
    """
    Turn a kill/death weapon code like
     'behr_rifle_ballistic_01_spc_01_2681914…'
    into 'P4-AR' (or fall back to the raw code).
    """
    for key, pretty in WEAPON_NAME_MAP.items():
        if raw.startswith(key):
            return pretty
    return raw


# ─── Defines Mode Descriptions ────────────────────────────────────────────────────────────────────
def format_mode(raw: str) -> str:
    if raw.startswith("SC_"):
        return "Persistent Universe"
    if raw.startswith("EA_"):
        return raw[3:]
    return raw


last_kill_id = 0
last_death_id = 0  # track the highest death.id seen

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


## Compute “since_time” for each period
def _period_start_iso(period: str) -> str:
    now = datetime.now(EST)

    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # 24 h rolling window (9 PM–9 PM)
    elif period == "daily":
        end = now.replace(hour=21, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=1)

    # last 7 days
    elif period in ("week", "weekly"):
        start = now - timedelta(days=7)

    # last calendar month
    elif period in ("month", "monthly"):
        last_month = now.month - 1 or 12
        year = now.year - (1 if now.month == 1 else 0)
        start = datetime(year, last_month, 1, tzinfo=EST)

    # last calendar quarter
    elif period in ("quarter", "quarterly"):
        # same as before but accept "quarter":
        q = ((now.month - 1) // 3) or 4
        year = now.year - (1 if q == 4 else 0)
        start = datetime(year, (q - 1) * 3 + 1, 1, tzinfo=EST)

    # last calendar year
    elif period == "yearly":
        start = datetime(now.year - 1, 1, 1, tzinfo=EST)

    # all time (no slice)
    elif period in ("all", "all time"):
        # pick a date far in the past so the slice includes everything
        start = datetime(1970, 1, 1, tzinfo=EST)

    else:
        # fallback to a week
        start = now - timedelta(days=7)

    return start.astimezone(timezone.utc).isoformat()


# ─── TEST COMMANDS ─────────────────────────────────────────────────────────────


@bot.tree.command(
    name="testdaily",
    description="Manually send the last 24 h (9 PM → 9 PM EST) summary",
    guild=discord.Object(id=GUILD_ID),
)
async def testdaily(interaction: discord.Interaction):
    embed = await _build_summary_embed("daily", "📅")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="testtoday",
    description="Show today's EST‐calendar summary (midnight → midnight)",
    guild=discord.Object(id=GUILD_ID),
)
async def testtoday(interaction: discord.Interaction):
    embed = await _build_summary_embed("today", "📅")
    await interaction.response.send_message(embed=embed)


# ─── Scheduled Cards (Leaderboards) ──────────────────────────────────────────────
STAR_CITIZEN_FEED_ID = int(os.getenv("STAR_CITIZEN_FEED"))


async def _fetch_events_for_period(period: str):
    iso_start = _period_start_iso(period)
    headers = {"Authorization": f"Bearer {API_KEY}"}
    async with httpx.AsyncClient() as client:
        r_k = await client.get(
            f"{API_BASE}/kills",
            params={"since_time": iso_start},
            headers=headers,
            timeout=10.0,
        )
        r_d = await client.get(
            f"{API_BASE}/deaths",
            params={"since_time": iso_start},
            headers=headers,
            timeout=10.0,
        )
        r_k.raise_for_status()
        r_d.raise_for_status()
        return r_k.json(), r_d.json()


def _in_period(ts: str, period: str) -> bool:
    # parse UTC timestamp, convert to local NY time
    dt_utc = datetime.fromisoformat(ts.rstrip("Z")).replace(tzinfo=timezone.utc)
    dt_local = dt_utc.astimezone(EST)
    now_local = datetime.now(EST)

    if period == "today":
        # calendar‐day midnight→midnight
        return dt_local.date() == now_local.date()

    if period == "daily":
        # 24 h slice: yesterday 9 PM → today 9 PM
        end = now_local.replace(hour=21, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=1)
        return start <= dt_local < end

    if period == "weekly":
        return (now_local - dt_local) < timedelta(days=7)

    if period == "monthly":
        # roll back into last calendar‐month
        last_month = now_local.month - 1
        year = now_local.year
        if last_month == 0:
            last_month = 12
            year -= 1
        return dt_local.year == year and dt_local.month == last_month

    if period == "quarterly":
        # figure out last quarter (1–4), rolling back into prior year if needed
        current_q = (now_local.month - 1) // 3 + 1
        last_q = current_q - 1
        year = now_local.year
        if last_q == 0:
            last_q = 4
            year -= 1
        # start of last quarter
        start_month = (last_q - 1) * 3 + 1
        start = datetime(year, start_month, 1, tzinfo=EST)
        # end = start of the next quarter
        next_q = last_q + 1 if last_q < 4 else 1
        end_year = year if next_q != 1 else year + 1
        end_month = (next_q - 1) * 3 + 1
        end = datetime(end_year, end_month, 1, tzinfo=EST)
        return start <= dt_local < end

    if period == "yearly":
        # last calendar year
        return dt_local.year == (now_local.year - 1)

    return False


def _top_list(counts: dict, top_n: int = 5) -> list[tuple]:
    return sorted(counts.items(), key=lambda x: x[1], reverse=True)[:top_n]


async def _build_summary_embed(period: str, emoji: str) -> discord.Embed:
    # 1) only fetch events since period start
    kills, deaths = await _fetch_events_for_period(period)
    # 2) existing logic for filtering, counting, embedding…
    kills_p = [k for k in kills if _in_period(k["time"], period)]
    deaths_p = [
        d
        for d in deaths
        if _in_period(d["time"], period) and d.get("damage_type") != "Suicide"
    ]

    # 2) Totals
    total_kills = len(kills_p)
    total_deaths = len(deaths_p)
    kd_ratio = total_kills / total_deaths if total_deaths else None
    kd_text = f"{kd_ratio:.2f}" if kd_ratio is not None else "N/A"

    # 3) Header embed
    embed = discord.Embed(
        title=f"{emoji} {period.capitalize()} Summary",
        description=(
            f"Kills: {total_kills}\n" f"Deaths: {total_deaths}\n" f"K/D: {kd_text}"
        ),
        color=discord.Color.blue(),
    )

    # 4) Top Players by Kills
    kc: dict[str, int] = {}
    for k in kills_p:
        kc[k["player"]] = kc.get(k["player"], 0) + 1
    lines = (
        "\n".join(
            f"{i}. {p} — {c} Kills" for i, (p, c) in enumerate(_top_list(kc), start=1)
        )
        or "None"
    )
    embed.add_field(name="🏆 Top Players (Kills)", value=lines, inline=False)

    # 5) Top Players by Deaths
    dc: dict[str, int] = {}
    for d in deaths_p:
        dc[d["victim"]] = dc.get(d["victim"], 0) + 1
    lines = (
        "\n".join(
            f"{i}. {p} — {c} Deaths" for i, (p, c) in enumerate(_top_list(dc), start=1)
        )
        or "None"
    )
    embed.add_field(name="💀 Top Players (Deaths)", value=lines, inline=False)

    # 6) Top Players by K/D
    stats: dict[str, dict[str, int]] = {}
    for k in kills_p:
        stats.setdefault(k["player"], {"kills": 0, "deaths": 0})["kills"] += 1
    for d in deaths_p:
        stats.setdefault(d["victim"], {"kills": 0, "deaths": 0})["deaths"] += 1
    ratios = {p: v["kills"] / max(1, v["deaths"]) for p, v in stats.items()}
    lines = (
        "\n".join(
            f"{i}. {p} — {r:.2f}" for i, (p, r) in enumerate(_top_list(ratios), start=1)
        )
        or "None"
    )
    embed.add_field(name="⚖️ Top Players (K/D)", value=lines, inline=False)

    # 7) Top Organizations by Kills
    oc: dict[str, int] = {}
    for k in kills_p:
        org = k.get("organization_name") or "Unknown"
        oc[org] = oc.get(org, 0) + 1
    # filter out Unknown, THREER, TRIPLER for leaderboard display
    filtered = {
        org: cnt
        for org, cnt in oc.items()
        if org not in ("Unknown", "THREER", "TRIPLER")
    }
    lines = (
        "\n".join(
            f"{i}. {o} — {c} kills"
            for i, (o, c) in enumerate(_top_list(filtered), start=1)
        )
        or "None"
    )
    embed.add_field(name="🏢 Top Organization (Kills)", value=lines, inline=False)

    # 8) Top Weapon
    wc: dict[str, int] = {}
    for k in kills_p:
        name = format_weapon(k["weapon"])  # ← map raw ID → friendly
        wc[name] = wc.get(name, 0) + 1

    if wc:
        weapon, cnt = _top_list(wc, 1)[0]
        embed.add_field(
            name="🔫 Top Weapon", value=f"{weapon} ({cnt} uses)", inline=True
        )
    else:
        embed.add_field(name="🔫 Top Weapon", value="None", inline=True)

    # 9) Hot Zone (skip "Unknown")
    zc: dict[str, int] = {}
    for k in kills_p:
        zone_name = k["zone"]
        if zone_name in ("Unknown", "N/A"):
            continue
        zc[zone_name] = zc.get(zone_name, 0) + 1

    if zc:
        zone, cnt = _top_list(zc, 1)[0]
        embed.add_field(name="📍 Hot Zone", value=f"{zone} ({cnt} kills)", inline=True)
    else:
        embed.add_field(name="📍 Hot Zone", value="None", inline=True)

    # 10) Active Players
    active = len({k["player"] for k in kills_p} | {d["victim"] for d in deaths_p})
    embed.add_field(name="👥 Active Players", value=str(active), inline=False)

    return embed


# ─── Helpers for Top‑Kills cards ──────────────────────────────────────────────

_PERIOD_DESC = {
    "daily": "within the last 24 hours.",
    "weekly": "within the last 7 days.",
    "monthly": "within the last calendar month.",
    "quarterly": "within the last quarter.",
    "yearly": "within the last calendar year.",
}


async def _build_top_pu_embed(period: str) -> discord.Embed:
    """Top 10 kills in Persistent Universe."""
    kills, _ = await _fetch_events_for_period(period)
    # filter by period  PU game_mode
    filtered = [
        k
        for k in kills
        if _in_period(k["time"], period) and k["game_mode"].startswith("SC_")
    ]
    counts = {}
    for k in filtered:
        counts[k["player"]] = counts.get(k["player"], 0) + 1
    top10 = _top_list(counts, 10)

    embed = discord.Embed(
        title=f"🏆 Top Kills in PU ({period.capitalize()})",
        description=f"These members have the most kills in the Persistent Universe {_PERIOD_DESC[period]}",
        color=discord.Color.blue(),
    )
    for i, (player, cnt) in enumerate(top10, start=1):
        embed.add_field(name=f"{i}. {player}", value=f"{cnt} kills", inline=False)
    return embed


async def _build_top_ac_flight_embed(period: str) -> discord.Embed:
    """Top 10 kills in AC Flight modes (Squadron Battle & Free Flight)."""
    kills, _ = await _fetch_events_for_period(period)
    modes = {"SquadronBattle", "FreeFlight"}
    filtered = [
        k
        for k in kills
        if _in_period(k["time"], period)
        and k["game_mode"].startswith("EA_")
        and k["game_mode"][3:] in modes
    ]
    counts = {}
    for k in filtered:
        counts[k["player"]] = counts.get(k["player"], 0) + 1
    top10 = _top_list(counts, 10)

    embed = discord.Embed(
        title=f"✈️ Top Kills in AC (Flight Modes) ({period.capitalize()})",
        description=f"These members have the most kills in Squadron Battle and Free Flight {_PERIOD_DESC[period]}",
        color=discord.Color.gold(),
    )
    for i, (player, cnt) in enumerate(top10, start=1):
        embed.add_field(name=f"{i}. {player}", value=f"{cnt} kills", inline=False)
    return embed


async def _build_top_ac_fps_embed(period: str) -> discord.Embed:
    """Top 10 kills in AC FPS modes (Elimination, Kill Confirmed, Gun Game)."""
    kills, _ = await _fetch_events_for_period(period)

    # the “pure” FPS mode names we care about
    modes = {"TeamElimination", "KillConfirmed", "GunGame"}

    # filter by period  EA_ prefix  FPS suffix stripped
    filtered = []
    for k in kills:
        if not _in_period(k["time"], period):
            continue
        gm = k["game_mode"]
        if not gm.startswith("EA_"):
            continue

        sub = gm[3:]  # e.g. "FPSGunGame"
        if sub.startswith("FPS"):
            sub = sub[3:]  # strip off "FPS" → "GunGame"

        if sub in modes:
            filtered.append(k)

    # tally per player
    counts: dict[str, int] = {}
    for k in filtered:
        counts[k["player"]] = counts.get(k["player"], 0) + 1
    top10 = _top_list(counts, 10)

    # build the embed
    embed = discord.Embed(
        title=f"🔫 Top Kills in AC (FPS Modes) ({period.capitalize()})",
        description=(
            f"These members have the most kills in Elimination, Kill Confirmed, "
            f"and Gun Game {_PERIOD_DESC[period]}"
        ),
        color=discord.Color.dark_theme(),
    )
    if top10:
        for i, (player, cnt) in enumerate(top10, start=1):
            embed.add_field(name=f"{i}. {player}", value=f"{cnt} kills", inline=False)
    else:
        embed.description = "\n\n_No kills recorded for these modes in this period._"

    return embed


# ─── Daily @ 9 PM America/New_York ────────────────────────────────────────────
@tasks.loop(time=time(hour=21, minute=0, tzinfo=EST))
async def daily_summary():
    embed = await _build_summary_embed("daily", "📅")
    chan = bot.get_channel(STAR_CITIZEN_FEED_ID)
    if chan:
        # 1) your existing summary
        await chan.send(embed=embed)
        # 2) the three new leaderboard cards
        await chan.send(embed=await _build_top_pu_embed("daily"))
        await chan.send(embed=await _build_top_ac_flight_embed("daily"))
        await chan.send(embed=await _build_top_ac_fps_embed("daily"))


# ─── Weekly (Mon) @ 9 PM America/New_York ──────────────────────────────────────
@tasks.loop(time=time(hour=21, minute=0, tzinfo=EST))
async def weekly_summary():
    if datetime.now(EST).weekday() != 0:
        return
    embed = await _build_summary_embed("weekly", "🗓️")
    chan = bot.get_channel(STAR_CITIZEN_FEED_ID)
    if chan:
        # 1) your existing summary
        await chan.send(embed=embed)
        # 2) the three new leaderboard cards
        await chan.send(embed=await _build_top_pu_embed("weekly"))
        await chan.send(embed=await _build_top_ac_flight_embed("weekly"))
        await chan.send(embed=await _build_top_ac_fps_embed("weekly"))


# ─── Monthly (1st) @ 9 PM America/New_York ─────────────────────────────────────
@tasks.loop(time=time(hour=21, minute=0, tzinfo=EST))
async def monthly_summary():
    if datetime.now(EST).day != 1:
        return
    embed = await _build_summary_embed("monthly", "📆")
    chan = bot.get_channel(STAR_CITIZEN_FEED_ID)
    if chan:
        # 1) your existing summary
        await chan.send(embed=embed)
        # 2) the three new leaderboard cards
        await chan.send(embed=await _build_top_pu_embed("monthly"))
        await chan.send(embed=await _build_top_ac_flight_embed("monthly"))
        await chan.send(embed=await _build_top_ac_fps_embed("monthly"))


# ─── Quarterly (Q-start) @ 9 PM America/New_York ───────────────────────────────
@tasks.loop(time=time(hour=21, minute=0, tzinfo=EST))
async def quarterly_summary():
    now = datetime.now(EST)
    if now.month not in (1, 4, 7, 10) or now.day != 1:
        return
    embed = await _build_summary_embed("quarterly", "📊")
    chan = bot.get_channel(STAR_CITIZEN_FEED_ID)
    if chan:
        # 1) your existing summary
        await chan.send(embed=embed)
        # 2) the three new leaderboard cards
        await chan.send(embed=await _build_top_pu_embed("quarterly"))
        await chan.send(embed=await _build_top_ac_flight_embed("quarterly"))
        await chan.send(embed=await _build_top_ac_fps_embed("quarterly"))


# ─── Yearly (Jan 1) @ 9 PM America/New_York ────────────────────────────────────
@tasks.loop(time=time(hour=21, minute=0, tzinfo=EST))
async def yearly_summary():
    now = datetime.now(EST)
    if not (now.month == 1 and now.day == 1):
        return
    embed = await _build_summary_embed("yearly", "🎉")
    chan = bot.get_channel(STAR_CITIZEN_FEED_ID)
    if chan:
        # 1) your existing summary
        await chan.send(embed=embed)
        # 2) the three new leaderboard cards
        await chan.send(embed=await _build_top_pu_embed("yearly"))
        await chan.send(embed=await _build_top_ac_flight_embed("yearly"))
        await chan.send(embed=await _build_top_ac_fps_embed("yearly"))


# ─── api key generator ──────────────────────────────────────────────────


@bot.event
async def on_ready():
    bot.add_view(GenerateKeyView())

    # Sync only to your guild for instant updates
    guild = discord.Object(id=GUILD_ID)
    await bot.tree.sync(guild=guild)
    print("🔁 Slash commands synced to guild")

    # post the “Generate Key” card if it’s not already there...
    channel = bot.get_channel(KEY_CHANNEL_ID)
    if channel:
        async for msg in channel.history(limit=50):
            if msg.author.id == bot.user.id and msg.embeds:
                break
        else:
            embed = discord.Embed(
                title="Generate RRRthurTracker Key",
                description=(
                    "Click the button below to generate a unique key for the "
                    "RRRthur Pirate Kill Tracker. Use this key in your kill tracker "
                    "client to post your kills in the #💀pu-kill-feed and/or "
                    "#💀ac-kill-feed.\n\n"
                    "Each key is valid for 72 hours. You may generate a new key at any time.\n\n"
                ),
                color=discord.Color.dark_gray(),
            )
            await channel.send(embed=embed, view=GenerateKeyView())

    # prime last_kill_id
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/kills", headers={"Authorization": f"Bearer {API_KEY}"}
        )
        resp.raise_for_status()
        all_k = resp.json()
    if all_k:
        global last_kill_id
        last_kill_id = max(k["id"] for k in all_k)

    # prime last_death_id
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/deaths", headers={"Authorization": f"Bearer {API_KEY}"}
        )
        resp.raise_for_status()
        all_d = resp.json()
    if all_d:
        global last_death_id
        last_death_id = max(d["id"] for d in all_d)

    # start your kill loop
    if not fetch_and_post_kills.is_running():
        fetch_and_post_kills.start()

    # **start your death loop** right here
    if not fetch_and_post_deaths.is_running():
        fetch_and_post_deaths.start()

    # ─── Start summary-card loops ───────────────────────────────────────────────
    if not daily_summary.is_running():
        daily_summary.start()
    if not weekly_summary.is_running():
        weekly_summary.start()
    if not monthly_summary.is_running():
        monthly_summary.start()
    if not quarterly_summary.is_running():
        quarterly_summary.start()
    if not yearly_summary.is_running():
        yearly_summary.start()


# ─── /reportkill ─────────────────────────────────────────────────────────────────
@bot.tree.command(
    name="reportkill",
    description="Log a kill (timestamp is set automatically)",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(
    player="Name of the killer",
    victim="Name of the victim",
    zone="Where it happened",
    weapon="Weapon used",
    damage_type="Type of damage",
    mode="Which mode: PU or AC",
    submode="If AC, choose the sub‑mode (flight or FPS)",
)
@app_commands.choices(
    mode=[
        app_commands.Choice(name="Persistent Universe", value="pu-kill"),
        app_commands.Choice(name="Arena Commander", value="ac-kill"),
    ],
    submode=[
        Choice(name="Squadron Battle", value="SquadronBattle"),
        Choice(name="Free Flight", value="FreeFlight"),
        Choice(name="Elimination", value="TeamElimination"),
        Choice(name="Kill Confirmed", value="KillConfirmed"),
        Choice(name="Gun Game", value="GunGame"),
    ],
)
async def reportkill(
    interaction: discord.Interaction,
    player: str,
    victim: str,
    zone: str,
    weapon: str,
    damage_type: str,
    mode: str = "pu-kill",
    submode: str | None = None,
):
    await interaction.response.defer(ephemeral=True)
    now_iso = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()

    # determine game_mode for the payload
    if mode == "ac-kill":
        if not submode:
            return await interaction.followup.send(
                "❌ You must choose an AC submode for Arena Commander kills.",
                ephemeral=True,
            )
        game_mode = f"EA_{submode}"
    else:
        game_mode = "SC_Default"

    # 2) full payload matching your backend’s KillEvent schema
    profile_url = f"https://robertsspaceindustries.com/citizens/{player}"
    payload = {
        "player": player,
        "victim": victim,
        "zone": zone,
        "weapon": weapon,
        "damage_type": damage_type,
        "time": now_iso,
        "mode": mode,
        "rsi_profile": profile_url,
        "game_mode": game_mode,
        "client_ver": "manual",
        "killers_ship": "N/A",
        "avatar_url": None,
        "organization_name": None,
        "organization_url": None,
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

    except httpx.HTTPStatusError as e:
        # catch 4xx/5xx from the API and show the body
        return await interaction.followup.send(
            f"❌ Could not record kill [{e.response.status_code}]:\n```{e.response.text}```",
            ephemeral=True,
        )

    except Exception as e:
        return await interaction.followup.send(
            f"❌ Could not record kill:\n```{e}```", ephemeral=True
        )

    # 3) confirm back to the user
    await interaction.followup.send(
        f"✅ Kill recorded for **{player}** vs **{victim}** at `{now_iso}`.",
        ephemeral=True,
    )

    # 4) mirror to the feed channel
    feed_id = PU_KILL_FEED_ID if mode == "pu-kill" else AC_KILL_FEED_ID
    channel = bot.get_channel(feed_id)
    if channel:
        embed = discord.Embed(
            title="RRR Kill",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name=player, url=profile_url)

        victim_url = f"https://robertsspaceindustries.com/citizens/{victim}"
        embed.add_field(name="Victim", value=f"[{victim}]({victim_url})", inline=True)
        embed.add_field(name="Zone", value=zone, inline=True)
        embed.add_field(name="Weapon", value=weapon, inline=True)
        embed.add_field(name="Damage", value=damage_type, inline=True)
        embed.add_field(name="Mode", value=mode, inline=True)
        embed.add_field(name="Ship", value="N/A", inline=True)

        await channel.send(embed=embed)


# ─── /leaderboard ────────────────────────────────────────────────────────────────
@bot.tree.command(
    name="leaderboard",
    description="Combined leaderboards (top kills, deaths, K/D) for a period",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(
    period="today, week, month, or all time",
)
@app_commands.choices(
    period=[
        app_commands.Choice(name="Today", value="today"),
        app_commands.Choice(name="This Week", value="week"),
        app_commands.Choice(name="This Month", value="month"),
        app_commands.Choice(name="All Time", value="all"),
    ],
)
async def leaderboard(
    interaction: discord.Interaction,
    period: str,
):
    await interaction.response.defer()
    # only fetch events since the start of this period
    iso_start = _period_start_iso(period)
    headers = {"Authorization": f"Bearer {API_KEY}"}

    # fetch only this period’s kills & deaths
    async with httpx.AsyncClient() as client:
        r_k = await client.get(
            f"{API_BASE}/kills",
            params={"since_time": iso_start},
            headers=headers,
            timeout=10.0,
        )
        r_d = await client.get(
            f"{API_BASE}/deaths",
            params={"since_time": iso_start},
            headers=headers,
            timeout=10.0,
        )
        r_k.raise_for_status()
        r_d.raise_for_status()
        kills = r_k.json()
        deaths = r_d.json()

    def in_period(ts: str) -> bool:
        dt_obj = datetime.fromisoformat(ts.rstrip("Z"))
        now = datetime.utcnow()
        if period == "today":
            return dt_obj.date() == now.date()
        if period == "week":
            return (now - dt_obj).days < 7
        if period == "month":
            return now.year == dt_obj.year and dt_obj.month == now.month
        return True

    # Top 5 kills
    kill_counts: dict[str, int] = {}
    for e in kills:
        if in_period(e["time"]):
            kill_counts[e["player"]] = kill_counts.get(e["player"], 0) + 1
    top_k = sorted(kill_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    kill_lines = "\n".join(f"{i}. {p} — {c} Kills" for i, (p, c) in enumerate(top_k))

    # Top 5 deaths
    death_counts: dict[str, int] = {}
    for e in deaths:
        if in_period(e["time"]) and e.get("damage_type") != "Suicide":
            death_counts[e["victim"]] = death_counts.get(e["victim"], 0) + 1
    top_d = sorted(death_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    death_lines = "\n".join(f"{i}. {p} — {c} Deaths" for i, (p, c) in enumerate(top_d))

    # Top 5 K/D
    stats: dict[str, dict[str, int]] = {}
    for e in kills:
        if in_period(e["time"]):
            stats.setdefault(e["player"], {"kills": 0, "deaths": 0})["kills"] += 1
    for e in deaths:
        if in_period(e["time"]) and e.get("damage_type") != "Suicide":
            stats.setdefault(e["victim"], {"kills": 0, "deaths": 0})["deaths"] += 1
    ratios = [
        (p, v["kills"], v["deaths"], v["kills"] / max(1, v["deaths"]))
        for p, v in stats.items()
    ]
    top_ratio = sorted(ratios, key=lambda x: x[3], reverse=True)[:5]
    kd_lines = "\n".join(
        f"{i}. {p} — {ratio:.2f}" for i, (p, _, _, ratio) in enumerate(top_ratio)
    )

    embed = discord.Embed(
        title=f"📊 Leaderboard ({period.capitalize()})",
        color=discord.Color.purple(),
    )
    embed.add_field(name="🏆 Top Kills", value=kill_lines or "None", inline=False)
    embed.add_field(name="💀 Top Deaths", value=death_lines or "None", inline=False)
    embed.add_field(name="⚖️ Top K/D", value=kd_lines or "None", inline=False)

    await interaction.followup.send(embed=embed)


# ─── /stats ───────────────────────────────────────────────────────────────────────
@bot.tree.command(
    name="stats",
    description="Show detailed stats for yourself or someone else",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(
    user="RSI handle (defaults to you)",
)
async def stats(
    interaction: discord.Interaction,
    user: str | None = None,
):
    await interaction.response.defer()
    target = user or interaction.user.name
    headers = {"Authorization": f"Bearer {API_KEY}"}

    # fetch
    async with httpx.AsyncClient() as client:
        r_k = await client.get(f"{API_BASE}/kills", headers=headers, timeout=10.0)
        r_d = await client.get(f"{API_BASE}/deaths", headers=headers, timeout=10.0)
        r_k.raise_for_status()
        r_d.raise_for_status()
        kills = r_k.json()
        deaths = r_d.json()

    total_k = sum(1 for e in kills if e["player"] == target)
    total_d = sum(
        1 for e in deaths if e["victim"] == target and e.get("damage_type") != "Suicide"
    )
    ratio = total_k / max(1, total_d)

    # top 5 orgs they've killed
    org_counts: dict[str, int] = {}
    for e in kills:
        if e["player"] == target:
            org = e.get("organization_name") or "Unknown"
            org_counts[org] = org_counts.get(org, 0) + 1
    # toss out any “Unknown” buckets
    filtered = {o: c for o, c in org_counts.items() if o != "Unknown"}
    top_orgs = sorted(filtered.items(), key=lambda x: x[1], reverse=True)[:5]
    org_lines = "\n".join(f"{o}: {c}" for o, c in top_orgs) or "None"

    embed = discord.Embed(
        title=f"📈 Stats for {target}",
        color=discord.Color.green(),
    )
    embed.add_field(name="Kills", value=str(total_k), inline=True)
    embed.add_field(name="Deaths", value=str(total_d), inline=True)
    embed.add_field(name="K/D", value=f"{ratio:.2f}", inline=True)
    embed.add_field(name="Top Killed Orgs", value=org_lines, inline=False)

    await interaction.followup.send(embed=embed)


# ─── /compare ─────────────────────────────────────────────────────────────────────
@bot.tree.command(
    name="compare",
    description="Compare stats for two RSI handles",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(
    period="today, week, month, or all time",
    user1="First RSI handle",
    user2="Second RSI handle",
    mode="Which game‐mode slice to compare",
)
@app_commands.choices(
    period=[
        Choice(name="Today", value="today"),
        Choice(name="This Week", value="week"),
        Choice(name="This Month", value="month"),
        Choice(name="All Time", value="all"),
    ],
    mode=[
        Choice(name="All", value="all"),
        Choice(name="PU Only", value="pu"),
        Choice(name="AC Flight Only", value="ac-flight"),
        Choice(name="AC FPS Only", value="ac-fps"),
    ],
)
async def compare(
    interaction: Interaction,
    period: str,
    user1: str,
    user2: str,
    mode: str = "all",
):
    await interaction.response.defer()

    # Fetch once
    headers = {"Authorization": f"Bearer {API_KEY}"}
    async with httpx.AsyncClient() as client:
        kills = (
            await client.get(f"{API_BASE}/kills", headers=headers, timeout=10.0)
        ).json()
        deaths = (
            await client.get(f"{API_BASE}/deaths", headers=headers, timeout=10.0)
        ).json()

    # Helpers
    def in_period(ts: str) -> bool:
        dt = datetime.fromisoformat(ts.rstrip("Z"))
        now = datetime.utcnow()
        if period == "today":
            return dt.date() == now.date()
        if period == "week":
            return (now - dt).days < 7
        if period == "month":
            return (dt.year, dt.month) == (now.year, now.month)
        return True

    def in_mode(ev):
        gm = ev["game_mode"]
        if mode == "pu":
            return gm.startswith("SC_")
        if mode == "ac-flight":
            return gm.startswith("EA_") and gm[3:] in {"SquadronBattle", "FreeFlight"}
        if mode == "ac-fps":
            # strip EA_ prefix and any leading "FPS"
            if not gm.startswith("EA_"):
                return False
            sub = gm[3:]  # e.g. "FPSGunGame" or "Elimination"
            if sub.startswith("FPS"):
                sub = sub[3:]  # -> "GunGame"
            return sub in {"TeamElimination", "KillConfirmed", "GunGame"}
        return True

    # Single stats_for, incorporating both filters
    def stats_for(handle: str):
        k = sum(
            1
            for e in kills
            if e["player"] == handle and in_period(e["time"]) and in_mode(e)
        )
        d = sum(
            1
            for e in deaths
            if e["victim"] == handle
            and in_period(e["time"])
            and in_mode(e)
            and e.get("damage_type") != "Suicide"
        )
        return k, d, k / max(1, d)

    # Compute
    k1, d1, r1 = stats_for(user1)
    k2, d2, r2 = stats_for(user2)

    # Build & send embed
    embed = Embed(
        title=f"🔍 Compare ({period.capitalize()} | {mode})\n{user1} vs {user2}",
        color=Color.purple(),
    )
    embed.add_field(
        name=user1, value=f"Kills: {k1}\nDeaths: {d1}\nK/D: {r1:.2f}", inline=True
    )
    embed.add_field(
        name=user2, value=f"Kills: {k2}\nDeaths: {d2}\nK/D: {r2:.2f}", inline=True
    )

    await interaction.followup.send(embed=embed)


# ─── /kills ──────────────────────────────────────────────────────────────────────
@bot.tree.command(
    name="kills",
    description="Show kills for a given period",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(period="Which time window to show kills for")
@app_commands.choices(
    period=[
        Choice(name="Today", value="today"),
        Choice(name="Daily", value="daily"),
        Choice(name="Weekly", value="weekly"),
        Choice(name="Monthly", value="monthly"),
    ]
)
async def kills(interaction: discord.Interaction, period: str):
    iso_start = _period_start_iso(period)  # now `period` is defined
    await interaction.response.defer()
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{API_BASE}/kills",
                params={"since_time": iso_start},
                headers={"Authorization": f"Bearer {API_KEY}"},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError:
        return await interaction.followup.send(
            f"❌ ListKills failed [{resp.status_code}]:\n```{resp.text}```"
        )
    except Exception as e:
        return await interaction.followup.send(f"❌ Error: `{e}`")

    if not data:
        return await interaction.followup.send("📭 No kills recorded yet.")

    # Build an embed “card”
    embed = discord.Embed(title="🗡️ Last 20 Kills", color=discord.Color.red())
    for e in data[-20:]:
        embed.add_field(
            name=f"{e['player']} ➔ {e['victim']}",
            value=f"{e['time']} • {e['zone']} • {e['weapon']}",
            inline=False,
        )
    await interaction.followup.send(embed=embed)


# ─── /topkd ──────────────────────────────────────────────────────────────────────
@bot.tree.command(
    name="topkd",
    description="Show the top 10 players by K/D ratio over a given period",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(
    period="today, week, month, or all time",
)
@app_commands.choices(
    period=[
        app_commands.Choice(name="Today", value="today"),
        app_commands.Choice(name="This Week", value="week"),
        app_commands.Choice(name="This Month", value="month"),
        app_commands.Choice(name="All Time", value="all"),
    ],
)
async def topkd(
    interaction: discord.Interaction,
    period: str,
):
    await interaction.response.defer()
    headers = {"Authorization": f"Bearer {API_KEY}"}

    # fetch both endpoints
    async with httpx.AsyncClient() as client:
        r_k = await client.get(f"{API_BASE}/kills", headers=headers, timeout=10.0)
        r_d = await client.get(f"{API_BASE}/deaths", headers=headers, timeout=10.0)
        r_k.raise_for_status()
        r_d.raise_for_status()
        kills = r_k.json()
        deaths = r_d.json()

    def in_period(ts: str) -> bool:
        dt_obj = datetime.fromisoformat(ts.rstrip("Z"))
        now = datetime.utcnow()
        if period == "today":
            return dt_obj.date() == now.date()
        if period == "week":
            return (now - dt_obj).days < 7
        if period == "month":
            return now.year == dt_obj.year and dt_obj.month == now.month
        return True

    # tally per player
    stats: dict[str, dict[str, int]] = {}
    for k in kills:
        if in_period(k["time"]):
            stats.setdefault(k["player"], {"kills": 0, "deaths": 0})["kills"] += 1
    for d in deaths:
        if in_period(d["time"]):
            stats.setdefault(d["victim"], {"kills": 0, "deaths": 0})["deaths"] += 1

    ratios = [
        (p, v["kills"], v["deaths"], v["kills"] / max(1, v["deaths"]))
        for p, v in stats.items()
    ]
    top_list = sorted(ratios, key=lambda x: x[3], reverse=True)[:10]

    embed = discord.Embed(
        title=f"⚖️ Top 10 K/D ({period.capitalize()})",
        color=discord.Color.blurple(),
    )
    for idx, (player, kc, dc, ratio) in enumerate(top_list, start=1):
        embed.add_field(
            name=f"{idx}. {player}", value=f"{kc}K / {dc}D → {ratio:.2f}", inline=False
        )

    await interaction.followup.send(embed=embed)


# ─── /kd ──────────────────────────────────────────────────────────────────────
@bot.tree.command(
    name="kd",
    description="Show your K/D (or someone else’s) over a given period",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(
    period="today, week, month, or all time",
    user="RSI handle (defaults to you)",
)
@app_commands.choices(
    period=[
        app_commands.Choice(name="Today", value="today"),
        app_commands.Choice(name="This Week", value="week"),
        app_commands.Choice(name="This Month", value="month"),
        app_commands.Choice(name="All Time", value="all"),
    ],
)
async def kd(
    interaction: discord.Interaction,
    period: str = "all",
    user: str | None = None,
):
    await interaction.response.defer()
    # fallback to yourself if user==None or blank
    target = user or interaction.user.name
    headers = {"Authorization": f"Bearer {API_KEY}"}

    # fetch events
    async with httpx.AsyncClient() as client:
        r_k = await client.get(f"{API_BASE}/kills", headers=headers, timeout=10.0)
        r_d = await client.get(f"{API_BASE}/deaths", headers=headers, timeout=10.0)
        r_k.raise_for_status()
        r_d.raise_for_status()
        kills = r_k.json()
        deaths = r_d.json()

    # helper to filter by period
    def in_period(ts: str) -> bool:
        dt_obj = datetime.fromisoformat(ts.rstrip("Z"))
        now = datetime.utcnow()
        if period == "today":
            return dt_obj.date() == now.date()
        if period == "week":
            return (now - dt_obj).days < 7
        if period == "month":
            return now.year == dt_obj.year and dt_obj.month == now.month
        return True

    # count
    total_kills = sum(
        1 for k in kills if k["player"] == target and in_period(k["time"])
    )
    total_deaths = sum(
        1
        for d in deaths
        if d["victim"] == target
        and in_period(d["time"])
        and d.get("damage_type") != "Suicide"
    )
    ratio = total_kills / max(1, total_deaths)

    embed = discord.Embed(
        title=f"K/D for {target} ({period.capitalize()})",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Kills", value=str(total_kills), inline=True)
    embed.add_field(name="Deaths", value=str(total_deaths), inline=True)
    embed.add_field(name="Ratio", value=f"{ratio:.2f}", inline=True)

    await interaction.followup.send(embed=embed)


# ─── /topkills ──────────────────────────────────────────────────────────────────────
@bot.tree.command(
    name="topkills",
    description="Show the top N players by kills",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(
    mode="Public Universe or Arena Commander",
    period="today, week, month, or all time",
    limit="How many top players to show",
)
@app_commands.choices(
    mode=[
        app_commands.Choice(name="PU", value="pu-kill"),
        app_commands.Choice(name="AC", value="ac-kill"),
    ],
    period=[
        app_commands.Choice(name="Today", value="today"),
        app_commands.Choice(name="This Week", value="week"),
        app_commands.Choice(name="This Month", value="month"),
        app_commands.Choice(name="All Time", value="all"),
    ],
)
async def topkills(
    interaction: discord.Interaction, mode: str, period: str, limit: int = 10
):
    await interaction.response.defer()
    iso_start = _period_start_iso(period)
    headers = {"Authorization": f"Bearer {API_KEY}"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/kills",
            params={"since_time": iso_start},
            headers=headers,
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

    def in_period_ts(ts: str) -> bool:
        dt = datetime.fromisoformat(ts.rstrip("Z"))
        now = datetime.utcnow()
        if period == "today":
            return dt.date() == now.date()
        if period == "week":
            return (now - dt).days < 7
        if period == "month":
            return dt.year == now.year and dt.month == now.month
        # “all” or anything else:
        return True

    stats: dict[str, int] = {}
    for k in data:
        if k["mode"] == mode and in_period_ts(k["time"]):
            stats[k["player"]] = stats.get(k["player"], 0) + 1

    top_list = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:limit]

    embed = discord.Embed(
        title=f"🏆 Top {limit} Players by Kills ({mode.upper()} / {period.capitalize()})",
        color=discord.Color.gold(),
    )
    for idx, (player, cnt) in enumerate(top_list, start=1):
        embed.add_field(name=f"{idx}. {player}", value=f"{cnt} kills", inline=False)

    await interaction.followup.send(embed=embed)


# ─── /toporgs ──────────────────────────────────────────────────────────────────────
@bot.tree.command(
    name="toporgdeaths",
    description="Show the top 10 organizations by how often they were killed",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(
    period="today, week, month, or all time",
)
@app_commands.choices(
    period=[
        app_commands.Choice(name="Today", value="today"),
        app_commands.Choice(name="This Week", value="week"),
        app_commands.Choice(name="This Month", value="month"),
        app_commands.Choice(name="All Time", value="all"),
    ],
)
async def toporgdeaths(
    interaction: discord.Interaction,
    period: str,
):
    await interaction.response.defer()
    iso_start = _period_start_iso(period)
    headers = {"Authorization": f"Bearer {API_KEY}"}

    # 1) Fetch all kills
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/kills",
            params={"since_time": iso_start},
            headers=headers,
            timeout=10.0,
        )
        resp.raise_for_status()
        kills = resp.json()

    # 2) Period filter
    def in_period(ts: str) -> bool:
        dt_obj = datetime.fromisoformat(ts.rstrip("Z"))
        now = datetime.utcnow()
        if period == "today":
            return dt_obj.date() == now.date()
        if period == "week":
            return (now - dt_obj).days < 7
        if period == "month":
            return now.year == dt_obj.year and dt_obj.month == now.month
        return True  # all time

    # 3) Tally per victim organization
    counts: dict[str, int] = {}
    for k in kills:
        org = k.get("organization_name") or "Unknown"
        if in_period(k["time"]):
            counts[org] = counts.get(org, 0) + 1

    # 4) Filter out unwanted organizations
    filtered_counts = {
        org: cnt
        for org, cnt in counts.items()
        if org not in ("Unknown", "THREER", "TRIPLER")
    }

    # 5) Pick the top 10 orgs (after filtering)
    top_list = sorted(filtered_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # 6) Build embed
    embed = discord.Embed(
        title=f"🏢 Top 10 Organizations by Times Killed ({period.capitalize()})",
        color=discord.Color.dark_gray(),
    )

    if top_list:
        for idx, (org, cnt) in enumerate(top_list, start=1):
            embed.add_field(name=f"{idx}. {org}", value=f"{cnt} kills", inline=False)
    else:
        embed.description = (
            "No organizations (other than Unknown) have kills in this period."
        )

    await interaction.followup.send(embed=embed)


# ─── /topdeaths ───────────────────────────────────────────────────────────────
@bot.tree.command(
    name="topdeaths",
    description="Show the top N players by how often they died",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(
    period="today, week, month, or all time",
    limit="How many top players to show",
)
@app_commands.choices(
    period=[
        app_commands.Choice(name="Today", value="today"),
        app_commands.Choice(name="This Week", value="week"),
        app_commands.Choice(name="This Month", value="month"),
        app_commands.Choice(name="All Time", value="all"),
    ],
)
async def topdeaths(
    interaction: discord.Interaction,
    period: str,
    limit: int = 10,
):
    await interaction.response.defer()
    # only fetch deaths since the start of this period
    iso_start = _period_start_iso(period)
    headers = {"Authorization": f"Bearer {API_KEY}"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/deaths",
            params={"since_time": iso_start},
            headers=headers,
            timeout=10.0,
        )
        resp.raise_for_status()
        deaths = resp.json()

    def in_period(ts: str) -> bool:
        dt_obj = datetime.fromisoformat(ts.rstrip("Z"))
        now = datetime.utcnow()
        if period == "today":
            return dt_obj.date() == now.date()
        if period == "week":
            return (now - dt_obj).days < 7
        if period == "month":
            return now.year == dt_obj.year and dt_obj.month == dt_obj.month
        return True

    counts: dict[str, int] = {}
    for d in deaths:
        if in_period(d["time"]):
            counts[d["victim"]] = counts.get(d["victim"], 0) + 1

    top_list = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]

    embed = discord.Embed(
        title=f"💀 Top {limit} Players by Deaths ({period.capitalize()})",
        color=discord.Color.dark_gray(),
    )
    for idx, (player, cnt) in enumerate(top_list, start=1):
        embed.add_field(name=f"{idx}. {player}", value=f"{cnt} deaths", inline=False)

    await interaction.followup.send(embed=embed)


# Keep track of the highest kill ID we've posted so far


@tasks.loop(seconds=10)
async def fetch_and_post_kills():
    global last_kill_id
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{API_BASE}/kills",
                params={"since": last_kill_id},  # <<–– only pull new ones
                headers={"Authorization": f"Bearer {API_KEY}"},
                timeout=10.0,
            )
            resp.raise_for_status()
            kills = resp.json()
    except Exception as e:
        logging.error(
            "⚠️ fetch_and_post_kills failed, will retry next iteration", exc_info=e
        )
        return  # swallow and let the loop fire again in 10s

    for kill in sorted(kills, key=lambda e: e["id"]):
        # 1️ skip stale
        if kill["id"] <= last_kill_id:
            continue

        # 2️ skip any NPC sentry worms
        if kill["victim"].startswith(IGNORED_VICTIM_PREFIX):
            continue

        feed_id = PU_KILL_FEED_ID if kill["mode"] == "pu-kill" else AC_KILL_FEED_ID
        channel = bot.get_channel(feed_id)
        if not channel:
            continue

        # build URLs and thumbnail
        killer_profile = f"https://robertsspaceindustries.com/citizens/{kill['player']}"
        victim_profile = f"https://robertsspaceindustries.com/citizens/{kill['victim']}"
        file_to_attach = discord.File(
            "3R_Transparent.png", filename="3R_Transparent.png"
        )
        thumb = "attachment://3R_Transparent.png"

        embed = discord.Embed(
            title="RRR Kill",
            color=discord.Color.red(),
            timestamp=discord.utils.parse_time(kill["time"]),
        )
        # Killer link (blue)
        embed.add_field(
            name="Killer", value=f"[{kill['player']}]({killer_profile})", inline=False
        )
        embed.add_field(
            name="Victim", value=f"[{kill['victim']}]({victim_profile})", inline=True
        )
        embed.add_field(
            name="Zone",
            value=format_weapon(kill["zone"]) or kill["zone"] or "Unknown",
            inline=True,
        )
        embed.add_field(name="Weapon", value=format_weapon(kill["weapon"]), inline=True)
        embed.add_field(name="Damage", value=kill["damage_type"], inline=True)

        # use our formatter here:
        display_mode = format_mode(kill["game_mode"])
        embed.add_field(name="Mode", value=display_mode, inline=True)

        embed.add_field(
            name="Killer’s Ship",
            value=format_weapon(kill["killers_ship"]) or "Unknown",
            inline=True,
        )
        embed.add_field(
            name="Victim’s Ship",
            value=format_weapon(kill.get("victim_ship") or "") or "Unknown",
            inline=True,
        )

        org_name = kill.get("organization_name") or "Unknown"
        org_url = kill.get("organization_url")
        if org_url:
            embed.add_field(
                name="Victim Organization",
                value=f"[{org_name}]({org_url})",
                inline=False,
            )
        else:
            embed.add_field(name="Victim Organization", value=org_name, inline=False)

        embed.set_thumbnail(url=thumb)
        await channel.send(embed=embed, file=file_to_attach)

        last_kill_id = kill["id"]


# Keep track of the last‑seen death time


@tasks.loop(seconds=10)
async def fetch_and_post_deaths():
    global last_death_id

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{API_BASE}/deaths",
                params={"since": last_death_id},  # <<–– only pull new ones
                headers={"Authorization": f"Bearer {API_KEY}"},
                timeout=10.0,
            )
            resp.raise_for_status()
            deaths = resp.json()
    except Exception as e:
        logging.error(
            "⚠️ fetch_and_post_deaths failed, will retry next iteration", exc_info=e
        )
        return

    for death in sorted(deaths, key=lambda e: e["id"]):
        # skip any we’ve already seen
        if death["id"] <= last_death_id:
            continue

        file_to_attach = discord.File(
            "3R_Transparent.png", filename="3R_Transparent.png"
        )
        thumb = "attachment://3R_Transparent.png"

        # route Persistent Universe → PU feed; everything else → AC
        feed_id = (
            PU_KILL_FEED_ID if death["game_mode"].startswith("SC_") else AC_KILL_FEED_ID
        )
        channel = bot.get_channel(feed_id)
        if not channel:
            continue

        embed = discord.Embed(
            title="💀 You Died",
            color=discord.Color.dark_gray(),
            timestamp=discord.utils.parse_time(death["time"]),
        )

        killer_profile = death.get("rsi_profile")
        embed.add_field(
            name="Killer", value=f"[{death['killer']}]({killer_profile})", inline=False
        )

        victim_profile = (
            f"https://robertsspaceindustries.com/citizens/{death['victim']}"
        )
        embed.add_field(
            name="Victim (You)",
            value=f"[{death['victim']}]({victim_profile})",
            inline=True,
        )
        embed.add_field(
            name="Zone",
            value=format_weapon(death["zone"]) or death["zone"] or "Unknown",
            inline=True,
        )
        embed.add_field(
            name="Weapon", value=format_weapon(death["weapon"]), inline=True
        )
        embed.add_field(name="Damage", value=death["damage_type"], inline=True)

        display_mode = format_mode(death["game_mode"])
        embed.add_field(name="Mode", value=display_mode, inline=True)

        embed.add_field(
            name="Killer’s Ship",
            value=format_weapon(death["killers_ship"]) or "Unknown",
            inline=True,
        )
        embed.add_field(
            name="Your Ship",
            value=format_weapon(death.get("victim_ship") or "") or "Unknown",
            inline=True,
        )

        org_name = death.get("organization_name") or "Unknown"
        org_url = death.get("organization_url")
        if org_url:
            embed.add_field(
                name="Killer’s Organization",
                value=f"[{org_name}]({org_url})",
                inline=False,
            )
        else:
            embed.add_field(name="Killer’s Organization", value=org_name, inline=False)

        embed.set_thumbnail(url=thumb)
        await channel.send(embed=embed, file=file_to_attach)

        last_death_id = death["id"]


# ─── Health check server ────────────────────────────────────────────────────────
async def handle_health(request):
    return web.json_response({"status": "ok"})


def start_health_server():
    def _run():
        app = web.Application()
        app.router.add_get("/health", handle_health)
        port = int(os.environ.get("PORT", 8080))
        logging.info(f"Starting HTTP server on 0.0.0.0:{port}")
        # disable signal-handler registration in this thread:
        web.run_app(app, host="0.0.0.0", port=port, handle_signals=False)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


# ─── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # 1) Start the tiny HTTP server
    start_health_server()

    # 2) Finally, launch your Discord bot (this is the one and only bot.run)
    bot.run(TOKEN)
