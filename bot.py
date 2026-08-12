import asyncio
import base64
import datetime
import json
import logging
import os
import sys
from typing import Dict, List, Optional, Any

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("discord_backup")

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Rate limit safety delay settings (in seconds)
API_DELAY = 0.5
EMOJI_DELAY = 1.0

# Initialize Bot with Required Intents
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.emojis_and_stickers = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ==========================================
# HELPER FUNCTIONS
# ==========================================

async def asset_to_b64(asset: Optional[discord.Asset]) -> Optional[str]:
    """Converts a discord.Asset (like server icon) to a base64 encoded string."""
    if not asset:
        return None
    try:
        data = await asset.read()
        return base64.b64encode(data).decode('utf-8')
    except Exception as e:
        logger.warning(f"Failed to read asset {asset.url}: {e}")
        return None


def serialize_overwrites(channel: discord.abc.GuildChannel) -> Dict[str, Dict[str, int]]:
    """Serializes role-based permission overwrites for a channel."""
    overwrites_data = {}
    for target, overwrite in channel.overwrites.items():
        if isinstance(target, discord.Role):
            allow_val, deny_val = overwrite.pair()
            overwrites_data[target.name] = {
                "allow": allow_val.value,
                "deny": deny_val.value
            }
    return overwrites_data


def deserialize_overwrites(
    overwrites_data: Dict[str, Dict[str, int]],
    role_map: Dict[str, discord.Role]
) -> Dict[discord.Role, discord.PermissionOverwrite]:
    """Reconstructs discord.PermissionOverwrite mapping using restored roles."""
    reconstructed = {}
    for role_name, pair in overwrites_data.items():
        target_role = role_map.get(role_name)
        if target_role:
            allow_perm = discord.Permissions(pair.get("allow", 0))
            deny_perm = discord.Permissions(pair.get("deny", 0))
            reconstructed[target_role] = discord.PermissionOverwrite.from_pair(allow_perm, deny_perm)
    return reconstructed


# ==========================================
# BOT EVENTS & SETUP
# ==========================================

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} slash command(s) globally.")
    except Exception as e:
        logger.error(f"Failed to sync slash commands: {e}")


# Global error handler for slash command permissions
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        embed = discord.Embed(
            title="Permission Denied",
            description="⚠️ You must have **Administrator** permissions to use backup commands.",
            color=discord.Color.red()
        )
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        logger.error(f"Slash command error: {error}", exc_info=error)
        msg = f"❌ An error occurred: `{error}`"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


# ==========================================
# SLASH COMMAND: /backup-create
# ==========================================

