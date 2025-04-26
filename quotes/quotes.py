import discord
from redbot.core import commands, Config, checks
from redbot.core.utils.chat_formatting import pagify
from redbot.core.utils.menus import DEFAULT_CONTROLS, menu
from typing import Optional, List
import asyncio


class Quotes(commands.Cog):
    """Quotes cog for Red-Discordbot.
    
    Send formatted quotes to a configured channel.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=951753852, force_registration=True)
        
        default_guild = {
            "quotes_channel": None,
            "restricted_roles": [],
            "anyone_can_use": True
        }
        
        self.config.register_guild(**default_guild)
    
    @commands.group(name="quoteset")
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def quote_set(self, ctx):
        """Configure the quotes system."""
        pass
    
    @quote_set.command(name="channel")
    async def set_quotes_channel(self, ctx, channel: discord.TextChannel = None):
        """Set the channel where quotes will be sent.
        
        If no channel is specified, quotes will be sent in the channel the command was used.
        """
        if channel is None:
            channel = ctx.channel
        
        await self.config.guild(ctx.guild).quotes_channel.set(channel.id)
        await ctx.send(f"Quotes channel has been set to {channel.mention}.")
    
    @quote_set.command(name="anyone")
    async def set_anyone_can_use(self, ctx, allowed: bool):
        """Set whether anyone can use the quote command.
        
        Use `True` to allow anyone, or `False` to restrict to specific roles.
        """
        await self.config.guild(ctx.guild).anyone_can_use.set(allowed)
        
        if allowed:
            message = "Anyone can now use the quote command."
        else:
            roles = await self.config.guild(ctx.guild).restricted_roles()
            if not roles:
                message = "Only specific roles can use the quote command, but no roles have been added yet. " \
                         "Use `[p]quoteset addrole` to add roles."
            else:
                role_mentions = [f"<@&{role_id}>" for role_id in roles]
                message = f"Only specific roles can use the quote command. Current roles: {', '.join(role_mentions)}"
        
        await ctx.send(message)
    
    @quote_set.command(name="addrole")
    async def add_role(self, ctx, role: discord.Role):
        """Add a role that can use the quote command when anyone_can_use is False."""
        async with self.config.guild(ctx.guild).restricted_roles() as roles:
            if role.id in roles:
                await ctx.send(f"The role {role.name} is already allowed to use the quote command.")
                return
            
            roles.append(role.id)
        
        await ctx.send(f"The role {role.name} can now use the quote command.")
    
    @quote_set.command(name="removerole")
    async def remove_role(self, ctx, role: discord.Role):
        """Remove a role from being able to use the quote command."""
        async with self.config.guild(ctx.guild).restricted_roles() as roles:
            if role.id not in roles:
                await ctx.send(f"The role {role.name} is not in the list of allowed roles.")
                return
            
            roles.remove(role.id)
        
        await ctx.send(f"The role {role.name} can no longer use the quote command.")
    
    @quote_set.command(name="listroles")
    async def list_roles(self, ctx):
        """List all roles that can use the quote command when anyone_can_use is False."""
        roles = await self.config.guild(ctx.guild).restricted_roles()
        
        if not roles:
            await ctx.send("No roles have been set up to use the quote command.")
            return
            
        role_mentions = []
        for role_id in roles:
            role = ctx.guild.get_role(role_id)
            if role:
                role_mentions.append(f"{role.name} (ID: {role.id})")
        
        if not role_mentions:
            await ctx.send("All previously configured roles have been deleted from the server.")
            return
            
        message = "Roles that can use the quote command:\n" + "\n".join(role_mentions)
        
        for page in pagify(message):
            await ctx.send(page)
    
    @quote_set.command(name="settings")
    async def show_settings(self, ctx):
        """Show the current quote settings."""
        config_data = await self.config.guild(ctx.guild).all()
        
        channel_id = config_data["quotes_channel"]
        channel = ctx.guild.get_channel(channel_id) if channel_id else None
        
        anyone_can_use = config_data["anyone_can_use"]
        
        roles = []
        for role_id in config_data["restricted_roles"]:
            role = ctx.guild.get_role(role_id)
            if role:
                roles.append(role.name)
        
        embed = discord.Embed(
            title="Quote System Settings",
            color=discord.Color.orange(),
            description="Current configuration for the quote system."
        )
        
        embed.add_field(
            name="Quotes Channel",
            value=channel.mention if channel else "Not set (will use command channel)",
            inline=False
        )
        
        embed.add_field(
            name="Access Control",
            value="Anyone can use" if anyone_can_use else "Restricted to specific roles",
            inline=False
        )
        
        if roles and not anyone_can_use:
            embed.add_field(
                name="Allowed Roles",
                value=", ".join(roles),
                inline=False
            )
        
        await ctx.send(embed=embed)
    
    async def can_use_command(self, ctx):
        """Check if a user can use the quote command based on guild settings."""
        # Server owner and administrators can always use the command
        if ctx.author.guild_permissions.administrator or ctx.author == ctx.guild.owner:
            return True
            
        config_data = await self.config.guild(ctx.guild).all()
        
        # If anyone can use the command
        if config_data["anyone_can_use"]:
            return True
            
        # Check if the user has any of the allowed roles
        user_roles = [role.id for role in ctx.author.roles]
        for role_id in config_data["restricted_roles"]:
            if role_id in user_roles:
                return True
                
        return False
    
    @commands.command(name="quote")
    @commands.guild_only()
    async def quote(self, ctx, quoted_person: str, *, quote_text: str):
        """Submit a quote to be displayed in the quotes channel.
        
        Example: [p]quote Einstein Energy equals mass times the speed of light squared.
        """
        # Check if the user can use the command
        can_use = await self.can_use_command(ctx)
        if not can_use:
            await ctx.send("You don't have permission to use this command.")
            return
        
        config_data = await self.config.guild(ctx.guild).all()
        
        # Get the channel to send the quote to
        channel_id = config_data["quotes_channel"]
        if channel_id:
            channel = self.bot.get_channel(channel_id)
            if not channel:
                await ctx.send("The configured quotes channel no longer exists. Please set a new one with `[p]quoteset channel`.")
                return
        else:
            channel = ctx.channel
        
        # Create and send the embed
        embed = discord.Embed(
            description=f"### {quote_text}\n*~ {quoted_person}*\n\n-# Submitted by: {ctx.author.mention}",
            color=discord.Color.orange()
        )
        
        quote_message = await channel.send(embed=embed)
        
        # Add the star reaction
        try:
            await quote_message.add_reaction(":star:")
        except discord.HTTPException:
            pass  # If adding the reaction fails, we'll just continue without it
        
        # If the quote was sent to a different channel, confirm to the user
        if channel != ctx.channel:
            await ctx.send(f"Quote submitted to {channel.mention}!")


async def setup(bot):
    """Load Quotes cog."""
    await bot.add_cog(Quotes(bot))