from __future__ import annotations

import asyncio
import dataclasses
from extensions.players import Player
import discord
from discord.mentions import AllowedMentions
import random
import typing

if typing.TYPE_CHECKING:
    from extensions import players as _players, utils


default_role_overwrites = discord.PermissionOverwrite(
    read_messages=False,
    send_messages=True,
    read_message_history=False,
    attach_files=False,
    add_reactions=False,
)
default_role_disabled_overwrites = discord.PermissionOverwrite(
    read_messages=False,
    send_messages=False,
    read_message_history=False,
    attach_files=False,
    add_reactions=False,
)
bot_overwrites = discord.PermissionOverwrite(
    read_messages=True,
    send_messages=True,
    attach_files=True,
    add_reactions=True,
)
user_overwrites = discord.PermissionOverwrite(read_messages=True)


@dataclasses.dataclass
class MafiaGameConfig:
    starting_mafia: int
    special_roles: typing.List[_players.Player]
    ctx: utils.CustomContext
    night_length: int = 90
    day_length: int = 120

class MafiaGame:
    def __init__(self, ctx: utils.CustomContext, *, config: str):
        # The discord members, we'll produce our list of players later
        self._members: typing.Optional[typing.List[discord.Member]] = None
        # The actual players of the game
        self.players: typing.List[_players.Player] = []

        self.ctx: utils.CustomContext = ctx
        self.is_day: bool = True

        # Different chats needed
        self.category = discord.CategoryChannel = None
        self.chat: typing.Optional[discord.TextChannel] = None
        self.info: typing.Optional[discord.TextChannel] = None
        self.jail: typing.Optional[discord.TextChannel] = None
        self.jail_webhook: typing.Optional[discord.Webhook] = None
        self.mafia_chat: typing.Optional[discord.TextChannel] = None
        self.dead_chat: typing.Optional[discord.TextChannel] = None

        self._alive_game_role_name: str = "Alive Players"
        self._alive_game_role: typing.Optional[discord.Role] = None

        self._rand = random.SystemRandom()
        self._config: typing.Optional[MafiaGameConfig] = None
        # The preconfigured option that can be provided
        self._preconfigured_config: str = config
        self._day: int = 1
        self._role_list: typing.Optional[list] = None

    @property
    def total_mafia(self) -> int:
        return sum(1 for player in self.players if player.is_mafia and not player.dead)

    @property
    def total_citizens(self) -> int:
        return sum(
            1 for player in self.players if player.is_citizen and not player.dead
        )

    @property
    def total_alive(self) -> int:
        return sum(1 for player in self.players if not player.dead)

    @property
    def total_players(self) -> int:
        return len(self.players)

    @property
    def godfather(self) -> _players.Player:
        for player in self.players:
            if player.is_godfather and not player.dead:
                return player

    async def night_notification(self):
        embed = discord.Embed(
            title=f"Night {self._day - 1}",
            description="Check your private channels",
            colour=0x0A0A86,
        )
        embed.set_thumbnail(
            url="https://www.jing.fm/clipimg/full/132-1327252_half-moon-png-images-moon-clipart-png.png"
        )
        await self.chat.send(content=self._alive_game_role.mention, embed=embed)

    async def day_notification(self, *deaths: Player):
        """Creates a notification image with all of todays notifications"""
        async with self.info.typing():
            buffer = await self.ctx.bot.create_day_image(self, list(deaths))
            await self.info.send(file=discord.File(buffer, filename="day.png"))

    def check_winner(self) -> bool:
        """Loops through all the winners and checks their win conditions"""
        for player in self.players:
            if not player.win_is_multi and player.win_condition(self):
                return True

        return False

    def get_winners(self) -> typing.List[Player]:
        """Returns all winners of this game"""
        return [p for p in self.players if p.win_condition(self)]

    async def choose_godfather(self):
        godfather = self._rand.choice(
            [
                p
                for p in self.players
                # We don't want to choose special mafia
                if p.role.__class__ is self.ctx.bot.role_mapping.get("Mafia")
            ]
        )
        godfather.role.is_godfather = True

        await godfather.channel.send("You are the godfather!")

    async def pick_players(self):
        player_cls = self.ctx.bot.mafia_player
        mafia_cls = self.ctx.bot.role_mapping["Mafia"]
        citizen_cls = self.ctx.bot.role_mapping["Citizen"]

        # I'm paranoid
        for i in range(5):
            self._rand.shuffle(self._members)
        # Set special roles first
        for role in self._config.special_roles:
            # Get member that will have this role
            member = self._members.pop()
            self.players.append(player_cls(member, self.ctx, role()))
        # Then get the remaining normal mafia needed
        for i in range(self._config.starting_mafia - self.total_mafia):
            member = self._members.pop()
            self.players.append(player_cls(member, self.ctx, mafia_cls()))
        # The rest are citizens
        while self._members:
            member = self._members.pop()
            self.players.append(player_cls(member, self.ctx, citizen_cls()))

    async def _claim_category(self) -> typing.Any[discord.CategoryChannel, None]:
        """Loops through the categories available on the server, returning
        a category we can lay claim to and use for caching. If it doesn't
        find one, it will return None
        """
        for category in self.ctx.guild.categories:
            # If this isn't the category name, we don't care
            if category.name != "MAFIA GAME":
                continue
            # If it's been claimed, we don't want this one
            if category.id in self.ctx.bot.claimed_categories:
                continue

            # Otherwise, if we're here, then it's a good category to claim
            self.ctx.bot.claimed_categories[category.id] = self
            return category

    async def _setup_category_channels(self, category: discord.CategoryChannel):
        # Setup all the overwrites needed
        info_overwrites = {
            self.ctx.guild.default_role: default_role_disabled_overwrites,
            self.ctx.guild.me: bot_overwrites,
        }
        chat_overwrites = {
            self.ctx.guild.default_role: default_role_overwrites,
            self.ctx.guild.me: bot_overwrites,
        }
        dead_overwrites = {
            self.ctx.guild.default_role: default_role_overwrites,
            self.ctx.guild.me: bot_overwrites,
        }
        mafia_overwrites = {
            self.ctx.guild.default_role: default_role_overwrites,
            self.ctx.guild.me: bot_overwrites,
        }
        jail_overwrites = {
            self.ctx.guild.default_role: default_role_overwrites,
            self.ctx.guild.me: bot_overwrites,
        }

        # Get each channel, if it exists edit... if not create
        info = discord.utils.get(category.text_channels, name="info")
        chat = discord.utils.get(category.text_channels, name="chat")
        dead = discord.utils.get(category.text_channels, name="dead")
        mafia = discord.utils.get(category.text_channels, name="mafia")
        jail = discord.utils.get(category.text_channels, name="jail")

        if info:
            if info.overwrites != info_overwrites:
                await info.edit(overwrites=info_overwrites)
        else:
            info = await category.create_text_channel(
                "info", overwrites=info_overwrites
            )
        if chat:
            if chat.overwrites != chat_overwrites:
                await chat.edit(overwrites=chat_overwrites)
        else:
            chat = await category.create_text_channel(
                "chat", overwrites=chat_overwrites
            )
        if dead:
            if dead.overwrites != dead_overwrites:
                await dead.edit(overwrites=dead_overwrites)
        else:
            dead = await category.create_text_channel(
                "dead", overwrites=dead_overwrites
            )
        if mafia:
            if mafia.overwrites != mafia_overwrites:
                await mafia.edit(overwrites=mafia_overwrites)
        else:
            mafia = await category.create_text_channel(
                "mafia", overwrites=mafia_overwrites
            )
        if jail:
            if jail.overwrites != jail_overwrites:
                await jail.edit(overwrites=jail_overwrites)
        else:
            jail = await category.create_text_channel(
                "jail", overwrites=jail_overwrites
            )
        # Jail has a special webhook, check that
        webhooks = await jail.webhooks()
        jail_webhook = discord.utils.get(webhooks, name="Jailor")
        if jail_webhook is None:
            b = await self.ctx.bot.user.avatar_url.read()
            jail_webhook = await jail.create_webhook(name="Jailor", avatar=b)

        # Now set each one
        self.info = info
        self.chat = chat
        self.dead_chat = dead
        self.mafia_chat = mafia
        self.jail = jail
        self.jail_webhook = jail_webhook

    async def _prune_category_channels(self, category: discord.CategoryChannel):
        """Removes all the personal channels in the category, leaving just the
        normal default channels"""
        for channel in category.text_channels:
            if channel.name not in ("info", "chat", "dead", "mafia", "jail"):
                await channel.delete()

    async def _setup_category(self):
        # Try to claim a category
        category = await self._claim_category()

        # If there isn't one available to claim, create and claim
        if category is None:
            category = await self.ctx.guild.create_category_channel("MAFIA GAME")
            self.ctx.bot.claimed_categories[category.id] = self

        self.category = category
        # Make sure the default channels are setup properly
        await self._setup_category_channels(category)
        # Then prune all the extra channels
        await self._prune_category_channels(category)

        return category

    async def _setup_channels(self, category: discord.CategoryChannel):
        """Receives a category with the default channels already setup, then sets up the
        rest of the players"""
        for p in self.players:
            # Let them see the mafia channel if they're mafia
            if p.is_mafia:
                await self.mafia_chat.set_permissions(
                    p.member, overwrite=user_overwrites
                )
            # Set access for info and chat
            await self.info.set_permissions(p.member, overwrite=user_overwrites)
            await self.chat.set_permissions(p.member, overwrite=user_overwrites)
            # Everyone has their own private channel, setup overwrites for them
            overwrites = {
                self.ctx.guild.default_role: default_role_overwrites,
                self.ctx.guild.me: bot_overwrites,
                p.member: user_overwrites,
            }
            # Create their channel
            channel = await category.create_text_channel(
                p.member.name, overwrites=overwrites
            )
            # Set it on the player object
            p.set_channel(channel)
            # Send them their startup message and pin it
            msg = await channel.send(p.role.startup_channel_message(self, p))
            await msg.pin()

    async def _setup_amount_players(self) -> typing.Tuple[int, int]:
        ctx = self.ctx
        minimum_players_needed = 3
        # Get max players
        await ctx.send(
            "Starting new game of Mafia! Please first select how many players "
            "you want to allow to play the game at maximum?"
        )
        answer = await ctx.bot.wait_for(
            "message", check=ctx.bot.min_max_check(ctx, minimum_players_needed, 25)
        )
        max_players = int(answer.content)
        # Min players
        await ctx.send("How many players at minimum?")
        answer = await ctx.bot.wait_for(
            "message",
            check=ctx.bot.min_max_check(ctx, minimum_players_needed, max_players),
        )
        min_players = int(answer.content)

        return min_players, max_players

    async def _setup_players(
        self, min_players: int, max_players: int
    ) -> typing.List[discord.Member]:
        wait_length_for_players_to_join = 60
        ctx = self.ctx
        game_players = set()

        async def wait_for_players():
            nonlocal game_players
            game_players = set()
            # Now start waiting for the players to actually join
            embed = discord.Embed(
                title="Mafia game!",
                description=f"Press \N{WHITE HEAVY CHECK MARK} to join! Waiting till at least {min_players} join. "
                f"After that will wait for {wait_length_for_players_to_join} seconds for the rest of the players to join",
                thumbnail=ctx.guild.icon_url,
            )
            embed.set_footer(text=f"{len(game_players)}/{min_players} Needed to join")
            msg = await ctx.send(embed=embed)
            await msg.add_reaction("\N{WHITE HEAVY CHECK MARK}")

            timer_not_started = True
            # Start the event here so that the update can use it
            join_event = asyncio.Event()

            async def joining_over():
                await asyncio.sleep(wait_length_for_players_to_join)
                join_event.set()

            async def update_embed():
                nonlocal timer_not_started
                while True:
                    # We want to start timeout if we've reached min players, but haven't
                    # already started it
                    start_timeout = (
                        len(game_players) >= min_players and timer_not_started
                    )
                    if start_timeout:
                        timer_not_started = False
                        embed.description += f"\n\nMin players reached! Waiting {wait_length_for_players_to_join} seconds or till max players ({max_players}) reached"
                        ctx.create_task(joining_over())
                    embed.set_footer(
                        text=f"{len(game_players)}/{min_players} Needed to join"
                    )
                    await msg.edit(embed=embed)
                    await asyncio.sleep(2)

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
                if p.event_type == "REACTION_REMOVE":
                    try:
                        game_players.remove(p.user_id)
                    except KeyError:
                        pass

            done, pending = await asyncio.wait(
                [
                    ctx.create_task(ctx.bot.wait_for("raw_reaction_add", check=check)),
                    ctx.create_task(
                        ctx.bot.wait_for("raw_reaction_remove", check=check)
                    ),
                    ctx.create_task(update_embed()),
                    ctx.create_task(join_event.wait()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
                timeout=300,
            )

            for task in pending:
                task.cancel()

            # If nothing was done, then the timeout happened
            if not done:
                raise asyncio.TimeoutError()

            return len(game_players) >= min_players

        for _ in range(5):
            if await wait_for_players():
                break

        if len(game_players) < min_players:
            await ctx.send("Failed to get players too many times")
            raise Exception()

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

        return game_players

    async def _setup_amount_mafia(self, players: int) -> int:
        ctx = self.ctx
        # Get amount of Mafia
        await ctx.send(
            f"How many mafia members (including special mafia members; Between 1 and {int(players / 2)})?"
        )
        answer = await ctx.bot.wait_for(
            "message", check=ctx.bot.min_max_check(ctx, 1, int(players / 2))
        )
        amount_of_mafia = int(answer.content)

        return amount_of_mafia

    async def _setup_special_roles(
        self, players: int, mafia: int
    ) -> typing.List[typing.Tuple[_players.Player, int]]:
        ctx = self.ctx
        amount_of_specials = [
            (v, 0)
            for k, v in ctx.bot.role_mapping.items()
            if k not in ["Mafia", "Citizen"]
        ]
        menu = ctx.bot.MafiaMenu(source=ctx.bot.MafiaPages(amount_of_specials, ctx))

        menu.amount_of_players = players
        menu.amount_of_mafia = mafia
        await menu.start(ctx, wait=True)

        return amount_of_specials

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
        await self._setup_config()
        await self._game_preparation()
        await self._start()

    async def _setup_config(self):
        """All the setup needed for the game to play"""
        ctx = self.ctx
        # Get/create the alive role
        self._alive_game_role = discord.utils.get(
            ctx.guild.roles, name=self._alive_game_role_name
        )
        if self._alive_game_role is None:
            self._alive_game_role = await ctx.guild.create_role(
                name=self._alive_game_role_name, hoist=True
            )

        # Config is already set
        if self._preconfigured_config:
            # Convert hex to the stuff we care about
            (
                amount_of_mafia,
                min_players,
                max_players,
                special_roles,
            ) = ctx.bot.hex_to_players(
                self._preconfigured_config,
                # A list of only the special roles
                (
                    v
                    for k, v in ctx.bot.role_mapping.items()
                    if k not in ["Mafia", "Citizen"]
                ),
            )
            # The only setup we need to do is get the players who will player
            self._members = await self._setup_players(min_players, max_players)
            # Set the config
            self._config = ctx.bot.MafiaGameConfig(amount_of_mafia, special_roles, ctx)
        else:
            # Go through normal setup. Amount of players, letting players join, amount of mafia, special roles
            min_players, max_players = await self._setup_amount_players()
            self._members = await self._setup_players(min_players, max_players)
            amount_of_mafia = await self._setup_amount_mafia(len(self._members))
            special_roles = await self._setup_special_roles(
                len(self._members), amount_of_mafia
            )
            # Convert the tuple of player, amount to just a list of all roles
            special_roles = [role for (role, amt) in special_roles for i in range(amt)]
            # Get hex to allow them to use this setup in the future
            h = ctx.bot.players_to_hex(
                special_roles, amount_of_mafia, min_players, max_players
            )
            await self.ctx.send(
                "In the future you can provide this to the mafia start command "
                f"to use the exact same configuration:\n{h}"
            )
            # Now that the setup is done, create the configuration for the game
            self._config = ctx.bot.MafiaGameConfig(amount_of_mafia, special_roles, ctx)

        for member in self._members:
            await member.add_roles(self._alive_game_role)

    async def _game_preparation(self):
        # Sort out the players
        await self.pick_players()
        # Setup the category required
        category = await self._setup_category()
        # And setup the channels in it
        await self._setup_channels(category)
        # Now choose the godfather
        await self.choose_godfather()
        # Mafia channel must be locked
        await self.lock_mafia_channel()
        # Now that everything is done unlock the channel

    async def _cycle(self) -> bool:
        """Performs one cycle of day/night"""
        # Do day tasks and check for winner
        await self.pre_day()
        if self.check_winner():
            return True
        await self.day_tasks()
        if self.check_winner():
            return True
        self._day += 1
        # Do night tasks and check for winner
        await self.night_tasks()
        if self.check_winner():
            return True

        # Schedule all the post night tasks
        for player in self.players:
            self.ctx.create_task(player.post_night_task(self))

        return False

    async def _start(self):
        """Play the game"""
        while True:
            if await self._cycle():
                break

        # The game is done, allow dead players to chat again
        for player in self.players:
            if player.dead:
                await self.chat.set_permissions(player.member, read_messages=True)

        # Send winners
        winners = self.get_winners()
        msg = "Winners are:\n{}".format(
            "\n".join(f"{winner.member.name} ({winner})" for winner in winners)
        )
        await self.chat.send(msg)
        # Send a message with everyone's roles
        msg = "\n".join(
            f"{player.member.mention} ({player})" for player in self.players
        )
        await self.ctx.send(msg, allowed_mentions=AllowedMentions(users=False))
        await asyncio.sleep(60)
        await self.cleanup()

    async def night_tasks(self):
        await self.night_notification()
        await self.lock_chat_channel()
        await self.unlock_mafia_channel()
        # Schedule tasks. Add the asyncio sleep to *ensure* we sleep that long
        # even if everyone finishes early
        async def night_sleep():
            await asyncio.sleep(self._config.night_length - 20)
            await self.mafia_chat.send("Night is about to end in 20 seconds")
            await asyncio.sleep(20)

        tasks = [self.ctx.create_task(night_sleep())]
        mapping = {
            count: player.member.name
            for count, player in enumerate(self.players)
            if not player.is_mafia and not player.dead
        }
        msg = "\n".join(f"{count}: {player}" for count, player in mapping.items())

        godfather = self.godfather
        if godfather.night_role_blocked:
            await self.mafia_chat.send("The godfather cannot kill tonight!")
        else:
            await self.mafia_chat.send(
                "**Godfather:** Type the number assigned to a member to kill someone. "
                f"Alive players are:\n{msg}"
            )

            async def mafia_check():
                msg = await self.ctx.bot.wait_for(
                    "message",
                    check=self.ctx.bot.mafia_kill_check(self, mapping),
                )
                player = mapping[int(msg.content)]
                player = self.ctx.bot.get_mafia_player(self, player)
                # They were protected during the day
                if (
                    player.protected_by
                    and player.protected_by.defense_type >= godfather.attack_type
                ):
                    await self.mafia_chat.send(
                        "That target has been protected for the night! Your attack failed!"
                    )
                else:
                    player.kill(godfather)
                    await self.mafia_chat.send("\N{THUMBS UP SIGN}")

            tasks.append(mafia_check())

        for p in self.players:
            if p.dead or p.night_role_blocked:
                p.night_role_blocked = False
                continue
            task = self.ctx.create_task(p.night_task(self))
            tasks.append(task)

        _, pending = await asyncio.wait(
            tasks, timeout=self._config.night_length, return_when=asyncio.ALL_COMPLETED
        )
        # Cancel pending tasks, times up
        for task in pending:
            task.cancel()

        await self.lock_mafia_channel()

    async def _handle_killing(self, killer: Player, killed: Player) -> typing.List[str]:
        # The notifications that will be sent to the day chat
        notifs = []
        protector = killed.protected_by
        # If protected, check the power of protection against attacking
        if protector and killer.attack_type <= protector.defense_type:
            await killed.channel.send(killed.protected_by.save_message)
            # If the killer was mafia, we also want to notify them of the saving
            if killer.is_mafia:
                await self.mafia_chat.send(
                    "{killed} was saved last night from your attack!"
                )
        # There was no protection, they're dead
        else:
            # If they were cleaned, let the cleaner know their role
            if cleaner := killed.cleaned_by:
                await cleaner.channel.send(
                    f"You cleaned {killed.member.name} up, their role was {killed}"
                )
            # If they suicided, send suicide message
            elif killer == killed:
                notifs.append(
                    killed.suicide_message.format(killer=killer, killed=killed)
                )
                await self.chat.send(
                    f"- {killed.member.mention} ({killed}) suicided during the night!"
                )
            # Otherwise send killed message
            else:
                notifs.append(
                    killer.attack_message.format(killer=killer, killed=killed)
                )
                await self.chat.send(
                    f"- {killed.member.mention} ({killed}) was killed during the night!"
                )
            # Set them as dead, remove alive role
            killed.dead = True
            await killed.member.remove_roles(self._alive_game_role)
            # This will permanently disable them from talking
            await self.chat.set_permissions(
                killed.member, read_messages=True, send_messages=False
            )
            if killed.channel:
                await killed.channel.set_permissions(
                    killed.member, read_messages=True, send_messages=False
                )
            if killed.is_mafia:
                await self.mafia_chat.set_permissions(
                    killed.member, read_messages=True, send_messages=False
                )
            await self.dead_chat.set_permissions(killed.member, read_messages=True)
            # Now if they were godfather, choose new godfather
            if killed.is_godfather:
                await self.choose_godfather()
                killed.role.is_godfather = False
            # If they had an executionor targetting them, they become a jester
            if killed.executionor_target and not killed.executionor_target.dead:
                killed.executionor_target.role = self.ctx.bot.role_mapping["Jester"]()

        return notifs

    async def pre_day(self):
        deaths = []
        if self._day > 1:
            for player in self.players:
                if player.dead:
                    continue
                if killer := player.killed_by:
                    await self._handle_killing(killer, player)
                    deaths.append(player)

            await self.day_notification(*deaths)
        else:
            await self.day_notification()

        # Cleanup everyone's attrs
        for p in self.players:
            if not p.dead:
                p.cleanup_attrs()
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

        tasks = [self.ctx.create_task(day_sleep())]

        nominations = {}
        msg: typing.Optional[discord.Message] = None

        async def nominate_player():
            nonlocal msg
            await self.ctx.bot.wait_for(
                "message",
                check=self.ctx.bot.nomination_check(self, nominations, self.chat),
            )
            # If we've passed to here that's two nominations
            msg = await self.chat.send(
                f"{nominations['nomination'].member.mention} is nominated for hanging! React to vote "
                "By the end of the day, all the votes will be tallied. If majority voted yes, they "
                "will be hung"
            )
            await msg.add_reaction("\N{THUMBS UP SIGN}")
            await msg.add_reaction("\N{THUMBS DOWN SIGN}")

        for p in self.players:
            # Dead players can't do shit
            if p.dead:
                continue
            task = self.ctx.create_task(p.day_task(self))
            tasks.append(task)

        if self._day > 1:
            tasks.append(self.ctx.create_task(nominate_player()))
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
            yes_votes = discord.utils.get(msg.reactions, emoji="\N{THUMBS UP SIGN}")
            no_votes = discord.utils.get(msg.reactions, emoji="\N{THUMBS DOWN SIGN}")
            yes_count = 0
            no_count = 0
            async for user in yes_votes.users():
                if [p for p in self.players if p.member == user and not p.dead]:
                    yes_count += 1
            async for user in no_votes.users():
                if [p for p in self.players if p.member == user and not p.dead]:
                    no_count += 1
            # The lynching happened
            if yes_count > no_count:
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
                if player.is_mafia:
                    await self.mafia_chat.set_permissions(
                        player.member, read_messages=True, send_messages=False
                    )
                    if player.is_godfather:
                        try:
                            await self.choose_godfather()
                        # If there's mafia, citizens win. Just return, the cycle will handle it
                        except IndexError:
                            return
                await self.day_notification()
                await player.member.remove_roles(self._alive_game_role)
                await self.dead_chat.set_permissions(player.member, read_messages=True)

        await self.lock_chat_channel()

    async def cleanup(self):
        for player in self.players:
            await player.member.remove_roles(self._alive_game_role)

        if category := self.category:
            # In order to cleanup the channels we want to remove all personal channels
            await self._prune_category_channels(category)
            # Then make sure the category channels are setup as they should be
            await self._setup_category_channels(category)

            # Now purge the channels
            await asyncio.wait(
                [
                    self.info.purge(limit=None),
                    self.dead_chat.purge(limit=None),
                    self.jail.purge(limit=None),
                    self.chat.purge(limit=None),
                    self.mafia_chat.purge(limit=None),
                ],
                return_when=asyncio.ALL_COMPLETED,
            )
            # Done with cleanup, remove our claim
            del self.ctx.bot.claimed_categories[self.category.id]


def setup(bot):
    bot.MafiaGameConfig = MafiaGameConfig
    bot.MafiaGame = MafiaGame
    # This is used for caching the categories, and claiming them

    # this is the only attribute like this, but we do NOT want to override
    # if it already exists. We would remove games that can already be running's
    # claims, and claim over them. This would cause chaos. Games can still be played
    # even if this is reloaded, as they will be stale references still stored in mafia
    if not hasattr(bot, "claimed_categories"):
        bot.claimed_categories = {}


def teardown(bot):
    del bot.MafiaGameConfig
    del bot.MafiaGame
