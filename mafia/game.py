from __future__ import annotations

import asyncio

from discord.activity import Game
import collections
import dataclasses
import math
import random
import typing

import discord
from discord.mentions import AllowedMentions

from mafia import role_mapping, Role, Player
from interactions import Vote, Config, Join
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
    Alignment,
)

if typing.TYPE_CHECKING:
    from custom_models import Context

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
    roles: typing.List[typing.Type[Role]]
    ctx: Context
    night_length: int = 90
    day_length: int = 120


class GameException(Exception):
    pass


class MafiaGame:
    def __init__(self, ctx: Context, *, config: str):
        # The discord members, we'll produce our list of players later
        self._members: typing.List[discord.Member] = []
        # The actual players of the game
        self.players: typing.List[Player] = []

        self.ctx: Context = ctx
        self.is_day: bool = True
        self.id: int = -1
        self.inter_mapping: typing.Dict[int, discord.Interaction] = {}

        # Different chats needed
        self.category = discord.CategoryChannel = None

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
        return sum(
            1
            for player in self.players
            if player.role.alignment is Alignment.mafia and not player.dead
        )

    @property
    def total_citizens(self) -> int:
        return sum(
            1
            for player in self.players
            if player.role.alignment is Alignment.citizen and not player.dead
        )

    @property
    def total_alive(self) -> int:
        return sum(1 for player in self.players if not player.dead)

    @property
    def total_players(self) -> int:
        return len(self.players)

    @property
    def alive_players(self) -> typing.List[Player]:
        return [p for p in self.players if not p.dead]

    @property
    def godfather(self) -> typing.Optional[Player]:
        g = discord.utils.get(self.players, is_godfather=True, dead=False)
        if g is None:
            g = self._rand.choice(
                [
                    p
                    for p in self.players
                    # We don't want to choose special mafia
                    if p.role.__class__ is role_mapping.get("Mafia")
                ]
            )
            g.role.is_godfather = True

            self.ctx.create_task(
                self.mafia_chat.send(f"{g.member.mention} has become the new godfather")
            )

        return g

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
            if (
                not player.win_is_multi and player.win_condition(self)
            ) or self.total_mafia < 1:
                return True

        return False

    def get_winners(self) -> typing.List[Player]:
        """Returns all winners of this game"""
        return [p for p in self.players if p.win_condition(self)]

    async def pick_players(self):
        # I'm paranoid
        for _ in range(5):
            self._rand.shuffle(self._members)

        for role in self._config.roles:
            member = self._members.pop()
            p = Player(member, self.ctx, role(), self.inter_mapping[member.id])
            self.players.append(p)

    # Channel setup methods

    async def _setup_chat_channel(self, category: discord.CategoryChannel):
        chat_overwrites = {
            self.ctx.guild.default_role: spectating_overwrites,
            self.ctx.guild.me: bot_overwrites,
            self._alive_game_role: can_send_overwrites,
        }
        self.chat: discord.TextChannel = await category.create_text_channel(
            "chat", overwrites=chat_overwrites
        )

    async def _setup_category_channels(self, category: discord.CategoryChannel):
        # Setup all the overwrites needed
        info_overwrites = {
            self.ctx.guild.default_role: spectating_overwrites,
            self.ctx.guild.me: bot_overwrites,
            self._alive_game_role: cannot_send_overwrites,
        }
        dead_overwrites = {
            self.ctx.guild.default_role: everyone_overwrites,
            self.ctx.guild.me: bot_overwrites,
        }
        mafia_overwrites = {
            self.ctx.guild.default_role: everyone_overwrites,
            self.ctx.guild.me: bot_overwrites,
            # Mafia can't talk during the day first, turn it off to start
            self._alive_game_role: cannot_send_overwrites,
        }
        jailed_overwrites = {
            self.ctx.guild.default_role: everyone_overwrites,
            self.ctx.guild.me: bot_overwrites,
            self._alive_game_role: can_send_overwrites,
        }
        jailor_overwrites = {
            self.ctx.guild.default_role: everyone_overwrites,
            self.ctx.guild.me: bot_overwrites,
            self._alive_game_role: can_send_overwrites,
        }

        # Now add player specific overwrites into them
        for p in self.players:
            if p.role.alignment is Alignment.mafia:
                mafia_overwrites[p.member] = can_read_overwrites
            if isinstance(p.role, role_mapping["jailor"]):
                jailor_overwrites[p.member] = can_read_overwrites
            info_overwrites[p.member] = can_read_overwrites

        self.info: discord.TextChannel = await category.create_text_channel(
            "info", overwrites=info_overwrites
        )
        self.dead_chat: discord.TextChannel = await category.create_text_channel(
            "dead", overwrites=dead_overwrites
        )
        self.mafia_chat: discord.TextChannel = await category.create_text_channel(
            "mafia", overwrites=mafia_overwrites
        )
        self.jailed: discord.TextChannel = await category.create_text_channel(
            "jailed", overwrites=jailed_overwrites
        )
        self.jailor: discord.TextChannel = await category.create_text_channel(
            "jailor", overwrites=jailor_overwrites
        )

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

        # Config is already set
        if self._preconfigured_config:
            # Convert hex to the stuff we care about
            roles = hex_to_players(
                self._preconfigured_config, list(role_mapping.values())
            )
            conf = self._preconfigured_config
        else:
            roles = await Config(list(role_mapping.values()), ctx.author).start(
                self.chat
            )
            if roles is None:
                raise GameException("Config setup was cancelled")
            else:
                roles = [r.role for r in roles for _ in range(r.amount)]

            conf = players_to_hex(roles)
        # Pass in the mapping dict that will be used to setup each member's personal interaction
        _members = await Join(len(roles), self.inter_mapping).start(self.chat)
        if _members is None:
            raise GameException("Timed out waiting for players to join")
        else:
            self._members = _members
        # Set the config
        self._config = MafiaGameConfig(roles, ctx)

        for member in self._members:
            await member.add_roles(self._alive_game_role)

        return conf

    async def _game_preparation(self):
        # Setup the category required
        self.category = await self.ctx.guild.create_category_channel("MAFIA GAME")
        # Get/create the alive role
        role = discord.utils.get(self.ctx.guild.roles, name=self._alive_game_role_name)
        if role is None:
            self._alive_game_role = await self.ctx.guild.create_role(
                name=self._alive_game_role_name, hoist=True
            )
        else:
            self._alive_game_role = role
        await self._setup_chat_channel(self.category)
        # Set config
        conf = await self._setup_config()
        # Sort out the players
        await self.pick_players()
        # Now setup the rest of the channels
        await self._setup_category_channels(self.category)

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
            if protector and killer.attack_type <= protector.defense_type:
                await player.send_message(content=protector.save_message)
                # If the killer was mafia, we also want to notify them of the saving
                if killer.role.alignment is Alignment.mafia:
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
                await cleaner.send_message(
                    content=f"You cleaned {player.member.name}'s dead body up, their role was {player}"
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
        overwrites = typing.cast(dict, self.chat.overwrites)
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

        view = Vote(
            "Make your votes now! Click either guilty or innocent to cast your vote!",
            allowed=[p.member for p in self.players if not p.dead],
            timeout=45,
            yes_label="Innocent",
            no_label="Guilty",
        )
        votes = await view.start(self.chat)
        inno = votes.get("Innocent", 0)
        guilty = votes.get("Guilty", 0)

        if guilty > inno:
            await self.chat.send(
                f"{player.member.mention} has been lynched! Votes {guilty} to {inno}"
            )
            player.dead = True
            player.lynched = True
            if player.role.alignment is Alignment.mafia:
                await self.mafia_chat.set_permissions(
                    player.member, read_messages=True, send_messages=False
                )
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
                f"{player.member.mention} has been spared! Votes {guilty} to {inno}"
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
            await self.mafia_chat.send("Night is about to end in 20 seconds")
            await asyncio.sleep(20)

        tasks = [self.ctx.create_task(night_sleep())]
        mapping = {
            count: player.member.name
            for count, player in enumerate(self.players)
            if player.role.alignment is not Alignment.mafia and not player.dead
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
        await self.chat.send(f"{self._alive_game_role.mention} game has started!")
        fmt = "\n".join(f"{player.role}" for player in self.players)
        msg = await self.info.send(f"Roles this game are:\n{fmt}")
        await msg.pin()

        for p in self.players:
            await p.send_message(content=p.role.startup_channel_message(self, p))

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
        try:
            await self._game_preparation()
        except GameException as e:
            await self.ctx.send(str(e))
            await self.cleanup()
        else:
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
