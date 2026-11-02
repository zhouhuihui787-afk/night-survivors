"""Night Survivors — window, drawing, sound and input (step 5: Sound and feel).

The rules live in rules.py; this file reads the mouse, paints the screen, shows
the level-up cards, plays the sounds and restarts the game. It uses nothing but
Python's standard library and pygame-ce. Pictures come from assets/ (made by
make_assets.py) and sounds from sounds/ (made by make_sounds.py); this file
never imports Pillow and never imports wave.
"""

import asyncio
import math
import os
import random

import pygame

import rules

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
SOUNDS = os.path.join(HERE, "sounds")
SOUND_NAMES = ("hit", "gem", "levelup", "hurt", "end")
WIDTH = 390   # corrected from data/game.json when the game starts
HEIGHT = 700

BG_COLOR = (20, 22, 30)
HP_BACK = (60, 20, 20)
HP_FRONT = (220, 60, 60)
XP_BACK = (20, 30, 60)
XP_FRONT = (90, 150, 240)
TEXT = (240, 240, 240)
SOFT_TEXT = (200, 200, 210)
GOOD_TEXT = (160, 220, 160)
PAUSE_TEXT = (240, 240, 120)
RING_COLOR = (120, 220, 255)
CARD_BACK = (38, 42, 58)
CARD_EDGE = (120, 140, 200)
CARD_LEVEL = (250, 210, 110)
FLASH = (255, 255, 255)
FLASH_EDGE = (250, 200, 120)
HURT_COLOR = (255, 120, 110)
BOSS_COLOR = (255, 200, 90)

tile_image = None  # made in run_game
_loaded = {}  # file name -> the 48x48 picture
_scaled = {}  # (file name, size) -> the picture at that size
_sounds = {}  # sound name -> the loaded sound, or None when the file is missing


def load_sound(name):
    """sounds/<name>.ogg if it is there, otherwise <name>.wav. Loaded once."""
    if name not in _sounds:
        _sounds[name] = None
        for suffix in (".ogg", ".wav"):
            path = os.path.join(SOUNDS, name + suffix)
            if os.path.isfile(path):
                try:
                    _sounds[name] = pygame.mixer.Sound(path)
                except pygame.error:  # no sound device: the game stays quiet
                    print("Could not play %s: the game runs without sound." % path)
                break
        if _sounds[name] is None and not os.path.isdir(SOUNDS):
            print("Missing sounds: %s\nRun this first:  python3 make_sounds.py" % name)
    return _sounds[name]


def play(name, now, last_played, gap):
    """Play a sound, but never the same one twice inside 'gap' seconds."""
    sound = load_sound(name)
    if sound is None or now - last_played.get(name, -1.0) < gap:
        return
    last_played[name] = now
    sound.play()


def load_picture(name, px):
    """assets/<name>, copied at the size we draw it (loaded once, then reused)."""
    key = (name, px)
    if key not in _scaled:
        if name not in _loaded:
            path = os.path.join(ASSETS, name)
            if not os.path.isfile(path):
                raise SystemExit(
                    "Missing picture: %s\nRun this first:  python3 make_assets.py" % path)
            _loaded[name] = pygame.image.load(path).convert_alpha()
        source = _loaded[name]
        _scaled[key] = pygame.transform.scale(source, (px, px)) if px != source.get_width() else source
    return _scaled[key]


def blit_centred(screen, picture, x, y):
    """Draw a picture with its middle at (x, y)."""
    rect = picture.get_rect()
    rect.center = (int(x), int(y))
    screen.blit(picture, rect)


