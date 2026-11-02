"""Tests for the rules in rules.py only (no drawing, no pictures, no sounds).

Every number comes from data/game.json, so changing the design data must not
need a change here.
"""

import copy
import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rules

CONFIG = rules.load_config()
DT = CONFIG["dt"]

# for the tests that watch one enemy only: same numbers, no new waves
NO_SPAWN = copy.deepcopy(CONFIG)
NO_SPAWN["spawn"]["table"] = []


def fresh_state():
    return rules.new_state(CONFIG)


def quiet_state():
    return rules.new_state(NO_SPAWN)


def still_config(hp=1000):
    """The normal numbers, but Bats do not move and are hard to kill."""
    data = copy.deepcopy(NO_SPAWN)
    data["enemies"]["bat.png"]["speed"] = 0
    data["enemies"]["bat.png"]["hp"] = hp
    return data


def run(state, rng, seconds, pick=None):
    """Advance the game. When the cards appear, choose card number 'pick'."""
    for _ in range(int(round(seconds / DT))):
        rules.step(state, rng)
        if pick is not None and state["level_up"] is not None:
            rules.apply_card(state, min(pick, len(state["level_up"]["cards"]) - 1), rng)
    return state


# ---------------------------------------------------------------- spawning


class TestSpawning(unittest.TestCase):
    def test_first_second_spawns_at_most_eight(self):
        state = run(fresh_state(), random.Random(1), 1.0)
        self.assertGreater(len(state["enemies"]), 0)
        self.assertLessEqual(len(state["enemies"]), CONFIG["spawn"]["max_per_tick"])

    def test_spawned_on_circle_around_hero(self):
        state = run(fresh_state(), random.Random(3), 1.0)
        hero = state["hero"]
        for e in state["enemies"]:
            gap = math.hypot(e["x"] - hero["x"], e["y"] - hero["y"])
            # the hero may have walked a little, so allow some slack
            self.assertLess(gap, CONFIG["spawn"]["circle_radius"] + 10)

    def test_reaches_the_minimum_of_the_table(self):
        data = copy.deepcopy(CONFIG)
        data["hero"]["hp"] = 1_000_000  # a hero who cannot die: only the waves matter
        state = rules.new_state(data)
        _, need = rules.minimum_alive(CONFIG, 0.0)
        run(state, random.Random(5), 20.0, pick=0)
        self.assertGreaterEqual(len(state["enemies"]), need)

    def test_never_more_than_max_alive(self):
        state = fresh_state()
        state["enemies"] = [
            rules.make_enemy(CONFIG, "bat.png", 0.0, 0.0)
            for _ in range(CONFIG["spawn"]["max_alive"])
        ]
        run(state, random.Random(7), 5.0, pick=0)
        self.assertLessEqual(len(state["enemies"]), CONFIG["spawn"]["max_alive"])

    def test_far_enemy_is_removed(self):
        state = fresh_state()
        limit = CONFIG["spawn"]["cull_distance"]
        state["enemies"].append(rules.make_enemy(CONFIG, "bat.png", limit + 50.0, 0.0))
        state["enemies"].append(rules.make_enemy(CONFIG, "bat.png", limit - 100.0, 0.0))
        rules.step(state, random.Random(9))
        gaps = [math.hypot(e["x"], e["y"]) for e in state["enemies"]]
        self.assertTrue(all(g <= limit for g in gaps))
        self.assertTrue(len(gaps) >= 1)

    def test_row_naming_an_unknown_enemy_is_ignored(self):
        # a row may name a picture this build does not have: it must not break the game
        data = copy.deepcopy(CONFIG)
        del data["enemies"]["ghost.png"]
        data["hero"]["hp"] = 1_000_000
        state = rules.new_state(data)
        run(state, random.Random(12), 50.0, pick=0)
        kinds = {e["kind"] for e in state["enemies"]}
        self.assertTrue(kinds.issubset(set(data["enemies"].keys())))
        self.assertNotIn("ghost.png", kinds)
        self.assertEqual(state["status"], "running")


