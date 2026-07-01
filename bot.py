import asyncio
import json
import os
import time
from collections import defaultdict, deque
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import discord
from discord.ext import commands, tasks


PREFIX = "$"

CONTROL_ROLE_ID = 1521554937266311382
QUARANTINE_ROLE_ID = 1472343485712433199
ANTINUKE_LOG_CHANNEL_ID = 1519446896664641657

DATA_DIR = Path(os.getenv("ANTINUKE_DATA_DIR", "antinuke_data"))
ASSET_DIR = DATA_DIR / "assets"
BACKUP_FILE = DATA_DIR / "backup.json"
CONFIG_FILE = DATA_DIR / "config.json"
LOG_FILE = DATA_DIR / "logs.json"
ROLE_CACHE_FILE = DATA_DIR / "role_cache.json"

AUDIT_LOOKBACK_SECONDS = 12
QUARANTINE_REASON = "Anti-Nuke: unauthorized protected action"
MAX_LOGS = 500

DANGEROUS_PERMISSION_NAMES = {
    "administrator",
    "manage_roles",
    "manage_channels",
    "ban_members",
    "kick_members",
    "manage_webhooks",
    "manage_guild",
    "mention_everyone",
}

SERVER_CHANNEL_TEMPLATE = [
    {
        "category": "IMPORTANT",
        "channels": [
            ("text", "📢┃announcements"),
            ("text", "📜┃rules"),
            ("text", "🎫┃support"),
            ("text", "🚀┃server-boosts"),
            ("text", "🎉┃giveaways"),
            ("text", "🔗┃joins"),
        ],
    },
    {
        "category": "Listings",
        "channels": [
            ("text", "👑┃owners-listing"),
            ("text", "⭐┃co-listing"),
        ],
    },
    {
        "category": "SERVICES",
        "channels": [
            ("text", "🛡┃tos"),
            ("text", "💎┃mm-request"),
            ("text", "🛍┃mutation-forges"),
            ("text", "✅┃mutation-vouches"),
        ],
    },
    {
        "category": "TEXT CHANNELS",
        "channels": [
            ("text", "💬┃social"),
            ("text", "🛒┃marketplace"),
            ("text", "🏷┃mm-listings"),
            ("text", "✅┃vouches"),
        ],
    },
    {
        "category": "STOCKS",
        "channels": [
            ("text", "🌱┃seeds"),
            ("text", "🌦┃weather"),
            ("text", "📦┃props"),
            ("text", "⚙┃gear"),
        ],
    },
    {"category": "INDEX TICKETS", "channels": []},
    {
        "category": "READ",
        "channels": [
            ("text", "⌁・main-method"),
            ("text", "⌁・auto-adv"),
            ("text", "⌁・main-guide"),
            ("text", "⌁・tutorial-guide"),
        ],
    },
    {
        "category": "IMPORTANT",
        "channels": [
            ("text", "⌁・announcements"),
            ("text", "⌁・updates"),
            ("text", "⌁・guide"),
            ("text", "⌁・rules"),
            ("text", "⌁・events"),
        ],
    },
    {
        "category": "STAFF",
        "channels": [
            ("text", "⌁・verify"),
            ("text", "⌁・staff-chat"),
            ("text", "⌁・cmds"),
            ("text", "⌁・staff-trading"),
            ("text", "⌁・staff-giveaways"),
            ("text", "⌁・suggestions"),
        ],
    },
    {"category": "TRAININGS", "channels": []},
    {"category": "ROLE TICKETS", "channels": []},
    {
        "category": "RECRUITS",
        "channels": [
            ("text", "⌁・recruit-guide"),
            ("text", "⌁・recruit-rewards"),
            ("text", "⌁・recruit-logs"),
        ],
    },
    {
        "category": "RATES",
        "channels": [
            ("text", "⌁・adopt-me-rates"),
            ("text", "⌁・mm2-rates"),
            ("text", "⌁・sab-rates"),
        ],
    },
    {
        "category": "EXTRA",
        "channels": [
            ("text", "⌁・middleman-commands"),
            ("text", "⌁・personal-mm"),
            ("text", "⌁・report-users"),
            ("text", "⌁・moderation-logs"),
        ],
    },
    {
        "category": "────────────",
        "channels": [
            ("voice", "VC1"),
            ("voice", "VC2"),
        ],
    },
    {
        "category": "view logs",
        "channels": [
            ("text", "⌁・transcripts"),
            ("text", "⌁・ban-logs"),
            ("text", "⌁・promotion-demotion-logs"),
            ("text", "⌁・antinuke-logs"),
        ],
    },
]


intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.moderation = True
intents.messages = True
intents.message_content = True
intents.emojis_and_stickers = True
intents.webhooks = True
intents.voice_states = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

state: dict[str, Any] = {
    "config": {},
    "backup": {},
    "logs": [],
    "role_cache": {},
    "recent_messages": defaultdict(lambda: defaultdict(lambda: deque(maxlen=8))),
    "recent_mod_actions": defaultdict(lambda: defaultdict(lambda: deque(maxlen=10))),
    "restoring": set(),
}