def time_text(seconds):
    whole = max(0, int(seconds))
    return "{}:{}".format(whole // 60, whole % 60)


def loadout_text(state):
    """The bottom line, e.g. 'Spark 2  Boots 1'."""
    config = state["config"]
    parts = []
    for key, level in state["weapons"].items():
        name = config["weapons"].get(key, {}).get("card_name", key)
        parts.append("{} {}".format(name, level))
    for key, level in state["items"].items():
        name = config["items"].get(key, {}).get("card_name", key)
        parts.append("{} {}".format(name, level))
    return "  ".join(parts)


def draw_floor(screen, config, camera_x, camera_y):
    """One tile repeated forever, lined up with the world so it looks still."""
    tile = config["window"]["tile"]
    left = camera_x - WIDTH / 2
    top = camera_y - HEIGHT / 2
    screen.fill(BG_COLOR)
    y = math.floor(top / tile) * tile
    while y < top + HEIGHT:
        x = math.floor(left / tile) * tile
        while x < left + WIDTH:
            screen.blit(tile_image, (x - left, y - top))
            x += tile
        y += tile


def to_screen(config, camera, world_x, world_y):
    return (world_x - camera[0] + WIDTH / 2, world_y - camera[1] + HEIGHT / 2)


def draw_enemy(config, screen, camera, enemy):
    spec = config["enemies"][enemy["kind"]]
    sx, sy = to_screen(config, camera, enemy["x"], enemy["y"])
    blit_centred(screen, load_picture(enemy["kind"], spec["draw_px"]), sx, sy)
    if enemy["hp"] < spec["hp"]:
        width = max(24, spec["draw_px"])  # the boss gets a bar it can read
        top = sy - spec["draw_px"] / 2 - 6
        pygame.draw.rect(screen, HP_BACK, (sx - width / 2, top, width, 3))
        ratio = max(0.0, enemy["hp"] / spec["hp"])
        pygame.draw.rect(screen, HP_FRONT, (sx - width / 2, top, width * ratio, 3))


def draw_flashes(config, screen, camera, flashes):
    """A short bright burst where an enemy died."""
    total = config["feel"]["flash_seconds"]
    for f in flashes:
        t = 1.0 - f["life"] / total          # 0 when it starts, 1 when it is gone
        radius = int(f["radius"] * (0.45 + 0.55 * t))
        sx, sy = to_screen(config, camera, f["x"], f["y"])
        size = radius * 2 + 4
        layer = pygame.Surface((size, size), pygame.SRCALPHA)
        centre = (size // 2, size // 2)
        alpha = int(230 * (1.0 - t))
        if t < 0.35:
            pygame.draw.circle(layer, FLASH + (alpha,), centre, radius)
        else:
            pygame.draw.circle(layer, FLASH_EDGE + (alpha,), centre, radius, 2)
        screen.blit(layer, (sx - size // 2, sy - size // 2))


def draw_floats(config, screen, camera, floats, font):
    """Damage numbers: they rise from the enemy and fade as they go."""
    feel = config["feel"]
    total = feel["damage_number_seconds"]
    for f in floats:
        t = 1.0 - f["life"] / total
        colour = tuple(int(a + (b - a) * t) for a, b in zip(f["start"], (30, 26, 24)))
        text = font.render(f["text"], True, colour)
        shadow = font.render(f["text"], True, (20, 20, 26))
        sx, sy = to_screen(config, camera, f["x"], f["y"] - feel["damage_number_rise"] * t)
        left = sx - text.get_width() / 2
        screen.blit(shadow, (left + 1, sy - text.get_height() + 1))
        screen.blit(text, (left, sy - text.get_height()))


def draw_hud(config, screen, state, fonts, paused):
    hero = state["hero"]
    big, small = fonts[0], fonts[2]
    # HP bar (red) and XP bar (blue) top left
    pygame.draw.rect(screen, HP_BACK, (10, 10, 150, 12))
    ratio = max(0.0, hero["hp"] / hero["max_hp"])
    pygame.draw.rect(screen, HP_FRONT, (10, 10, 150 * ratio, 12))
    pygame.draw.rect(screen, TEXT, (10, 10, 150, 12), 1)
    need = rules.xp_needed(config, state["level"])
    pygame.draw.rect(screen, XP_BACK, (10, 26, 150, 8))
    pygame.draw.rect(screen, XP_FRONT, (10, 26, 150 * min(1.0, state["xp"] / need), 8))
    pygame.draw.rect(screen, TEXT, (10, 26, 150, 8), 1)
    level = small.render("Lv {}".format(state["level"]), True, TEXT)
    screen.blit(level, (10, 38))
    # timer top right
    timer = big.render(
        "{} / {}".format(time_text(state["elapsed"]), time_text(config["game"]["win_time"])),
        True, TEXT)
    screen.blit(timer, (WIDTH - timer.get_width() - 10, 8))
    # what you have, bottom
    line = small.render(loadout_text(state), True, SOFT_TEXT)
    screen.blit(line, (10, HEIGHT - line.get_height() - 10))
    if paused:
        word = big.render("PAUSED  (P)", True, PAUSE_TEXT)
        screen.blit(word, ((WIDTH - word.get_width()) / 2, 40))


def gem_picture_name(config, xp):
    """The gem file for this much XP: the biggest 'by_xp' step that fits."""
    by_xp = config["gems"]["by_xp"]
    best = None
    for key, name in by_xp.items():
        worth = int(key)
        if worth <= xp and (best is None or worth > best):
            best, chosen = worth, name
    return chosen if best is not None else "gem.png"


def draw_gems(config, screen, camera, state):
    px = config["gems"]["draw_px"]
    for gem in state["gems"]:
        sx, sy = to_screen(config, camera, gem["x"], gem["y"])
        blit_centred(screen, load_picture(gem_picture_name(config, gem["xp"]), px), sx, sy)


def draw_blades(config, screen, camera, state):
    for blade in rules.blade_positions(state):
        sx, sy = to_screen(config, camera, blade["x"], blade["y"])
        blit_centred(screen, load_picture("sword.png", blade["stats"]["draw_px"]), sx, sy)


def draw_ring(config, screen, camera, state):
    """The Holy Ring circle: bright for a moment after each pulse."""
    level = state["weapons"].get("ring")
    if level is None:
        return
    stats = rules.weapon_stats(config, "ring", level)
    timer = state["weapon_timers"].get("ring", 0.0)
    hx, hy = to_screen(config, camera, state["hero"]["x"], state["hero"]["y"])
    just_pulsed = timer > stats["interval"] - 2 * config["dt"]
    pygame.draw.circle(screen, RING_COLOR, (hx, hy), stats["radius"], 2 if just_pulsed else 1)


def card_rects(count):
    """Where the 1-3 level-up cards go, so drawing and clicking agree."""
    width, height, gap = 350, 110, 16
    left = (WIDTH - width) / 2
    top = HEIGHT * 0.30
    return [pygame.Rect(left, top + n * (height + gap), width, height) for n in range(count)]


def draw_level_up(screen, state, fonts):
    """The game is frozen; the player picks one card."""
    big, mid, small = fonts
    veil = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    veil.fill((0, 0, 0, 190))
    screen.blit(veil, (0, 0))
    title = big.render("LEVEL UP!  pick a card", True, CARD_LEVEL)
    screen.blit(title, ((WIDTH - title.get_width()) / 2, HEIGHT * 0.30 - 55))
    for rect, card in zip(card_rects(len(state["level_up"]["cards"])), state["level_up"]["cards"]):
        pygame.draw.rect(screen, CARD_BACK, rect, border_radius=10)
        pygame.draw.rect(screen, CARD_EDGE, rect, 2, border_radius=10)
        name = mid.render(card["name"], True, TEXT)
        screen.blit(name, (rect.x + 14, rect.y + 12))
        tag = "NEW" if card["level"] <= 1 else "Lv {}".format(card["level"])
        badge = small.render(tag, True, CARD_LEVEL)
        screen.blit(badge, (rect.right - badge.get_width() - 14, rect.y + 14))
        text = small.render(card["text"], True, SOFT_TEXT)
        screen.blit(text, (rect.x + 14, rect.y + 48))


def draw_end(config, screen, state, fonts):
    """VICTORY when the time is up, GAME OVER when the hero falls."""
    big, small = fonts[0], fonts[2]
    won = state["status"] == "victory"
    veil = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    veil.fill((0, 0, 0, 180))
    screen.blit(veil, (0, 0))
    title = big.render("VICTORY" if won else "GAME OVER", True,
                       GOOD_TEXT if won else (240, 80, 80))
    screen.blit(title, ((WIDTH - title.get_width()) / 2, HEIGHT * 0.38))
    stats = small.render(
        "time {}   kills {}   Lv {}".format(time_text(state["elapsed"]), state["kills"], state["level"]),
        True, TEXT)
    screen.blit(stats, ((WIDTH - stats.get_width()) / 2, HEIGHT * 0.38 + 40))
    hint = small.render("click or tap to play again", True, GOOD_TEXT)
    screen.blit(hint, ((WIDTH - hint.get_width()) / 2, HEIGHT * 0.38 + 70))


def clamp_pointer(x, y):
    """Keep a pointer position inside the window."""
    return max(0.0, min(float(x), WIDTH - 1.0)), max(0.0, min(float(y), HEIGHT - 1.0))


def make_font(size, bold):
    """A system font, or pygame's own font when the browser has no system fonts."""
    try:
        font = pygame.font.SysFont("arial", size, bold)
    except pygame.error:
        font = None
    return font if font is not None else pygame.font.Font(None, size)


def age(items, seconds):
    """Count every effect down a little and drop the ones that are finished."""
    for item in items:
        item["life"] -= seconds
    return [item for item in items if item["life"] > 0]


async def run_game(config, outcome):
    """The whole game. 'outcome' lets the headless check see the last state."""
    global WIDTH, HEIGHT, tile_image
    WIDTH = config["window"]["width"]
    HEIGHT = config["window"]["height"]
    feel = config["feel"]
    try:
        pygame.mixer.pre_init(22050, -16, 1, 512)
    except pygame.error:
        pass
    try:
        pygame.init()
    except pygame.error as problem:  # a browser with no sound device must still open the window
        print("Sound would not start (%s): the game plays without it." % problem)
        pygame.display.init()
        pygame.font.init()
    if pygame.mixer.get_init() is None:
        try:
            pygame.mixer.init(22050, -16, 1, 512)
        except pygame.error:
            print("No sound device: the game plays without sound.")
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Night Survivors")
    # convert_alpha() needs the window, so every picture is loaded after this point
    tile_image = load_picture("floor.png", config["window"]["tile"])
    for name in SOUND_NAMES:
        load_sound(name)
    outcome["display"] = True
    clock = pygame.time.Clock()
    fonts = (make_font(22, True), make_font(18, True), make_font(14, False))

    rng = random.Random()
    view_rng = random.Random()
    state = rules.new_state(config)
    outcome["state"] = state
    running = True
    paused = False
    acc = 0.0
    dt_ms = config["dt"] * 1000.0
    floats = []      # damage numbers on their way up
    flashes = []     # the burst left by a dead enemy
    shake = 0.0      # seconds of screen shake still to play
    last_played = {}  # sound name -> when it last played
    pointer = [WIDTH / 2.0, HEIGHT / 2.0]  # where the player last pointed
    using_touch = False  # a finger has been seen: from then on it owns the walking
    touching = False     # a finger is on the screen right now

    while running:
        tap = None  # one click or one tap per frame, even if the browser sends both events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_p:
                paused = not paused
            elif event.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                # a finger that has been seen owns walking, so the mouse must not
                # move the old pointer any more - but a click is still a click
                if not using_touch:
                    pointer[:] = clamp_pointer(event.pos[0], event.pos[1])
                if event.type == pygame.MOUSEBUTTONDOWN and not touching:
                    tap = event.pos
            elif event.type in (pygame.FINGERDOWN, pygame.FINGERMOTION):
                using_touch = True
                touching = True
                pointer[:] = clamp_pointer(event.x * WIDTH, event.y * HEIGHT)
                if event.type == pygame.FINGERDOWN:
                    tap = tuple(pointer)
            elif event.type == pygame.FINGERUP:
                touching = False

        if tap is not None:
            if state["status"] != "running":
                state = rules.new_state(config)
                outcome["state"] = state
                floats, flashes, shake = [], [], 0.0
            elif state["level_up"] is not None:
                cards = state["level_up"]["cards"]
                for index, rect in enumerate(card_rects(len(cards))):
                    if rect.collidepoint(tap):
                        rules.apply_card(state, index, rng)
                        break

        # where is the pointer, in world coordinates?
        # mouse: keep walking to the last place it was seen, even when it does not move.
        # finger: walk only while it touches the screen, and stop when it lifts.
        if using_touch and not touching:
            px, py = WIDTH / 2.0, HEIGHT / 2.0  # the middle is the hero: he stands still
        else:
            px, py = pointer
        state["target"]["x"] = state["hero"]["x"] + px - WIDTH / 2
        state["target"]["y"] = state["hero"]["y"] + py - HEIGHT / 2

        ms = min(clock.tick(60), 250.0)  # real time since last frame, capped after a lag
        if not paused:
            acc += ms
            while acc >= dt_ms:
                acc -= dt_ms
                rules.step(state, rng)
        outcome["state"] = state

        # what just happened? play it and start the matching effect
        now = pygame.time.get_ticks() / 1000.0
        gap = feel["same_sound_gap"]
        hero = state["hero"]
        for note in state["events"]:
            kind = note["kind"]
            if kind == "hit":
                play("hit", now, last_played, gap)
                floats.append({"x": note["x"], "y": note["y"], "text": str(int(note["amount"])),
                               "life": feel["damage_number_seconds"], "start": TEXT})
            elif kind == "hurt":
                play("hurt", now, last_played, gap)
                shake = feel["shake_seconds"]
                floats.append({"x": hero["x"], "y": hero["y"], "text": "-%d" % int(note["amount"]),
                               "life": feel["damage_number_seconds"], "start": HURT_COLOR})
            elif kind == "gem":
                play("gem", now, last_played, gap)
            elif kind == "level_up":
                play("levelup", now, last_played, gap)
            elif kind == "die":
                radius = feel["boss_flash_radius"] if note["boss"] else feel["flash_radius"]
                flashes.append({"x": note["x"], "y": note["y"], "radius": radius,
                                "life": feel["flash_seconds"]})
            elif kind == "end":
                play("end", now, last_played, gap)
        del state["events"][:]
        seconds = ms / 1000.0
        floats = age(floats, seconds)
        flashes = age(flashes, seconds)

        camera = (hero["x"], hero["y"])
        if shake > 0:
            shake = max(0.0, shake - seconds)
            amount = feel["shake_px"] * shake / feel["shake_seconds"]
            camera = (camera[0] + view_rng.uniform(-amount, amount),
                      camera[1] + view_rng.uniform(-amount, amount))

        draw_floor(screen, config, camera[0], camera[1])
        draw_gems(config, screen, camera, state)
        draw_ring(config, screen, camera, state)
        for enemy in state["enemies"]:
            draw_enemy(config, screen, camera, enemy)
        draw_flashes(config, screen, camera, flashes)
        for shot in state["shots"]:
            sx, sy = to_screen(config, camera, shot["x"], shot["y"])
            blit_centred(screen, load_picture("sword.png", shot["draw_px"]), sx, sy)
        hx, hy = to_screen(config, camera, hero["x"], hero["y"])
        blit_centred(screen, load_picture("hero.png", config["hero"]["draw_px"]), hx, hy)
        draw_blades(config, screen, camera, state)
        draw_floats(config, screen, camera, floats, fonts[1])

        draw_hud(config, screen, state, fonts, paused)
        if state["level_up"] is not None:
            draw_level_up(screen, state, fonts)
        if state["status"] != "running":
            draw_end(config, screen, state, fonts)

        pygame.display.flip()
        await asyncio.sleep(0)

    pygame.quit()


async def main():
    config = rules.load_config(os.path.join(HERE, "data", "game.json"))
    await run_game(config, {})


if __name__ == "__main__":
    asyncio.run(main())