# ---------------------------------------------------------------- waves

BOSS_KINDS = [k for k, spec in CONFIG["enemies"].items() if spec.get("boss")]


class TestWaves(unittest.TestCase):
    def immortal(self):
        data = copy.deepcopy(CONFIG)
        data["hero"]["hp"] = 1_000_000
        return rules.new_state(data)

    def test_every_row_names_pictures_the_game_has(self):
        for row in CONFIG["spawn"]["table"]:
            for kind in row["types"]:
                self.assertIn(kind, CONFIG["enemies"])
            if row.get("boss"):
                self.assertIn(row["boss"], CONFIG["enemies"])

    def test_there_is_exactly_one_boss_in_the_data(self):
        self.assertEqual(len(BOSS_KINDS), 1)

    def test_slime_is_tough_and_slow_ghost_is_faster_than_the_hero(self):
        enemies, hero = CONFIG["enemies"], CONFIG["hero"]
        self.assertGreater(enemies["slime.png"]["hp"], enemies["bat.png"]["hp"])
        self.assertLess(enemies["slime.png"]["speed"], hero["speed"])
        self.assertGreater(enemies["ghost.png"]["speed"], hero["speed"])

    def test_the_boss_is_big_tough_and_gives_no_xp(self):
        boss = CONFIG["enemies"][BOSS_KINDS[0]]
        normal = [k for k in CONFIG["enemies"] if not CONFIG["enemies"][k].get("boss")]
        self.assertEqual(boss["xp"], 0)
        self.assertEqual(boss["draw_px"], 2 * CONFIG["enemies"]["bat.png"]["draw_px"])
        for kind in normal:
            self.assertGreater(boss["hp"], CONFIG["enemies"][kind]["hp"])

    def test_slime_and_ghost_really_appear_later_in_the_run(self):
        state = self.immortal()
        run(state, random.Random(14), 50.0, pick=0)
        kinds = {e["kind"] for e in state["enemies"]}
        self.assertTrue(kinds & {"slime.png", "ghost.png"})
        _, need = rules.minimum_alive(CONFIG, 50.0)
        self.assertGreaterEqual(len(state["enemies"]), need)

    def test_the_boss_comes_once(self):
        state = self.immortal()
        run(state, random.Random(16), 95.0, pick=0)
        self.assertEqual(state["bosses"], BOSS_KINDS)
        run(state, random.Random(17), 20.0, pick=0)
        self.assertEqual(state["bosses"], BOSS_KINDS)  # still exactly one of each

    def test_the_boss_is_never_removed(self):
        state = self.immortal()
        far = CONFIG["spawn"]["cull_distance"] + 100.0
        state["enemies"].append(rules.make_enemy(CONFIG, BOSS_KINDS[0], far, 0.0))
        rules.step(state, random.Random(19))
        bosses = [e for e in state["enemies"] if rules.is_boss(CONFIG, e["kind"])]
        self.assertEqual(len(bosses), 1)
        # it was pulled back to the spawn circle instead of being thrown away
        self.assertLessEqual(rules.distance(bosses[0], state["hero"]), CONFIG["spawn"]["circle_radius"] + 1)

    def test_a_normal_enemy_far_away_is_removed_but_the_boss_stays(self):
        state = self.immortal()
        far = CONFIG["spawn"]["cull_distance"] + 100.0
        state["enemies"] = [rules.make_enemy(CONFIG, "bat.png", far, 0.0),
                            rules.make_enemy(CONFIG, BOSS_KINDS[0], far, 1.0)]
        rules.cull(state, random.Random(21))
        kinds = [e["kind"] for e in state["enemies"]]
        self.assertNotIn("bat.png", kinds)
        self.assertIn(BOSS_KINDS[0], kinds)

    def test_a_dead_boss_drops_no_gem(self):
        state = quiet_state()
        boss = rules.make_enemy(NO_SPAWN, BOSS_KINDS[0], 100.0, 0.0)
        boss["hp"] = 0.0
        state["enemies"].append(boss)
        rules.drop_dead(state)
        self.assertEqual(state["kills"], 1)
        self.assertEqual(state["gems"], [])
        self.assertEqual(state["xp"], 0)

    def test_the_boss_is_not_the_first_thing_you_meet(self):
        self.assertIsNone(rules.boss_for(CONFIG, 0.0))
        state = self.immortal()
        run(state, random.Random(23), 60.0, pick=0)
        self.assertEqual(state["bosses"], [])