@bot.tree.command(
    name="backup-create",
    description="Export complete server configuration, roles, channels, emojis, and messages to JSON."
)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(include_messages="Archive the last 50 messages per text channel (Default: True)")
async def backup_create(interaction: discord.Interaction, include_messages: bool = True):
    await interaction.response.defer(thinking=True)
    guild = interaction.guild
    if not guild:
        await interaction.followup.send("❌ This command can only be used within a server.")
        return

    logger.info(f"Starting backup for guild '{guild.name}' (ID: {guild.id})")
    start_time = datetime.datetime.now(datetime.timezone.utc)

    try:
        # ----------------------------------
        # 1. Server Settings & Metadata
        # ----------------------------------
        icon_b64 = await asset_to_b64(guild.icon)
        
        backup_data: Dict[str, Any] = {
            "version": "2.0",
            "created_at": start_time.isoformat(),
            "guild_info": {
                "id": guild.id,
                "name": guild.name,
                "description": guild.description,
                "icon_url": str(guild.icon.url) if guild.icon else None,
                "icon_b64": icon_b64,
                "verification_level": guild.verification_level.value,
                "default_notifications": guild.default_notifications.value,
                "afk_timeout": guild.afk_timeout,
                "afk_channel_name": guild.afk_channel.name if guild.afk_channel else None
            },
            "roles": [],
            "categories": [],
            "text_channels": [],
            "voice_channels": [],
            "emojis": []
        }

        # ----------------------------------
        # 2. Export Roles
        # ----------------------------------
        # Sort roles by position (lowest to highest)
        sorted_roles = sorted(guild.roles, key=lambda r: r.position)
        for role in sorted_roles:
            # Skip managed integration/bot roles (cannot be created via standard API)
            if role.managed or role.is_bot_managed():
                continue
            
            backup_data["roles"].append({
                "name": role.name,
                "color": role.color.value,
                "hoist": role.hoist,
                "mentionable": role.mentionable,
                "permissions": role.permissions.value,
                "position": role.position,
                "is_everyone": role.is_default()
            })

        # ----------------------------------
        # 3. Export Categories
        # ----------------------------------
        sorted_categories = sorted(guild.categories, key=lambda c: c.position)
        for category in sorted_categories:
            backup_data["categories"].append({
                "name": category.name,
                "position": category.position,
                "overwrites": serialize_overwrites(category)
            })

        # ----------------------------------
        # 4. Export Text Channels & Messages
        # ----------------------------------
        sorted_text_channels = sorted(guild.text_channels, key=lambda c: c.position)
        for channel in sorted_text_channels:
            channel_data = {
                "name": channel.name,
                "position": channel.position,
                "topic": channel.topic,
                "nsfw": channel.nsfw,
                "slowmode_delay": channel.slowmode_delay,
                "category_name": channel.category.name if channel.category else None,
                "overwrites": serialize_overwrites(channel),
                "messages": []
            }

            if include_messages:
                try:
                    async for msg in channel.history(limit=50, oldest_first=False):
                        channel_data["messages"].append({
                            "author": str(msg.author),
                            "author_id": msg.author.id,
                            "timestamp": msg.created_at.isoformat(),
                            "content": msg.content,
                            "attachments": [a.url for a in msg.attachments]
                        })
                except discord.Forbidden:
                    logger.warning(f"No permission to read history in #{channel.name}")
                except Exception as e:
                    logger.warning(f"Error fetching messages for #{channel.name}: {e}")

            backup_data["text_channels"].append(channel_data)

        # ----------------------------------
        # 5. Export Voice Channels
        # ----------------------------------
        sorted_voice_channels = sorted(guild.voice_channels, key=lambda c: c.position)
        for channel in sorted_voice_channels:
            backup_data["voice_channels"].append({
                "name": channel.name,
                "position": channel.position,
                "bitrate": channel.bitrate,
                "user_limit": channel.user_limit,
                "category_name": channel.category.name if channel.category else None,
                "overwrites": serialize_overwrites(channel)
            })

        # ----------------------------------
        # 6. Export Custom Emojis (with Base64 Image Data)
        # ----------------------------------
        async with aiohttp.ClientSession() as session:
            for emoji in guild.emojis:
                try:
                    async with session.get(str(emoji.url)) as resp:
                        if resp.status == 200:
                            img_bytes = await resp.read()
                            b64_img = base64.b64encode(img_bytes).decode('utf-8')
                            backup_data["emojis"].append({
                                "name": emoji.name,
                                "image_b64": b64_img
                            })
                except Exception as e:
                    logger.warning(f"Failed to export emoji {emoji.name}: {e}")

        # ----------------------------------
        # 7. Write to Local JSON File
        # ----------------------------------
        filename = f"backup_{guild.id}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, indent=4, ensure_ascii=False)

        total_messages = sum(len(tc["messages"]) for tc in backup_data["text_channels"])
        
        embed = discord.Embed(
            title="✅ Backup Created Successfully",
            description=f"Exported complete structure for **{guild.name}** into `{filename}`.",
            color=discord.Color.green(),
            timestamp=start_time
        )
        embed.add_field(name="Roles", value=str(len(backup_data["roles"])), inline=True)
        embed.add_field(name="Categories", value=str(len(backup_data["categories"])), inline=True)
        embed.add_field(name="Text Channels", value=str(len(backup_data["text_channels"])), inline=True)
        embed.add_field(name="Voice Channels", value=str(len(backup_data["voice_channels"])), inline=True)
        embed.add_field(name="Custom Emojis", value=str(len(backup_data["emojis"])), inline=True)
        embed.add_field(name="Archived Messages", value=str(total_messages), inline=True)
        embed.set_footer(text=f"File: {filename}")

        await interaction.followup.send(embed=embed)
        logger.info(f"Backup successfully saved to {filename}")

    except Exception as e:
        logger.error(f"Backup creation failed: {e}", exc_info=True)
        await interaction.followup.send(f"❌ Backup failed due to an error: `{e}`")


