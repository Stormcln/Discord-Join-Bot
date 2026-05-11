import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
import os
import json
import asyncio
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import tempfile
from collections import Counter
from datetime import timedelta

TOKEN = "TOKEN"

intents = discord.Intents.default()
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="j!", intents=intents)

CONFIG_FILE = "welcome_config.json"
LOG_DIR = "join"
MAX_GREET_CHANNELS = 10

# Charger la config
if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
else:
    config = {}

if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

def save_config():
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

def ensure_guild_config(guild_id: str):
    if guild_id not in config:
        config[guild_id] = {
            "welcome_channel": None,
            "welcome_enabled": True,
            "greet_channels": []
        }

def log_member(guild: discord.Guild, message: str):
    filepath = os.path.join(LOG_DIR, f"{guild.id}.log")
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(message + "\n")

def format_duration(delta):
    total = int(delta.total_seconds())
    days = total // 86400
    hours = (total % 86400) // 3600
    mins = (total % 3600) // 60
    parts = []
    if days: parts.append(f"{days}d")
    if hours: parts.append(f"{hours}h")
    parts.append(f"{mins}m")
    return " ".join(parts)


def parse_join_log(guild_id: str):
    """Parse join/<guild_id>.log and return list of datetimes (UTC) for JOIN entries."""
    path = os.path.join(LOG_DIR, f"{guild_id}.log")
    if not os.path.exists(path):
        return []
    joins = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            # Expected format: [JOIN] MemberName (id) at 2025-10-20 12:34:56+00:00
            if line.startswith("[JOIN]"):
                try:
                    parts = line.rsplit(" at ", 1)
                    if len(parts) == 2:
                        dt_str = parts[1].strip()
                        # Parse ISO-like with timezone
                        dt = datetime.fromisoformat(dt_str)
                        joins.append(dt)
                except Exception:
                    continue
    return joins


def aggregate_counts(dts, days_back=None):
    """Aggregate datetimes into daily counts for the last `days_back` days. If days_back is None, return all-time daily counts."""
    if not dts:
        return [], []
    now = datetime.now(timezone.utc)
    # Convert to dates
    dates = [dt.astimezone(timezone.utc).date() for dt in dts]
    counts = Counter(dates)
    if days_back is not None:
        start_date = (now - timedelta(days=days_back - 1)).date()
        days = [start_date + timedelta(days=i) for i in range(days_back)]
    else:
        # all time: from earliest to today
        min_date = min(dates)
        max_date = now.date()
        days = []
        cur = min_date
        while cur <= max_date:
            days.append(cur)
            cur += timedelta(days=1)
    y = [counts.get(d, 0) for d in days]
    x = days
    return x, y


async def plot_and_send(interaction: discord.Interaction, x, y, label):
    if not x:
        await interaction.followup.send("⚠️ No join data available.", ephemeral=True)
        return
    plt.figure(figsize=(10, 4))
    plt.bar(x, y, color="#22C55E")
    plt.title(f"Joins - {label}")
    plt.xlabel("Date")
    plt.ylabel("Joins")
    plt.tight_layout()
    # Rotate dates
    plt.xticks(rotation=45)
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    try:
        plt.savefig(tmp.name)
        plt.close()
        await interaction.followup.send(file=discord.File(tmp.name), ephemeral=False)
    finally:
        try:
            tmp.close()
            os.unlink(tmp.name)
        except Exception:
            pass

# === CHECK ADMIN ===
def admin_only(interaction: discord.Interaction) -> bool:
    return interaction.user.guild_permissions.administrator

@app_commands.check(admin_only)
async def check_admin(interaction: discord.Interaction):
    return True

# === BOT READY ===
@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game("Welcoming members 👋"))
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"❌ Error syncing commands: {e}")
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")

# === SLASH COMMANDS ===

@bot.tree.command(name="welcome_config", description="Set the channel for welcome/leave messages")
@app_commands.describe(channel="The channel where welcome messages should appear")
async def welcome_config_cmd(interaction: discord.Interaction, channel: discord.TextChannel):
    await interaction.response.defer(ephemeral=True)
    guild_id = str(interaction.guild.id)
    ensure_guild_config(guild_id)
    config[guild_id]["welcome_channel"] = channel.id
    save_config()
    await interaction.followup.send(f"✅ Welcome channel set to {channel.mention}", ephemeral=True)

