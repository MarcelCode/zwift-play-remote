#!/usr/bin/env bash
# Claude Code Notification hook: desktop notification + sound when an agent waits for input.
# Wire it up in ~/.claude/settings.json, see hooks/settings.example.json.
message=$(jq -r '.message // "An agent needs input"')
notify-send --app-name="Claude Code" --urgency=critical "Agent needs input" "$message"
canberra-gtk-play --id=message-new-instant 2>/dev/null &
