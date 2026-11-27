"""Count the L1 scenario types of the bounded grammar in ``L1_DESIGN.md`` (proposal). No map code: only the rules of the grammar.

    python paper/p3/count_l1.py [--steps 3] [--rules 2]
"""
import argparse
from itertools import combinations, permutations, product
from math import comb, perm

GOALS = ["reach", "within", "stay", "either", "look", "wait", "cross"]
VISITS = {"reach", "within", "stay", "either"}
RULES = ["keep_distance", "avoid_area", "stay_on_sidewalk", "near_line", "obey_signal", "look_before_road"]
VEHICLE_RULES = {"keep_distance", "look_before_road"}
WINDOWS = {"no crossing, no vehicle road": (False, False, False), "road, no crossing": (False, False, True),
           "unsignalised crossing": (True, False, True), "signalised crossing": (True, True, True)}


def valid(steps, order, rules, vehicle, crossing, signal):
    crosses = steps.count("cross")
    if crosses > (1 if crossing else 0) or steps.count("wait") > (1 if signal else 0) or steps.count("look") > 1:
        return False
    if "wait" in steps and (steps.index("wait") + 1 >= len(steps) or steps[steps.index("wait") + 1] != "cross"):
        return False                                    # waiting for green is directly followed by that crossing
    if "look" in steps and (vehicle == "none" or steps[-1] == "look" and len(steps) > 1):
        return False
    if "stay_on_sidewalk" in rules and crosses:
        return False
    if "obey_signal" in rules and not (crosses and signal):
        return False
    if "look_before_road" in rules and (not crosses or "look" in steps):
        return False
    if VEHICLE_RULES & set(rules) and vehicle == "none":
        return False
    if vehicle != "none" and "look" not in steps and not VEHICLE_RULES & set(rules):
        return False                                    # a vehicle must matter to the task
    return True


def types(window, max_steps, max_rules):
    crossing, signal, road = WINDOWS[window]
    vehicles = ["none"] + (["parked", "moving"] if road else [])
    seen, formulas = set(), set()
    for n in range(1, max_steps + 1):
        for steps in product(GOALS, repeat=n):
            orders = ["one"] if n == 1 else ["sequence"] + (["ordered", "any"] if set(steps) <= VISITS else [])
            for order in orders:
                key_steps = tuple(sorted(steps)) if order == "any" else steps
                for k in range(max_rules + 1):
                    for rules in combinations(RULES, k):
                        for v in vehicles:
                            if valid(list(steps), order, rules, v, crossing, signal):
                                formulas.add((key_steps, order, rules))
                                seen.add((key_steps, order, rules, v))
    return len(formulas), len(seen)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=3)
    ap.add_argument("--rules", type=int, default=2)
    a = ap.parse_args()
    for steps, rules in sorted({(1, 2), (2, 2), (3, 1), (3, 2), (3, 3), (a.steps, a.rules)}):
        for w in WINDOWS:
            f, s = types(w, steps, rules)
            print(f"steps<={steps} rules<={rules} | {w}: specification types {f}, with vehicle setting {s}")
