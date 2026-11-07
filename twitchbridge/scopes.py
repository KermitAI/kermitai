"""Up-front bundles for the bridge's current and already-planned capabilities."""
BOT_SCOPES = frozenset({
    "user:read:chat", "user:write:chat", "moderator:manage:announcements",
    "moderator:manage:shoutouts", "user:bot",
})
BROADCASTER_SCOPES = frozenset({
    "user:read:chat", "moderation:read", "channel:read:subscriptions", "channel:read:vips",
    "channel:bot", "channel:read:redemptions", "channel:manage:redemptions",
})
