# Telegram VC Music Bot

Commands:
- `/play song name`
- `/pause`
- `/resume`
- `/skip`
- `/queue`
- `/stop`
- `/broadcast message` (ADMIN ONLY)

## Railway Variables

Add:
- `API_ID`
- `API_HASH`
- `BOT_TOKEN`
- `SESSION_STRING`
- `ADMIN_ID` = your Telegram numeric user ID

The bot stores groups that send messages to it in `groups.db`, so broadcast targets survive restarts when Railway persistent storage is available. The bot must remain a member of a group to broadcast there.