# ---------------------------------------------------------------- movement


class TestMovement(unittest.TestCase):
    def test_hero_walks_towards_the_pointer(self):
        state = fresh_state()
        state["target"]["x"] = 100.0
        run(state, random.Random(31), 0.5)
        self.assertAlmostEqual(state["hero"]["x"], CONFIG["hero"]["speed"] * 0.5, places=4)
        self.assertAlmostEqual(state["hero"]["y"], 0.0, places=6)

    def test_hero_stops_at_the_pointer_dead_zone(self):
        state = fresh_state()
        state["target"]["x"] = 100.0
        run(state, random.Random(33), 1.0)
        self.assertLessEqual(abs(state["hero"]["x"] - 100.0), CONFIG["pointer"]["walk_min_distance"])
        before = state["hero"]["x"]
        rules.step(state, random.Random(33))
        self.assertEqual(state["hero"]["x"], before)  # stands still, does not jitter

    def test_enemy_stops_at_the_hero(self):
        state = quiet_state()
        reach = NO_SPAWN["hero"]["hit_radius"] + NO_SPAWN["enemies"]["bat.png"]["hit_radius"]
        state["enemies"].append(rules.make_enemy(NO_SPAWN, "bat.png", 60.0, 0.0))
        run(state, random.Random(35), 0.5)  # shorter than one wand shot
        self.assertAlmostEqual(state["enemies"][0]["x"], reach, places=4)
        run(state, random.Random(35), 0.2)
        self.assertAlmostEqual(state["enemies"][0]["x"], reach, places=4)  # no pushing through


# ---------------------------------------------------------------- damage


class TestDamage(unittest.TestCase):
    def test_touch_hurts_once_per_cooldown(self):
        state = fresh_state()
        damage = CONFIG["enemies"]["bat.png"]["damage"]
        state["enemies"].append(rules.make_enemy(CONFIG, "bat.png", 5.0, 0.0))
        rules.step(state, random.Random(11))
        self.assertAlmostEqual(state["hero"]["hp"], CONFIG["hero"]["hp"] - damage)
        run(state, random.Random(11), CONFIG["contact"]["hit_cooldown"] - 0.05)
        self.assertAlmostEqual(state["hero"]["hp"], CONFIG["hero"]["hp"] - damage)

    def test_spark_kills_a_bat(self):
        state = quiet_state()
        state["enemies"].append(rules.make_enemy(NO_SPAWN, "bat.png", 60.0, 0.0))
        run(state, random.Random(13), 3.0)
        self.assertEqual(state["kills"], 1)
        self.assertEqual(state["enemies"], [])

    def test_spark_shoots_at_the_nearest(self):
        data = still_config()
        state = rules.new_state(data)
        state["enemies"] = [
            rules.make_enemy(data, "bat.png", 250.0, 300.0),
            rules.make_enemy(data, "bat.png", 250.0, 0.0),
        ]
        interval = data["weapons"]["spark"]["base"]["interval"]
        run(state, random.Random(17), interval + 0.02)
        self.assertEqual(len(state["shots"]), 1)
        shot = state["shots"][0]
        self.assertGreater(shot["vx"], 0)  # flies at the nearer bat, on the x axis
        self.assertAlmostEqual(shot["vy"], 0.0, places=6)
        self.assertAlmostEqual(math.hypot(shot["vx"], shot["vy"]), data["weapons"]["spark"]["base"]["speed"])
        self.assertAlmostEqual(shot["damage"], data["weapons"]["spark"]["base"]["damage"])

    def test_wand_level_one_matches_the_data(self):
        base = CONFIG["weapons"]["spark"]["base"]
        stats = rules.weapon_stats(CONFIG, "spark", 1)
        self.assertAlmostEqual(stats["interval"], base["interval"])
        self.assertEqual(stats["damage"], base["damage"])
        self.assertEqual(stats["count"], base["count"])

    def test_one_shot_per_interval(self):
        data = still_config(hp=100000)
        state = rules.new_state(data)
        state["enemies"].append(rules.make_enemy(data, "bat.png", 250.0, 0.0))
        interval = data["weapons"]["spark"]["base"]["interval"]
        run(state, random.Random(23), interval * 3.5)
        self.assertEqual(state["shots_fired"], 3)  # 3.5 intervals -> three shots
        self.assertLessEqual(len(state["shots"]), 1)


