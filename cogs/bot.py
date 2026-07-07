import os
import sqlite3
import datetime
import discord
from discord import app_commands
from discord.ext import commands
from keep_alive import keep_alive  # Render free-tier keep awake engine

# ==========================================================
# ADVANCED PERSISTENT STORAGE MANAGEMENT (SQLite)
# ==========================================================
DB_FILE = "tripwire_advanced.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            guild_id INTEGER PRIMARY KEY,
            channel_name TEXT,
            channel_id INTEGER,
            log_channel_id INTEGER,
            action TEXT,
            timeout_hours INTEGER,
            mute_role_id INTEGER,
            visibility TEXT,
            exempt_role_id INTEGER,
            notify_offender INTEGER
        )
    ''')
    conn.commit()
    conn.close()

def save_advanced_settings(guild_id, channel_name, channel_id, log_channel_id, action, timeout_hours, mute_role_id, visibility, exempt_role_id, notify_offender):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO settings (guild_id, channel_name, channel_id, log_channel_id, action, timeout_hours, mute_role_id, visibility, exempt_role_id, notify_offender)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (guild_id, channel_name, channel_id, log_channel_id, action, timeout_hours, mute_role_id, visibility, exempt_role_id, notify_offender))
    conn.commit()
    conn.close()

def get_advanced_settings(guild_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT channel_name, channel_id, log_channel_id, action, timeout_hours, mute_role_id, visibility, exempt_role_id, notify_offender FROM settings WHERE guild_id = ?', (guild_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "channel_name": row[0], "channel_id": row[1], "log_channel_id": row[2], "action": row[3],
            "timeout_hours": row[4], "mute_role_id": row[5], "visibility": row[6], "exempt_role_id": row[7], "notify_offender": row[8]
        }
    return None

init_db()

# ==========================================================
# SECURITY CORE SUBSYSTEM
# ==========================================================
intents = discord.Intents.default()
intents.message_content = True  
intents.members = True          

bot = commands.Bot(command_prefix="/", intents=intents)

@bot.event
async def on_ready():
    print(f"🛡️ Tripwire Custom Core Running: {bot.user}")
    try:
        await bot.tree.sync()
        print("🔄 Universal security options synced globally.")
    except Exception as e:
        print(f"❌ Synchronization Error: {e}")

# ==========================================================
# THE FULLY CUSTOMIZABLE ALL-IN-ONE MASTER SETUP
# ==========================================================
@bot.tree.command(
    name="setup-tripwire",
    description="Deploys the trap channel, creates private logs, and configures security enforcement."
)
@app_commands.describe(
    action="The core punishment executed when a bot types in the tripwire channel.",
    exempt_role="The role allowed to see logs, bypass punishments, and talk in the trap.",
    channel_name="Custom name for the trap channel (Default: tripwire).",
    visibility="Should normal members see the channel read-only warning or hide it entirely?",
    timeout_hours="If Action is Timeout, how many hours should it last? (Default: 24)",
    mute_role="If Action is Mute Role, specify the role to give to the offender.",
    notify_offender="Should the bot try to DM the caught user explaining why they were moderated?",
    custom_headline="Custom headline displayed on the channel warning message.",
    custom_body="Custom body text printed into the channel warning message."
)
@app_commands.choices(
    action=[
        app_commands.Choice(name="Instant Ban", value="ban"),
        app_commands.Choice(name="Softban (Ban + Instant Unban to clear 24h of history)", value="softban"),
        app_commands.Choice(name="Instant Kick", value="kick"),
        app_commands.Choice(name="Isolate via Timeout", value="timeout"),
        app_commands.Choice(name="Assign Mute Role", value="muterole")
    ],
    visibility=[
        app_commands.Choice(name="Public (Visible warning card for normal users)", value="public"),
        app_commands.Choice(name="Private (Completely invisible to non-administrators)", value="private")
    ]
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_advanced_tripwire(
    interaction: discord.Interaction,
    action: app_commands.Choice[str],
    exempt_role: discord.Role,
    channel_name: str = "tripwire",
    visibility: app_commands.Choice[str] = None,
    timeout_hours: int = 24,
    mute_role: discord.Role = None,
    notify_offender: bool = True,
    custom_headline: str = None,
    custom_body: str = None
):
    guild = interaction.guild
    await interaction.response.defer(ephemeral=True)

    clean_channel_name = channel_name.strip().lower().replace(" ", "-")
    chosen_visibility = visibility.value if visibility else "public"

    if action.value == "muterole" and not mute_role:
        return await interaction.followup.send("❌ Setup Error: You chose 'Assign Mute Role' but did not provide a role in the `mute_role` option.", ephemeral=True)

    # 1. Clean up old text channels matching the custom trap name or logs name
    for channel in guild.text_channels:
        if channel.name.lower() in [clean_channel_name, f"{clean_channel_name}-logs"]:
            try:
                await channel.delete(reason="Tripwire Configuration Wipe")
            except discord.Forbidden:
                return await interaction.followup.send(f"❌ Permission Failure: Bot cannot clear old channel variations.", ephemeral=True)

    # 2. Build Strict Trap Channel Permission Masks
    is_public = (chosen_visibility == "public")
    trap_overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=is_public, send_messages=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        exempt_role: discord.PermissionOverwrite(view_channel=True, send_messages=True)
    }

    # 3. Create the Trap Channel
    try:
        new_channel = await guild.create_text_channel(name=clean_channel_name, overwrites=trap_overwrites)
    except discord.Forbidden:
        return await interaction.followup.send("❌ Permission Failure: Cannot initialize channels. Check bot permissions.", ephemeral=True)

    # 4. Create the Strictly Private Log Channel (Only Owner, Exempt Role, and Bot can view)
    log_overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),  # Block everyone else
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        exempt_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        guild.owner: discord.PermissionOverwrite(view_channel=True, send_messages=True)  # Server owner always allowed
    }

    try:
        log_channel = await guild.create_text_channel(name=f"{clean_channel_name}-logs", overwrites=log_overwrites)
    except discord.Forbidden:
        return await interaction.followup.send("❌ Permission Failure: Created trap but failed to create private logs.", ephemeral=True)

    # 5. Save settings to DB
    mute_id = mute_role.id if mute_role else 0
    save_advanced_settings(
        guild.id, clean_channel_name, new_channel.id, log_channel.id, action.value,
        timeout_hours, mute_id, chosen_visibility, exempt_role.id, int(notify_offender)
    )

    # 6. Post Trap Warning Embed
    headline = custom_headline if custom_headline else "⚠️ SECURITY PERIMETER ACTIVE"
    body = custom_body if custom_body else "Do not type inside this channel. Doing so will result in an automated moderation execution."

    embed = discord.Embed(
        title=headline,
        description=f"**{body}**",
        color=discord.Color.red(),
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    embed.add_field(name="⚙️ Automated Action", value=f"`{action.name}`", inline=True)
    embed.add_field(name="🛡️ Staff/Exempt Role", value=exempt_role.mention, inline=True)
    embed.set_footer(text="Tripwire System Core")

    await new_channel.send(embed=embed)

    # Post initial setup log confirmation card
    log_embed = discord.Embed(
        title="⚙️ TRIPWIRE LOCKDOWN SECURED",
        description=f"System fully customized and operational.\n\n**Trap Channel:** {new_channel.mention}\n**Enforcement Protocol:** `{action.name}`\n**Authorized Role:** {exempt_role.mention}",
        color=discord.Color.green(),
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    await log_channel.send(embed=log_embed)

    await interaction.followup.send(f"✅ Tripwire active! Trap: {new_channel.mention} | Private Logs: {log_channel.mention}", ephemeral=True)

# ==========================================================
# MITIGATION EVENT RADAR LOOP
# ==========================================================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    config = get_advanced_settings(message.guild.id)
    if not config:
        return

    # Check if this message was sent in our active tripwire trap channel
    if message.channel.id != config["channel_id"]:
        return

    offender = message.author

    # Bypass Shield: Owner, Admins, Message Managers, and the set Exempt Role are immune
    if (offender.guild_permissions.manage_messages or 
        offender.guild_permissions.administrator or 
        offender.id == message.guild.owner_id or
        config["exempt_role_id"] in [role.id for role in offender.roles]):
        return

    violation_reason = f"Tripwire Intrusion: Unauthorized message posted inside trap channel `#{config['channel_name']}`"

    try:
        # 1. Instantly delete the payload text
        await message.delete()

        # 2. Try to notify the offender if enabled
        if config["notify_offender"] == 1:
            try:
                await offender.send(f"⚠️ **Security Notice:** You have been automatically moderated in **{message.guild.name}** for typing in a restricted system trap channel.")
            except discord.Forbidden:
                pass

        # 3. Process Custom Advanced Punishments
        action_type = config["action"]
        
        if action_type == "ban":
            await message.guild.ban(offender, reason=violation_reason, delete_message_days=1)
        
        elif action_type == "softban":
            # Ban + instantly unban (effectively kicks them and wipes all their message history from the last 24h)
            await message.guild.ban(offender, reason=f"[SOFTBAN] {violation_reason}", delete_message_days=1)
            await message.guild.unban(offender, reason="Softban cycle complete.")
        
        elif action_type == "kick":
            await message.guild.kick(offender, reason=violation_reason)
        
        elif action_type == "timeout":
            duration = datetime.timedelta(hours=config["timeout_hours"])
            await offender.timeout(duration, reason=violation_reason)
        
        elif action_type == "muterole":
            mute_role = message.guild.get_role(config["mute_role_id"])
            if mute_role:
                await offender.add_roles(mute_role, reason=violation_reason)

        # 4. Route Execution metrics straight to the private log channel
        log_channel = bot.get_channel(config["log_channel_id"])
        if log_channel:
            report = discord.Embed(
                title="🛡️ TRIPWIRE INTERCEPTION INFLICTED",
                color=discord.Color.dark_orange(),
                timestamp=datetime.datetime.now(datetime.timezone.utc)
            )
            report.add_field(name="Account Caught", value=f"{offender.mention} (`{offender.id}`)", inline=True)
            report.add_field(name="Enforcement Action", value=f"`{action_type.upper()}`", inline=True)
            report.add_field(name="Captured Content", value=f"
http://googleusercontent.com/immersive_entry_chip/0
