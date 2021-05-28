from __future__ import annotations

import asyncio
import collections
import dataclasses
import math
import random
import typing

import discord
from discord.mentions import AllowedMentions

from mafia import role_mapping, Role, Player
from utils import (
    create_night_image,
    create_day_image,
    min_max_check,
    MafiaMenu,
    MafiaPages,
    hex_to_players,
    players_to_hex,
    nomination_check,
    mafia_kill_check,
    get_mafia_player,
    cleanup_game,
)

if typing.TYPE_CHECKING:
    from utils import Context

can_send_overwrites = discord.PermissionOverwrite(send_messages=True)
cannot_send_overwrites = discord.PermissionOverwrite(send_messages=False)
can_read_overwrites = discord.PermissionOverwrite(read_messages=True)
everyone_overwrites = discord.PermissionOverwrite(
    read_messages=False,
    send_messages=False,
    attach_files=False,
    add_reactions=False,
)
spectating_overwrites = discord.PermissionOverwrite(
    read_messages=True,
    send_messages=False,
    attach_files=False,
    add_reactions=False,
)
bot_overwrites = discord.PermissionOverwrite(
    read_messages=True,
    send_messages=True,
    attach_files=True,
    add_reactions=True,
)


@dataclasses.dataclass
class MafiaGameConfig:
    starting_mafia: int
    special_roles: typing.List[typing.Type[Role]]
    ctx: Context
    night_length: int = 90
    day_length: int = 120


