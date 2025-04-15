import re
import discord
from redbot.core import commands, Config
from redbot.core.utils.chat_formatting import box, pagify
from typing import Dict, List, Optional, Pattern, Union


class AutoTrigger(commands.Cog):
    """Auto Trigger cog for Red-Discordbot.
    
    This cog allows you to set up automatic responses when specific keywords are detected in messages.
    Supports exact matches and wildcards using * as a placeholder for any characters.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9283467154, force_registration=True)
        
        default_guild = {
            "triggers": {},  # {trigger_name: {"pattern": str, "response": str, "wildcard": bool}}
            "enabled": True
        }
        
        self.config.register_guild(**default_guild)
        self.compiled_patterns = {}
        self.cache = {}
        
    async def initialize(self):
        """Load triggers from all guilds into cache when the cog loads."""
        all_guilds = await self.config.all_guilds()
        for guild_id, guild_data in all_guilds.items():
            self.cache[guild_id] = guild_data
            if "triggers" in guild_data:
                self.compiled_patterns[guild_id] = {}
                for name, trigger_data in guild_data["triggers"].items():
                    pattern = trigger_data["pattern"]
                    is_wildcard = trigger_data.get("wildcard", False)
                    if is_wildcard:
                        # Convert * wildcards to regex pattern
                        regex_pattern = pattern.replace("*", ".*")
                        self.compiled_patterns[guild_id][name] = re.compile(f"\\b{regex_pattern}\\b", re.IGNORECASE)
    
    @commands.group(name="autotrigger", aliases=["at"])
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def auto_trigger(self, ctx):
        """Manage automatic triggers that respond to keywords."""
        pass
    
    @auto_trigger.command(name="add")
    async def add_trigger(self, ctx, name: str, *, data: str):
        """Add a new trigger.
        
        The format should be: pattern :: response
        
        Use * as a wildcard to match any characters.
        
        Example:
        [p]autotrigger add hello hello* :: Hello there, {author}!
        """
        if "::" not in data:
            return await ctx.send("Invalid format. Use: `pattern :: response`")
        
        pattern, response = data.split("::", 1)
        pattern = pattern.strip()
        response = response.strip()
        
        if not pattern or not response:
            return await ctx.send("Pattern and response cannot be empty.")
        
        guild_id = ctx.guild.id
        is_wildcard = "*" in pattern
        
        async with self.config.guild(ctx.guild).triggers() as triggers:
            triggers[name] = {
                "pattern": pattern,
                "response": response,
                "wildcard": is_wildcard
            }
        
        # Update cache and compile pattern
        if guild_id not in self.cache:
            self.cache[guild_id] = {"triggers": {}, "enabled": True}
        if "triggers" not in self.cache[guild_id]:
            self.cache[guild_id]["triggers"] = {}
        
        self.cache[guild_id]["triggers"][name] = {
            "pattern": pattern,
            "response": response,
            "wildcard": is_wildcard
        }
        
        if guild_id not in self.compiled_patterns:
            self.compiled_patterns[guild_id] = {}
        
        if is_wildcard:
            regex_pattern = pattern.replace("*", ".*")
            self.compiled_patterns[guild_id][name] = re.compile(f"\\b{regex_pattern}\\b", re.IGNORECASE)
        
        await ctx.send(f"Trigger `{name}` has been added successfully.")
    
    @auto_trigger.command(name="remove", aliases=["delete", "del"])
    async def remove_trigger(self, ctx, name: str):
        """Remove a trigger by name."""
        guild_id = ctx.guild.id
        
        async with self.config.guild(ctx.guild).triggers() as triggers:
            if name not in triggers:
                return await ctx.send(f"Trigger `{name}` not found.")
            
            del triggers[name]
        
        # Update cache
        if guild_id in self.cache and "triggers" in self.cache[guild_id]:
            if name in self.cache[guild_id]["triggers"]:
                del self.cache[guild_id]["triggers"][name]
        
        # Update compiled patterns
        if guild_id in self.compiled_patterns and name in self.compiled_patterns[guild_id]:
            del self.compiled_patterns[guild_id][name]
        
        await ctx.send(f"Trigger `{name}` has been removed.")
    
    @auto_trigger.command(name="list")
    async def list_triggers(self, ctx):
        """List all triggers for this guild."""
        guild_id = ctx.guild.id
        
        if guild_id not in self.cache or "triggers" not in self.cache[guild_id] or not self.cache[guild_id]["triggers"]:
            return await ctx.send("No triggers have been set up in this server.")
        
        triggers = self.cache[guild_id]["triggers"]
        
        message = "**Configured Triggers:**\n\n"
        for name, data in triggers.items():
            wildcard_info = " (with wildcards)" if data.get("wildcard", False) else ""
            message += f"• **{name}**{wildcard_info}\n"
            message += f"  Pattern: `{data['pattern']}`\n"
            message += f"  Response: `{data['response']}`\n\n"
        
        for page in pagify(message, delims=["\n\n"]):
            await ctx.send(page)
    
    @auto_trigger.command(name="toggle")
    async def toggle_triggers(self, ctx):
        """Toggle auto triggers on or off for this guild."""
        guild_id = ctx.guild.id
        
        if guild_id not in self.cache:
            self.cache[guild_id] = {"triggers": {}, "enabled": True}
        
        current_status = self.cache[guild_id].get("enabled", True)
        new_status = not current_status
        
        await self.config.guild(ctx.guild).enabled.set(new_status)
        self.cache[guild_id]["enabled"] = new_status
        
        status_message = "enabled" if new_status else "disabled"
        await ctx.send(f"Auto triggers have been {status_message} for this server.")
    
    @auto_trigger.command(name="show")
    async def show_trigger(self, ctx, name: str):
        """Show details for a specific trigger."""
        guild_id = ctx.guild.id
        
        if guild_id not in self.cache or "triggers" not in self.cache[guild_id]:
            return await ctx.send("No triggers have been set up in this server.")
        
        triggers = self.cache[guild_id]["triggers"]
        
        if name not in triggers:
            return await ctx.send(f"Trigger `{name}` not found.")
        
        data = triggers[name]
        wildcard_info = "Yes" if data.get("wildcard", False) else "No"
        
        message = f"**Trigger: {name}**\n"
        message += f"Pattern: `{data['pattern']}`\n"
        message += f"Response: `{data['response']}`\n"
        message += f"Uses wildcards: {wildcard_info}"
        
        await ctx.send(message)
    
    @auto_trigger.command(name="edit")
    async def edit_trigger(self, ctx, name: str, *, data: str):
        """Edit an existing trigger.
        
        The format should be: pattern :: response
        
        Example:
        [p]autotrigger edit hello hello* :: Hello there, {author}!
        """
        guild_id = ctx.guild.id
        
        if guild_id not in self.cache or "triggers" not in self.cache[guild_id]:
            return await ctx.send("No triggers have been set up in this server.")
        
        triggers = self.cache[guild_id]["triggers"]
        
        if name not in triggers:
            return await ctx.send(f"Trigger `{name}` not found.")
        
        if "::" not in data:
            return await ctx.send("Invalid format. Use: `pattern :: response`")
        
        pattern, response = data.split("::", 1)
        pattern = pattern.strip()
        response = response.strip()
        
        if not pattern or not response:
            return await ctx.send("Pattern and response cannot be empty.")
        
        is_wildcard = "*" in pattern
        
        async with self.config.guild(ctx.guild).triggers() as config_triggers:
            config_triggers[name] = {
                "pattern": pattern,
                "response": response,
                "wildcard": is_wildcard
            }
        
        # Update cache
        self.cache[guild_id]["triggers"][name] = {
            "pattern": pattern,
            "response": response,
            "wildcard": is_wildcard
        }
        
        # Update compiled patterns
        if is_wildcard:
            regex_pattern = pattern.replace("*", ".*")
            self.compiled_patterns[guild_id][name] = re.compile(f"\\b{regex_pattern}\\b", re.IGNORECASE)
        elif name in self.compiled_patterns.get(guild_id, {}):
            # If it was a wildcard before but now it's not, remove from compiled patterns
            del self.compiled_patterns[guild_id][name]
        
        await ctx.send(f"Trigger `{name}` has been updated successfully.")
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen for messages and respond with triggers if appropriate."""
        # Ignore bot messages and DMs
        if message.author.bot or not message.guild:
            return
        
        guild_id = message.guild.id
        
        # Check if triggers are enabled for this guild
        if guild_id not in self.cache or self.cache[guild_id].get("enabled", True) is False:
            return
        
        # Check if we have any triggers for this guild
        if "triggers" not in self.cache[guild_id] or not self.cache[guild_id]["triggers"]:
            return
        
        content = message.content.lower()
        ctx = await self.bot.get_context(message)
        
        # Ignore command invocations
        if ctx.valid:
            return
        
        triggers = self.cache[guild_id]["triggers"]
        
        for name, data in triggers.items():
            pattern = data["pattern"].lower()
            response = data["response"]
            is_wildcard = data.get("wildcard", False)
            
            if is_wildcard:
                # Use regex pattern for wildcard matching
                if name in self.compiled_patterns.get(guild_id, {}) and self.compiled_patterns[guild_id][name].search(content):
                    await self._send_response(message, response)
                    break
            else:
                # Exact matching
                if f" {pattern} " in f" {content} " or content == pattern:
                    await self._send_response(message, response)
                    break
    
    async def _send_response(self, message: discord.Message, response: str):
        """Format and send the trigger response."""
        # Process placeholder replacements
        formatted_response = response.replace("{author}", message.author.mention)
        formatted_response = formatted_response.replace("{channel}", message.channel.mention)
        formatted_response = formatted_response.replace("{guild}", message.guild.name)
        
        await message.channel.send(formatted_response)

    def cog_unload(self):
        """Clean up when cog is unloaded."""
        # Clear caches
        self.cache.clear()
        self.compiled_patterns.clear()


async def setup(bot):
    """Load AutoTrigger cog."""
    cog = AutoTrigger(bot)
    await cog.initialize()
    await bot.add_cog(cog)