@bot.tree.command(name="welcome_test", description="Send a test welcome message")
async def welcome_test(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    guild_id = str(interaction.guild.id)
    ensure_guild_config(guild_id)
    channel_id = config[guild_id]["welcome_channel"]
    if not channel_id:
        await interaction.followup.send("⚠️ No welcome channel configured.", ephemeral=True)
        return
    channel = interaction.guild.get_channel(channel_id)
    if not channel:
        await interaction.followup.send("⚠️ Configured channel not found.", ephemeral=True)
        return
    embed = discord.Embed(
        description=f"{interaction.user.mention} just joined **{interaction.guild.name}**.\n"
                    f"There are now **{interaction.guild.member_count}** members.",
        color=0x22C55E
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    await channel.send(embed=embed)
    await interaction.followup.send("✅ Test welcome message sent.", ephemeral=True)

@bot.tree.command(name="welcome_message_toggle", description="Enable or disable welcome messages")
@app_commands.describe(enabled="true or false")
async def welcome_message_toggle(interaction: discord.Interaction, enabled: bool):
    await interaction.response.defer(ephemeral=True)
    guild_id = str(interaction.guild.id)
    ensure_guild_config(guild_id)
    config[guild_id]["welcome_enabled"] = enabled
    save_config()
    await interaction.followup.send(f"✅ Welcome messages {'enabled' if enabled else 'disabled'}.", ephemeral=True)

@bot.tree.command(name="greet", description="Enable greet in this channel")
async def greet_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    guild_id = str(interaction.guild.id)
    ensure_guild_config(guild_id)
    chans = config[guild_id]["greet_channels"]
    channel_id = interaction.channel.id
    if channel_id in chans:
        chans.remove(channel_id)
        msg = f"❌ Greet disabled in {interaction.channel.mention}"
    else:
        if len(chans) >= MAX_GREET_CHANNELS:
            await interaction.followup.send(f"⚠️ You reached the limit of {MAX_GREET_CHANNELS} greet channels.", ephemeral=True)
            return
        chans.append(channel_id)
        msg = f"✅ Greet enabled in {interaction.channel.mention}"
    config[guild_id]["greet_channels"] = chans
    save_config()
    await interaction.followup.send(msg, ephemeral=True)

@bot.tree.command(name="greet_info", description="List all greet-enabled channels")
async def greet_info(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    guild_id = str(interaction.guild.id)
    ensure_guild_config(guild_id)
    chans = config[guild_id]["greet_channels"]
    if not chans:
        await interaction.followup.send("⚠️ No greet channels enabled.", ephemeral=True)
        return
    text = "\n".join([f"<#{cid}>" for cid in chans])
    await interaction.followup.send(f"📢 Greet enabled in:\n{text}", ephemeral=True)


@bot.tree.command(name="join_stats", description="Show a graph of joins over time (7/30/90/all)")
@app_commands.describe(range_days="Choose range: 7, 30, 90 or all")
async def join_stats(interaction: discord.Interaction, range_days: str = "7"):
    await interaction.response.defer(ephemeral=False)
    guild_id = str(interaction.guild.id)
    # Read join datetimes from log
    dts = parse_join_log(guild_id)
    if range_days == "7":
        x, y = aggregate_counts(dts, days_back=7)
        label = "Last 7 days"
    elif range_days == "30":
        x, y = aggregate_counts(dts, days_back=30)
        label = "Last 30 days"
    elif range_days == "90":
        x, y = aggregate_counts(dts, days_back=90)
        label = "Last 90 days"
    else:
        x, y = aggregate_counts(dts, days_back=None)
        label = "All time"
    await plot_and_send(interaction, x, y, label)

# === MEMBER EVENTS ===

@bot.event
async def on_member_join(member: discord.Member):
    guild_id = str(member.guild.id)
    ensure_guild_config(guild_id)

    # Welcome message
    if config[guild_id]["welcome_enabled"] and config[guild_id]["welcome_channel"]:
        channel = member.guild.get_channel(config[guild_id]["welcome_channel"])
        if channel:
            embed = discord.Embed(
                description=f"{member.mention} just joined **{member.guild.name}**.\n"
                            f"There are now **{member.guild.member_count}** members.",
                color=0x22C55E
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await channel.send(embed=embed)

    # Greet messages
    for cid in config[guild_id]["greet_channels"]:
        chan = member.guild.get_channel(cid)
        if chan:
            msg = await chan.send(f"{member.mention}")
            await asyncio.sleep(1)
            await msg.delete()

    log_member(member.guild, f"[JOIN] {member} ({member.id}) at {datetime.now(timezone.utc)}")

@bot.event
async def on_member_remove(member: discord.Member):
    guild_id = str(member.guild.id)
    ensure_guild_config(guild_id)
    stayed_text = "unknown"
    if member.joined_at:
        stayed_text = format_duration(datetime.now(timezone.utc) - member.joined_at)
    if config[guild_id]["welcome_enabled"] and config[guild_id]["welcome_channel"]:
        channel = member.guild.get_channel(config[guild_id]["welcome_channel"])
        if channel:
            embed = discord.Embed(
                description=f"{member.mention} left **{member.guild.name}**.\n"
                            f"Stayed **{stayed_text}**.\n"
                            f"There are now **{member.guild.member_count}** members.",
                color=0xEF4444
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await channel.send(embed=embed)
    log_member(member.guild, f"[LEAVE] {member} ({member.id}) stayed {stayed_text}, left at {datetime.now(timezone.utc)}")

# === RUN BOT ===
bot.run(TOKEN)