# ---------------------------------------------------------------- weapons


class TestWeaponLevels(unittest.TestCase):
    def test_spark_damage_and_sparks_per_level(self):
        per = CONFIG["weapons"]["spark"]["per_level"]
        base = CONFIG["weapons"]["spark"]["base"]
        for level in range(1, 6):
            stats = rules.weapon_stats(CONFIG, "spark", level)
            self.assertAlmostEqual(stats["damage"], base["damage"] + per["damage"] * (level - 1))
            self.assertAlmostEqual(stats["interval"], base["interval"] + per["interval"] * (level - 1))
        self.assertEqual(rules.weapon_stats(CONFIG, "spark", 3)["count"], 2)
        self.assertEqual(rules.weapon_stats(CONFIG, "spark", 5)["count"], 3)

    def test_spark_level_three_fires_two_sparks(self):
        data = still_config()
        state = rules.new_state(data)
        state["weapons"]["spark"] = 3
        state["weapon_timers"]["spark"] = 0.0
        state["enemies"].append(rules.make_enemy(data, "bat.png", 250.0, 0.0))
        rules.step(state, random.Random(41))
        self.assertEqual(len(state["shots"]), 2)
        self.assertNotAlmostEqual(state["shots"][0]["vy"], state["shots"][1]["vy"], places=3)

    def test_blades_levels_add_blades(self):
        base = CONFIG["weapons"]["blades"]["base"]
        self.assertEqual(rules.weapon_stats(CONFIG, "blades", 1)["count"], base["count"])
        self.assertEqual(rules.weapon_stats(CONFIG, "blades", 2)["count"], base["count"] + 1)
        self.assertEqual(rules.weapon_stats(CONFIG, "blades", 4)["count"], base["count"] + 2)
        self.assertEqual(rules.weapon_stats(CONFIG, "blades", 5)["damage"],
                         base["damage"] + CONFIG["weapons"]["blades"]["per_level"]["damage"] * 4)

    def test_blades_hit_once_per_turn_and_not_again_soon(self):
        data = still_config()
        state = rules.new_state(data)
        state["weapons"] = {"blades": 1}  # no wand, so only the blades can hurt
        orbit = data["weapons"]["blades"]["base"]["orbit"]
        state["enemies"].append(rules.make_enemy(data, "bat.png", float(orbit), 0.0))
        stats = rules.weapon_stats(data, "blades", 1)
        # a little under one full turn, so each blade passes the enemy exactly once
        run(state, random.Random(43), stats["turn_seconds"] * 0.9)
        lost = data["enemies"]["bat.png"]["hp"] - state["enemies"][0]["hp"]
        self.assertEqual(lost, stats["damage"] * stats["count"])

    def test_ring_hurts_everything_inside_once_per_interval(self):
        data = still_config()
        state = rules.new_state(data)
        state["weapons"] = {"ring": 1}
        stats = rules.weapon_stats(data, "ring", 1)
        inside = rules.make_enemy(data, "bat.png", 30.0, 0.0)
        outside = rules.make_enemy(data, "bat.png", float(stats["radius"]) + 40.0, 0.0)
        state["enemies"] = [inside, outside]
        # the ring fires at once, then every 0.5 s: pulses near 0.0, 0.5 and 1.0 seconds
        run(state, random.Random(45), stats["interval"] * 2.0 + 0.1)
        hp = data["enemies"]["bat.png"]["hp"]
        self.assertEqual(hp - inside["hp"], stats["damage"] * 3)
        self.assertEqual(hp - outside["hp"], 0)

    def test_ring_grows_with_levels(self):
        base = CONFIG["weapons"]["ring"]["base"]
        per = CONFIG["weapons"]["ring"]["per_level"]
        stats = rules.weapon_stats(CONFIG, "ring", 3)
        self.assertEqual(stats["radius"], base["radius"] + per["radius"] * 2)
        self.assertEqual(stats["damage"], base["damage"] + per["damage"] * 2)


