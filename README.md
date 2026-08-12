# Discord Server Backup & Restore Bot (`discord.py` v2)

A complete, production-ready Discord bot written in Python using `discord.py` (v2 Slash Commands). It provides a full two-step backup and restore system for Discord servers, archiving complete server structures, roles, permission overwrites, channel categories, text/voice channels, custom emojis, and channel message histories.

---

## 🌟 Core Features

1. **Two-Step Backup System**:
   - `/backup-create`: Scrapes the source server structure and saves it to `backup_<guild_id>.json`.
   - `/backup-load`: Reads the JSON file and recreates the server structure in the target server.
2. **Comprehensive Server Data Export**:
   - **Server Settings**: Server name, base64-encoded icon, verification level, notification settings, AFK timeout/channel.
   - **Roles**: Name, hex colors, display settings (hoist/mentionable), bitwise permission integers, and hierarchy preservation (skips managed bot roles).
   - **Categories**: Name, position, and role permission overwrites.
   - **Text & Voice Channels**: Name, topic, slowmode delay, NSFW flag, bitrate, user limit, category binding, and role permission overwrites.
   - **Custom Emojis**: Downloads custom emojis and embeds them as base64 image data into the JSON file so restoration works even if URLs expire.
   - **Message Archiving**: Archives up to the last 50 messages per text channel (author, timestamp, text, attachments).
3. **Safety & Security**:
   - **Permission Verification**: Restricted exclusively to users with **Administrator** permissions (`@app_commands.checks.has_permissions(administrator=True)`).
   - **Rate Limit Protection**: Built-in asynchronous delays (`asyncio.sleep`) between role and channel creation to prevent Discord HTTP 429 rate limits.
   - **Error Handling**: Full `try-except` error handling around all API operations with detailed logging.

---

## 🛠️ Prerequisites & Discord Bot Setup

### 1. Create a Discord Bot
1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application**, name your bot, and save.
3. Navigate to the **Bot** tab on the left sidebar.
4. Click **Reset Token** (or Copy Token) and copy your Bot Token.

### 2. Enable Privileged Gateway Intents
Under the **Bot** tab in the Developer Portal, scroll down to **Privileged Gateway Intents** and enable:
- ✅ **Server Members Intent** (required to inspect role structures)
- ✅ **Message Content Intent** (required to archive text channel messages)

### 3. Invite Bot to Your Servers
1. Go to **OAuth2** -> **URL Generator**.
2. Select the `bot` and `applications.commands` scopes.
3. Under **Bot Permissions**, select **Administrator**.
4. Copy the generated URL and use it to invite the bot to both your source and target servers.

---

## 📦 Installation & Setup

### 1. Clone or Download Repository
Ensure Python **3.8+** is installed on your machine.

```bash
cd github2
```

### 2. Install Dependencies
Install required packages using `pip`:

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env` and insert your Discord Bot Token:

```bash
cp .env.example .env
```

Edit `.env`:
```env
DISCORD_TOKEN=your_bot_token_here
```

### 4. Run the Bot
Start the bot using Python:

```bash
python bot.py
```

Upon starting, you will see output in your console indicating that slash commands have been synced:
```text
2026-08-12 01:40:00 [INFO] discord_backup: Logged in as BackupBot#1234 (ID: 123456789012345678)
2026-08-12 01:40:01 [INFO] discord_backup: Synced 2 slash command(s) globally.
```

---

## 💻 Command Usage

### 1. Create a Server Backup (`/backup-create`)
Exports the current server configuration and saves it locally on the bot machine as `backup_<guild_id>.json`.

**Command:**
```
/backup-create [include_messages: True/False]
```

- **`include_messages`** *(Optional)*: `True` by default. Archives the last 50 messages per text channel. Set to `False` for faster, structural-only backups.

**Example Response:**
```
✅ Backup Created Successfully
Exported complete structure for My Community Server into backup_123456789012345678.json.

Roles: 12 | Categories: 4 | Text Channels: 15 | Voice Channels: 6 | Custom Emojis: 8 | Archived Messages: 450
```

---

### 2. Restore Server Structure (`/backup-load`)
Recreates roles, categories, channels, permissions, custom emojis, and server settings in the target server.

**Command:**
```
/backup-load guild_id:<SOURCE_GUILD_ID_OR_FILENAME>
```

**Parameters:**
- **`guild_id`**: The source server's Guild ID (e.g. `123456789012345678`) or exact backup filename (e.g. `backup_123456789012345678.json`).

**Example Response:**
```
🔄 Starting restoration process from backup_123456789012345678.json...
[Stage 1/5] Restoring Roles...
[Stage 2/5] Restoring Categories...
[Stage 3/5] Restoring Text Channels...
[Stage 4/5] Restoring Voice Channels...
[Stage 5/5] Restoring Custom Emojis...

🎉 Server Restoration Complete
Successfully restored structure into Target Server from backup_123456789012345678.json.
```

---

## 📁 File Structure

```text
github2/
├── bot.py           # Main Discord bot implementation (Slash commands & logic)
├── requirements.txt # Python dependencies (discord.py, aiohttp, python-dotenv)
├── .env.example     # Environment variable configuration template
├── bot.log          # Runtime log file
└── README.md        # Comprehensive documentation
```

---

## 🛡️ Technical Details & API Safety

- **Permission Overwrite Translation**: When channels and categories are restored, original role permission overrides are mapped dynamically to the target server's newly created role objects using bitwise permission integers (`discord.PermissionOverwrite.from_pair`).
- **Base64 Emoji & Icon Encoding**: Custom emojis and server icons are converted directly into base64 image strings during `/backup-create`, preventing broken restorations if original CDN links expire.
- **Rate Limit Delay**: Role, category, channel, and emoji creation steps are separated by an `asyncio.sleep` delay (`0.5s` for channels/roles, `1.0s` for emojis) to ensure full compliance with Discord's API rate limits.
