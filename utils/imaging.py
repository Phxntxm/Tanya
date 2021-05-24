from __future__ import annotations

import io
import multiprocessing
import typing
from concurrent.futures import ThreadPoolExecutor

import discord
from PIL import Image, ImageDraw, ImageFont

if typing.TYPE_CHECKING:
    from mafia import MafiaGame, Player

alpha = None
# fonts in
font_28days_title = ImageFont.truetype("./resources/28 Days Later.ttf", size=256)
font_28days = ImageFont.truetype("./resources/28 Days Later.ttf", size=64)
font_vermillion = ImageFont.truetype("./resources/Vermillion.ttf", size=34)

death_marker = Image.open("./resources/death-marker.png", formats=("png",)).resize(
    (96, 96)
)

processes: typing.Dict[int, "GameProcessor"] = {}
pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ImageWaiter-")


async def create_day_image(game: MafiaGame, deaths: typing.List[Player]) -> io.BytesIO:
    if id(game) not in processes:
        # make a new renderer
        parent, child = multiprocessing.Pipe(True)
        processes[id(game)] = proc = GameProcessor(args=(child,))
        proc.start()
        proc.pipe = parent
        parent.send({"g": await serialize_game(game, include_avatars=True)})
        parent.send({"op": 1, "g": {}, "d": [x.member.id for x in deaths]})

    else:
        proc = processes[id(game)]
        proc.pipe.send(
            {
                "op": 1,
                "d": [x.member.id for x in deaths],
                "g": await serialize_game(game, include_avatars=False),
            }
        )

    return await game.ctx.bot.loop.run_in_executor(pool, proc.pipe.recv)


async def create_night_image(game: MafiaGame) -> io.BytesIO:
    if id(game) not in processes:
        # make a new renderer
        parent, child = multiprocessing.Pipe(True)
        processes[id(game)] = proc = GameProcessor(args=(child,))
        proc.start()
        proc.pipe = parent
        parent.send({"g": await serialize_game(game, include_avatars=True)})
        parent.send({"op": 0, "d": game._day - 1})  # noqa

    else:
        proc = processes[id(game)]
        proc.pipe.send({"op": 0, "d": game._day - 1})  # noqa

    return await game.ctx.bot.loop.run_in_executor(pool, proc.pipe.recv)


def add_corners(im, rad):
    if im.size != (128, 128):
        im = im.resize((128, 128))

    global alpha
    if not alpha:  # cache the alpha layer
        circle = Image.new("L", (rad * 2, rad * 2), 0)
        draw = ImageDraw.Draw(circle)
        draw.ellipse((0, 0, rad * 2, rad * 2), fill=255)
        alpha = Image.new("L", im.size, 255)
        alpha.paste(circle.crop((0, 0, rad, rad)), (0, 0))
        alpha.paste(circle.crop((0, rad, rad, rad * 2)), (0, im.size[0] - rad))
        alpha.paste(circle.crop((rad, 0, rad * 2, rad)), (128 - rad, 0))
        alpha.paste(
            circle.crop((rad, rad, rad * 2, rad * 2)),
            (im.size[0] - rad, im.size[0] - rad),
        )

    im.putalpha(alpha)
    return im.resize((96, 96))  # resize it to a more respectable size


def round_avatar(avy: io.BytesIO, rad=64) -> Image:
    return add_corners(Image.open(avy, formats=("png",)), rad)


async def serialize_player(p: Player, ia: bool) -> dict:
    if ia:
        b = io.BytesIO()
        await p.member.avatar_url_as(format="png", size=128).save(b)

    return {
        "ni": p.member.nick,
        "na": p.member.name,
        "i": p.member.id,
        "d": p.dead,
        "r": str(p.role),
        "a": b if ia else None,  # noqa
    }


async def serialize_game(g: MafiaGame, include_avatars=False) -> dict:
    return {
        "p": [await serialize_player(p, include_avatars) for p in g.players],
        "d": g._day,  # noqa
    }


class GameProcessor(multiprocessing.Process):
    def run(self) -> None:
        pipe = self._args[0]  # noqa
        avatars = {}  # cache the avatar images throughout the game
        data: dict = (
            pipe.recv()
        )  # receives the initial game dump, with the avatars. Avatars won't be sent in later updates
        game: dict = data["g"]
        for player in game["p"]:
            # turns the bytesio into image objects and applies the rounding masks
            avatars[player["i"]] = round_avatar(player["a"])

        while True:
            d = pipe.recv()
            if d["op"] == 0:  # nighttime images
                resp = _sync_make_night_image(d["d"])
            elif d["op"] == 1:  # daytime images
                game.update(d["g"])
                deaths = d["d"]
                resp = _sync_make_day_image(game, deaths, avatars)
            else:
                raise RuntimeError("unknown opcode")

            pipe.send(resp)