# ---------------------------------------------------------------- passives


class TestPassiveItems(unittest.TestCase):
    def test_boots_add_speed(self):
        state = fresh_state()
        base = CONFIG["hero"]["speed"]
        percent = CONFIG["items"]["boots"]["per_level"]["speed_pct"]
        state["items"]["boots"] = 3
        self.assertAlmostEqual(rules.hero_speed(state), base * (1 + 3 * percent / 100.0))

    def test_heart_adds_max_hp_and_heals(self):
        state = fresh_state()
        state["hero"]["hp"] = 50.0
        per = CONFIG["items"]["heart"]["per_level"]
        state["level_up"] = {"cards": [rules.card_for(CONFIG, "item", "heart", 1)]}
        rules.apply_card(state, 0, random.Random(47))
        self.assertEqual(state["hero"]["max_hp"], CONFIG["hero"]["hp"] + per["max_hp"])
        self.assertEqual(state["hero"]["hp"], 50.0 + per["heal"])

    def test_magnet_widens_the_pull(self):
        state = fresh_state()
        base = CONFIG["hero"]["magnet_radius"]
        extra = CONFIG["items"]["magnet"]["per_level"]["radius"]
        state["items"]["magnet"] = 2
        self.assertEqual(rules.magnet_radius(state), base + 2 * extra)


# ---------------------------------------------------------------- gems, xp, cards


