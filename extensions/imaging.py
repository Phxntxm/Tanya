from __future__ import annotations

import multiprocessing
import typing
from concurrent.futures import ThreadPoolExecutor
import io

import discord
from PIL import Image, ImageDraw, ImageFont

if typing.TYPE_CHECKING:
    from .game import MafiaGame
    from . import players

alpha = None
font_28days_title = ImageFont.truetype("./resources/28 Days Later.ttf", size=256)
font_28days_subtitle = ImageFont.truetype("./resources/28 Days Later.ttf", size=64)
font_28days = ImageFont.truetype("./resources/28 Days Later.ttf", size=64)
font_vermillion = ImageFont.truetype("./resources/Vermillion.ttf", size=34)
death_marker = Image.open("./resources/death-marker.png", formats=("png",)).resize((96, 96))

processes: typing.Dict[int, "GameProcessor"] = {}
pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ImageWaiter-")

async def serialize_player(p: players.Player, ia: bool) -> dict:
    if ia:
        b = io.BytesIO()
        await p.member.avatar_url_as(format="png", size=128).save(b)

    return {
        "ni": p.member.nick,
        "na": p.member.name,
        "i": p.member.id,
        "d": p.dead,
        "r": str(p.role),
        "a": b if ia else None # noqa
    }

async def serialize_game(g: MafiaGame, include_avatars=False) -> dict:
    return {
        "p": [await serialize_player(p, include_avatars) for p in g.players],
        "d": g._day # noqa
    }

class GameProcessor(multiprocessing.Process):
    def run(self) -> None:
        print("daemon start")
        pipe = self._args[0] # noqa
        avatars = {}
        print("waiting")
        data: dict = pipe.recv()
        print("received")
        game: dict = data['g']
        for player in game['p']:
            avatars[player['i']] = round_avatar(player['a'])

        while True:
            d = pipe.recv()
            if d['op'] == 0:
                resp = _sync_make_night_image(d['d'])
            elif d['op'] == 1:
                game.update(d['g'])
                deaths = d['d']
                resp = _sync_make_day_image(game, deaths, avatars)
            else:
                raise RuntimeError("unknown opcode")

            pipe.send(resp)

def add_corners(im, rad):
    if im.size != (128, 128):
        im = im.resize((128, 128))

    global alpha
    if not alpha: # cache the alpha layer
        circle = Image.new('L', (rad * 2, rad * 2), 0)
        draw = ImageDraw.Draw(circle)
        draw.ellipse((0, 0, rad * 2, rad * 2), fill=255)
        alpha = Image.new('L', im.size, 255)
        alpha.paste(circle.crop((0, 0, rad, rad)), (0, 0))
        alpha.paste(circle.crop((0, rad, rad, rad * 2)), (0, im.size[0] - rad))
        alpha.paste(circle.crop((rad, 0, rad * 2, rad)), (128 - rad, 0))
        alpha.paste(circle.crop((rad, rad, rad * 2, rad * 2)), (im.size[0] - rad, im.size[0] - rad))

    im.putalpha(alpha)
    return im.resize((96,96))

def round_avatar(avy: io.BytesIO, rad=64) -> Image:
    return add_corners(Image.open(avy, formats=("png",)), rad)

async def create_day_image(game: MafiaGame, deaths: typing.List[players.Player]) -> io.BytesIO:
    if id(game) not in processes:
        parent, child = multiprocessing.Pipe(True)
        processes[id(game)] = proc = GameProcessor(args=(child,))
        proc.start()
        proc.pipe = parent
        parent.send({"g": await serialize_game(game, include_avatars=True)})
        parent.send({"op": 1, "g": {}, "d": [x.member.id for x in deaths]})

    else:
        proc = processes[id(game)]
        proc.pipe.send({"op": 1, "d": [x.member.id for x in deaths], "g": await serialize_game(game, include_avatars=False)})

    return await game.ctx.bot.loop.run_in_executor(pool, proc.pipe.recv)

