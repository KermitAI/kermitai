from datetime import timedelta


def is_due(member, role_id, days, enabled_at, now):
    """Check cached eligibility; the caller must refresh before kicking."""
    if member.bot or member.id == member.guild.owner_id:
        return False
    if member.guild_permissions.administrator or member.joined_at is None:
        return False
    if any(role.id == role_id for role in member.roles):
        return False
    me = member.guild.me
    if me is None or not me.guild_permissions.kick_members:
        return False
    if member.top_role >= me.top_role:
        return False
    return now >= max(member.joined_at, enabled_at) + timedelta(days=days)