class TestGemsAndXp(unittest.TestCase):
    def test_dead_enemy_drops_a_gem_worth_its_xp(self):
        state = quiet_state()
        state["enemies"].append(rules.make_enemy(NO_SPAWN, "bat.png", 100.0, 0.0))
        state["enemies"][0]["hp"] = 0.0
        rules.drop_dead(state)
        self.assertEqual(state["kills"], 1)
        self.assertEqual(state["enemies"], [])
        self.assertEqual(len(state["gems"]), 1)
        self.assertEqual(state["gems"][0]["xp"], NO_SPAWN["enemies"]["bat.png"]["xp"])

    def test_a_killed_bat_ends_up_as_xp_on_the_hero(self):
        state = quiet_state()
        state["enemies"].append(rules.make_enemy(NO_SPAWN, "bat.png", 60.0, 0.0))
        run(state, random.Random(52), 3.0)
        self.assertEqual(state["xp"], NO_SPAWN["enemies"]["bat.png"]["xp"])
        self.assertEqual(state["gems"], [])

    def test_gem_inside_the_magnet_radius_flys_to_the_hero(self):
        data = copy.deepcopy(NO_SPAWN)
        data["spawn"]["table"] = []
        state = rules.new_state(data)
        state["weapons"] = {}  # no wand: the gem is the only thing under test
        state["gems"].append({"x": 40.0, "y": 0.0, "xp": 1})
        run(state, random.Random(53), 1.0)
        self.assertEqual(state["gems"], [])
        self.assertEqual(state["xp"], 1)

    def test_gem_outside_the_magnet_radius_stays(self):
        data = copy.deepcopy(NO_SPAWN)
        state = rules.new_state(data)
        state["weapons"] = {}
        far = rules.magnet_radius(state) + 50.0
        state["gems"].append({"x": far, "y": 0.0, "xp": 2})
        run(state, random.Random(55), 1.0)
        self.assertEqual(len(state["gems"]), 1)
        self.assertAlmostEqual(state["gems"][0]["x"], far)
        self.assertEqual(state["xp"], 0)

    def test_xp_needed_grows_by_three(self):
        xp = CONFIG["xp"]
        for level in range(1, 6):
            self.assertEqual(rules.xp_needed(CONFIG, level), xp["first"] + xp["step"] * (level - 1))

    def test_full_bar_is_a_level_and_the_game_waits(self):
        state = quiet_state()
        state["xp"] = xp = rules.xp_needed(CONFIG, 1)
        rules.step(state, random.Random(57))
        self.assertEqual(state["level"], 2)
        self.assertEqual(state["xp"], 0)
        self.assertEqual(len(state["level_up"]["cards"]), CONFIG["cards"]["count"])
        # while the cards are up, nothing moves
        frozen = state["elapsed"]
        run(state, random.Random(57), 1.0)
        self.assertEqual(state["elapsed"], frozen)

    def test_two_levels_show_their_cards_one_after_the_other(self):
        state = quiet_state()
        state["xp"] = rules.xp_needed(CONFIG, 1) + rules.xp_needed(CONFIG, 2)
        rules.step(state, random.Random(59))
        self.assertEqual(state["level"], 3)
        self.assertEqual(state["pending_level_ups"], 2)
        rules.apply_card(state, 0, random.Random(59))
        self.assertEqual(state["pending_level_ups"], 1)
        self.assertIsNotNone(state["level_up"])
        rules.apply_card(state, 0, random.Random(59))
        self.assertIsNone(state["level_up"])
        run(state, random.Random(59), 0.5)
        self.assertGreater(state["elapsed"], 0.0)  # the game moves again


class TestCards(unittest.TestCase):
    def test_offers_are_three_and_never_repeat(self):
        state = fresh_state()
        cards = rules.make_offers(state, random.Random(61))
        self.assertEqual(len(cards), CONFIG["cards"]["count"])
        keys = [(c["kind"], c["key"]) for c in cards]
        self.assertEqual(len(keys), len(set(keys)))

    def test_a_new_weapon_offers_level_one_with_the_description(self):
        state = fresh_state()
        cards = [c for c in rules.make_offers(state, random.Random(63)) if c["kind"] == "weapon"]
        for card in cards:
            if card["key"] not in state["weapons"]:
                self.assertEqual(card["level"], 1)
                self.assertEqual(card["text"], CONFIG["weapons"][card["key"]]["description"])

    def test_upgrade_card_names_the_new_level(self):
        state = fresh_state()
        state["weapons"]["spark"] = 2
        cards = [c for c in rules.make_offers(state, random.Random(65))
                 if c["kind"] == "weapon" and c["key"] == "spark"]
        self.assertEqual(cards[0]["level"], 3)
        self.assertIn("2 sparks", cards[0]["text"])  # level 3 is the first "+1 spark" step

    def test_nothing_already_at_level_five_is_offered(self):
        max_level = CONFIG["growth"]["max_level"]
        state = fresh_state()
        state["items"]["boots"] = max_level  # nothing better to give for boots
        for card in rules.make_offers(state, random.Random(67)):
            self.assertLessEqual(card["level"], max_level)
            self.assertNotEqual((card["kind"], card["key"]), ("item", "boots"))

    def test_at_most_three_weapons(self):
        state = fresh_state()
        state["weapons"] = {"spark": 1, "blades": 1, "ring": 1}
        for card in rules.make_offers(state, random.Random(69)):
            if card["kind"] == "weapon":
                self.assertIn(card["key"], state["weapons"])
                self.assertGreater(card["level"], 1)  # only upgrades, never a fourth weapon

    def test_heal_when_nothing_is_left(self):
        state = fresh_state()
        state["weapons"] = {key: CONFIG["growth"]["max_level"] for key in CONFIG["weapons"]}
        state["items"] = {key: CONFIG["growth"]["max_level"] for key in CONFIG["items"]}
        cards = rules.make_offers(state, random.Random(71))
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["kind"], "heal")
        before = state["hero"]["hp"]
        state["hero"]["hp"] = before - 40
        state["level_up"] = {"cards": cards}
        rules.apply_card(state, 0, random.Random(71))
        self.assertEqual(state["hero"]["hp"], before - 40 + CONFIG["heal_card"]["amount"])