async def create_night_image(game: MafiaGame) -> io.BytesIO:
    if id(game) not in processes:
        parent, child = multiprocessing.Pipe(True)
        processes[id(game)] = proc = GameProcessor(args=(child,))
        proc.start()
        proc.pipe = parent
        parent.send({"g": await serialize_game(game, include_avatars=True)})
        parent.send({"op": 1, "g": {}})

    else:
        proc = processes[id(game)]
        proc.pipe.send({"op": 0, "g": serialize_game(game, False)})

    return await game.ctx.bot.loop.run_in_executor(pool, proc.pipe.recv)

def _sync_make_night_image(night: int) -> io.BytesIO:
    base: Image.Image = Image.open("./resources/background-night.png", formats=("png",))
    base = base.resize((1920, 1080))
    raster = ImageDraw.Draw(base)
    raster.text(((1920-__w)/2, 30), f"Day {night}", font=font_28days_title, fill="black") # noqa

    buf = io.BytesIO()
    base.save(buf, format="png")
    buf.seek(0)
    base.close()
    return buf

def _sync_make_day_image(game: dict, deaths: typing.List[int], avatars: dict) -> io.BytesIO:
    base: Image.Image = Image.open("./resources/background-day.png", formats=("png",))
    base = base.resize((1920, 1080)).convert("RGBA")
    raster = ImageDraw.Draw(base)
    alive = list(filter(lambda player: not player['d'], game['p']))
    dead = list(filter(lambda player: player['d'] and player['i'] not in deaths, game['p']))
    __w, _ = raster.textsize(f"Day {game['d']}", font=font_28days_title) # noqa
    raster.text(((1920-__w)/2, 30), f"Day {game['d']}", font=font_28days_title, fill="black") # noqa
    raster.text((30, 260), f"Alive Players", font=font_28days_subtitle,) # noqa
    spe = 105
    col_width = 400
    row = col = 0

    def paste_avatar(player: dict, text_fill, do_x, show_role):
        nonlocal col, row
        avy = avatars[player['i']]
        x = (30 + (col * col_width), int(330 + (spe * row)), 30 + avy.size[0] + (col * col_width),
             int(330 + (spe * row) + avy.size[1]))
        base.paste(avy, x, mask=avy)
        if do_x:
            base.paste(death_marker, x, mask=death_marker)

        nick = f"{player['ni'] + ' ' if player['ni'] else ''}{'('+player['na']+')' if player['ni'] else player['na']}"
        if len(nick) >= 17:
            nick = nick[:17] + "..."

        if show_role:
            nick += f"\n\t{player['r']}"
            t = (x[2] + 20, int(330 + (spe * row)))

        else:
            _, _h = raster.textsize(nick, font=font_vermillion)
            t = (x[2] + 20, int(330 + (spe * row) + (_h / 2)))

        raster.text(t, nick, font=font_vermillion, fill=text_fill)
        row += 1
        if row >= 7:
            row = 0
            col += 1

    if deaths:
        d = [discord.utils.find(lambda pl: pl['i'] == x, game['p']) for x in deaths]
        for p in d:
            fill = "black" if col >= 1 and 3 > row > 0 else "white"
            paste_avatar(p, fill, True, True)

    for p in alive:
        fill = "black" if col >= 1 and 3 > row > 0 else "white"
        paste_avatar(p, fill, False, False)

    if dead:
        if row:
            col += 1
            row = 0

        raster.text((30+(col*col_width), 260), f"Dead Players", font=font_28days_subtitle, fill="black")
        for p in dead:
            fill = "black" if (col >= 1 and row == 2) or (col == 3 and (row == 0 or row == 2)) else "white"
            paste_avatar(p, fill, True, True)

    buf = io.BytesIO()
    base.save(buf, format="png")
    buf.seek(0)
    base.close()
    return buf

def cleanup_game(game: MafiaGame):
    if id(game) in processes:
        processes[id(game)].terminate()
        del processes[id(game)]

def setup(bot):
    bot.create_day_image = create_day_image
    bot.create_night_image = create_night_image
    bot.cleanup_imaging = cleanup_game

def teardown(bot):
    del bot.create_day_image
    del bot.create_night_image
    del bot.cleanup_imaging
    for proc in processes.values():
        proc.terminate()
