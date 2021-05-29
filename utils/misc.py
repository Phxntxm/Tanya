from __future__ import annotations
from mafia.roles import Alignment

import re
import typing

import discord
from discord.ext import commands
from fuzzywuzzy import process

if typing.TYPE_CHECKING:
    from mafia import MafiaGame, Player, Role


def hex_to_players(
    hex_repr: str, all_roles: typing.List[typing.Type[Role]]
) -> typing.Tuple[int, int, int, typing.List[typing.Type[Role]]]:
    """Takes in a hex number and converts it to a configuration
    based on the amount of special roles it specifies"""

    num = int(hex_repr, 16)
    roles_to_play = []
    # The first 3 sets of 2 of the hex represent the min, max, and amount of mafia
    min_players = num & 0xFF
    num = num >> 0x8
    max_players = num & 0xFF
    num = num >> 0x8
    amount_of_mafia = num & 0xFF
    num = num >> 0x8

    while num != 0:
        # The rest of the hex is made up of any number of 2 parts of 2
        # The first part is the role they're specifying
        role = num & 0xFF
        # After getting the last bit, shift over two spots
        num = num >> 0x8
        # The second is the amount for that role
        amount = num & 0xFF
        # Shift again, we're done with this set
        num = num >> 0x8

        # Get the one with the matching ID
        role = next(r for r in all_roles if r.id == role)
        # Add the amount of roles we'll use to the list
        for _ in range(amount):
            roles_to_play.append(role)

    return amount_of_mafia, min_players, max_players, roles_to_play


def players_to_hex(
    roles: typing.List[typing.Type[Role]],
    amount_of_mafia: int,
    min_players: int = None,
    max_players: int = None,
) -> str:
    """Takes in a list of players and produces a hex configuration. If min and max
    are not provided, then min and max will be the amount of roles"""
    mapping: typing.Dict[int, int] = {}
    min_players = min_players if min_players else len(roles)
    max_players = max_players if max_players else len(roles)

    role_hex = f"{hex(amount_of_mafia)[2:].zfill(2)}{hex(max_players)[2:].zfill(2)}{hex(min_players)[2:].zfill(2)}"

    for role in roles:
        # Get amount currently set
        amt = mapping.get(role.id, 0)
        # Add one
        amt += 1
        # Set back in mapping
        mapping[role.id] = amt

    for role, amt in mapping.items():
        role_hex = f"{hex(amt)[2:].zfill(2)}{hex(role)[2:].zfill(2)}" + role_hex

    return role_hex


def get_mafia_player(game: MafiaGame, arg: str) -> Player:
    if not game:
        raise commands.BadArgument(
            "No game playing for this guild, cannot grab players"
        )

    result = None
    players = game.players
    match = re.match(r"([0-9]{15,20})$", arg) or re.match(r"<@!?([0-9]{15,20})>$", arg)
    if match is None:
        choices = {player: player.member.name for player in game.players}
        best = process.extractBests(arg, choices, score_cutoff=80, limit=1)

        if best:
            result = best[0][2]
    else:
        user_id = int(match.group(1))
        result = discord.utils.get(players, member__id=user_id)

    if not result:
        raise commands.MemberNotFound(arg)

    return result


def to_keycap(i: typing.Any[str, int]) -> str:
    return f"{i}\N{variation selector-16}\N{combining enclosing keycap}"


def min_max_check(ctx: commands.Context, min: int, max: int) -> typing.Callable:
    def check(m: discord.Message) -> bool:
        if m.channel != ctx.channel:
            return False
        if m.author != ctx.author:
            return False
        try:
            amt = int(m.content)
        except ValueError:
            return False
        else:
            return min <= amt <= max

    return check


def nomination_check(game: MafiaGame, nominations: typing.Dict) -> typing.Callable:
    def check(m: discord.Message) -> bool:
        # Ignore if not in channel we want
        if m.channel != game.chat:
            return False
        # Ignore if not player of game (admins, bots)
        if m.author not in [p.member for p in game.players]:
            return False
        # Ignore if not the right type of message
        if not m.content.startswith(">>nominate "):
            return False
        # Try to get the player
        try:
            content = m.content.split(">>nominate ")[1]
            player = get_mafia_player(game, content)
            nominator = discord.utils.get(game.players, member=m.author)
        except commands.MemberNotFound:
            return False
        else:
            # Don't let them nominate themselves
            if nominator == player:
                return False
            # Check if dead
            if player.dead:
                return False
            # Set their nomination
            nominations[nominator] = player
            game.ctx.create_task(m.add_reaction("\N{THUMBS UP SIGN}"))
            return False

    return check


def private_channel_check(
    game: MafiaGame,
    player: Player,
    mapping: typing.Dict[int, str],
    can_choose_self: bool = False,
) -> typing.Callable[[discord.Message], bool]:
    def check(m: discord.Message) -> bool:
        # Only care about messages from the author in their channel
        if m.channel != player.channel:
            return False
        elif m.author != player.member:
            return False
        # Now make sure it's a num, and in our mapping
        # Set the player for use after
        try:
            player_id = mapping[int(m.content)]
            p: Player = get_mafia_player(game, player_id)
        except (ValueError, KeyError, commands.MemberNotFound):
            return False
        # Check the choosing self
        if not can_choose_self and player == p:
            game.ctx.create_task(p.channel.send("You cannot chooose yourself"))
        elif p is not None:
            return True

        return False

    return check


def mafia_kill_check(
    game: MafiaGame, mapping: typing.Dict[int, str]
) -> typing.Callable:
    def check(m: discord.Message) -> bool:
        # Only care about messages from the author in their channel
        if m.channel != game.mafia_chat:
            return False
        elif m.author != game.godfather.member:
            return False
        # Set the player for use after
        try:
            player_id = mapping[int(m.content)]
            p = get_mafia_player(game, player_id)
        except (ValueError, KeyError, commands.MemberNotFound):
            return False
        else:
            if p.role.alignment is Alignment.mafia:
                return False
            else:
                return True

    return check