def _sync_make_night_image(night: int) -> io.BytesIO:
    base: Image.Image = Image.open("./resources/background-night.png", formats=("png",))
    base = base.resize((1920, 1080))
    raster = ImageDraw.Draw(base)

    __w, _ = raster.textsize(f"Night {night}", font=font_28days_title)  # noqa
    raster.text(
        ((1920 - __w) / 2, 30), f"Night {night}", font=font_28days_title, fill="black"
    )  # noqa center the night #

    buf = io.BytesIO()
    base.save(buf, format="png")
    buf.seek(0)
    base.close()
    return buf


def _sync_make_day_image(
    game: dict, deaths: typing.List[int], avatars: dict
) -> io.BytesIO:
    base: Image.Image = Image.open("./resources/background-day.png", formats=("png",))
    base = base.resize((1920, 1080)).convert("RGBA")
    raster = ImageDraw.Draw(base)

    alive = list(filter(lambda player: not player["d"], game["p"]))
    dead = list(
        filter(lambda player: player["d"] and player["i"] not in deaths, game["p"])
    )

    __w, _ = raster.textsize(f"Day {game['d']}", font=font_28days_title)  # noqa
    raster.text(
        ((1920 - __w) / 2, 30), f"Day {game['d']}", font=font_28days_title, fill="black"
    )  # noqa center the day #
    raster.text(
        (30, 260),
        f"Alive Players",
        font=font_28days,
    )  # noqa put this above row 1

    row_width = 105  # how far apart each row is
    col_width = 400  # how far apart each column is
    row = col = 0  # row is up/down, col(umn) is left/right

    def paste_avatar(player: dict, text_fill: str, do_x: bool, show_role: bool):
        nonlocal col, row
        avy = avatars[player["i"]]

        # determine the co-ords based off the column and row
        x = (
            30 + (col * col_width),
            int(330 + (row_width * row)),
            30 + avy.size[0] + (col * col_width),
            int(330 + (row_width * row) + avy.size[1]),
        )

        base.paste(avy, x, mask=avy)
        if do_x:
            # paste the red x across their avatar
            base.paste(death_marker, x, mask=death_marker)

        # if they have a nick, format as `nick (name)`, else just the name
        nick = f"{player['ni'] + ' ' if player['ni'] else ''}{'(' + player['na'] + ')' if player['ni'] else player['na']}"
        if len(nick) >= 17:
            # nick is too long, shorten it
            nick = nick[:17] + "..."

        if show_role:
            # add their role to the nick text
            nick += f"\n\t{player['r']}"
            t = (
                x[2] + 20,
                int(330 + (row_width * row)),
            )  # don't bother centering as there's 2 lines of text which centers itself

        else:
            _, _h = raster.textsize(nick, font=font_vermillion)
            t = (x[2] + 20, int(330 + (row_width * row) + (_h / 2)))  # center the text

        raster.text(t, nick, font=font_vermillion, fill=text_fill)
        row += 1
        if row >= 7:
            # 7 people per row, jump to the next column
            row = 0
            col += 1

    if deaths:
        # these are the people who have died today
        d = [discord.utils.find(lambda pl: pl["i"] == x, game["p"]) for x in deaths]
        for p in d:
            # fill certain slots with black text to contrast the background
            fill = "black" if col >= 1 and 3 > row > 0 else "white"
            paste_avatar(p, fill, True, True)

    for p in alive:
        # fill certain slots with black text to contrast the background
        fill = "black" if col >= 1 and 3 > row > 0 else "white"
        paste_avatar(p, fill, False, False)

    if dead:
        if row:
            # if we're not in an empty column, jump to a new one
            col += 1
            row = 0

        raster.text(
            (30 + (col * col_width), 260),
            f"Dead Players",
            font=font_28days,
            fill="black",
        )
        for p in dead:
            # fill certain slots with black text to contrast the background
            fill = (
                "black"
                if (col >= 1 and row == 2) or (col == 3 and (row == 0 or row == 2))
                else "white"
            )
            paste_avatar(p, fill, True, True)

    buf = io.BytesIO()
    base.save(buf, format="png")
    buf.seek(0)
    base.close()
    return buf


def cleanup_game(game: MafiaGame):
    g_id = id(game)
    if g_id in processes:
        proc = processes.pop(g_id)
        proc.terminate()


def setup(bot):
    bot.create_day_image = create_day_image
    bot.create_night_image = create_night_image
    bot.cleanup_imaging = cleanup_game


def teardown(bot):
    del bot.create_day_image
    del bot.create_night_image
    del bot.cleanup_imaging
    for proc in processes.values():
        # force a cleanup of any lingering renderers
        proc.terminate()