# ---------------------------------------------------------------- win and lose


class TestWinAndLose(unittest.TestCase):
    def test_hero_dies(self):
        state = fresh_state()
        reach = CONFIG["hero"]["hit_radius"] + CONFIG["enemies"]["bat.png"]["hit_radius"] - 1
        state["enemies"].append(rules.make_enemy(CONFIG, "bat.png", reach, 0.0))
        damage = CONFIG["enemies"]["bat.png"]["damage"]
        for _ in range(int(CONFIG["hero"]["hp"] // damage) + 1):
            state["enemies"][0]["hit_cooldown"] = 0.0
            state["enemies"][0]["x"] = reach
            rules.step(state, random.Random(19))
        self.assertEqual(state["status"], "game_over")
        self.assertEqual(state["hero"]["hp"], 0.0)

    def test_a_stopped_game_does_not_tick(self):
        state = fresh_state()
        state["status"] = "game_over"
        before = state["elapsed"]
        run(state, random.Random(21), 1.0)
        self.assertEqual(state["elapsed"], before)

    def test_surviving_to_the_win_time_is_a_victory(self):
        data = copy.deepcopy(NO_SPAWN)
        data["hero"]["hp"] = 1_000_000  # nothing to fight: only the clock matters
        state = rules.new_state(data)
        run(state, random.Random(25), CONFIG["game"]["win_time"] + 2.0)
        self.assertEqual(state["status"], "victory")
        self.assertLessEqual(state["elapsed"], CONFIG["game"]["win_time"] + DT)

    def test_the_game_stops_ticking_after_the_victory(self):
        data = copy.deepcopy(NO_SPAWN)
        data["hero"]["hp"] = 1_000_000
        state = rules.new_state(data)
        run(state, random.Random(27), CONFIG["game"]["win_time"] + 1.0)
        before = state["elapsed"]
        run(state, random.Random(29), 3.0)
        self.assertEqual(state["elapsed"], before)
        self.assertEqual(state["status"], "victory")

    def test_dying_first_is_still_a_loss(self):
        data = copy.deepcopy(NO_SPAWN)
        data["game"]["win_time"] = 10.0
        data["enemies"]["bat.png"]["hp"] = 1_000_000  # the wand cannot clear it away
        data["enemies"]["bat.png"]["damage"] = 500    # one touch is enough
        state = rules.new_state(data)
        reach = data["hero"]["hit_radius"] + data["enemies"]["bat.png"]["hit_radius"] - 1
        state["enemies"].append(rules.make_enemy(data, "bat.png", reach, 0.0))
        run(state, random.Random(31), 2.0)
        self.assertEqual(state["status"], "game_over")

    def test_restart_makes_a_fresh_game(self):
        fresh = rules.new_state(CONFIG)
        self.assertEqual(fresh["status"], "running")
        self.assertEqual(fresh["enemies"], [])
        self.assertEqual(fresh["gems"], [])
        self.assertEqual(fresh["level"], 1)
        self.assertEqual(fresh["weapons"], {"spark": 1})


# ---------------------------------------------------------------- events for the screen and the speakers


def kinds(state):
    return [note["kind"] for note in state["events"]]


class TestEvents(unittest.TestCase):
    def test_a_fresh_game_has_no_events(self):
        self.assertEqual(fresh_state()["events"], [])

    def test_a_hit_by_a_spark_is_written_down(self):
        data = still_config()
        state = rules.new_state(data)
        state["enemies"].append(rules.make_enemy(data, "bat.png", 60.0, 0.0))
        run(state, random.Random(71), 1.0)
        hits = [n for n in state["events"] if n["kind"] == "hit"]
        self.assertGreaterEqual(len(hits), 1)
        self.assertEqual(hits[0]["amount"], data["weapons"]["spark"]["base"]["damage"])
        self.assertIn("x", hits[0])  # where the number should float up

    def test_a_blade_and_a_ring_hit_are_written_down(self):
        data = still_config()
        state = rules.new_state(data)
        state["weapons"] = {"blades": 1, "ring": 1}
        state["enemies"].append(rules.make_enemy(data, "bat.png", 40.0, 0.0))
        run(state, random.Random(73), 2.0)
        self.assertGreaterEqual(len([n for n in state["events"] if n["kind"] == "hit"]), 2)

    def test_a_hurt_hero_is_written_down(self):
        data = still_config()
        state = rules.new_state(data)
        reach = data["hero"]["hit_radius"] + data["enemies"]["bat.png"]["hit_radius"] - 1
        state["enemies"].append(rules.make_enemy(data, "bat.png", reach, 0.0))
        rules.step(state, random.Random(75))
        hurts = [n for n in state["events"] if n["kind"] == "hurt"]
        self.assertEqual(len(hurts), 1)
        self.assertEqual(hurts[0]["amount"], data["enemies"]["bat.png"]["damage"])

    def test_a_collected_gem_is_written_down(self):
        state = quiet_state()
        state["enemies"].append(rules.make_enemy(NO_SPAWN, "bat.png", 40.0, 0.0))
        run(state, random.Random(77), 3.0)
        gems = [n for n in state["events"] if n["kind"] == "gem"]
        self.assertEqual(len(gems), 1)
        self.assertEqual(gems[0]["amount"], NO_SPAWN["enemies"]["bat.png"]["xp"])

    def test_a_dead_enemy_is_written_down_and_the_boss_is_marked(self):
        state = quiet_state()
        state["enemies"].append(rules.make_enemy(NO_SPAWN, "bat.png", 40.0, 0.0))
        state["enemies"].append(rules.make_enemy(NO_SPAWN, BOSS_KINDS[0], 90.0, 0.0))
        for e in state["enemies"]:
            e["hp"] = 0.0
        rules.drop_dead(state)
        deaths = [n for n in state["events"] if n["kind"] == "die"]
        self.assertEqual(len(deaths), 2)
        self.assertEqual(sorted(n["boss"] for n in deaths), [False, True])

    def test_a_level_up_is_written_down_once(self):
        state = quiet_state()
        state["xp"] = rules.xp_needed(CONFIG, 1)
        rules.step(state, random.Random(79))
        self.assertEqual(kinds(state).count("level_up"), 1)
        rules.apply_card(state, 0, random.Random(81))
        rules.step(state, random.Random(83))
        self.assertEqual(kinds(state).count("level_up"), 1)  # no second note for the same level

    def test_the_end_is_written_down(self):
        data = copy.deepcopy(NO_SPAWN)
        data["hero"]["hp"] = 1_000_000
        state = rules.new_state(data)
        run(state, random.Random(85), CONFIG["game"]["win_time"] + 1.0)
        self.assertEqual([n["status"] for n in state["events"] if n["kind"] == "end"], ["victory"])

    def test_the_reader_can_empty_the_list(self):
        state = quiet_state()
        state["enemies"].append(rules.make_enemy(NO_SPAWN, "bat.png", 40.0, 0.0))
        run(state, random.Random(87), 1.0)
        self.assertGreater(len(state["events"]), 0)
        del state["events"][:]
        self.assertEqual(state["events"], [])
        # the first bat is gone, so give the wand a new one
        state["enemies"].append(rules.make_enemy(NO_SPAWN, "bat.png", 40.0, 0.0))
        run(state, random.Random(89), 1.0)
        self.assertGreater(len(state["events"]), 0)  # the next frame writes new notes


if __name__ == "__main__":
    unittest.main()