# ==========================================
# SLASH COMMAND: /backup-load
# ==========================================

@bot.tree.command(
    name="backup-load",
    description="Restore a server structure from a local backup JSON file."
)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(guild_id="Source Guild ID of the backup file (e.g., 123456789012345678 or filename)")
async def backup_load(interaction: discord.Interaction, guild_id: str):
    await interaction.response.defer(thinking=True)
    guild = interaction.guild
    if not guild:
        await interaction.followup.send("❌ This command can only be used within a server.")
        return

    # Clean filename input
    filename = guild_id.strip()
    if not filename.endswith(".json"):
        filename = f"backup_{filename}.json"

    if not os.path.exists(filename):
        await interaction.followup.send(f"❌ Backup file `{filename}` not found on the bot server.")
        return

    try:
        with open(filename, "r", encoding="utf-8") as f:
            backup_data = json.load(f)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to parse backup JSON file: `{e}`")
        return

    logger.info(f"Starting restore on guild '{guild.name}' (ID: {guild.id}) from '{filename}'")
    status_msg = await interaction.followup.send(f"🔄 **Starting restoration process from `{filename}`...**")

    async def update_status(text: str):
        try:
            await status_msg.edit(content=text)
        except Exception:
            pass

    try:
        role_map: Dict[str, discord.Role] = {"@everyone": guild.default_role}
        category_map: Dict[str, discord.CategoryChannel] = {}

        # ----------------------------------
        # 1. Restore Roles
        # ----------------------------------
        await update_status("🔄 **Stage 1/5:** Restoring Roles...")
        roles_data = backup_data.get("roles", [])
        
        for r_data in roles_data:
            if r_data.get("is_everyone"):
                # Update @everyone permissions
                try:
                    perms = discord.Permissions(r_data["permissions"])
                    await guild.default_role.edit(permissions=perms)
                except Exception as e:
                    logger.warning(f"Failed to edit @everyone permissions: {e}")
                role_map["@everyone"] = guild.default_role
                continue

            # Check if matching role name exists
            existing_role = discord.utils.get(guild.roles, name=r_data["name"])
            if existing_role and not existing_role.managed:
                role_map[r_data["name"]] = existing_role
            else:
                try:
                    new_role = await guild.create_role(
                        name=r_data["name"],
                        color=discord.Color(r_data["color"]),
                        hoist=r_data["hoist"],
                        mentionable=r_data["mentionable"],
                        permissions=discord.Permissions(r_data["permissions"])
                    )
                    role_map[r_data["name"]] = new_role
                    await asyncio.sleep(API_DELAY)
                except discord.HTTPException as e:
                    logger.error(f"Failed to create role {r_data['name']}: {e}")

        # ----------------------------------
        # 2. Restore Categories
        # ----------------------------------
        await update_status("🔄 **Stage 2/5:** Restoring Categories...")
        categories_data = backup_data.get("categories", [])
        
        for cat_data in categories_data:
            overwrites = deserialize_overwrites(cat_data.get("overwrites", {}), role_map)
            existing_cat = discord.utils.get(guild.categories, name=cat_data["name"])
            if existing_cat:
                category_map[cat_data["name"]] = existing_cat
            else:
                try:
                    new_cat = await guild.create_category(
                        name=cat_data["name"],
                        overwrites=overwrites
                    )
                    category_map[cat_data["name"]] = new_cat
                    await asyncio.sleep(API_DELAY)
                except discord.HTTPException as e:
                    logger.error(f"Failed to create category {cat_data['name']}: {e}")

        # ----------------------------------
        # 3. Restore Text Channels
        # ----------------------------------
        await update_status("🔄 **Stage 3/5:** Restoring Text Channels...")
        text_channels_data = backup_data.get("text_channels", [])
        
        for tc_data in text_channels_data:
            overwrites = deserialize_overwrites(tc_data.get("overwrites", {}), role_map)
            category = category_map.get(tc_data.get("category_name"))
            
            try:
                await guild.create_text_channel(
                    name=tc_data["name"],
                    category=category,
                    topic=tc_data.get("topic"),
                    nsfw=tc_data.get("nsfw", False),
                    slowmode_delay=tc_data.get("slowmode_delay", 0),
                    overwrites=overwrites
                )
                await asyncio.sleep(API_DELAY)
            except discord.HTTPException as e:
                logger.error(f"Failed to create text channel #{tc_data['name']}: {e}")

        # ----------------------------------
        # 4. Restore Voice Channels
        # ----------------------------------
        await update_status("🔄 **Stage 4/5:** Restoring Voice Channels...")
        voice_channels_data = backup_data.get("voice_channels", [])
        
        for vc_data in voice_channels_data:
            overwrites = deserialize_overwrites(vc_data.get("overwrites", {}), role_map)
            category = category_map.get(vc_data.get("category_name"))
            
            # Ensure bitrate does not exceed target server's maximum limit
            target_bitrate = int(min(vc_data.get("bitrate", 64000), guild.bitrate_limit))

            try:
                await guild.create_voice_channel(
                    name=vc_data["name"],
                    category=category,
                    bitrate=target_bitrate,
                    user_limit=vc_data.get("user_limit", 0),
                    overwrites=overwrites
                )
                await asyncio.sleep(API_DELAY)
            except discord.HTTPException as e:
                logger.error(f"Failed to create voice channel {vc_data['name']}: {e}")

        # ----------------------------------
        # 5. Restore Custom Emojis
        # ----------------------------------
        await update_status("🔄 **Stage 5/5:** Restoring Custom Emojis...")
        emojis_data = backup_data.get("emojis", [])
        restored_emojis_count = 0
        
        for emoji_data in emojis_data:
            emoji_name = emoji_data.get("name")
            b64_img = emoji_data.get("image_b64")
            
            if not emoji_name or not b64_img:
                continue

            # Skip if emoji with same name already exists
            if discord.utils.get(guild.emojis, name=emoji_name):
                continue

            try:
                img_bytes = base64.b64decode(b64_img)
                await guild.create_custom_emoji(name=emoji_name, image=img_bytes)
                restored_emojis_count += 1
                await asyncio.sleep(EMOJI_DELAY)
            except discord.HTTPException as e:
                logger.error(f"Failed to restore emoji :{emoji_name}: : {e}")

        # ----------------------------------
        # 6. Restore Server Settings
        # ----------------------------------
        guild_info = backup_data.get("guild_info", {})
        try:
            update_kwargs = {}
            if "name" in guild_info:
                update_kwargs["name"] = guild_info["name"]
            
            if "verification_level" in guild_info:
                try:
                    update_kwargs["verification_level"] = discord.VerificationLevel(guild_info["verification_level"])
                except Exception:
                    pass

            if "default_notifications" in guild_info:
                try:
                    update_kwargs["default_notifications"] = discord.NotificationLevel(guild_info["default_notifications"])
                except Exception:
                    pass

            if guild_info.get("icon_b64"):
                try:
                    update_kwargs["icon"] = base64.b64decode(guild_info["icon_b64"])
                except Exception as e:
                    logger.warning(f"Failed to decode server icon: {e}")

            if update_kwargs:
                await guild.edit(**update_kwargs)
        except Exception as e:
            logger.warning(f"Failed to update guild settings: {e}")

        # Final Embed Completion
        embed = discord.Embed(
            title="🎉 Server Restoration Complete",
            description=f"Successfully restored structure into **{guild.name}** from `{filename}`.",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.add_field(name="Roles Mapped/Created", value=str(len(role_map)), inline=True)
        embed.add_field(name="Categories Created", value=str(len(category_map)), inline=True)
        embed.add_field(name="Text Channels", value=str(len(text_channels_data)), inline=True)
        embed.add_field(name="Voice Channels", value=str(len(voice_channels_data)), inline=True)
        embed.add_field(name="Emojis Restored", value=str(restored_emojis_count), inline=True)

        await interaction.followup.send(embed=embed)
        logger.info(f"Restoration finished successfully for guild {guild.id}")

    except Exception as e:
        logger.error(f"Restore process encountered a critical error: {e}", exc_info=True)
        await interaction.followup.send(f"❌ Restoration aborted due to error: `{e}`")


# ==========================================
# BOT RUNNER
# ==========================================

def main():
    if not TOKEN or TOKEN == "your_bot_token_here":
        logger.critical("DISCORD_TOKEN environment variable is missing or set to placeholder in .env file.")
        print("\n[ERROR] Please set your DISCORD_TOKEN in the .env file before running.\n")
        sys.exit(1)
        
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