class MafiaGame:
    def __init__(self, ctx: Context, *, config: str):
        # The discord members, we'll produce our list of players later
        self._members: typing.List[discord.Member] = []
        # The actual players of the game
        self.players: typing.List[Player] = []

        self.ctx: Context = ctx
        self.is_day: bool = True
        self.id: int = -1

        # Different chats needed
        # self.category = discord.CategoryChannel = None
        # self.chat: typing.Optional[discord.TextChannel] = None
        # self.info: typing.Optional[discord.TextChannel] = None
        # self.mafia_chat: typing.Optional[discord.TextChannel] = None
        # self.dead_chat: typing.Optional[discord.TextChannel] = None

        self._alive_game_role_name: str = "Alive Players"
        # self._alive_game_role: discord.Role

        self._rand = random.SystemRandom()
        # self._config: typing.Optional[MafiaGameConfig] = None
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
    def godfather(self) -> typing.Optional[Player]:
        for player in self.players:
            if player.is_godfather and not player.dead:
                return player

    # Notification methods

    async def night_notification(self):
        async with self.chat.typing():
            buffer = await create_night_image(self)
            await self.info.send(file=discord.File(buffer, filename="night.png"))
            await self.chat.send(
                "It's nighttime! Check your private channels if you have a task tonight"
            )

    async def day_notification(self, *deaths: Player):
        """Creates a notification image with all of the overnight deaths"""
        async with self.info.typing():
            buffer = await create_day_image(self, list(deaths))
            await self.info.send(file=discord.File(buffer, filename="day.png"))

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
                if p.role.__class__ is role_mapping.get("Mafia")
            ]
        )
        godfather.role.is_godfather = True

        await godfather.channel.send("You are the godfather!")

    async def pick_players(self):
        player_cls = Player
        mafia_cls = role_mapping["Mafia"]
        citizen_cls = role_mapping["Citizen"]

        # I'm paranoid
        for _ in range(5):
            self._rand.shuffle(self._members)
        # Set special roles first
        for role in self._config.special_roles:
            # Get member that will have this role
            member = self._members.pop()
            self.players.append(player_cls(member, self.ctx, role()))
        # Then get the remaining normal mafia needed
        for _ in range(self._config.starting_mafia - self.total_mafia):
            member = self._members.pop()
            self.players.append(player_cls(member, self.ctx, mafia_cls()))
        # The rest are citizens
        while self._members:
            member = self._members.pop()
            self.players.append(player_cls(member, self.ctx, citizen_cls()))

    # Channel setup methods

    async def _setup_category_channels(self, category: discord.CategoryChannel):
        # Setup all the overwrites needed
        info_overwrites = {
            self.ctx.guild.default_role: spectating_overwrites,
            self.ctx.guild.me: bot_overwrites,
            self._alive_game_role: cannot_send_overwrites,
        }
        chat_overwrites = {
            self.ctx.guild.default_role: spectating_overwrites,
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
            self._alive_game_role: cannot_send_overwrites,
        }

        # Now add player specific overwrites into them
        for p in self.players:
            if p.is_mafia:
                mafia_overwrites[p.member] = can_read_overwrites
            chat_overwrites[p.member] = can_read_overwrites
            info_overwrites[p.member] = can_read_overwrites

        self.info: discord.TextChannel = await category.create_text_channel(
            "info", overwrites=info_overwrites
        )
        self.chat: discord.TextChannel = await category.create_text_channel(
            "chat", overwrites=chat_overwrites
        )
        self.dead_chat: discord.TextChannel = await category.create_text_channel(
            "dead", overwrites=dead_overwrites
        )
        self.mafia_chat: discord.TextChannel = await category.create_text_channel(
            "mafia", overwrites=mafia_overwrites
        )

    async def _setup_category(self):
        # Create category the channels will be in first
        self.category = category = await self.ctx.guild.create_category_channel(
            "MAFIA GAME"
        )
        # Make sure the default channels are setup properly
        await self._setup_category_channels(category)

        # Do this in the background to allow for playing while waiting
        self.ctx.create_task(self._setup_channels(category))

        return category

    async def _setup_channels(self, category: discord.CategoryChannel):
        """Receives a category with the default channels already setup, then sets up the
        rest of the players. This will also spawn the day tasks for each player for the first day"""
        tasks = []

        for p in self.players:
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
            # Set it on the player object
            p.set_channel(channel)
            # Send them their startup message and pin it
            msg = await channel.send(p.role.startup_channel_message(self, p))
            await msg.pin()

            tasks.append(self.ctx.create_task(p.day_task(self)))

        # Now that their channels are setup, we can choose the godfather
        await self.choose_godfather()

        # Now wait till day is over and cancel the rest of the tasks
        await asyncio.sleep(self._config.day_length)
        for task in tasks:
            if not task.done():
                task.cancel()

    async def _setup_amount_players(self) -> typing.Tuple[int, int]:
        ctx = self.ctx
        minimum_players_needed = 2
        # Get max players
        await ctx.send(
            "Starting new game of Mafia! Please first select how many players "
            "you want to allow to play the game at maximum?"
        )
        answer = await ctx.bot.wait_for(
            "message", check=min_max_check(ctx, minimum_players_needed, 25)
        )
        max_players = int(answer.content)
        # Min players
        await ctx.send("How many players at minimum?")
        answer = await ctx.bot.wait_for(
            "message",
            check=min_max_check(ctx, minimum_players_needed, max_players),
        )
        min_players = int(answer.content)

        return min_players, max_players

    async def _setup_players(
        self, min_players: int, max_players: int
    ) -> typing.List[discord.Member]:
        wait_length_for_players_to_join = 60
        ctx = self.ctx
        game_players: typing.Set[int] = set()

        async def wait_for_players():
            nonlocal game_players
            game_players = set()
            # Now start waiting for the players to actually join
            embed = discord.Embed(
                title="Mafia game!",
                description=f"Press \N{WHITE HEAVY CHECK MARK} to join! Waiting till at least {min_players} join. "
                f"After that will wait for {wait_length_for_players_to_join} seconds for the rest of the players to join",
            )
            embed.set_thumbnail(url=str(ctx.guild.icon_url))
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
                        embed.description = f"{embed.description}\n\nMin players reached! Waiting {wait_length_for_players_to_join} seconds or till max players ({max_players}) reached"
                        ctx.create_task(joining_over())
                    embed.set_footer(
                        text=f"{len(game_players)}/{min_players} Needed to join"
                    )
                    await msg.edit(embed=embed)
                    await asyncio.sleep(2)

            def check(p) -> bool:
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

                return False

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
        game_members = await ctx.guild.query_members(user_ids=list(game_players))
        admins = [p.mention for p in game_members if p.guild_permissions.administrator]
        if admins:
            await ctx.send(
                "There are admins in this game, which means I cannot hide the "
                f"game channels from them. I will DM you the role you have {','.join(admins)}"
                ". Please only check the corresponding channel and the chat channel. "
                "Don't chat during the night, only respond to prompts in your channel. **Please "
                "make sure your DMs are open on this server, the game WILL fail to start if I can't "
                "DM you.**"
            )

        return game_members

    async def _setup_amount_mafia(self, players: int) -> int:
        ctx = self.ctx
        # Get amount of Mafia
        await ctx.send(
            f"How many mafia members (including special mafia members; Between 1 and {int(players / 2)})?"
        )
        answer = await ctx.bot.wait_for(
            "message", check=min_max_check(ctx, 1, int(players / 2))
        )
        amount_of_mafia = int(answer.content)

        return amount_of_mafia

    async def _setup_special_roles(
        self, players: int, mafia: int
    ) -> typing.List[typing.Tuple[typing.Type[Role], int]]:
        ctx = self.ctx
        amount_of_specials = [
            (v, 0) for k, v in role_mapping.items() if k not in ["Mafia", "Citizen"]
        ]
        menu = MafiaMenu(source=MafiaPages(amount_of_specials, ctx))

        menu.amount_of_players = players
        menu.amount_of_mafia = mafia
        await menu.start(ctx, wait=True)

        return amount_of_specials

    # During game channel modification

    async def lock_chat_channel(self):
        await self.chat.set_permissions(
            self._alive_game_role, overwrite=cannot_send_overwrites
        )

    async def unlock_chat_channel(self):
        await self.chat.set_permissions(
            self._alive_game_role, overwrite=can_send_overwrites
        )

    async def lock_mafia_channel(self):
        await self.mafia_chat.set_permissions(
            self._alive_game_role, overwrite=cannot_send_overwrites
        )

    async def unlock_mafia_channel(self):
        await self.mafia_chat.set_permissions(
            self._alive_game_role, overwrite=can_send_overwrites
        )

    # Pre game entry methods

    async def _setup_config(self) -> str:
        """All the setup needed for the game to play"""
        ctx = self.ctx
        # Get/create the alive role
        role = discord.utils.get(ctx.guild.roles, name=self._alive_game_role_name)
        if role is None:
            self._alive_game_role = await ctx.guild.create_role(
                name=self._alive_game_role_name, hoist=True
            )
        else:
            self._alive_game_role = role

        # Config is already set
        if self._preconfigured_config:
            # Convert hex to the stuff we care about
            (
                amount_of_mafia,
                min_players,
                max_players,
                special_roles,
            ) = hex_to_players(
                self._preconfigured_config,
                # A list of only the special roles
                [v for k, v in role_mapping.items() if k not in ["Mafia", "Citizen"]],
            )
            # The only setup we need to do is get the players who will player
            self._members = await self._setup_players(min_players, max_players)
            # Set the config
            self._config = MafiaGameConfig(amount_of_mafia, special_roles, ctx)

            conf = self._preconfigured_config
        else:
            # Go through normal setup. Amount of players, letting players join, amount of mafia, special roles
            min_players, max_players = await self._setup_amount_players()
            self._members = await self._setup_players(min_players, max_players)
            amount_of_mafia = await self._setup_amount_mafia(len(self._members))
            special_roles = await self._setup_special_roles(
                len(self._members), amount_of_mafia
            )
            # Convert the tuple of player, amount to just a list of all roles
            special_roles = [role for (role, amt) in special_roles for _ in range(amt)]
            # Get hex to allow them to use this setup in the future
            h = players_to_hex(special_roles, amount_of_mafia, min_players, max_players)
            await self.ctx.send(
                "In the future you can provide this to the mafia start command "
                f"to use the exact same configuration:\n{h}"
            )
            # Now that the setup is done, create the configuration for the game
            self._config = MafiaGameConfig(amount_of_mafia, special_roles, ctx)

            conf = h

        for member in self._members:
            await member.add_roles(self._alive_game_role)

        return conf

    async def _game_preparation(self, conf: str):
        # Sort out the players
        await self.pick_players()
        # Setup the category required
        await self._setup_category()

        async with self.ctx.acquire() as conn:
            query = "INSERT INTO games (guild_id, config) VALUES ($1, $2) RETURNING id"
            ret = await conn.fetchval(query, self.ctx.guild.id, conf)
            self.id = typing.cast(int, ret)

            batched = [
                (self.id, player.member.id, player.role.id) for player in self.players
            ]
            query = "INSERT INTO players VALUES ($1, $2, $3)"
            await conn.executemany(query, batched)

    # Day/Night cycles

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
            await self.day_notification()
            await asyncio.sleep(10)
            await self.chat.send("Day is ending in 20 seconds")
            await asyncio.sleep(20)

            return

        await self.chat.send(f"{self._alive_game_role.mention} Day has begun!")

        await self._day_notify_of_night_phase()
        if self.check_winner():
            return

        # Start everyones day tasks
        tasks = [
            self.ctx.create_task(p.day_task(self)) for p in self.players if not p.dead
        ]
        await self._day_discussion_phase()
        # We'll cycle nomination -> voting up to three times
        # if no one gets nominated, or a vote is successful we'll break out
        for _ in range(3):
            nominated = await self._day_nomination_phase()
            if nominated is None:
                break

            await self._day_defense_phase(nominated)
            # If vote went through don't allow more nominations
            if await self._day_vote_phase(nominated):
                break
            if self.check_winner():
                return

        for task in tasks:
            if not task.done():
                task.cancel()

    async def _day_notify_of_night_phase(self):
        """Handles notification of what happened during the night"""
        killed: typing.Dict[Player, str] = {}
        batched_kills: typing.List[typing.Tuple[int, int, int, int, bool]] = []

        for player in self.players:
            killer = player.attacked_by
            cleaner = player.cleaned_by
            protector = player.protected_by

            # Don't care about already dead players
            if player.dead:
                continue
            # If they weren't killed, we don't care
            if not killer:
                player.cleanup_attrs()
                continue

            # If they were protected, then let them know
            if (
                protector
                and killer.attack_type
                and protector.defense_type
                and killer.attack_type <= protector.defense_type
            ):
                await player.channel.send(protector.save_message)
                # If the killer was mafia, we also want to notify them of the saving
                if killer.is_mafia:
                    await self.mafia_chat.send(
                        f"{player.member.name} was saved last night from your attack!"
                    )
                player.cleanup_attrs()
                continue

            batched_kills.append(
                (
                    self.id,
                    killer.member.id,
                    player.member.id,
                    self._day - 1,
                    killer == player,
                )
            )

            # If they were cleaned, then notify the cleaner
            if cleaner:
                await cleaner.channel.send(
                    f"You cleaned {player.member.name}'s dead body up, their role was {player}"
                )

            # Now if we're here it's a kill that wasn't stopped
            player.dead = True
            # Check if it's a suicide or not
            if player == killer:
                msg = "f{player.member.mention} ({player}) suicided during the night!"
            else:
                msg = killer.attack_message.format(killer=killer, killed=player)

            killed[player] = msg

            # Remove their alive role and let them see dead chat
            await player.member.remove_roles(self._alive_game_role)
            await self.dead_chat.set_permissions(
                player.member, read_messages=True, send_messages=True
            )
            # Now if they were godfather, choose new godfather
            if player.is_godfather:
                await self.choose_godfather()
                player.role.is_godfather = False
            # If they had an executionor targetting them, they become a jester
            if player.executionor_target and not player.executionor_target.dead:
                player.executionor_target.role = role_mapping["Jester"]()

        task = create_day_image(self, list(killed.keys()))

        async with self.ctx.acquire() as conn:
            query = "INSERT INTO kills VALUES ($1, $2, $3, $4, $5)"
            await conn.executemany(query, batched_kills)

            query = "UPDATE players SET die = true WHERE game_id = $1 AND user_id = $2"
            await conn.executemany(query, [(self.id, x[2]) for x in batched_kills])

        for player, msg in killed.items():
            await self.chat.send(msg)
            # Give a bit of a pause for people to digest information
            await asyncio.sleep(2)

        if not killed:
            await self.chat.send("No one died last night!")

        # Wait for the task to get the image and send it
        buff = await task
        await self.info.send(file=discord.File(buff, filename="day.png"))

    async def _day_discussion_phase(self):
        """Handles the discussion phase of the day"""
        await self.unlock_chat_channel()
        await self.chat.send(
            "Discussion time! You have 45 seconds before nomination will start"
        )
        await asyncio.sleep(45)

    async def _day_nomination_phase(self) -> typing.Optional[Player]:
        """Handles a nomination vote phase of the day"""
        noms_needed = math.floor(self.total_alive / 2) + 1
        await self.chat.send(
            "Nomination started! 30 seconds to nominate, at any point "
            "type `>>nominate @Member` to nominate the person you want to put up. "
            f"Need {noms_needed} players to nominate"
        )
        nominations: typing.Dict[Player, Player] = {}
        try:
            await self.ctx.bot.wait_for(
                "message",
                check=nomination_check(self, nominations),
                timeout=30,
            )
        except asyncio.TimeoutError:
            pass

        # Nomination done, get the one voted the most
        try:
            most, count = collections.Counter(nominations.values()).most_common()[0]
        except IndexError:
            return

        if count >= noms_needed:
            return most

    async def _day_defense_phase(self, player: Player):
        """Handles the defense of a player phase"""
        # Set the overwrites so only this person can talk
        overwrites = self.chat.overwrites
        overwrites[self._alive_game_role] = cannot_send_overwrites
        overwrites[player.member] = can_send_overwrites
        await self.chat.edit(overwrites=overwrites)
        await self.chat.send(f"What is your defense {player.member.mention}?")
        await asyncio.sleep(30)
        # Now set them back to to anyone alive can talk
        overwrites[player.member] = can_read_overwrites
        overwrites[self._alive_game_role] = can_send_overwrites

    async def _day_vote_phase(self, player: Player):
        """Handles the voting for a player"""
        votes = {}

        def check(m):
            if m.channel != self.chat:
                return False
            if not (voter := discord.utils.get(self.players, member=m.author)):
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

        guilty_votes = list(votes.values()).count("guilty")
        innocent_votes = list(votes.values()).count("innocent")

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
            async with self.ctx.acquire() as conn:
                query = "INSERT INTO kills VALUES ($1, null, $2, $3, false)"
                await conn.execute(query, self.id, player.member.id, self._day)

            return True
        else:
            await self.chat.send(
                f"{player.member.mention} has been spared! Votes {guilty_votes} to {innocent_votes}"
            )
            return False

    async def _night_phase(self):
        await self.night_notification()
        await self.lock_chat_channel()
        await self.unlock_mafia_channel()

        # Schedule tasks. Add the asyncio sleep to *ensure* we sleep that long
        # even if everyone finishes early
        async def night_sleep():
            await asyncio.sleep(self._config.night_length - 20)
            for p in self.players:
                if p.dead or p.night_role_blocked:
                    continue
                self.ctx.create_task(
                    p.channel.send("Night is about to end in 20 seconds")
                )
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

            async def mafia_check() -> None:
                msg = await self.ctx.bot.wait_for(
                    "message",
                    check=mafia_kill_check(self, mapping),
                )
                player = mapping[int(msg.content)]
                player = get_mafia_player(self, player)
                assert godfather is not None
                player.kill(godfather)
                await self.mafia_chat.send("\N{THUMBS UP SIGN}")

            tasks.append(self.ctx.create_task(mafia_check()))

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

    async def _start(self):
        """Play the game"""
        await self.chat.send(
            f"{self._alive_game_role.mention} game has started! (Your private channels will be created shortly)"
        )
        fmt = "\n".join(f"{player.role}" for player in self.players)
        msg = await self.info.send(f"Roles this game are:\n{fmt}")
        await msg.pin()

        while True:
            if await self._cycle():
                break

        # The game is done, allow dead players to chat again
        for player in self.players:
            if player.dead:
                await self.chat.set_permissions(player.member, read_messages=True)

        # Send winners
        winners = self.get_winners()
        winner_msg = "Winners are:\n{}".format(
            "\n".join(f"{winner.member.mention} ({winner})" for winner in winners)
        )
        await self.chat.send(winner_msg, allowed_mentions=AllowedMentions(users=False))
        # Send a message with everyone's roles
        roles_msg = "\n".join(
            f"{player.member.mention} ({player})" for player in self.players
        )
        await self.ctx.send(
            f"The game is over! Roles were:\n{roles_msg}\n\n{winner_msg}",
            allowed_mentions=AllowedMentions(users=False),
        )

        async with self.ctx.acquire() as conn:
            query = "UPDATE players SET win = true WHERE game_id = $1 AND user_id = $2"
            await conn.executemany(
                query, [(self.id, player.member.id) for player in winners]
            )
            await conn.execute(
                "UPDATE games SET day_count = $1 WHERE id = $2", self._day, self.id
            )

        await asyncio.sleep(60)
        await self.cleanup()

    async def play(self):
        """Handles the preparation and the playing of the game"""
        conf = await self._setup_config()
        await self._game_preparation(conf)
        await self._start()

    # Cleanup

    async def cleanup(self):
        cleanup_game(self)

        for player in self.players:
            await player.member.remove_roles(self._alive_game_role)

        if category := self.category:
            for channel in category.channels:
                await channel.delete()

            await category.delete()
