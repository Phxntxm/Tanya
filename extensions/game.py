import asyncio
import collections
import dataclasses
import discord
from discord.ext import commands
import random
import typing


default_role_overwrites = discord.PermissionOverwrite(
    read_messages=False,
    send_messages=True,
    read_message_history=True,
    attach_files=False,
    add_reactions=False,
)
default_role_disabled_overwrites = discord.PermissionOverwrite(
    read_messages=False,
    send_messages=False,
    read_message_history=True,
    attach_files=False,
    add_reactions=False,
)
bot_overwrites = discord.PermissionOverwrite(
    read_messages=True,
    send_messages=True,
    add_reactions=True,
)
user_overwrites = discord.PermissionOverwrite(read_messages=True)


@dataclasses.dataclass
class MafiaGameConfig:
    starting_mafia: int
    special_roles: typing.List
    ctx: commands.Context
    night_length: int = 60
    day_length: int = 120


class MafiaGame:
    def __init__(self, ctx: commands.Context):
        # The discord members, we'll produce our list of players later
        self._members: list = None
        # The actual players of the game
        self.players: list = []

        self.ctx = ctx
        self.is_day: bool = True

        # Different chats needed
        self.chat: discord.TextChannel = None
        self.mafia_chat: discord.TextChannel = None
        self.info: discord.TextChannel = None
        self.dead_chat: discord.TextChannel = None

        self._rand = random.SystemRandom()
        self._config: MafiaGameConfig = None
        self._day: int = 1
        self._day_notifications: collections.defaultdict(list)
        self._role_list: list = None

    @property
    def total_mafia(self):
        return sum(1 for player in self.players if player.is_mafia and not player.dead)

    @property
    def total_citizens(self):
        return sum(
            1 for player in self.players if player.is_citizen and not player.dead
        )

    @property
    def total_alive(self):
        return sum(1 for player in self.players if not player.dead)

    @property
    def total_players(self):
        return len(self.players)

    async def night_notification(self):
        embed = discord.Embed(
            title=f"Night {self._day}",
            description="Check your private channels",
            colour=0x0A0A86,
        )
        embed.set_thumbnail(
            url="https://www.jing.fm/clipimg/full/132-1327252_half-moon-png-images-moon-clipart-png.png"
        )
        await self.info.send(embed=embed)

    def add_day_notification(self, *notifications: str):
        msg, current_notifications = self._day_notifications.get(self._day, (None, []))
        current_notifications.extend(notifications)

        self._day_notifications[self._day] = (msg, current_notifications)

    async def day_notification(self, *notifications: str):
        """Creates a notification embed with all of todays notifications"""
        msg, current_notifications = self._day_notifications.get(self._day, (None, []))
        current_notifications.extend(notifications)
        fmt = ""
        if self._day > 1:
            fmt += f"**Type >>nominate member to nominate someone to be lynched**. Chat in {self.chat.mention}\n\n"
        fmt += "**Recent Actions**\n"
        fmt += "\n -".join(current_notifications)

        embed = discord.Embed(
            title=f"Day {self._day}", description=fmt, colour=0xF6F823
        )
        embed.set_thumbnail(
            url="https://media.discordapp.net/attachments/840698427755069475/841841923936485416/Sw5vSWOjshUo40xEj-hWqfiRu8Ma2CtYjjh7prRsF6ADPk_z7znpEBf-E3i44U9Hukh3ZJOFhm9S43naa4dEA8pXX4dfAJeEv0bl.png"
        )
        embed.add_field(name="Alive", value=self.total_alive)
        embed.add_field(name="Dead", value=self.total_players - self.total_alive)
        embed.add_field(name="Mafia Remaining", value=self.total_mafia)
        if msg is None:
            msg = await self.info.send(embed=embed)
        else:
            await msg.edit(embed=embed)

        self._day_notifications[self._day] = (msg, current_notifications)

    async def update_role_list(self):
        msg = "\n".join(
            f"**{'Town' if role.is_citizen else 'Mafia'}** - {role}"
            for role in self.players
        )
        if self._role_list is None:
            self._role_list = await self.info.send(msg)
        else:
            await self._role_list.edit(content=msg)

    def check_winner(self):
        """Loops through all the winners and checks their win conditions"""
        for player in self.players:
            if player.win_condition(self):
                return player

    async def pick_players(self):
        # I'm paranoid
        for i in range(5):
            self._rand.shuffle(self._members)
        # Set special roles first
        for role in self._config.special_roles:
            # Get member that will have this role
            member = self._members.pop()
            self.players.append(role(member))
        # Then get the remaining normal mafia needed
        for i in range(self._config.starting_mafia - self.total_mafia):
            member = self._members.pop()
            self.players.append(self.ctx.bot.mafia_role(member))
        # The rest are citizens
        for member in self._members:
            self.players.append(self.ctx.bot.citizen_role(member))

    async def setup_channels(self):
        # Get category, create if it doesn't exist yet
        category = await self.ctx.guild.create_category_channel("MAFIA GAME")
        channels_needed = collections.defaultdict(dict)
        # All of these channel overwrites are the same concept:
        # Everyone role has read_messages disabled, send_messages enabled (will swap based on day/night)
        # Bot has read_messages enabled, send_messages enabled
        # The person has read_messages enabled
        # This allows read messages to be overridden by the person, making sure only they can
        # see the channel, it will never be touched. We will change send_messages only on the
        # everyone role, allowing only one update for everyone in a single role.
        # We cannot use roles for this task, because everyone can see other people's roles

        # Info channel
        channels_needed["info"][
            self.ctx.guild.default_role
        ] = default_role_disabled_overwrites
        channels_needed["info"][self.ctx.guild.me] = bot_overwrites
        # Chat channel
        channels_needed["chat"][self.ctx.guild.default_role] = default_role_overwrites
        channels_needed["chat"][self.ctx.guild.me] = bot_overwrites
        # Mafia channel
        channels_needed["mafia"][self.ctx.guild.default_role] = default_role_overwrites
        channels_needed["mafia"][self.ctx.guild.me] = bot_overwrites
        # Mafia channel
        channels_needed["dead"][self.ctx.guild.default_role] = default_role_overwrites
        channels_needed["dead"][self.ctx.guild.me] = bot_overwrites
        for player in self.players:
            if player.is_mafia:
                channels_needed["mafia"][player.member] = user_overwrites
        # For each player, add their overwrite to the channel
        for player in self.players:
            channels_needed["chat"][player.member] = user_overwrites
            channels_needed["info"][player.member] = user_overwrites
            channels_needed[player][
                self.ctx.guild.default_role
            ] = default_role_overwrites
            channels_needed[player][player.member] = user_overwrites
            channels_needed[player][self.ctx.guild.me] = bot_overwrites
        # Now simply set all channels and overwrites
        for player, overwrite in channels_needed.items():
            # Save mafia channel for night tasks
            if player == "mafia":
                current_channel = await category.create_text_channel(
                    player, overwrites=overwrite
                )
                self.mafia_chat = current_channel
            # Save the chat channel for day tasks
            elif player == "chat":
                current_channel = await category.create_text_channel(
                    player, overwrites=overwrite
                )
                self.chat = current_channel
                await current_channel.send("@here The game is about to start")
            elif player == "info":
                current_channel = await category.create_text_channel(
                    player, overwrites=overwrite
                )
                self.info = current_channel
            elif player == "dead":
                current_channel = await category.create_text_channel(
                    player, overwrites=overwrite
                )
                self.dead_chat = current_channel
            # All personal channels
            else:
                channel = player.member.display_name.lower()
                current_channel = await category.create_text_channel(
                    channel,
                    overwrites=overwrite,
                    topic=f"Your role is {player}",
                )
                player.set_channel(current_channel)
                msg = await current_channel.send(player.startup_channel_message(self))
                await msg.pin()

    async def lock_chat_channel(self):
        await self.chat.set_permissions(
            self.ctx.guild.default_role, overwrite=default_role_disabled_overwrites
        )

    async def unlock_chat_channel(self):
        await self.chat.set_permissions(
            self.ctx.guild.default_role, overwrite=default_role_overwrites
        )

    async def lock_mafia_channel(self):
        await self.mafia_chat.set_permissions(
            self.ctx.guild.default_role, overwrite=default_role_disabled_overwrites
        )

    async def unlock_mafia_channel(self):
        await self.mafia_chat.set_permissions(
            self.ctx.guild.default_role, overwrite=default_role_overwrites
        )

    async def play(self):
        """Handles the preparation and the playing of the game"""
        await self._prepare()
        await self._start()

    async def redo(self):
        await self.cleanup_channels()
        await self.start()

    async def _prepare(self):
        """All the setup needed for the game to play"""
        # Variables just for easy setting for testing
        wait_length_for_players_to_join = 30
        minimum_players_needed = 3

        ctx = self.ctx
        amount_of_specials = [(k, 0) for k in ctx.bot.__special_roles__]
        menu = ctx.bot.MafiaMenu(source=ctx.bot.MafiaPages(amount_of_specials, ctx))
        # Get max players
        msg = await ctx.send(
            "Starting new game of Mafia! Please first select how many players "
            "you want to allow to play the game at maximum?"
        )
        answer = await ctx.bot.wait_for(
            "message", check=ctx.bot.min_max_check(ctx, minimum_players_needed, 100)
        )
        max_players = int(answer.content)
        # Min players
        msg = await ctx.send("How many players at minimum?")
        answer = await ctx.bot.wait_for(
            "message",
            check=ctx.bot.min_max_check(ctx, minimum_players_needed, max_players),
        )
        min_players = int(answer.content)

        # Now start waiting for the players to actually join
        embed = discord.Embed(
            title="Mafia game!",
            description=f"Press \N{WHITE HEAVY CHECK MARK} to join! Waiting till at least {min_players} join. "
            f"After that will wait for {wait_length_for_players_to_join} seconds for the rest of the players to join",
            thumbnail=ctx.guild.icon_url,
        )
        game_players = set()
        embed.set_footer(text=f"{len(game_players)}/{min_players} Needed to join")
        msg = await ctx.send(embed=embed)
        await msg.add_reaction("\N{WHITE HEAVY CHECK MARK}")

        timer_not_started = True
        # Start the event here so that the update can use it
        join_event = asyncio.Event()

        async def update_embed(start_timeout=False):
            if start_timeout:
                nonlocal timer_not_started
                timer_not_started = False
                embed.description += f"\n\nMin players reached! Players locked in, waiting {wait_length_for_players_to_join} seconds or till max players reached"
                embed.set_footer(
                    text=f"{len(game_players)}/{min_players} Needed to join"
                )
                await msg.edit(embed=embed)
                await asyncio.sleep(wait_length_for_players_to_join)
                join_event.set()
            else:
                embed.set_footer(
                    text=f"{len(game_players)}/{min_players} Needed to join"
                )
                await msg.edit(embed=embed)

        def check(p):
            # First don't accept any reactions that aren't actually people joining/leaving
            if p.message_id != msg.id:
                return False
            if str(p.emoji) != "\N{WHITE HEAVY CHECK MARK}":
                return False
            if p.user_id == ctx.bot.user.id:
                return False
            if p.event_type == "REACTION_ADD":
                game_players.add(p.user_id)
                # If we've hit the max, finish
                if len(game_players) == max_players:
                    return True
            # Only allow people to leave if we haven't hit the min
            if p.event_type == "REACTION_REMOVE" and timer_not_started:
                game_players.remove(p.user_id)
            ctx.bot.loop.create_task(
                update_embed(
                    start_timeout=len(game_players) == min_players and timer_not_started
                )
            )

        done, pending = await asyncio.wait(
            [
                self.ctx.bot.loop.create_task(
                    ctx.bot.wait_for("raw_reaction_add", check=check)
                ),
                self.ctx.bot.loop.create_task(
                    ctx.bot.wait_for("raw_reaction_remove", check=check)
                ),
                self.ctx.bot.loop.create_task(join_event.wait()),
            ],
            return_when=asyncio.FIRST_COMPLETED,
            timeout=300,
        )
        # If nothing was done, then the timeout happened
        if not done:
            raise asyncio.TimeoutError()

        for task in pending:
            task.cancel()

        # Get the member objects
        game_players = await ctx.guild.query_members(user_ids=list(game_players))
        admins = [p.mention for p in game_players if p.guild_permissions.administrator]
        if admins:
            await ctx.send(
                "There are admins in this game, which means I cannot hide the "
                f"game channels from them. I will DM you the role you have {','.join(admins)}"
                ". Please only check the corresponding channel and the chat channel. "
                "Don't chat during the night, only respond to prompts in your channel. **Please "
                "make sure your DMs are open on this server, the game WILL fail to start if I can't "
                "DM you.**"
            )

        # Now do the handling of roles
        # Get amount of Mafia
        msg = await ctx.send(
            f"How many mafia members (including special mafia members; Between 1 and {int(len(game_players) / 2)})?"
        )
        answer = await ctx.bot.wait_for(
            "message", check=ctx.bot.min_max_check(ctx, 1, int(len(game_players) / 2))
        )
        amount_of_mafia = int(answer.content)
        # Special roles
        menu.amount_of_players = len(game_players)
        menu.amount_of_mafia = amount_of_mafia
        await menu.start(ctx, wait=True)

        # Now that the setup is done, create the configuration for the game
        self._config = ctx.bot.MafiaGameConfig(
            menu.amount_of_mafia,
            # The special roles
            [role for (role, amt) in amount_of_specials for i in range(amt)],
            ctx,
        )
        self._members = game_players

    async def _cycle(self):
        """Performs one cycle of day/night"""
        # Do day tasks and check for winner
        await self.pre_day()
        if winner := self.check_winner():
            await self.chat.send(f"Winner: {winner}!. (Will remove game in 1 minute)")
            return True
        await self.day_tasks()
        if winner := self.check_winner():
            await self.chat.send(f"Winner: {winner}!. (Will remove game in 1 minute)")
            return True
        self._day += 1
        # Do night tasks and check for winner
        await self.night_tasks()
        if winner := self.check_winner():
            await self.chat.send(f"Winner: {winner}!. (Will remove game in 1 minute)")
            return True

    async def _start(self):
        """Play the game"""
        # Sort out the players
        await self.pick_players()
        # Setup the categories and channels
        await self.setup_channels()
        while True:
            if await self._cycle():
                break

        # The game is done, allow dead players to chat again
        for player in self.players:
            if player.dead:
                await self.chat.set_permissions(player.member, read_messages=True)

        # Send a message with everyone's roles
        msg = "\n".join(
            f"{player.member.display_name} ({player})" for player in self.players
        )
        await self.ctx.send(msg)
        await asyncio.sleep(60)
        await self.cleanup_channels()

    def stop(self):
        if self._game_task:
            self._game_task.cancel()

    async def night_tasks(self):
        await self.night_notification()
        await self.lock_chat_channel()
        await self.unlock_mafia_channel()
        # Schedule tasks. Add the asyncio sleep to *ensure* we sleep that long
        # even if everyone finishes early
        tasks = [
            self.ctx.bot.loop.create_task(asyncio.sleep(self._config.night_length))
        ]
        msg = "\n".join(
            player.member.name
            for player in self.players
            if not player.is_mafia and not player.dead
        )
        nominations = {}

        await self.mafia_chat.send(
            "**Type `>>nominate Member` to nominate someone to be killed** Alive players are:\n"
            f"{msg}"
        )

        # We need the actual message object, so that we can count reactions on it after
        msg = None

        async def nominate_player():
            nonlocal msg
            await self.ctx.bot.wait_for(
                "message",
                check=self.ctx.bot.nomination_check(
                    self, nominations, self.mafia_chat, True
                ),
            )
            player = nominations["nomination"]
            # If we've passed to here that's two nominations
            msg = await self.mafia_chat.send(
                f"{player.member.display_name} is nominated for killing! React to vote. "
                "By the end of the night, all the votes will be tallied. If majority voted yes, they "
                "will be killed"
            )
            await msg.add_reaction("\N{THUMBS UP SIGN}")
            await msg.add_reaction("\N{THUMBS DOWN SIGN}")

        tasks.append(nominate_player())

        for p in self.players:
            # Dead players can't do shit
            if p.dead:
                continue
            task = self.ctx.bot.loop.create_task(p.night_task(self))
            tasks.append(task)

        done, pending = await asyncio.wait(
            tasks, timeout=self._config.night_length, return_when=asyncio.ALL_COMPLETED
        )
        # Cancel pending tasks, times up
        for task in pending:
            task.cancel()

        # Now check for the nominated player, if it's here then there was a killing vote
        if msg:
            # Reactions aren't updated in place, need to refetch
            msg = await msg.channel.fetch_message(msg.id)
            count = (
                discord.utils.get(msg.reactions, emoji="\N{THUMBS UP SIGN}").count - 1
            )
            player = nominations["nomination"]
            if count > self.total_mafia / 2:
                player.kill()

        await self.lock_mafia_channel()

    async def pre_day(self):
        # Check if anyone was killed
        if self._day > 1:
            killed = []

            for player in self.players:
                # Already dead people
                if player.dead:
                    continue
                # If saved, they can't have been killed
                if player.saved_for_tonight:
                    player.saved_for_tonight = False
                    player.killed = False
                if player.killed:
                    player.dead = True
                    killed.append(player)
                    # This will permanently disable them from talking
                    await self.chat.set_permissions(
                        player.member, read_messages=True, send_messages=False
                    )
                    if player.channel:
                        await player.channel.set_permissions(
                            player.member, read_messages=True, send_messages=False
                        )

            notifs = []
            if killed:
                for player in killed:
                    notifs.append(
                        f"{player.member.mention}({player}) was slain by the mafia"
                    )
                    await self.dead_chat.set_permissions(
                        player.member, read_messages=True
                    )
            else:
                notifs.append("No one was killed last night!")

            await self.day_notification(*notifs)
        else:
            await self.day_notification("Game has started!")

        # Unlock the channel
        await self.unlock_chat_channel()

    async def day_tasks(self):
        day_length = (
            self._config.day_length if self._day > 1 else self._config.day_length / 2
        )

        # Ensure day takes this long no matter what
        async def day_sleep():
            await asyncio.sleep(day_length - 20)
            await self.chat.send("Day is about to end in 20 seconds")
            await asyncio.sleep(20)

        tasks = [self.ctx.bot.loop.create_task(day_sleep())]

        nominations = {}
        msg = None

        async def nominate_player():
            nonlocal msg
            await self.ctx.bot.wait_for(
                "message",
                check=self.ctx.bot.nomination_check(self, nominations, self.chat),
            )
            # If we've passed to here that's two nominations
            msg = await self.chat.send(
                f"{nominations['nomination'].member.display_name} is nominated for hanging! React to vote "
                "By the end of the day, all the votes will be tallied. If majority voted yes, they "
                "will be hung"
            )
            await msg.add_reaction("\N{THUMBS UP SIGN}")
            await msg.add_reaction("\N{THUMBS DOWN SIGN}")

        if self._day > 1:
            tasks.append(self.ctx.bot.loop.create_task(nominate_player()))
        _, pending = await asyncio.wait(
            tasks, timeout=day_length, return_when=asyncio.ALL_COMPLETED
        )
        # Cancel pending tasks, times up
        for task in pending:
            task.cancel()

        # Now check for msg, if it's here then there was a hanging vote
        if msg:
            # Reactions aren't updated in place, need to refetch
            msg = await msg.channel.fetch_message(msg.id)
            count = (
                discord.utils.get(msg.reactions, emoji="\N{THUMBS UP SIGN}").count - 1
            )
            # The lynching happened
            if count > self.total_alive / 2:
                player = nominations["nomination"]
                player.dead = True
                player.lynched = True
                await self.chat.set_permissions(
                    player.member, read_messages=True, send_messages=False
                )
                if player.channel:
                    await player.channel.set_permissions(
                        player.member, read_messages=True, send_messages=False
                    )
                await self.day_notification(
                    f"The town lynched **{player.member.display_name}**({player})"
                )
                await self.dead_chat.set_permissions(player.member, read_messages=True)

        await self.lock_chat_channel()

    async def cleanup_channels(self):
        try:
            category = self.chat.category
            for channel in category.channels:
                await channel.delete()

            await category.delete()
        except (AttributeError, discord.HTTPException):
            return


def setup(bot):
    bot.MafiaGameConfig = MafiaGameConfig
    bot.MafiaGame = MafiaGame


def teardown(bot):
    del bot.MafiaGameConfig
    del bot.MafiaGame
