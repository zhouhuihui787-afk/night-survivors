"""The game rules of Night Survivors, with a fixed time step.

No pygame here: this file only does maths, so the tests can check the rules
and main.py can draw whatever it likes.
Call new_state() once, then step(state, rng) 60 times per second.
step() also writes down what just happened in state["events"] (a hit, a gem, a
death, a level-up, the end); main.py reads that list every frame and empties it.
"""

import json
import math
import os

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "game.json")


def load_config(path=DATA_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def distance(a, b):
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def weapon_stats(config, key, level):
    """All the numbers of one weapon at one level (1 to 5)."""
    weapon = config["weapons"][key]
    stats = dict(weapon["base"])
    for name, extra in weapon.get("per_level", {}).items():
        stats[name] = stats.get(name, 0) + extra * (level - 1)
    if "count" in stats:
        for at_level, add in weapon.get("count_at_levels", {}).items():
            if level >= int(at_level):
                stats["count"] += add
    return stats


def item_level(state, key):
    return state["items"].get(key, 0)


def hero_speed(state):
    """Walking speed with Swift Boots taken into account."""
    config = state["config"]
    percent = config["items"]["boots"]["per_level"]["speed_pct"]
    return config["hero"]["speed"] * (1.0 + percent * item_level(state, "boots") / 100.0)


def magnet_radius(state):
    config = state["config"]
    extra = config["items"]["magnet"]["per_level"]["radius"]
    return config["hero"]["magnet_radius"] + extra * item_level(state, "magnet")


def xp_needed(config, level):
    """XP needed to go from this level to the next: 5, 8, 11, 14, ..."""
    return config["xp"]["first"] + config["xp"]["step"] * (level - 1)


def weapon_text(config, key, level):
    """One line that says what this weapon does at this level."""
    stats = weapon_stats(config, key, level)
    if key == "spark":
        return "{} damage, every {:.2f} s, {} spark{}".format(
            stats["damage"], stats["interval"], stats["count"], "s" if stats["count"] > 1 else "")
    if key == "blades":
        return "{} blades, {} damage, {} px around you".format(
            stats["count"], stats["damage"], stats["orbit"])
    return "{} damage, radius {} px".format(stats["damage"], stats["radius"])


def make_enemy(config, kind, x, y):
    spec = config["enemies"][kind]
    return {
        "kind": kind,
        "x": x,
        "y": y,
        "hp": float(spec["hp"]),
        "hit_cooldown": 0.0,
        "blade_timers": {},
    }


def is_boss(config, kind):
    """The boss is the enemy marked 'boss' in the data (the Demon)."""
    return bool(config["enemies"][kind].get("boss"))


def add_event(state, kind, **data):
    """Write down that something happened, for main.py to draw and play.

    main.py reads state["events"] once per frame and then empties the list.
    """
    event = {"kind": kind}
    event.update(data)
    state["events"].append(event)


def new_state(config, hero_x=0.0, hero_y=0.0):
    return {
        "config": config,
        "status": "running",
        "elapsed": 0.0,
        "kills": 0,
        "shots_fired": 0,
        "level": 1,
        "xp": 0,
        "pending_level_ups": 0,
        "level_up": None,
        "hero": {
            "x": hero_x,
            "y": hero_y,
            "hp": float(config["hero"]["hp"]),
            "max_hp": float(config["hero"]["hp"]),
        },
        "target": {"x": hero_x, "y": hero_y},
        "weapons": {"spark": 1},
        "items": {},
        "weapon_timers": {"spark": weapon_stats(config, "spark", 1)["interval"]},
        "blades_angle": 0.0,
        "enemies": [],
        "shots": [],
        "gems": [],
        "bosses": [],
        "events": [],
        "spawn_timer": config["spawn"]["interval"],
    }


def minimum_alive(config, elapsed):
    """The 'Minimum alive' for this time from the spawn table."""
    chosen = None
    for row in config["spawn"]["table"]:
        if elapsed >= row["from"]:
            chosen = row
    return [] if chosen is None else chosen["types"], 0 if chosen is None else chosen["min_alive"]


def boss_for(config, elapsed):
    """The boss a spawn row names for this time, or None. Each boss comes once."""
    chosen = None
    for row in config["spawn"]["table"]:
        if elapsed >= row["from"] and row.get("boss"):
            chosen = row["boss"]
    return chosen


# ---------------------------------------------------------------- choices


def card_for(config, kind, key, level):
    if kind == "heal":
        heal = config["heal_card"]
        return {"kind": "heal", "key": None, "level": 0, "name": heal["name"], "text": heal["text"]}
    part = config["weapons"][key] if kind == "weapon" else config["items"][key]
    if kind == "item" or level == 1:
        text = part["description"]
    else:
        text = weapon_text(config, key, level)
    return {"kind": kind, "key": key, "level": level, "name": part["card_name"], "text": text}


def make_offers(state, rng):
    """Three random cards: a new weapon, +1 level, or a passive item."""
    config = state["config"]
    max_weapons = config["growth"]["max_weapons"]
    max_level = config["growth"]["max_level"]
    offers = []
    for key in config["weapons"]:
        level = state["weapons"].get(key)
        if level is None:
            if len(state["weapons"]) < max_weapons:
                offers.append(card_for(config, "weapon", key, 1))
        elif level < max_level:
            offers.append(card_for(config, "weapon", key, level + 1))
    for key in config["items"]:
        level = state["items"].get(key)
        if level is None:
            offers.append(card_for(config, "item", key, 1))
        elif level < max_level:
            offers.append(card_for(config, "item", key, level + 1))
    if not offers:
        return [card_for(config, "heal", None, 0)]
    rng.shuffle(offers)
    return offers[: config["cards"]["count"]]


def apply_card(state, index, rng):
    """The player picked a card: apply it, then show the next one if any is waiting."""
    config = state["config"]
    card = state["level_up"]["cards"][index]
    if card["kind"] == "weapon":
        state["weapons"][card["key"]] = card["level"]
        state["weapon_timers"][card["key"]] = 0.0  # a new weapon works at once
    elif card["kind"] == "item":
        key = card["key"]
        old = item_level(state, key)
        state["items"][key] = card["level"]
        if key == "heart":
            per = config["items"]["heart"]["per_level"]
            steps = card["level"] - old
            hero = state["hero"]
            hero["max_hp"] += per["max_hp"] * steps
            hero["hp"] = min(hero["max_hp"], hero["hp"] + per["heal"] * steps)
    else:
        hero = state["hero"]
        hero["hp"] = min(hero["max_hp"], hero["hp"] + config["heal_card"]["amount"])

    state["pending_level_ups"] -= 1
    if state["pending_level_ups"] > 0:
        state["level_up"] = {"cards": make_offers(state, rng)}
    else:
        state["level_up"] = None


# ---------------------------------------------------------------- movement


def move_hero(state):
    config = state["config"]
    hero = state["hero"]
    target = state["target"]
    gap = distance(hero, target)
    dead_zone = config["pointer"]["walk_min_distance"]
    if gap <= dead_zone:
        return  # the pointer is on the hero: stand still, do not jitter
    per_step = hero_speed(state) * config["dt"]
    new_gap = max(dead_zone, gap - per_step)
    scale = new_gap / gap
    hero["x"] = target["x"] + (hero["x"] - target["x"]) * scale
    hero["y"] = target["y"] + (hero["y"] - target["y"]) * scale


def move_enemies(state):
    config = state["config"]
    dt = config["dt"]
    hero = state["hero"]
    hero_r = config["hero"]["hit_radius"]
    for e in state["enemies"]:
        spec = config["enemies"][e["kind"]]
        stop_at = hero_r + spec["hit_radius"]
        gap = distance(e, hero)
        room = gap - stop_at
        if room <= 0:
            continue  # already touching: it does not push through the hero
        per_step = spec["speed"] * dt
        if per_step >= room:
            per_step = room
        scale = per_step / gap
        e["x"] += (hero["x"] - e["x"]) * scale
        e["y"] += (hero["y"] - e["y"]) * scale


def blade_positions(state):
    """Where each Spin Blade is right now."""
    if "blades" not in state["weapons"]:
        return []
    stats = weapon_stats(state["config"], "blades", state["weapons"]["blades"])
    hero = state["hero"]
    places = []
    for index in range(stats["count"]):
        angle = state["blades_angle"] + index * 2.0 * math.pi / stats["count"]
        places.append(
            {
                "index": index,
                "x": hero["x"] + stats["orbit"] * math.cos(angle),
                "y": hero["y"] + stats["orbit"] * math.sin(angle),
                "stats": stats,
            }
        )
    return places


# ---------------------------------------------------------------- weapons


def fire_spark(state):
    """The Spark Wand shoots its sparks at the nearest enemy when the timer is ready."""
    config = state["config"]
    if "spark" not in state["weapons"]:
        return
    timer = state["weapon_timers"].get("spark", 0.0) - config["dt"]
    if timer > 0:
        state["weapon_timers"]["spark"] = timer
        return
    state["weapon_timers"]["spark"] = 0.0
    if not state["enemies"]:
        return  # hold the charge: the first enemy is shot at once
    hero = state["hero"]
    stats = weapon_stats(config, "spark", state["weapons"]["spark"])
    nearest = min(state["enemies"], key=lambda e: distance(e, hero))
    gap = distance(nearest, hero)
    if gap <= 0.0001:
        aim = 0.0
    else:
        aim = math.atan2(nearest["y"] - hero["y"], nearest["x"] - hero["x"])
    spread = math.radians(stats["spread_deg"])
    for k in range(stats["count"]):
        angle = aim + (k - (stats["count"] - 1) / 2.0) * spread
        state["shots"].append(
            {
                "x": hero["x"],
                "y": hero["y"],
                "vx": math.cos(angle) * stats["speed"],
                "vy": math.sin(angle) * stats["speed"],
                "damage": stats["damage"],
                "draw_px": stats["draw_px"],
                "hit_radius": stats["hit_radius"],
                "life": stats["lifetime"],
            }
        )
        state["shots_fired"] += 1
    state["weapon_timers"]["spark"] = stats["interval"]


def move_shots(state):
    config = state["config"]
    dt = config["dt"]
    survivors = []
    for s in state["shots"]:
        s["x"] += s["vx"] * dt
        s["y"] += s["vy"] * dt
        s["life"] -= dt
        hit = None
        for e in state["enemies"]:
            if distance(s, e) <= s["hit_radius"]:
                hit = e
                break
        if hit is not None:
            hit["hp"] -= s["damage"]
            add_event(state, "hit", x=hit["x"], y=hit["y"], amount=s["damage"])
            continue
        if s["life"] > 0:
            survivors.append(s)
    state["shots"] = survivors


def spin_blades(state):
    """Blades go round the hero; each blade hurts one enemy at most every 0.5 s."""
    config = state["config"]
    dt = config["dt"]
    if "blades" not in state["weapons"]:
        return
    stats = weapon_stats(config, "blades", state["weapons"]["blades"])
    state["blades_angle"] = (state["blades_angle"] + 2.0 * math.pi / stats["turn_seconds"] * dt) % (2.0 * math.pi)
    for e in state["enemies"]:
        for index in list(e["blade_timers"]):
            e["blade_timers"][index] -= dt
            if e["blade_timers"][index] <= 0:
                del e["blade_timers"][index]
    for blade in blade_positions(state):
        for e in state["enemies"]:
            if e["blade_timers"].get(blade["index"], 0.0) > 0:
                continue
            reach = stats["hit_radius"] + config["enemies"][e["kind"]]["hit_radius"]
            if math.hypot(blade["x"] - e["x"], blade["y"] - e["y"]) <= reach:
                e["hp"] -= stats["damage"]
                e["blade_timers"][blade["index"]] = stats["hit_cooldown"]
                add_event(state, "hit", x=e["x"], y=e["y"], amount=stats["damage"])


def holy_ring(state):
    """Every 0.5 s everything inside the circle around the hero is hurt."""
    config = state["config"]
    if "ring" not in state["weapons"]:
        return
    stats = weapon_stats(config, "ring", state["weapons"]["ring"])
    timer = state["weapon_timers"].get("ring", 0.0) - config["dt"]
    if timer > 0:
        state["weapon_timers"]["ring"] = timer
        return
    state["weapon_timers"]["ring"] = stats["interval"]
    for e in state["enemies"]:
        if distance(e, state["hero"]) <= stats["radius"]:
            e["hp"] -= stats["damage"]
            add_event(state, "hit", x=e["x"], y=e["y"], amount=stats["damage"])


# ---------------------------------------------------------------- spawning


def place_on_circle(state, rng):
    """A random point on the spawn circle, just outside the screen."""
    config = state["config"]
    hero = state["hero"]
    angle = rng.uniform(0.0, 2.0 * math.pi)
    r = config["spawn"]["circle_radius"]
    return hero["x"] + r * math.cos(angle), hero["y"] + r * math.sin(angle)


def spawn(state, rng):
    """Once per second: top up to the minimum for this time, at most 8, never over 120."""
    config = state["config"]
    spawn_cfg = config["spawn"]
    state["spawn_timer"] -= config["dt"]
    if state["spawn_timer"] > 0:
        return
    state["spawn_timer"] = spawn_cfg["interval"]
    room = spawn_cfg["max_alive"] - len(state["enemies"])

    # the boss of a row comes exactly once for the whole game
    boss = boss_for(config, state["elapsed"])
    if boss and room > 0 and boss not in state["bosses"] and boss in config["enemies"]:
        state["bosses"].append(boss)
        x, y = place_on_circle(state, rng)
        state["enemies"].append(make_enemy(config, boss, x, y))
        room -= 1

    types, need = minimum_alive(config, state["elapsed"])
    # a row may name enemies this build does not have yet: ignore those
    types = [t for t in types if t in config["enemies"]]
    if not types or need <= 0:
        return
    to_add = max(0, min(need - len(state["enemies"]), spawn_cfg["max_per_tick"], room))
    for _ in range(to_add):
        x, y = place_on_circle(state, rng)
        state["enemies"].append(make_enemy(config, rng.choice(types), x, y))


def cull(state, rng):
    """Normal enemies far away are removed; the boss is pulled back to the spawn circle."""
    config = state["config"]
    limit = config["spawn"]["cull_distance"]
    reset = config["spawn"]["boss_reset_distance"]
    hero = state["hero"]
    kept = []
    for e in state["enemies"]:
        gap = distance(e, hero)
        if is_boss(config, e["kind"]):
            if gap > reset:  # it never leaves, it just comes back to you
                e["x"], e["y"] = place_on_circle(state, rng)
            kept.append(e)
        elif gap <= limit:
            kept.append(e)
    state["enemies"] = kept


def contact_damage(state):
    config = state["config"]
    dt = config["dt"]
    hero = state["hero"]
    hero_r = config["hero"]["hit_radius"]
    cooldown = config["contact"]["hit_cooldown"]
    for e in state["enemies"]:
        if e["hit_cooldown"] > 0:
            e["hit_cooldown"] -= dt
            continue
        reach = hero_r + config["enemies"][e["kind"]]["hit_radius"]
        if distance(e, hero) <= reach:
            hurt = config["enemies"][e["kind"]]["damage"]
            hero["hp"] -= hurt
            e["hit_cooldown"] = cooldown
            add_event(state, "hurt", amount=hurt)


def drop_dead(state):
    """A dead enemy disappears and leaves a gem worth its XP."""
    config = state["config"]
    alive = []
    for e in state["enemies"]:
        if e["hp"] <= 0:
            state["kills"] += 1
            add_event(state, "die", x=e["x"], y=e["y"], boss=is_boss(config, e["kind"]))
            if config["enemies"][e["kind"]]["xp"] > 0:
                state["gems"].append({"x": e["x"], "y": e["y"], "xp": config["enemies"][e["kind"]]["xp"]})
        else:
            alive.append(e)
    state["enemies"] = alive


def move_gems(state):
    """Gems inside the magnet radius fly to the hero; the rest wait on the floor."""
    config = state["config"]
    dt = config["dt"]
    hero = state["hero"]
    pull = magnet_radius(state)
    pickup = config["gems"]["pickup_radius"]
    speed = config["gems"]["speed"]
    left = []
    for gem in state["gems"]:
        gap = distance(gem, hero)
        if gap <= pickup:
            state["xp"] += gem["xp"]
            add_event(state, "gem", x=gem["x"], y=gem["y"], amount=gem["xp"])
            continue
        if gap <= pull and gap > 0.0001:
            move = min(speed * dt, gap)
            gem["x"] += (hero["x"] - gem["x"]) / gap * move
            gem["y"] += (hero["y"] - gem["y"]) / gap * move
        left.append(gem)
    state["gems"] = left


def check_level_up(state, rng):
    """Every full bar is one level, and each level waits for its own choice."""
    while state["xp"] >= xp_needed(state["config"], state["level"]):
        state["xp"] -= xp_needed(state["config"], state["level"])
        state["level"] += 1
        state["pending_level_ups"] += 1
    if state["pending_level_ups"] > 0 and state["level_up"] is None:
        state["level_up"] = {"cards": make_offers(state, rng)}
        add_event(state, "level_up", level=state["level"])


def step(state, rng):
    """One fixed time step (1/60 s). Returns the same state."""
    if state["status"] != "running":
        return state
    if state["level_up"] is not None:
        return state  # the game waits while the player reads the cards
    config = state["config"]
    state["elapsed"] += config["dt"]
    move_hero(state)
    move_enemies(state)
    fire_spark(state)
    spin_blades(state)
    holy_ring(state)
    move_shots(state)
    spawn(state, rng)
    cull(state, rng)
    contact_damage(state)
    drop_dead(state)
    move_gems(state)
    check_level_up(state, rng)
    if state["elapsed"] >= config["game"]["win_time"]:
        state["status"] = "victory"  # you held on until 2:00
        add_event(state, "end", status="victory")
    elif state["hero"]["hp"] <= 0:
        state["hero"]["hp"] = 0.0
        state["status"] = "game_over"
        add_event(state, "end", status="game_over")
    return state