DEFAULT_CONFIG = {
    "enabled": True,
    "spam_window_seconds": 8,
    "mass_action_window_seconds": 10,
    "mass_action_threshold": 3,
    "duplicate_message_threshold": 4,
    "message_spam_threshold": 6,
    "invite_spam_threshold": 2,
    "protections": {
        "members": True,
        "roles": True,
        "channels": True,
        "threads": True,
        "webhooks": True,
        "emojis": True,
        "stickers": True,
        "server": True,
        "bots": True,
        "mentions": True,
        "spam": True,
        "voice": True,
    },
    "whitelist": [],
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_data_files() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
    if not BACKUP_FILE.exists():
        BACKUP_FILE.write_text("{}", encoding="utf-8")
    if not LOG_FILE.exists():
        LOG_FILE.write_text("[]", encoding="utf-8")
    if not ROLE_CACHE_FILE.exists():
        ROLE_CACHE_FILE.write_text("{}", encoding="utf-8")


def load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return deepcopy(fallback)


def save_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def guild_key(guild_id: int) -> str:
    return str(guild_id)


def get_config(guild: discord.Guild) -> dict[str, Any]:
    key = guild_key(guild.id)
    if key not in state["config"]:
        cfg = deepcopy(DEFAULT_CONFIG)
        cfg["whitelist"] = []
        state["config"][key] = cfg
        save_json(CONFIG_FILE, state["config"])
    merged = deepcopy(DEFAULT_CONFIG)
    merged.update(state["config"][key])
    merged["protections"].update(state["config"][key].get("protections", {}))
    return merged


def set_config(guild: discord.Guild, config: dict[str, Any]) -> None:
    state["config"][guild_key(guild.id)] = config
    save_json(CONFIG_FILE, state["config"])


def protection_enabled(guild: discord.Guild, name: str) -> bool:
    cfg = get_config(guild)
    return bool(cfg.get("enabled") and cfg.get("protections", {}).get(name, False))


def is_bot_or_owner(member: discord.Member) -> bool:
    return member.bot or member.id == member.guild.owner_id


def is_whitelisted(member: Optional[discord.Member]) -> bool:
    if member is None:
        return False
    if is_bot_or_owner(member):
        return True
    cfg = get_config(member.guild)
    return member.id in set(map(int, cfg.get("whitelist", [])))


def can_use_commands(member: discord.Member) -> bool:
    if is_whitelisted(member):
        return True
    return any(role.id == CONTROL_ROLE_ID for role in member.roles)


async def command_check(ctx: commands.Context) -> bool:
    if not isinstance(ctx.author, discord.Member):
        return False
    if can_use_commands(ctx.author):
        return True
    await ctx.reply("You are not allowed to use Anti-Nuke commands.", mention_author=False)
    return False


bot.add_check(command_check)


def serialise_overwrites(channel: discord.abc.GuildChannel) -> dict[str, Any]:
    overwrites: dict[str, Any] = {}
    for target, overwrite in channel.overwrites.items():
        allow, deny = overwrite.pair()
        target_type = "role" if isinstance(target, discord.Role) else "member"
        overwrites[str(target.id)] = {
            "type": target_type,
            "allow": allow.value,
            "deny": deny.value,
        }
    return overwrites


def deserialise_overwrites(guild: discord.Guild, data: dict[str, Any]) -> dict[Any, discord.PermissionOverwrite]:
    overwrites: dict[Any, discord.PermissionOverwrite] = {}
    for target_id, payload in data.items():
        target = guild.get_role(int(target_id)) if payload.get("type") == "role" else guild.get_member(int(target_id))
        if target is None:
            continue
        overwrites[target] = discord.PermissionOverwrite.from_pair(
            discord.Permissions(int(payload.get("allow", 0))),
            discord.Permissions(int(payload.get("deny", 0))),
        )
    return overwrites


def role_to_data(role: discord.Role) -> dict[str, Any]:
    return {
        "id": role.id,
        "name": role.name,
        "permissions": role.permissions.value,
        "colour": role.colour.value,
        "hoist": role.hoist,
        "mentionable": role.mentionable,
        "position": role.position,
        "managed": role.managed,
    }


def channel_to_data(channel: discord.abc.GuildChannel) -> dict[str, Any]:
    base = {
        "id": channel.id,
        "name": channel.name,
        "type": str(channel.type),
        "position": channel.position,
        "category_id": channel.category_id,
        "overwrites": serialise_overwrites(channel),
    }
    if isinstance(channel, discord.TextChannel):
        base.update(
            {
                "topic": channel.topic,
                "nsfw": channel.nsfw,
                "slowmode_delay": channel.slowmode_delay,
                "default_auto_archive_duration": channel.default_auto_archive_duration,
            }
        )
    elif isinstance(channel, discord.VoiceChannel):
        base.update(
            {
                "bitrate": channel.bitrate,
                "user_limit": channel.user_limit,
                "rtc_region": str(channel.rtc_region) if channel.rtc_region else None,
            }
        )
    elif isinstance(channel, discord.StageChannel):
        base.update(
            {
                "bitrate": channel.bitrate,
                "user_limit": channel.user_limit,
                "rtc_region": str(channel.rtc_region) if channel.rtc_region else None,
                "topic": channel.topic,
            }
        )
    elif isinstance(channel, discord.ForumChannel):
        base.update(
            {
                "topic": channel.topic,
                "nsfw": channel.nsfw,
                "slowmode_delay": channel.slowmode_delay,
                "default_auto_archive_duration": channel.default_auto_archive_duration,
            }
        )
    return base


def emoji_to_data(emoji: discord.Emoji) -> dict[str, Any]:
    return {"id": emoji.id, "name": emoji.name, "animated": emoji.animated, "url": str(emoji.url)}


def sticker_to_data(sticker: discord.GuildSticker) -> dict[str, Any]:
    return {
        "id": sticker.id,
        "name": sticker.name,
        "description": sticker.description,
        "emoji": sticker.emoji,
        "format": str(sticker.format),
        "url": str(sticker.url),
    }


def guild_settings_to_data(guild: discord.Guild) -> dict[str, Any]:
    return {
        "name": guild.name,
        "verification_level": guild.verification_level.name,
        "default_notifications": guild.default_notifications.name,
        "explicit_content_filter": guild.explicit_content_filter.name,
        "afk_channel_id": guild.afk_channel.id if guild.afk_channel else None,
        "afk_timeout": guild.afk_timeout,
        "system_channel_id": guild.system_channel.id if guild.system_channel else None,
        "rules_channel_id": guild.rules_channel.id if guild.rules_channel else None,
        "public_updates_channel_id": guild.public_updates_channel.id if guild.public_updates_channel else None,
        "preferred_locale": str(guild.preferred_locale),
        "icon_file": None,
        "banner_file": None,
        "splash_file": None,
    }


async def save_asset(asset: Optional[discord.Asset], path: Path) -> Optional[str]:
    if asset is None:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(await asset.read())
        return str(path)
    except (discord.HTTPException, OSError):
        return None


async def guild_settings_backup(guild: discord.Guild) -> dict[str, Any]:
    data = guild_settings_to_data(guild)
    folder = ASSET_DIR / str(guild.id)
    data["icon_file"] = await save_asset(guild.icon, folder / "icon.bin")
    data["banner_file"] = await save_asset(guild.banner, folder / "banner.bin")
    data["splash_file"] = await save_asset(guild.splash, folder / "splash.bin")
    return data


async def make_backup(guild: discord.Guild) -> None:
    key = guild_key(guild.id)
    state["backup"][key] = {
        "created_at": utc_now(),
        "guild": await guild_settings_backup(guild),
        "roles": [role_to_data(role) for role in guild.roles if role.name != "@everyone"],
        "channels": [channel_to_data(channel) for channel in guild.channels],
        "emojis": [emoji_to_data(emoji) for emoji in guild.emojis],
        "stickers": [sticker_to_data(sticker) for sticker in guild.stickers],
    }
    save_json(BACKUP_FILE, state["backup"])
    cache_role_assignments(guild)


def cache_role_assignments(guild: discord.Guild) -> None:
    key = guild_key(guild.id)
    state["role_cache"][key] = {
        str(member.id): [role.id for role in member.roles if role.name != "@everyone" and not role.managed]
        for member in guild.members
    }
    save_json(ROLE_CACHE_FILE, state["role_cache"])


async def send_log(guild: discord.Guild, entry: dict[str, Any]) -> None:
    state["logs"].append(entry)
    state["logs"] = state["logs"][-MAX_LOGS:]
    save_json(LOG_FILE, state["logs"])

    channel = guild.get_channel(ANTINUKE_LOG_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        channel = discord.utils.get(guild.text_channels, name="⌁・antinuke-logs") or discord.utils.get(guild.text_channels, name="antinuke-logs")
    if not isinstance(channel, discord.TextChannel):
        return

    embed = discord.Embed(
        title="Anti-Nuke Detection",
        colour=discord.Colour.red() if entry.get("punishment") else discord.Colour.orange(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="User", value=entry.get("user", "Unknown"), inline=True)
    embed.add_field(name="Action", value=entry.get("action", "Unknown"), inline=True)
    embed.add_field(name="Target", value=str(entry.get("target", "Unknown"))[:1024], inline=False)
    embed.add_field(name="Punishment", value=entry.get("punishment", "None"), inline=True)
    embed.add_field(name="Restoration", value=entry.get("restoration", "Not attempted"), inline=True)
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass


async def log_event(
    guild: discord.Guild,
    user: Any,
    action: str,
    target: str,
    punishment: str = "None",
    restoration: str = "Not attempted",
) -> None:
    await send_log(
        guild,
        {
            "time": utc_now(),
            "guild_id": guild.id,
            "user_id": getattr(user, "id", None),
            "user": f"{user} ({getattr(user, 'id', 'unknown')})" if user else "Unknown",
            "action": action,
            "target": target,
            "punishment": punishment,
            "restoration": restoration,
        },
    )


async def find_audit_user(
    guild: discord.Guild,
    action: discord.AuditLogAction,
    target_id: Optional[int] = None,
    limit: int = 8,
) -> Optional[discord.Member]:
    now = datetime.now(timezone.utc)
    try:
        async for entry in guild.audit_logs(limit=limit, action=action):
            if (now - entry.created_at).total_seconds() > AUDIT_LOOKBACK_SECONDS:
                continue
            if target_id is not None and getattr(entry.target, "id", None) != target_id:
                continue
            member = guild.get_member(entry.user.id) if entry.user else None
            if member:
                return member
    except (discord.Forbidden, discord.HTTPException):
        return None
    return None


async def quarantine(member: Optional[discord.Member], reason: str = QUARANTINE_REASON) -> str:
    if member is None:
        return "Skipped: offender unknown"
    if is_whitelisted(member):
        return "Skipped: whitelisted"

    guild = member.guild
    quarantine_role = guild.get_role(QUARANTINE_ROLE_ID)
    if quarantine_role is None:
        return "Failed: quarantine role missing"

    cache_role_assignments(guild)
    removable = [
        role
        for role in member.roles
        if role.name != "@everyone"
        and not role.managed
        and role != quarantine_role
        and role < guild.me.top_role
    ]
    try:
        await member.remove_roles(*removable, reason=reason)
        await member.add_roles(quarantine_role, reason=reason)
        return "Quarantined"
    except discord.Forbidden:
        return "Failed: missing role hierarchy or permissions"
    except discord.HTTPException as exc:
        return f"Failed: {exc}"


def dangerous_permissions(permissions: discord.Permissions) -> set[str]:
    return {name for name, value in permissions if value and name in DANGEROUS_PERMISSION_NAMES}


async def strip_dangerous_permissions(role: discord.Role) -> str:
    if role.managed or role >= role.guild.me.top_role:
        return "Skipped: role is managed or above bot"
    perms = discord.Permissions(role.permissions.value)
    changed = False
    for name in DANGEROUS_PERMISSION_NAMES:
        if getattr(perms, name, False):
            setattr(perms, name, False)
            changed = True
    if not changed:
        return "No dangerous permissions found"
    try:
        await role.edit(permissions=perms, reason="Anti-Nuke: remove dangerous permissions")
        return "Removed dangerous permissions"
    except discord.HTTPException as exc:
        return f"Failed: {exc}"


async def restore_role(guild: discord.Guild, data: dict[str, Any]) -> str:
    existing = guild.get_role(int(data["id"]))
    permissions = discord.Permissions(int(data["permissions"]))
    try:
        if existing and existing < guild.me.top_role and not existing.managed:
            await existing.edit(
                name=data["name"],
                permissions=permissions,
                colour=discord.Colour(int(data["colour"])),
                hoist=bool(data["hoist"]),
                mentionable=bool(data["mentionable"]),
                reason="Anti-Nuke restore role",
            )
            return "Restored role settings"
        new_role = await guild.create_role(
            name=data["name"],
            permissions=permissions,
            colour=discord.Colour(int(data["colour"])),
            hoist=bool(data["hoist"]),
            mentionable=bool(data["mentionable"]),
            reason="Anti-Nuke restore deleted role",
        )
        await new_role.edit(position=min(int(data["position"]), guild.me.top_role.position - 1), reason="Anti-Nuke restore role position")
        return f"Recreated role as {new_role.id}"
    except discord.HTTPException as exc:
        return f"Failed: {exc}"


async def restore_channel(guild: discord.Guild, data: dict[str, Any]) -> str:
    overwrites = deserialise_overwrites(guild, data.get("overwrites", {}))
    category = guild.get_channel(int(data["category_id"])) if data.get("category_id") else None
    existing = guild.get_channel(int(data["id"]))
    kwargs = {
        "name": data["name"],
        "overwrites": overwrites,
        "category": category if isinstance(category, discord.CategoryChannel) else None,
        "reason": "Anti-Nuke restore channel",
    }
    try:
        if existing:
            await existing.edit(**kwargs)
            if hasattr(existing, "position"):
                await existing.edit(position=int(data.get("position", existing.position)), reason="Anti-Nuke restore channel position")
            return "Restored channel settings"

        channel_type = data.get("type")
        if channel_type == "category":
            created = await guild.create_category(name=data["name"], overwrites=overwrites, reason="Anti-Nuke restore category")
        elif channel_type == "voice":
            created = await guild.create_voice_channel(
                bitrate=int(data.get("bitrate") or 64000),
                user_limit=int(data.get("user_limit") or 0),
                **kwargs,
            )
        elif channel_type == "stage_voice":
            created = await guild.create_stage_channel(
                topic=data.get("topic"),
                bitrate=int(data.get("bitrate") or 64000),
                user_limit=int(data.get("user_limit") or 0),
                **kwargs,
            )
        elif channel_type == "forum":
            create_forum = getattr(guild, "create_forum", None) or getattr(guild, "create_forum_channel", None)
            if create_forum is None:
                return "Failed: installed discord.py does not expose forum creation"
            created = await create_forum(
                topic=data.get("topic"),
                nsfw=bool(data.get("nsfw", False)),
                slowmode_delay=int(data.get("slowmode_delay") or 0),
                default_auto_archive_duration=int(data.get("default_auto_archive_duration") or 1440),
                **kwargs,
            )
        else:
            created = await guild.create_text_channel(
                topic=data.get("topic"),
                nsfw=bool(data.get("nsfw", False)),
                slowmode_delay=int(data.get("slowmode_delay") or 0),
                default_auto_archive_duration=int(data.get("default_auto_archive_duration") or 1440),
                **kwargs,
            )
        await created.edit(position=int(data.get("position", created.position)), reason="Anti-Nuke restore channel position")
        return f"Recreated channel as {created.id}"
    except discord.HTTPException as exc:
        return f"Failed: {exc}"


async def delete_all_channels(guild: discord.Guild) -> list[str]:
    results = []
    channels = sorted(guild.channels, key=lambda channel: isinstance(channel, discord.CategoryChannel))
    for channel in channels:
        try:
            await channel.delete(reason="Anti-Nuke restore: full channel reset")
            results.append(f"Deleted {channel.name}")
            await asyncio.sleep(0.35)
        except discord.HTTPException as exc:
            results.append(f"Failed deleting {channel.name}: {exc}")
    return results


async def restore_template_channels(guild: discord.Guild) -> list[str]:
    results = []
    for category_block in SERVER_CHANNEL_TEMPLATE:
        try:
            category = await guild.create_category(
                category_block["category"],
                reason="Anti-Nuke restore: recreate template category",
            )
            results.append(f"Created category {category.name}")
            await asyncio.sleep(0.35)
        except discord.HTTPException as exc:
            results.append(f"Failed creating category {category_block['category']}: {exc}")
            continue

        for channel_type, channel_name in category_block["channels"]:
            try:
                if channel_type == "voice":
                    created = await guild.create_voice_channel(
                        channel_name,
                        category=category,
                        reason="Anti-Nuke restore: recreate template voice channel",
                    )
                else:
                    created = await guild.create_text_channel(
                        channel_name,
                        category=category,
                        reason="Anti-Nuke restore: recreate template text channel",
                    )
                results.append(f"Created {created.name}")
                await asyncio.sleep(0.35)
            except discord.HTTPException as exc:
                results.append(f"Failed creating {channel_name}: {exc}")
    return results


async def full_channel_template_restore(guild: discord.Guild) -> list[str]:
    results = ["Starting full channel reset from screenshot template"]
    results.extend(await delete_all_channels(guild))
    results.extend(await restore_template_channels(guild))
    return results


def find_backup_item(guild: discord.Guild, section: str, item_id: int) -> Optional[dict[str, Any]]:
    backup = state["backup"].get(guild_key(guild.id), {})
    for item in backup.get(section, []):
        if int(item.get("id", 0)) == int(item_id):
            return item
    return None


async def restore_guild_settings(guild: discord.Guild) -> str:
    backup = state["backup"].get(guild_key(guild.id), {}).get("guild")
    if not backup:
        return "Failed: no guild backup"
    kwargs: dict[str, Any] = {}
    enum_maps = {
        "verification_level": discord.VerificationLevel,
        "default_notifications": discord.NotificationLevel,
        "explicit_content_filter": discord.ContentFilter,
    }
    for key, enum_type in enum_maps.items():
        value = backup.get(key)
        if value and hasattr(enum_type, value):
            kwargs[key] = getattr(enum_type, value)
    for key in ("afk_channel_id", "system_channel_id", "rules_channel_id", "public_updates_channel_id"):
        channel_id = backup.get(key)
        kwargs[key[:-3] if key.endswith("_id") else key] = guild.get_channel(channel_id) if channel_id else None
    kwargs["name"] = backup.get("name", guild.name)
    kwargs["afk_timeout"] = int(backup.get("afk_timeout", guild.afk_timeout))
    for asset_key, edit_key in (("icon_file", "icon"), ("banner_file", "banner"), ("splash_file", "splash")):
        asset_path = backup.get(asset_key)
        if asset_path and Path(asset_path).exists():
            kwargs[edit_key] = Path(asset_path).read_bytes()
    try:
        await guild.edit(reason="Anti-Nuke restore server settings", **kwargs)
        return "Restored server settings"
    except discord.HTTPException as exc:
        return f"Failed: {exc}"


async def punish_and_log(
    guild: discord.Guild,
    offender: Optional[discord.Member],
    action: str,
    target: str,
    restoration: str = "Not attempted",
) -> None:
    punishment = await quarantine(offender)
    await log_event(guild, offender, action, target, punishment, restoration)


async def handle_mass_action(member: Optional[discord.Member], action: str) -> bool:
    if member is None or is_whitelisted(member):
        return False
    cfg = get_config(member.guild)
    window = float(cfg.get("mass_action_window_seconds", 10))
    threshold = int(cfg.get("mass_action_threshold", 3))
    now = time.monotonic()
    bucket = state["recent_mod_actions"][member.guild.id][(member.id, action)]
    bucket.append(now)
    while bucket and now - bucket[0] > window:
        bucket.popleft()
    return len(bucket) >= threshold


async def delete_created_channel(channel: discord.abc.GuildChannel) -> str:
    try:
        await channel.delete(reason="Anti-Nuke: unauthorized channel creation")
        return "Deleted created channel"
    except discord.HTTPException as exc:
        return f"Failed: {exc}"


async def delete_created_role(role: discord.Role) -> str:
    if role >= role.guild.me.top_role or role.managed:
        return "Skipped: role is managed or above bot"
    try:
        await role.delete(reason="Anti-Nuke: unauthorized role creation")
        return "Deleted created role"
    except discord.HTTPException as exc:
        return f"Failed: {exc}"


@bot.event
async def on_ready() -> None:
    ensure_data_files()
    state["config"] = load_json(CONFIG_FILE, {})
    state["backup"] = load_json(BACKUP_FILE, {})
    state["logs"] = load_json(LOG_FILE, [])
    state["role_cache"] = load_json(ROLE_CACHE_FILE, {})
    for guild in bot.guilds:
        await make_backup(guild)
    if not backup_loop.is_running():
        backup_loop.start()
    print(f"Logged in as {bot.user} ({bot.user.id})")


@tasks.loop(minutes=5)
async def backup_loop() -> None:
    for guild in bot.guilds:
        await make_backup(guild)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member) -> None:
    if before.roles != after.roles:
        cache_role_assignments(after.guild)
    if not protection_enabled(after.guild, "members"):
        return
    if before.timed_out_until != after.timed_out_until and after.timed_out_until:
        offender = await find_audit_user(after.guild, discord.AuditLogAction.member_update, after.id)
        if offender and not is_whitelisted(offender):
            await punish_and_log(after.guild, offender, "Timeout Member", str(after), "Timeout remains; Discord does not expose safe automatic reversal in every case")

    added_roles = [role for role in after.roles if role not in before.roles]
    for role in added_roles:
        bad = dangerous_permissions(role.permissions)
        if not bad:
            continue
        offender = await find_audit_user(after.guild, discord.AuditLogAction.member_role_update, after.id)
        if offender and not is_whitelisted(offender):
            try:
                await after.remove_roles(role, reason="Anti-Nuke: dangerous role grant")
                restoration = f"Removed dangerous role grant: {role.name}"
            except discord.HTTPException as exc:
                restoration = f"Failed: {exc}"
            await punish_and_log(after.guild, offender, "Give dangerous permissions", f"{after} received {role.name}", restoration)


@bot.event
async def on_member_remove(member: discord.Member) -> None:
    if not protection_enabled(member.guild, "members"):
        return
    offender = await find_audit_user(member.guild, discord.AuditLogAction.kick, member.id)
    if offender and not is_whitelisted(offender):
        mass = await handle_mass_action(offender, "kick")
        action = "Mass kicks" if mass else "Kick Member"
        await punish_and_log(member.guild, offender, action, str(member))


@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User) -> None:
    if not protection_enabled(guild, "members"):
        return
    offender = await find_audit_user(guild, discord.AuditLogAction.ban, user.id)
    if offender and not is_whitelisted(offender):
        mass = await handle_mass_action(offender, "ban")
        action = "Mass bans" if mass else "Ban Member"
        try:
            await guild.unban(user, reason="Anti-Nuke: restore banned member")
            restoration = "Unbanned member"
        except discord.HTTPException as exc:
            restoration = f"Failed: {exc}"
        await punish_and_log(guild, offender, action, str(user), restoration)


@bot.event
async def on_member_join(member: discord.Member) -> None:
    if not protection_enabled(member.guild, "bots") or not member.bot:
        return
    offender = await find_audit_user(member.guild, discord.AuditLogAction.bot_add, member.id)
    if offender and not is_whitelisted(offender):
        try:
            await member.kick(reason="Anti-Nuke: unauthorized bot invite")
            restoration = "Kicked invited bot"
        except discord.HTTPException as exc:
            restoration = f"Failed: {exc}"
        await punish_and_log(member.guild, offender, "Invite a bot", str(member), restoration)


@bot.event
async def on_guild_role_create(role: discord.Role) -> None:
    if not protection_enabled(role.guild, "roles"):
        return
    offender = await find_audit_user(role.guild, discord.AuditLogAction.role_create, role.id)
    if offender and not is_whitelisted(offender):
        restoration = await delete_created_role(role)
        action = "Create Administrator role" if role.permissions.administrator else "Create Role"
        await punish_and_log(role.guild, offender, action, role.name, restoration)
    await make_backup(role.guild)


@bot.event
async def on_guild_role_delete(role: discord.Role) -> None:
    if not protection_enabled(role.guild, "roles"):
        return
    offender = await find_audit_user(role.guild, discord.AuditLogAction.role_delete, role.id)
    restoration = "Not attempted"
    data = find_backup_item(role.guild, "roles", role.id)
    if data:
        restoration = await restore_role(role.guild, data)
    if offender and not is_whitelisted(offender):
        await punish_and_log(role.guild, offender, "Delete Role", role.name, restoration)


@bot.event
async def on_guild_role_update(before: discord.Role, after: discord.Role) -> None:
    if not protection_enabled(after.guild, "roles"):
        return
    offender = await find_audit_user(after.guild, discord.AuditLogAction.role_update, after.id)
    if offender and not is_whitelisted(offender):
        data = role_to_data(before)
        restoration = await restore_role(after.guild, data)
        if dangerous_permissions(after.permissions) - dangerous_permissions(before.permissions):
            strip_result = await strip_dangerous_permissions(after)
            restoration = f"{restoration}; {strip_result}"
            action = "Give Administrator" if after.permissions.administrator and not before.permissions.administrator else "Give dangerous permissions"
        else:
            action = "Edit Role"
        await punish_and_log(after.guild, offender, action, after.name, restoration)
    await make_backup(after.guild)


@bot.event
async def on_guild_channel_create(channel: discord.abc.GuildChannel) -> None:
    protection = "voice" if isinstance(channel, discord.VoiceChannel) else "channels"
    if not protection_enabled(channel.guild, protection):
        return
    offender = await find_audit_user(channel.guild, discord.AuditLogAction.channel_create, channel.id)
    if offender and not is_whitelisted(offender):
        restoration = await delete_created_channel(channel)
        if isinstance(channel, discord.CategoryChannel):
            action = "Create Category"
        elif isinstance(channel, discord.VoiceChannel):
            action = "Create Voice Channel"
        else:
            action = "Create Channel"
        await punish_and_log(channel.guild, offender, action, channel.name, restoration)
    await make_backup(channel.guild)


@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel) -> None:
    protection = "voice" if isinstance(channel, discord.VoiceChannel) else "channels"
    if not protection_enabled(channel.guild, protection):
        return
    offender = await find_audit_user(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
    data = find_backup_item(channel.guild, "channels", channel.id)
    restoration = await restore_channel(channel.guild, data) if data else "Failed: no channel backup"
    if offender and not is_whitelisted(offender):
        if isinstance(channel, discord.CategoryChannel):
            action = "Delete Category"
        elif isinstance(channel, discord.VoiceChannel):
            action = "Delete Voice Channel"
        else:
            action = "Delete Channel"
        await punish_and_log(channel.guild, offender, action, channel.name, restoration)


@bot.event
async def on_guild_channel_update(before: discord.abc.GuildChannel, after: discord.abc.GuildChannel) -> None:
    protection = "voice" if isinstance(after, discord.VoiceChannel) else "channels"
    if not protection_enabled(after.guild, protection):
        return
    offender = await find_audit_user(after.guild, discord.AuditLogAction.channel_update, after.id)
    if offender and not is_whitelisted(offender):
        restoration = await restore_channel(after.guild, channel_to_data(before))
        action = "Edit Voice Channel" if isinstance(after, discord.VoiceChannel) else "Edit Channel"
        await punish_and_log(after.guild, offender, action, after.name, restoration)
    await make_backup(after.guild)


@bot.event
async def on_thread_create(thread: discord.Thread) -> None:
    if not protection_enabled(thread.guild, "threads"):
        return
    offender = await find_audit_user(thread.guild, discord.AuditLogAction.thread_create, thread.id)
    if offender and not is_whitelisted(offender):
        try:
            await thread.delete(reason="Anti-Nuke: unauthorized thread creation")
            restoration = "Deleted created thread"
        except discord.HTTPException as exc:
            restoration = f"Failed: {exc}"
        await punish_and_log(thread.guild, offender, "Create Thread", thread.name, restoration)


@bot.event
async def on_thread_delete(thread: discord.Thread) -> None:
    if not protection_enabled(thread.guild, "threads"):
        return
    offender = await find_audit_user(thread.guild, discord.AuditLogAction.thread_delete, thread.id)
    if offender and not is_whitelisted(offender):
        await punish_and_log(thread.guild, offender, "Delete Thread", thread.name, "Cannot reliably restore deleted thread contents")


@bot.event
async def on_thread_update(before: discord.Thread, after: discord.Thread) -> None:
    if not protection_enabled(after.guild, "threads"):
        return
    offender = await find_audit_user(after.guild, discord.AuditLogAction.thread_update, after.id)
    if offender and not is_whitelisted(offender):
        try:
            await after.edit(name=before.name, archived=before.archived, locked=before.locked, reason="Anti-Nuke restore thread")
            restoration = "Restored thread settings"
        except discord.HTTPException as exc:
            restoration = f"Failed: {exc}"
        await punish_and_log(after.guild, offender, "Edit Thread", after.name, restoration)


@bot.event
async def on_webhooks_update(channel: discord.abc.GuildChannel) -> None:
    if not protection_enabled(channel.guild, "webhooks"):
        return
    offender = (
        await find_audit_user(channel.guild, discord.AuditLogAction.webhook_create)
        or await find_audit_user(channel.guild, discord.AuditLogAction.webhook_update)
        or await find_audit_user(channel.guild, discord.AuditLogAction.webhook_delete)
    )
    if offender and not is_whitelisted(offender):
        try:
            hooks = await channel.webhooks()
            for hook in hooks:
                if hook.user and hook.user.id == offender.id:
                    await hook.delete(reason="Anti-Nuke: unauthorized webhook")
            restoration = "Deleted offender-created webhooks when found"
        except discord.HTTPException as exc:
            restoration = f"Failed: {exc}"
        await punish_and_log(channel.guild, offender, "Webhook change", channel.name, restoration)


@bot.event
async def on_guild_emojis_update(guild: discord.Guild, before: list[discord.Emoji], after: list[discord.Emoji]) -> None:
    if not protection_enabled(guild, "emojis"):
        return
    before_ids = {emoji.id for emoji in before}
    after_ids = {emoji.id for emoji in after}
    if len(after_ids) > len(before_ids):
        action = "Create Emoji"
        audit_action = discord.AuditLogAction.emoji_create
    elif len(after_ids) < len(before_ids):
        action = "Delete Emoji"
        audit_action = discord.AuditLogAction.emoji_delete
    else:
        action = "Edit Emoji"
        audit_action = discord.AuditLogAction.emoji_update
    offender = await find_audit_user(guild, audit_action)
    if offender and not is_whitelisted(offender):
        await punish_and_log(guild, offender, action, "Emoji update", "Emoji binary restore requires a saved image file; metadata logged")
    await make_backup(guild)


@bot.event
async def on_guild_stickers_update(guild: discord.Guild, before: list[discord.GuildSticker], after: list[discord.GuildSticker]) -> None:
    if not protection_enabled(guild, "stickers"):
        return
    before_ids = {sticker.id for sticker in before}
    after_ids = {sticker.id for sticker in after}
    if len(after_ids) > len(before_ids):
        action = "Create Sticker"
        audit_action = discord.AuditLogAction.sticker_create
    elif len(after_ids) < len(before_ids):
        action = "Delete Sticker"
        audit_action = discord.AuditLogAction.sticker_delete
    else:
        action = "Edit Sticker"
        audit_action = discord.AuditLogAction.sticker_update
    offender = await find_audit_user(guild, audit_action)
    if offender and not is_whitelisted(offender):
        await punish_and_log(guild, offender, action, "Sticker update", "Sticker binary restore requires a saved file; metadata logged")
    await make_backup(guild)


@bot.event
async def on_guild_update(before: discord.Guild, after: discord.Guild) -> None:
    if not protection_enabled(after, "server"):
        return
    offender = await find_audit_user(after, discord.AuditLogAction.guild_update, after.id)
    if offender and not is_whitelisted(offender):
        restoration = await restore_guild_settings(after)
        await punish_and_log(after, offender, "Server settings changed", after.name, restoration)
    await make_backup(after)


@bot.event
async def on_message(message: discord.Message) -> None:
    if not message.guild or message.author.bot:
        return
    member = message.author if isinstance(message.author, discord.Member) else message.guild.get_member(message.author.id)
    cfg = get_config(message.guild)

    if protection_enabled(message.guild, "mentions") and member and not is_whitelisted(member):
        if message.mention_everyone:
            try:
                await message.delete()
                restoration = "Deleted mention message"
            except discord.HTTPException as exc:
                restoration = f"Failed: {exc}"
            action = "Send @everyone/@here"
            await punish_and_log(message.guild, member, action, f"Message {message.id}", restoration)
            return

    if protection_enabled(message.guild, "spam") and member and not is_whitelisted(member):
        bucket = state["recent_messages"][message.guild.id][member.id]
        now = time.monotonic()
        bucket.append((now, message.content, message.id, message.channel.id))
        window = float(cfg.get("spam_window_seconds", 8))
        while bucket and now - bucket[0][0] > window:
            bucket.popleft()

        content_counts = defaultdict(int)
        invite_count = 0
        for _, content, _, _ in bucket:
            content_counts[content] += 1
            if "discord.gg/" in content.lower() or "discord.com/invite/" in content.lower():
                invite_count += 1

        spam = len(bucket) >= int(cfg.get("message_spam_threshold", 6))
        duplicate = max(content_counts.values() or [0]) >= int(cfg.get("duplicate_message_threshold", 4))
        invite_spam = invite_count >= int(cfg.get("invite_spam_threshold", 2))

        if spam or duplicate or invite_spam:
            deleted = 0
            for _, _, message_id, channel_id in list(bucket):
                channel = message.guild.get_channel(channel_id)
                if isinstance(channel, discord.TextChannel):
                    try:
                        old_message = await channel.fetch_message(message_id)
                        await old_message.delete()
                        deleted += 1
                    except discord.HTTPException:
                        pass
            reason = "Invite spam" if invite_spam else "Duplicate message spam" if duplicate else "Mass message spam"
            await punish_and_log(message.guild, member, reason, f"{deleted} messages deleted", "Deleted spam messages")
            bucket.clear()
            return

    await bot.process_commands(message)


@bot.command(name="on")
async def enable_antinue(ctx: commands.Context) -> None:
    cfg = get_config(ctx.guild)
    cfg["enabled"] = True
    set_config(ctx.guild, cfg)
    await ctx.reply("Anti-Nuke protection is now enabled.", mention_author=False)


@bot.command(name="off")
async def disable_antinue(ctx: commands.Context) -> None:
    cfg = get_config(ctx.guild)
    cfg["enabled"] = False
    set_config(ctx.guild, cfg)
    await ctx.reply("Anti-Nuke protection is now disabled.", mention_author=False)


@bot.group(name="whitelist", invoke_without_command=True)
async def whitelist(ctx: commands.Context) -> None:
    await ctx.reply(f"Use `{PREFIX}whitelist add @user`, `{PREFIX}whitelist remove @user`, or `{PREFIX}whitelist list`.", mention_author=False)


@whitelist.command(name="add")
async def whitelist_add(ctx: commands.Context, member: discord.Member) -> None:
    cfg = get_config(ctx.guild)
    ids = set(map(int, cfg.get("whitelist", [])))
    ids.add(member.id)
    cfg["whitelist"] = sorted(ids)
    set_config(ctx.guild, cfg)
    await ctx.reply(f"Added {member.mention} to the Anti-Nuke whitelist.", mention_author=False)


@whitelist.command(name="remove")
async def whitelist_remove(ctx: commands.Context, member: discord.Member) -> None:
    cfg = get_config(ctx.guild)
    ids = set(map(int, cfg.get("whitelist", [])))
    ids.discard(member.id)
    cfg["whitelist"] = sorted(ids)
    set_config(ctx.guild, cfg)
    await ctx.reply(f"Removed {member.mention} from the Anti-Nuke whitelist.", mention_author=False)


@whitelist.command(name="list")
async def whitelist_list(ctx: commands.Context) -> None:
    cfg = get_config(ctx.guild)
    ids = sorted(set(map(int, cfg.get("whitelist", []))))
    names = []
    for user_id in ids:
        member = ctx.guild.get_member(user_id)
        names.append(member.mention if member else f"`{user_id}`")
    owner = ctx.guild.owner.mention if ctx.guild.owner else f"`{ctx.guild.owner_id}`"
    bot_member = ctx.guild.me.mention if ctx.guild.me else "Anti-Nuke Bot"
    text = ", ".join([owner, bot_member] + names) or "None"
    await ctx.reply(f"Whitelisted users: {text}", mention_author=False)


@bot.command(name="quarantine")
async def manual_quarantine(ctx: commands.Context, member: discord.Member) -> None:
    result = await quarantine(member, reason=f"Manual quarantine by {ctx.author}")
    await log_event(ctx.guild, ctx.author, "Manual quarantine", str(member), result, "Not attempted")
    await ctx.reply(result, mention_author=False)


@bot.command(name="unquarantine")
async def manual_unquarantine(ctx: commands.Context, member: discord.Member) -> None:
    quarantine_role = ctx.guild.get_role(QUARANTINE_ROLE_ID)
    key = guild_key(ctx.guild.id)
    cached_ids = state["role_cache"].get(key, {}).get(str(member.id), [])
    roles = [
        role
        for role_id in cached_ids
        if (role := ctx.guild.get_role(int(role_id))) and role < ctx.guild.me.top_role and not role.managed
    ]
    try:
        if quarantine_role and quarantine_role in member.roles:
            await member.remove_roles(quarantine_role, reason=f"Manual unquarantine by {ctx.author}")
        if roles:
            await member.add_roles(*roles, reason=f"Restore roles after unquarantine by {ctx.author}")
        result = f"Unquarantined {member.mention} and restored {len(roles)} cached roles."
    except discord.HTTPException as exc:
        result = f"Failed: {exc}"
    await log_event(ctx.guild, ctx.author, "Manual unquarantine", str(member), result, "Restored cached roles")
    await ctx.reply(result, mention_author=False)


@bot.command(name="status")
async def status(ctx: commands.Context) -> None:
    cfg = get_config(ctx.guild)
    backup = state["backup"].get(guild_key(ctx.guild.id), {})
    uptime = int(time.monotonic() - bot.start_time)
    enabled = [name for name, value in cfg.get("protections", {}).items() if value]
    embed = discord.Embed(title="Anti-Nuke Status", colour=discord.Colour.green() if cfg["enabled"] else discord.Colour.red())
    embed.add_field(name="Protection", value="Enabled" if cfg["enabled"] else "Disabled", inline=True)
    embed.add_field(name="Backup", value=backup.get("created_at", "No backup yet"), inline=False)
    embed.add_field(name="Enabled protections", value=", ".join(enabled) or "None", inline=False)
    embed.add_field(name="Uptime", value=f"{uptime // 3600}h {(uptime % 3600) // 60}m {uptime % 60}s", inline=True)
    await ctx.reply(embed=embed, mention_author=False)


@bot.command(name="logs")
async def logs(ctx: commands.Context, limit: int = 10) -> None:
    limit = max(1, min(limit, 20))
    guild_logs = [entry for entry in state["logs"] if entry.get("guild_id") == ctx.guild.id][-limit:]
    if not guild_logs:
        await ctx.reply("No Anti-Nuke logs yet.", mention_author=False)
        return
    lines = [
        f"`{entry['time']}` **{entry['action']}** by {entry['user']} -> {entry['punishment']} / {entry['restoration']}"
        for entry in guild_logs
    ]
    await ctx.reply("\n".join(lines)[:1900], mention_author=False)


@bot.command(name="restore")
async def restore(ctx: commands.Context) -> None:
    backup = state["backup"].get(guild_key(ctx.guild.id))
    if not backup:
        await ctx.reply("No backup exists yet.", mention_author=False)
        return

    await ctx.reply(
        "Starting full restore. I will delete every channel, recreate the screenshot layout, then restore roles/settings where possible.",
        mention_author=False,
    )
    results = []
    results.append(await restore_guild_settings(ctx.guild))

    for role_data in sorted(backup.get("roles", []), key=lambda item: item.get("position", 0)):
        if role_data.get("managed"):
            continue
        results.append(await restore_role(ctx.guild, role_data))
        await asyncio.sleep(0.5)

    results.extend(await full_channel_template_restore(ctx.guild))

    await make_backup(ctx.guild)
    summary = "\n".join(f"- {result}" for result in results[-15:])
    finish_message = f"Restore finished. Last results:\n{summary[:1800]}"
    log_channel = discord.utils.get(ctx.guild.text_channels, name="⌁・antinuke-logs") or discord.utils.get(ctx.guild.text_channels, name="antinuke-logs")
    try:
        if isinstance(log_channel, discord.TextChannel):
            await log_channel.send(finish_message)
        else:
            await ctx.author.send(finish_message)
    except discord.HTTPException:
        pass


@bot.group(name="config", invoke_without_command=True)
async def config(ctx: commands.Context) -> None:
    cfg = get_config(ctx.guild)
    lines = [f"Protection: `{'on' if cfg['enabled'] else 'off'}`"]
    lines.extend(f"{name}: `{'on' if value else 'off'}`" for name, value in sorted(cfg["protections"].items()))
    await ctx.reply("\n".join(lines), mention_author=False)


@config.command(name="set")
async def config_set(ctx: commands.Context, protection: str, value: str) -> None:
    protection = protection.lower()
    value = value.lower()
    cfg = get_config(ctx.guild)
    if protection not in cfg["protections"]:
        await ctx.reply(f"Unknown protection. Options: {', '.join(sorted(cfg['protections']))}", mention_author=False)
        return
    if value not in {"on", "off", "true", "false", "enable", "disable", "enabled", "disabled"}:
        await ctx.reply("Value must be on/off.", mention_author=False)
        return
    cfg["protections"][protection] = value in {"on", "true", "enable", "enabled"}
    set_config(ctx.guild, cfg)
    await ctx.reply(f"{protection} protection is now {'enabled' if cfg['protections'][protection] else 'disabled'}.", mention_author=False)


@bot.command(name="help")
async def help_command(ctx: commands.Context) -> None:
    commands_text = (
        f"`{PREFIX}on`, `{PREFIX}off`, `{PREFIX}status`, `{PREFIX}logs [limit]`, `{PREFIX}restore`, "
        f"`{PREFIX}config`, `{PREFIX}config set <protection> <on/off>`, "
        f"`{PREFIX}quarantine @user`, `{PREFIX}unquarantine @user`, "
        f"`{PREFIX}whitelist add/remove/list`"
    )
    await ctx.reply(commands_text, mention_author=False)


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.CheckFailure):
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply(f"Missing argument: `{error.param.name}`", mention_author=False)
    elif isinstance(error, commands.BadArgument):
        await ctx.reply("Bad argument. Use mentions or valid IDs where needed.", mention_author=False)
    else:
        await ctx.reply(f"Command failed: `{error}`", mention_author=False)


async def main() -> None:
    ensure_data_files()
    bot.start_time = time.monotonic()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Set DISCORD_TOKEN in your environment before running the bot.")
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
