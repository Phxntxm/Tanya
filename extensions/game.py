from __future__ import annotations

import asyncio
import collections
import dataclasses
import math
import random
import typing

import discord
from discord.mentions import AllowedMentions

from extensions.players import Player

if typing.TYPE_CHECKING:
    from extensions import players as _players, utils

can_send_overwrites = discord.PermissionOverwrite(send_messages=True)
cannot_send_overwrites = discord.PermissionOverwrite(send_messages=False)
can_read_overwrites = discord.PermissionOverwrite(read_messages=True)
everyone_overwrites = discord.PermissionOverwrite(
    read_messages=False,
    send_messages=False,
    attach_files=False,
    add_reactions=False,
)
bot_overwrites = discord.PermissionOverwrite(
    read_messages=True,
    send_messages=True,
    add_reactions=True,
)


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
        self._day_notifications = collections.defaultdict(list)
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

    # Notification methods

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

    async def day_notification(self, *notifications: str):
        """Creates a notification embed with all of todays notifications"""
        msg, current_notifications = self._day_notifications.get(self._day, (None, []))
        current_notifications.extend(notifications)
        fmt = "Roles Alive:\n"
        # Get alive players to add to alive roles
        alive_players = {}
        for player in self.players:
            if player.dead:
                continue
            alive_players[str(player)] = alive_players.get(str(player), 0) + 1
        fmt += "\n".join(f"{key}: {count}" for key, count in alive_players.items())
        fmt += "\n\n"
        # If we're not on day one, notify that you can nominate
        if self._day > 1:
            fmt += f"**Type >>nominate member to nominate someone to be lynched**. Chat in {self.chat.mention}\n\n"
        else:
            fmt += f"Chat in {self.chat.mention}\n\n"
        # Add the recent actions
        fmt += "**Recent Actions**\n"
        fmt += "\n".join(current_notifications)

        embed = discord.Embed(
            title=f"Day {self._day}", description=fmt, colour=0xF6F823
        )
        embed.set_thumbnail(
            url="https://media.discordapp.net/attachments/840698427755069475/841841923936485416/Sw5vSWOjshUo40xEj-hWqfiRu8Ma2CtYjjh7prRsF6ADPk_z7znpEBf-E3i44U9Hukh3ZJOFhm9S43naa4dEA8pXX4dfAJeEv0bl.png"
        )
        if msg is None:
            msg = await self.info.send(
                content=self._alive_game_role.mention, embed=embed
            )
        else:
            await msg.edit(embed=embed)

        self._day_notifications[self._day] = [msg, current_notifications]

    # Winner methods

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

    # Channel setup methods

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
            self.ctx.guild.default_role: everyone_overwrites,
            self.ctx.guild.me: bot_overwrites,
            self._alive_game_role: cannot_send_overwrites,
        }
        chat_overwrites = {
            self.ctx.guild.default_role: everyone_overwrites,
            self.ctx.guild.me: bot_overwrites,
            self._alive_game_role: can_send_overwrites,
        }
        dead_overwrites = {
            self.ctx.guild.default_role: everyone_overwrites,
            self.ctx.guild.me: bot_overwrites,
        }
        mafia_overwrites = {
            self.ctx.guild.default_role: everyone_overwrites,
            self.ctx.guild.me: bot_overwrites,
            self._alive_game_role: can_send_overwrites,
        }
        jail_overwrites = {
            self.ctx.guild.default_role: everyone_overwrites,
            self.ctx.guild.me: bot_overwrites,
            self._alive_game_role: can_send_overwrites,
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
                    p.member, overwrite=can_read_overwrites
                )
            # Everyone has their own private channel, setup overwrites for them
            overwrites = {
                self.ctx.guild.default_role: everyone_overwrites,
                self.ctx.guild.me: bot_overwrites,
                self._alive_game_role: can_send_overwrites,
                p.member: can_read_overwrites,
            }
            # Create their channel
            channel = await category.create_text_channel(
                p.member.name, overwrites=overwrites
            )
            # Allow them to see info and chat
            await self.chat.set_permissions(p.member, read_messages=True)
            await self.info.set_permissions(p.member, read_messages=True)
            # If they're mafia let them see the mafia channel
            if p.is_mafia:
                await self.mafia_chat.set_permissions(p.member, read_messages=True)
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

    # During game channel modification

    async def lock_chat_channel(self, target: discord.Member = None):
        if target is None:
            target = self._alive_game_role
        await self.chat.set_permissions(target, overwrite=cannot_send_overwrites)

    async def unlock_chat_channel(self, target: discord.Member = None):
        if target is None:
            target = self._alive_game_role
        await self.chat.set_permissions(target, overwrite=can_send_overwrites)

    async def lock_mafia_channel(self):
        await self.mafia_chat.set_permissions(
            self._alive_game_role, overwrite=cannot_send_overwrites
        )

    async def unlock_mafia_channel(self):
        await self.mafia_chat.set_permissions(
            self._alive_game_role, overwrite=can_send_overwrites
        )

    # Pre game entry methods

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

    # Day/Night cycles

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
        await self.ctx.send(
            f"The game is over! Roles were:\n{msg}",
            allowed_mentions=AllowedMentions(users=False),
        )
        await asyncio.sleep(60)
        await self.cleanup()

    async def _cycle(self) -> bool:
        """Performs one cycle of day/night"""
        # Do day tasks and check for winner
        await self._day_phase()
        if self.check_winner():
            return True
        self._day += 1
        # Then night tasks
        await self._night_phase()
        for player in self.players:
            self.ctx.create_task(player.post_night_task(self))

        return False

    async def _day_phase(self):
        if self._day == 1:
            await asyncio.sleep(10)
            await self.chat.send("Day is ending in 20 seconds")
            await asyncio.sleep(20)
            return

        await self._day_notify_of_night_phase()
        if self.check_winner():
            return
        await self._day_discussion_phase()
        for _ in range(3):
            nominated = await self._day_nomination_phase()
            if nominated is None:
                break

            await self._day_defense_phase(nominated)
            await self._day_vote_phase(nominated)
            if self.check_winner():
                return

    async def _day_notify_of_night_phase(self):
        """Handles notification of what happened during the night"""
        killed = {}

        for player in self.players:
            killer = player.attacked_by
            cleaner = player.cleaned_by
            protector = player.protected_by

            # If they weren't killed, we don't care
            if not killer:
                continue

            # If they were protected, then let them know
            if protector and killer.attack_type <= protector.defense_type:
                await player.channel.send(protector.save_message)
                # If the killer was mafia, we also want to notify them of the saving
                if killer.is_mafia:
                    await self.mafia_chat.send(
                        "{player} was saved last night from your attack!"
                    )
                continue

            # If they were cleaned, then notify the cleaner
            if cleaner:
                await cleaner.channel.send(
                    f"You cleaned {player.member.name} up, their role was {player}"
                )
                continue

            # Now if we're here it's a kill that wasn't stopped/cleaned
            player.dead = True
            # Check if it's a suicide or not
            if player == killer:
                msg = "f{player.member.mention} ({player}) suicided during the night!"
            else:
                msg = killer.attack_message.format(killer=killer, killed=player)

            killed[player] = msg

            # Remove their alive role and let them see dead chat
            await player.member.remove_roles(self._alive_game_role)
            await self.dead_chat.set_permissions(player.member, read_messages=True)
            # Now if they were godfather, choose new godfather
            if player.is_godfather:
                await self.choose_godfather()
                player.role.is_godfather = False
            # If they had an executionor targetting them, they become a jester
            if player.executionor_target and not player.executionor_target.dead:
                player.executionor_target.role = self.ctx.bot.role_mapping["Jester"]()

        # This is where we'll send the day notification
        # task = self.ctx.create_task()

        for player, msg in killed.items():
            await self.channel.send(msg)
            # Give a bit of a pause for people to digest information
            await asyncio.sleep(2)
        else:
            await self.channel.send("No one died last night!")

        # f = await task
        # await self.info.send(file=f)

    async def _day_discussion_phase(self):
        """Handles the discussion phase of the day"""
        await self.unlock_chat_channel()
        await self.chat.send(
            "Discussion time! You have 45 seconds before nomination will start"
        )
        await asyncio.sleep(45)

    async def _day_nomination_phase(self) -> Player:
        """Handles a nomination vote phase of the day"""
        noms_needed = math.floor(self.total_alive / 2) + 1
        await self.chat.send(
            "Nomination started! 30 seconds to nominate, at any point "
            "type `>>nominate @Member` to nominate the person you want to put up. "
            f"Need {noms_needed} players to nominate"
        )
        nominations = {}
        try:
            await self.ctx.bot.wait_for(
                "message",
                check=self.ctx.bot.nomination_check(self, nominations),
                timeout=30,
            )
        except asyncio.TimeoutError:
            pass

        # Nomination done, get the one voted the most
        try:
            most, count = collections.Counter(nominations.values()).most_common()[0]
        except IndexError:
            most, count = (0, 0)

        if count >= noms_needed:
            return most

    async def _day_defense_phase(self, player: Player):
        """Handles the defense of a player phase"""
        await self.lock_chat_channel()
        await self.unlock_chat_channel(player)
        await self.chat.send(f"What is your defense {player.member.mention}?")
        await asyncio.sleep(30)

    async def _day_vote_phase(self, player: Player):
        """Handles the voting for a player"""
        votes = {}

        def check(m):
            if m.channel != self.chat:
                return False
            if voter := discord.utils.get(self.players, member=m.author):
                return False
            if m.content.lower() not in ("guilty", "innocent"):
                return False
            # Override to allow them to change their decision
            votes[voter] = m.content.lower()
            self.ctx.create_task(m.add_reaction("\N{THUMBS UP SIGN}"))
            return False

        await self.chat.send(
            "Make your votes now! Send either `Guilty` or `Innocent` to cast your vote"
        )
        try:
            await self.ctx.bot.wait_for("message", check=check, timeout=30)
        except asyncio.TimeoutError:
            pass

        guilty_votes = votes.get("guilty", 0)
        innocent_votes = votes.get("innocent", 0)

        if guilty_votes > innocent_votes:
            await self.chat.send(
                f"{player.member.mention} has been lynched! Votes {guilty_votes} to {innocent_votes}"
            )
            player.dead = True
            player.lynched = True
            # Remove their permissions from their channel
            await player.channel.set_permissions(
                player.member, read_messages=True, send_messages=False
            )
            if player.is_mafia:
                await self.mafia_chat.set_permissions(
                    player.member, read_messages=True, send_messages=False
                )
                # Repick godfather if they were godfather
                if player.is_godfather:
                    try:
                        await self.choose_godfather()
                    # If there's no mafia, citizens win. Just return, the cycle will handle it
                    except IndexError:
                        return
            await player.member.remove_roles(self._alive_game_role)
            await self.dead_chat.set_permissions(
                player.member, read_messages=True, send_messages=True
            )
        else:
            await self.chat.send(
                f"{player.member.mention} has been spared! Votes {guilty_votes} to {innocent_votes}"
            )

    async def _night_phase(self):
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

    # Entry points

    async def play(self):
        """Handles the preparation and the playing of the game"""
        await self._setup_config()
        await self._game_preparation()
        await self._start()

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

    # Cleanup

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
