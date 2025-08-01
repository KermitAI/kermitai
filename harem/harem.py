import discord
from redbot.core import commands, Config, bank
from redbot.core.utils.chat_formatting import box, pagify
from redbot.core.utils.predicates import MessagePredicate
from redbot.core.utils.menus import DEFAULT_CONTROLS, menu
import asyncio
import random
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
import aiohttp

# Import our character database module
from .characters import CharacterDatabase

class harem(commands.Cog):
    """A character collection and marriage system."""
    
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        
        # Guild settings
        default_guild = {
            "admin_role": None,
            "marriage_cost": 10000,
            "divorce_cost": 5000,
            "trade_cost": 1000,
            "cooldown_minutes": 1,
            "enabled": True,
            "ping_wishlist": True,
            "max_marriages": 50,
            "extra_rolls_roles": {}
        }
        
        # User settings
        default_user = {
            "marriages": [],  # List of character/user IDs they're married to
            "claimed_characters": [],  # List of character IDs they've claimed
            "wishlist": [],  # List of character names they want
            "last_roll": None,  # Timestamp of last roll
            "harem_title": "Harem",  # Custom title for their collection
            "favorite_character": None,  # Their favorite character ID
            "total_rolls": 0,
            "successful_claims": 0
        }
        
        self.config.register_guild(**default_guild)
        self.config.register_user(**default_user)
        
        # Initialize character database
        self.character_db = CharacterDatabase()
        
        # Active rolls tracking
        self.active_rolls = {}
        
    async def check_permissions(self, ctx):
        """Check if user has admin permissions for harem commands"""
        if ctx.author.guild_permissions.administrator:
            return True
        
        admin_role_id = await self.config.guild(ctx.guild).admin_role()
        if admin_role_id:
            admin_role = ctx.guild.get_role(admin_role_id)
            if admin_role and admin_role in ctx.author.roles:
                return True
        
        return False
    
    async def is_on_cooldown(self, user):
        """Check if user is on cooldown for rolling"""
        last_roll = await self.config.user(user).last_roll()
        if not last_roll:
            return False
    
        cooldown_minutes = await self.config.guild(user.guild).cooldown_minutes()
        last_roll_time = datetime.fromisoformat(last_roll)
        cooldown_end = last_roll_time + timedelta(minutes=cooldown_minutes)
        
        return datetime.now() < cooldown_end

    async def get_cooldown_remaining(self, user):
        """Get remaining cooldown time"""
        last_roll = await self.config.user(user).last_roll()
        if not last_roll:
            return timedelta(0)
    
        cooldown_minutes = await self.config.guild(user.guild).cooldown_minutes()
        last_roll_time = datetime.fromisoformat(last_roll)
        cooldown_end = last_roll_time + timedelta(minutes=cooldown_minutes)
    
        return cooldown_end - datetime.now()
    
    def get_rarity_color(self, rarity):
        """Get color for rarity"""
        colors = {
            "Common": 0x95A5A6,
            "Rare": 0x3498DB,
            "Epic": 0x9B59B6,
            "Legendary": 0xF1C40F
        }
        return colors.get(rarity.lower(), 0x95A5A6)
    
    async def roll_characters(self, gender=None, count=10):
        """Roll random characters based on gender and count"""
        available = self.character_db.get_available_characters(gender)
        if len(available) < count:
            # If not enough available, include some claimed characters
            all_chars = [(char_id, char) for char_id, char in self.character_db.get_all_characters().items() 
                        if gender is None or char["gender"] == gender]
            available = all_chars
        
        if not available:
            return []
        
        # If we have fewer characters than requested, just return all available
        if len(available) <= count:
            return available
        
        # Weight by rarity (legendary = 1, epic = 2, rare = 3, common = 4)
        weights = []
        for char_id, char in available:
            rarity = char["rarity"]
            if rarity == "Legendary":
                weights.append(1)
            elif rarity == "Epic":
                weights.append(2)
            elif rarity == "Rare":
                weights.append(3)
            else:  # common
                weights.append(4)
        
        # Simple approach: shuffle with weights and take first N
        selected = []
        available_copy = available.copy()
        
        for _ in range(count):
            if not available_copy:
                break
            
            # Create weights for remaining characters
            current_weights = []
            for char_id, char in available_copy:
                rarity = char["rarity"]
                if rarity == "Legendary":
                    current_weights.append(1)
                elif rarity == "Epic":
                    current_weights.append(2)
                elif rarity == "Rare":
                    current_weights.append(3)
                else:  # common
                    current_weights.append(4)
            
            # Select one character
            chosen_char = random.choices(available_copy, weights=current_weights, k=1)[0]
            selected.append(chosen_char)
            
            # Remove from available
            available_copy.remove(chosen_char)
        
        return selected
    
    @commands.group(name="harem", aliases=["h"])
    async def harem(self, ctx):
        """Paimon's Harem - Character collection and marriage system"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)
    
    @harem.command(name="rollf", aliases=["rf"])
    async def roll_female(self, ctx):
        """Roll for female characters"""
        await self.roll_characters_command(ctx, "female")
    
    @harem.command(name="rollm", aliases=["rm"])
    async def roll_male(self, ctx):
        """Roll for male characters"""
        await self.roll_characters_command(ctx, "male")
    
    @harem.command(name="roll", aliases=["r"])
    async def roll_all(self, ctx):
        """Roll for any gender characters"""
        await self.roll_characters_command(ctx, None)
    
    async def roll_characters_command(self, ctx, gender):
        """Handle character rolling"""
        if not await self.config.guild(ctx.guild).enabled():
            await ctx.send("❌ Paimon's Harem is disabled in this server.")
            return
        
        if await self.is_on_cooldown(ctx.author):
            remaining = await self.get_cooldown_remaining(ctx.author)
            # Updated to handle both minutes and hours
            total_minutes = int(remaining.total_seconds() // 60)
            if total_minutes >= 60:
                hours = total_minutes // 60
                minutes = total_minutes % 60
                await ctx.send(f"❄️ You're on cooldown! Try again in {hours}h {minutes}m")
            else:
                await ctx.send(f"❄️ You're on cooldown! Try again in {total_minutes}m")
            return
        
        # Calculate total rolls including extra rolls from roles
        base_rolls = 10  # Default 10 characters per roll
        extra_rolls = 0
        
        # Get role bonuses from config
        role_bonuses = await self.config.guild(ctx.guild).extra_rolls_roles()

        # Debug: Print role bonuses and user roles
        print(f"Role bonuses config: {role_bonuses}")
        print(f"User roles: {[f'{role.name} ({role.id})' for role in ctx.author.roles]}")
        
        # Check user's roles for bonuses
        for role in ctx.author.roles:
            role_id_str = str(role.id)
            if role_id_str in role_bonuses:
                role_bonus = role_bonuses[role_id_str]
                print(f"Found role bonus: {role.name} gives {role_bonus} extra rolls")
                extra_rolls = max(extra_rolls, role_bonus)
        
        total_rolls = base_rolls + extra_rolls
        
        # Debug: Print final calculation
        print(f"Final calculation: base_rolls={base_rolls}, extra_rolls={extra_rolls}, total_rolls={total_rolls}")
        
        # Now we can use total_rolls safely
        print(f"Requesting {total_rolls} characters")
        rolled_chars = await self.roll_characters(gender, count=total_rolls)
        print(f"Got {len(rolled_chars)} characters back")

        if not rolled_chars:
            await ctx.send("❌ No characters available to roll!")
            return
        
        # Create embed
        embed = discord.Embed(
            title="🎲 Character Roll",
            description=f"React to any character to claim them!\n**Total Rolls:** {total_rolls} (Base: {base_rolls} + Extra: {extra_rolls})\n\n",
            color=0x00ff00
        )
        
        # Add characters to embed
        reactions = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        char_mapping = {}
        
        for i, (char_id, char) in enumerate(rolled_chars):
            if i >= 10:  # Maximum 10 characters
                break
            
            emoji = reactions[i]
            char_mapping[emoji] = char_id
            
            status = "✅ Available" if char["claimed_by"] is None else "❌ Claimed"
            embed.add_field(
                name=f"{emoji} {char['name']}",
                value=f"**Anime:** {char['anime']}\n**Class:** {char.get('rarity', 'N/A')}\n**Status:** {status}",
                inline=True
            )
        
        # Send embed and add reactions
        message = await ctx.send(embed=embed)
        for emoji in char_mapping.keys():
            await message.add_reaction(emoji)
        
        # Store active roll
        self.active_rolls[message.id] = {
            "author": ctx.author.id,
            "chars": char_mapping,
            "timestamp": datetime.now()
        }
        
        # Update user stats
        await self.config.user(ctx.author).last_roll.set(datetime.now().isoformat())
        total_rolls_stat = await self.config.user(ctx.author).total_rolls()
        await self.config.user(ctx.author).total_rolls.set(total_rolls_stat + 1)
        
        # Clean up after 5 minutes
        await asyncio.sleep(300)
        if message.id in self.active_rolls:
            del self.active_rolls[message.id]
    
    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        """Handle character claiming via reactions"""
        if user.bot or reaction.message.id not in self.active_rolls:
            return
        
        roll_data = self.active_rolls[reaction.message.id]
        if str(reaction.emoji) not in roll_data["chars"]:
            return
        
        char_id = roll_data["chars"][str(reaction.emoji)]
        char = self.character_db.get_character(char_id)
        
        if not char:
            return
        
        # Check if character is already claimed
        if char["claimed_by"] is not None:
            await reaction.message.channel.send(f"❌ {user.mention}, {char['name']} is already claimed!")
            return
        
        # Claim character
        if self.character_db.claim_character(char_id, user.id):
            # Update user data
            claimed_chars = await self.config.user(user).claimed_characters()
            claimed_chars.append(char_id)
            await self.config.user(user).claimed_characters.set(claimed_chars)
            
            # Update successful claims
            successful_claims = await self.config.user(user).successful_claims()
            await self.config.user(user).successful_claims.set(successful_claims + 1)
            
            # Create claim embed
            embed = discord.Embed(
                title="💖 Character Claimed!",
                description=f"{user.mention} claimed **{char['name']}** from {char['anime']}!",
                color=self.get_rarity_color(char['rarity'])
            )
            
            if char['image_url']:
                embed.set_thumbnail(url=char['image_url'])
            
            await reaction.message.channel.send(embed=embed)
            
            # Check wishlist notifications
            await self.check_wishlist_notifications(reaction.message.guild, char['name'], user)
            
            # Remove from active rolls
            if reaction.message.id in self.active_rolls:
                del self.active_rolls[reaction.message.id]
    
    async def check_wishlist_notifications(self, guild, char_name, claimer):
        """Check if anyone has this character on their wishlist"""
        if not await self.config.guild(guild).ping_wishlist():
            return
        
        for member in guild.members:
            if member.bot or member.id == claimer.id:
                continue
            
            wishlist = await self.config.user(member).wishlist()
            if char_name.lower() in [w.lower() for w in wishlist]:
                try:
                    await member.send(f"🔔 **{char_name}** from your wishlist was just claimed by {claimer.mention} in {guild.name}!")
                except discord.Forbidden:
                    pass  # User has DMs disabled
    
    @harem.command(name="profile", aliases=["p", "hpf"])
    async def profile(self, ctx, *, user: discord.Member = None):
        """View someone's harem profile"""
        if user is None:
            user = ctx.author
        
        # Get user data
        user_data = await self.config.user(user).all()
        
        # Get currency from economy cog
        try:
            balance = await bank.get_balance(user)
        except:
            balance = 0
        
        # Create embed
        embed = discord.Embed(
            title=f"💖 {user.display_name}'s {user_data['harem_title']}",
            color=user.color or 0x00ff00
        )
        
        embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)
        
        # Add stats
        embed.add_field(
            name="📊 Stats",
            value=f"**Balance:** {balance:,}\n"
                  f"**Total Rolls:** {user_data['total_rolls']}\n"
                  f"**Successful Claims:** {user_data['successful_claims']}\n"
                  f"**Success Rate:** {(user_data['successful_claims']/max(user_data['total_rolls'], 1)*100):.1f}%",
            inline=True
        )
        
        # Get character marriages
        char_marriages = []
        for char_id in user_data['claimed_characters']:
            char = self.character_db.get_character(char_id)
            if char and char_id in user_data['marriages']:
                char_marriages.append(f"💍 {char['name']} ({char['anime']})")
        
        # Get member marriages
        member_marriages = []
        for marriage in user_data['marriages']:
            if not marriage.startswith('char_'):
                try:
                    member = ctx.guild.get_member(int(marriage))
                    if member:
                        member_marriages.append(f"💍 {member.display_name}")
                except ValueError:
                    pass
        
        # Add marriages
        if char_marriages:
            embed.add_field(
                name="👥 Character Marriages",
                value="\n".join(char_marriages[:10]) + (f"\n*... and {len(char_marriages)-10} more*" if len(char_marriages) > 10 else ""),
                inline=False
            )
        
        if member_marriages:
            embed.add_field(
                name="💕 Member Marriages",
                value="\n".join(member_marriages[:10]) + (f"\n*... and {len(member_marriages)-10} more*" if len(member_marriages) > 10 else ""),
                inline=False
            )
        
        # Add favorite character
        if user_data['favorite_character']:
            fav_char = self.character_db.get_character(user_data['favorite_character'])
            if fav_char:
                embed.add_field(
                    name="⭐ Favorite Character",
                    value=f"{fav_char['name']} ({fav_char['anime']})",
                    inline=True
                )
        
        await ctx.send(embed=embed)
    
    @harem.command(name="collection", aliases=["c", "chars"])
    async def collection(self, ctx, *, user: discord.Member = None):
        """View someone's character collection"""
        if user is None:
            user = ctx.author
        
        # Get user's claimed characters
        claimed_chars = await self.config.user(user).claimed_characters()
        
        if not claimed_chars:
            await ctx.send(f"❌ {user.display_name} hasn't claimed any characters yet!")
            return
        
        # Get character details
        chars_data = []
        for char_id in claimed_chars:
            char = self.character_db.get_character(char_id)
            if char:
                chars_data.append((char_id, char))
        
        if not chars_data:
            await ctx.send(f"❌ {user.display_name}'s characters are no longer available!")
            return
        
        # Sort by rarity then by name
        rarity_order = {"Legendary": 0, "Epic": 1, "Rare": 2, "Common": 3}
        chars_data.sort(key=lambda x: (rarity_order.get(x[1]["rarity"], 4), x[1]["name"]))
        
        # Create embed pages
        pages = []
        chars_per_page = 10
        
        for i in range(0, len(chars_data), chars_per_page):
            page_chars = chars_data[i:i+chars_per_page]
            
            embed = discord.Embed(
                title=f"💖 {user.display_name}'s Character Collection",
                description=f"Page {i//chars_per_page + 1}/{(len(chars_data)-1)//chars_per_page + 1}",
                color=user.color or 0x00ff00
            )
            
            for char_id, char in page_chars:
                status = "💍 Married" if char["married_to"] == user.id else "💖 Owned"
                embed.add_field(
                    name=f"{char['name']}",
                    value=f"**Anime:** {char['anime']}\n**Class:** {char.get('rarity', 'N/A')}\n**Status:** {status}",
                    inline=True
                )
            
            pages.append(embed)
        
        # Send pages
        if len(pages) == 1:
            await ctx.send(embed=pages[0])
        else:
            await menu(ctx, pages, DEFAULT_CONTROLS)
    
    @harem.command(name="search", aliases=["s"])
    async def search(self, ctx, *, query: str):
        """Search for characters by name or anime"""
        results = self.character_db.search_characters(query)
        
        if not results:
            await ctx.send(f"❌ No characters found matching '{query}'")
            return
        
        # Limit results to 20
        results = results[:20]
        
        embed = discord.Embed(
            title=f"🔍 Search Results for '{query}'",
            color=0x00ff00
        )
        
        for char_id, char in results:
            status = "❌ Claimed" if char["claimed_by"] else "✅ Available"
            embed.add_field(
                name=f"{char['name']}",
                value=f"**Anime:** {char['anime']}**Class:** {char.get('rarity', 'N/A')}\n**Status:** {status}",
                inline=True
            )
        
        await ctx.send(embed=embed)
    
    @harem.command(name="marry")
    async def marry(self, ctx, *, target):
        """Marry a character or member"""
        if not await self.config.guild(ctx.guild).enabled():
            await ctx.send("❌ Paimon's Harem is disabled in this server.")
            return
        
        marriage_cost = await self.config.guild(ctx.guild).marriage_cost()
        
        # Check if user has enough currency
        try:
            balance = await bank.get_balance(ctx.author)
            if balance < marriage_cost:
                await ctx.send(f"❌ You need {marriage_cost:,} currency to marry! You have {balance:,}.")
                return
        except:
            await ctx.send("❌ Could not access your balance.")
            return
        
        # Check if target is a member
        try:
            member = await commands.MemberConverter().convert(ctx, target)
            target_id = str(member.id)
            target_name = member.display_name
            is_member = True
        except:
            # Try to find character
            char_id = None
            claimed_chars = await self.config.user(ctx.author).claimed_characters()
            
            for cid in claimed_chars:
                char = self.character_db.get_character(cid)
                if char and char['name'].lower() == target.lower():
                    char_id = cid
                    break
            
            if not char_id:
                await ctx.send(f"❌ Could not find character or member '{target}' that you own.")
                return
            
            target_id = f"char_{char_id}"
            target_name = self.character_db.get_character(char_id)['name']
            is_member = False
        
        # Check if already married
        user_marriages = await self.config.user(ctx.author).marriages()
        if target_id in user_marriages:
            await ctx.send(f"❌ You're already married to {target_name}!")
            return
        
        # Check marriage limit
        max_marriages = await self.config.guild(ctx.guild).max_marriages()
        if len(user_marriages) >= max_marriages:
            await ctx.send(f"❌ You've reached the maximum number of marriages ({max_marriages})!")
            return
        
        # If marrying a member, check if they consent
        if is_member:
            embed = discord.Embed(
                title="💍 Marriage Proposal",
                description=f"{ctx.author.mention} wants to marry {member.mention}!\n\n"
                           f"**Cost:** {marriage_cost:,} currency\n\n"
                           f"React with ✅ to accept or ❌ to decline.",
                color=0xff69b4
            )
            
            msg = await ctx.send(embed=embed)
            await msg.add_reaction("✅")
            await msg.add_reaction("❌")
            
            def check(reaction, user):
                return user == member and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg.id
            
            try:
                reaction, user = await self.bot.wait_for("reaction_add", timeout=60.0, check=check)
                if str(reaction.emoji) == "❌":
                    await ctx.send(f"💔 {member.mention} declined the marriage proposal.")
                    return
            except asyncio.TimeoutError:
                await ctx.send("💔 Marriage proposal timed out.")
                return
        
        # Process marriage
        try:
            await bank.withdraw_credits(ctx.author, marriage_cost)
        except:
            await ctx.send("❌ Could not process payment.")
            return
        
        # Add marriage
        user_marriages.append(target_id)
        await self.config.user(ctx.author).marriages.set(user_marriages)
        
        # If marrying a member, add to their marriages too
        if is_member:
            member_marriages = await self.config.user(member).marriages()
            member_marriages.append(str(ctx.author.id))
            await self.config.user(member).marriages.set(member_marriages)
        else:
            # If marrying a character, update character's married_to field
            char_id = target_id.replace("char_", "")
            self.character_db.marry_character(char_id, ctx.author.id)
        
        # Create success embed
        embed = discord.Embed(
            title="💍 Marriage Successful!",
            description=f"{ctx.author.mention} married {target_name}!",
            color=0xff69b4
        )
        
        await ctx.send(embed=embed)
    
    @harem.command(name="divorce")
    async def divorce(self, ctx, *, target):
        """Divorce a character or member"""
        if not await self.config.guild(ctx.guild).enabled():
            await ctx.send("❌ Paimon's Harem is disabled in this server.")
            return
        
        divorce_cost = await self.config.guild(ctx.guild).divorce_cost()
        
        # Check if user has enough currency
        try:
            balance = await bank.get_balance(ctx.author)
            if balance < divorce_cost:
                await ctx.send(f"❌ You need {divorce_cost:,} currency to divorce! You have {balance:,}.")
                return
        except:
            await ctx.send("❌ Could not access your balance.")
            return
        
        # Find target
        try:
            member = await commands.MemberConverter().convert(ctx, target)
            target_id = str(member.id)
            target_name = member.display_name
            is_member = True
        except:
            # Try to find character
            char_id = None
            user_marriages = await self.config.user(ctx.author).marriages()
            
            for marriage in user_marriages:
                if marriage.startswith("char_"):
                    cid = marriage.replace("char_", "")
                    char = self.character_db.get_character(cid)
                    if char and char['name'].lower() == target.lower():
                        char_id = cid
                        break
            
            if not char_id:
                await ctx.send(f"❌ Could not find character or member '{target}' that you're married to.")
                return
            
            target_id = f"char_{char_id}"
            target_name = self.character_db.get_character(char_id)['name']
            is_member = False
        
        # Check if married
        user_marriages = await self.config.user(ctx.author).marriages()
        if target_id not in user_marriages:
            await ctx.send(f"❌ You're not married to {target_name}!")
            return
        
        # Process divorce
        try:
            await bank.withdraw_credits(ctx.author, divorce_cost)
        except:
            await ctx.send("❌ Could not process payment.")
            return
        
        # Remove marriage
        user_marriages.remove(target_id)
        await self.config.user(ctx.author).marriages.set(user_marriages)
        
        # If divorcing a member, remove from their marriages too
        if is_member:
            member_marriages = await self.config.user(member).marriages()
            if str(ctx.author.id) in member_marriages:
                member_marriages.remove(str(ctx.author.id))
                await self.config.user(member).marriages.set(member_marriages)
        else:
            # If divorcing a character, update character's married_to field
            char_id = target_id.replace("char_", "")
            self.character_db.divorce_character(char_id)
        
        # Create success embed
        embed = discord.Embed(
            title="💔 Divorce Successful",
            description=f"{ctx.author.mention} divorced {target_name}.",
            color=0xff0000
        )
        
        await ctx.send(embed=embed)
    
    @harem.command(name="wishlist", aliases=["wl"])
    async def wishlist(self, ctx, action: str = None, *, character_name: str = None):
        """Manage your character wishlist"""
        if action is None:
            # Show wishlist
            wishlist = await self.config.user(ctx.author).wishlist()
            if not wishlist:
                await ctx.send("❌ Your wishlist is empty!")
                return
            
            embed = discord.Embed(
                title=f"🌟 {ctx.author.display_name}'s Wishlist",
                description="\n".join(f"• {char}" for char in wishlist),
                color=0xffd700
            )
            await ctx.send(embed=embed)
            return
        
        if action.lower() not in ["add", "remove", "clear"]:
            await ctx.send("❌ Action must be: add, remove, or clear")
            return
        
        wishlist = await self.config.user(ctx.author).wishlist()
        
        if action.lower() == "clear":
            await self.config.user(ctx.author).wishlist.set([])
            await ctx.send("✅ Wishlist cleared!")
            return
        
        if not character_name:
            await ctx.send("❌ Please provide a character name!")
            return
        
        if action.lower() == "add":
            if character_name in wishlist:
                await ctx.send(f"❌ {character_name} is already in your wishlist!")
                return
            
            wishlist.append(character_name)
            await self.config.user(ctx.author).wishlist.set(wishlist)
            await ctx.send(f"✅ Added {character_name} to your wishlist!")
        
        elif action.lower() == "remove":
            if character_name not in wishlist:
                await ctx.send(f"❌ {character_name} is not in your wishlist!")
                return
            
            wishlist.remove(character_name)
            await self.config.user(ctx.author).wishlist.set(wishlist)
            await ctx.send(f"✅ Removed {character_name} from your wishlist!")
    
    @harem.command(name="stats")
    async def stats(self, ctx):
        """Show character database statistics"""
        stats = self.character_db.get_stats()
        
        embed = discord.Embed(
            title="📊 Character Database Statistics",
            color=0x00ff00
        )
        
        embed.add_field(
            name="📈 General Stats",
            value=f"**Total Characters:** {stats['total_characters']}\n"
                  f"**Available:** {stats['available_characters']}\n"
                  f"**Claimed:** {stats['claimed_characters']}\n"
                  f"**Married:** {stats['married_characters']}",
            inline=True
        )
        
        # Rarity distribution
        rarity_text = []
        for rarity, count in stats['rarity_distribution'].items():
            rarity_text.append(f"**{rarity.title()}:** {count}")
        
        embed.add_field(
            name="🎯 Rarity Distribution",
            value="\n".join(rarity_text),
            inline=True
        )
        
        # Gender distribution
        gender_text = []
        for gender, count in stats['gender_distribution'].items():
            gender_text.append(f"**{gender.title()}:** {count}")
        
        embed.add_field(
            name="👥 Gender Distribution",
            value="\n".join(gender_text),
            inline=True
        )
        
        # Top 5 anime by character count
        top_anime = sorted(stats['anime_distribution'].items(), key=lambda x: x[1], reverse=True)[:5]
        anime_text = []
        for anime, count in top_anime:
            anime_text.append(f"**{anime}:** {count}")
        
        embed.add_field(
            name="🎌 Top Anime",
            value="\n".join(anime_text),
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @harem.group(name="admin", aliases=["a"])
    async def harem_admin(self, ctx):
        """Admin commands for Paimon's Harem"""
        if not await self.check_permissions(ctx):
            await ctx.send("❌ You don't have permission to use admin commands.")
            return
        
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)
    
    @harem_admin.command(name="toggle")
    async def admin_toggle(self, ctx):
        """Toggle Paimon's Harem on/off"""
        current = await self.config.guild(ctx.guild).enabled()
        await self.config.guild(ctx.guild).enabled.set(not current)
        status = "enabled" if not current else "disabled"
        await ctx.send(f"✅ Paimon's Harem {status}.")
    
    @harem_admin.command(name="debug")
    async def admin_debug(self, ctx):
        """Debug extra rolls configuration"""
        # Get role bonuses from config
        role_bonuses = await self.config.guild(ctx.guild).extra_rolls_roles()
        
        embed = discord.Embed(
            title="🔍 Debug: Extra Rolls Configuration",
            color=0x00ff00
        )
        
        # Show configured roles
        if role_bonuses:
            role_text = []
            for role_id, bonus in role_bonuses.items():
                role = ctx.guild.get_role(int(role_id))
                role_name = role.name if role else f"Unknown Role ({role_id})"
                role_text.append(f"**{role_name}:** {bonus} extra rolls")
            
            embed.add_field(
                name="Configured Roles",
                value="\n".join(role_text),
                inline=False
            )
        else:
            embed.add_field(
                name="Configured Roles",
                value="No roles configured for extra rolls",
                inline=False
            )
        
        # Show user's roles
        user_roles = []
        for role in ctx.author.roles:
            bonus = role_bonuses.get(str(role.id), 0)
            user_roles.append(f"**{role.name}** (ID: {role.id}): {bonus} extra rolls")
        
        embed.add_field(
            name="Your Roles",
            value="\n".join(user_roles) if user_roles else "No roles",
            inline=False
        )
        
        # Calculate what the user should get
        extra_rolls = 0
        for role in ctx.author.roles:
            if str(role.id) in role_bonuses:
                extra_rolls = max(extra_rolls, role_bonuses[str(role.id)])
        
        embed.add_field(
            name="Expected Extra Rolls",
            value=f"{extra_rolls} extra rolls",
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @harem_admin.command(name="setcost")
    async def admin_set_cost(self, ctx, cost_type: str, amount: int):
        """Set costs for various actions (marriage, divorce, trade)"""
        if cost_type.lower() not in ["marriage", "divorce", "trade"]:
            await ctx.send("❌ Cost type must be: marriage, divorce, or trade")
            return
        
        if amount < 0:
            await ctx.send("❌ Amount must be positive.")
            return
        
        cost_key = f"{cost_type.lower()}_cost"
        await self.config.guild(ctx.guild).set_raw(cost_key, value=amount)
        await ctx.send(f"✅ {cost_type.title()} cost set to {amount:,}")
    
    
    @harem_admin.command(name="setextrarolls")
    async def admin_set_extra_rolls(self, ctx, role: discord.Role, rolls: int):
        """Set extra roll count for a role"""
        if rolls < 0:
            await ctx.send("❌ Extra rolls must be 0 or positive.")
            return
        
        # Get current data
        data = await self.config.guild(ctx.guild).extra_rolls_roles()
        
        # Update the role
        data[str(role.id)] = rolls
        
        # Save back to config
        await self.config.guild(ctx.guild).extra_rolls_roles.set(data)
        
        # Confirm the save
        saved_data = await self.config.guild(ctx.guild).extra_rolls_roles()
        
        if str(role.id) in saved_data and saved_data[str(role.id)] == rolls:
            await ctx.send(f"✅ {role.name} now grants {rolls} extra roll(s).")
        else:
            await ctx.send(f"❌ Failed to save extra rolls for {role.name}. Please try again.")
        
        # Show current configuration
        embed = discord.Embed(
            title="Current Extra Rolls Configuration",
            color=0x00ff00
        )
        
        if saved_data:
            role_text = []
            for role_id, bonus in saved_data.items():
                config_role = ctx.guild.get_role(int(role_id))
                role_name = config_role.name if config_role else f"Unknown Role ({role_id})"
                role_text.append(f"**{role_name}:** {bonus} extra rolls")
            
            embed.description = "\n".join(role_text)
        else:
            embed.description = "No roles configured for extra rolls"
        
        await ctx.send(embed=embed)


    @harem_admin.command(name="setcooldown")
    async def admin_set_cooldown(self, ctx, minutes: int):
        """Set cooldown between rolls (in minutes)"""
        if minutes < 0:
            await ctx.send("❌ Cooldown must be positive.")
            return
    
        await self.config.guild(ctx.guild).cooldown_minutes.set(minutes)
    
    # Display in human-readable format
        if minutes >= 60:
            hours = minutes // 60
            remaining_minutes = minutes % 60
            if remaining_minutes > 0:
                await ctx.send(f"✅ Roll cooldown set to {hours}h {remaining_minutes}m ({minutes} minutes).")
            else:
                await ctx.send(f"✅ Roll cooldown set to {hours}h ({minutes} minutes).")
        else:
            await ctx.send(f"✅ Roll cooldown set to {minutes} minutes.")
    
    @harem_admin.command(name="setrole")
    async def admin_set_role(self, ctx, role: discord.Role):
        """Set the admin role for harem management"""
        await self.config.guild(ctx.guild).admin_role.set(role.id)
        await ctx.send(f"✅ Admin role set to {role.mention}")
    
    @harem_admin.command(name="addchar")
    async def admin_add_character(self, ctx, name: str, anime: str, gender: str, rarity: str, image_url: str = ""):
        """Add a new character to the database"""
        if gender.lower() not in ["male", "female"]:
            await ctx.send("❌ Gender must be 'male' or 'female'")
            return
        
        if rarity.lower() not in ["Common", "Rare", "Epic", "Legendary"]:
            await ctx.send("❌ Rarity must be: Common, Rare, Epic, or Legendary")
            return
        
        char_id = self.character_db.add_character(name, anime, gender.lower(), rarity.lower(), image_url)
        await ctx.send(f"✅ Added character **{name}** from {anime} (ID: {char_id})")
    
    @harem_admin.command(name="removechar")
    async def admin_remove_character(self, ctx, char_id: str):
        """Remove a character from the database"""
        char = self.character_db.get_character(char_id)
        if not char:
            await ctx.send(f"❌ Character with ID {char_id} not found!")
            return
        
        if self.character_db.remove_character(char_id):
            await ctx.send(f"✅ Removed character **{char['name']}** from the database")
        else:
            await ctx.send(f"❌ Failed to remove character")
    
    @harem_admin.command(name="releasechar")
    async def admin_release_character(self, ctx, char_id: str):
        """Release a character back to the unclaimed pool"""
        char = self.character_db.get_character(char_id)
        if not char:
            await ctx.send(f"❌ Character with ID {char_id} not found!")
            return
        
        if self.character_db.release_character(char_id):
            await ctx.send(f"✅ Released character **{char['name']}** back to the pool")
        else:
            await ctx.send(f"❌ Failed to release character")
    
    @harem_admin.command(name="backup")
    async def admin_backup(self, ctx):
        """Create a backup of the character database"""
        try:
            backup_path = os.path.join(os.path.dirname(__file__), f"character_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            with open(backup_path, 'w', encoding='utf-8') as f:
                json.dump(self.character_db.get_all_characters(), f, indent=2, ensure_ascii=False)
            await ctx.send(f"✅ Database backup created: {os.path.basename(backup_path)}")
        except Exception as e:
            await ctx.send(f"❌ Failed to create backup: {e}")
    
    @harem_admin.command(name="reload")
    async def admin_reload(self, ctx):
        """Reload the character database from file"""
        try:
            self.character_db.load_characters()
            await ctx.send("✅ Character database reloaded successfully!")
        except Exception as e:
            await ctx.send(f"❌ Failed to reload database: {e}")
    @harem_admin.command(name="resetcooldown")
    async def admin_reset_cooldown(self, ctx, target: str, member: Optional[discord.Member] = None):
        """Reset cooldowns: global or user"""
        if target.lower() == "global":
            all_users = await self.config.all_users()
            for user_id in all_users:
                await self.config.user_from_id(user_id).last_roll.set(None)
            await ctx.send("✅ Global cooldown reset.")
        
        elif target.lower() == "user":
            if not member:
                await ctx.send("❌ Please specify a user.")
                return
            await self.config.user(member).last_roll.set(None)
            await ctx.send(f"✅ Cooldown reset for {member.display_name}.")
        
        else:
            await ctx.send("❌ Invalid option. Use `global` or `user`.")
