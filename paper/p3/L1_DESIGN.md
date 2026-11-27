# L1 language: operator design and number of types (proposal, 27 Nov 2026, not implemented)

Point notes, not paper text.

## 1. Basis in prior work
| source | what we take | checked today |
|---|---|---|
| Signal temporal logic (Maler & Nickovic 2004) and its robustness (Donze & Maler 2010), both in `refs.bib` | operators over timed trajectories, signed margins; already our monitor | from knowledge and our code |
| Metric temporal logic (Koymans 1990) | time bounds on operators | from knowledge |
| Specification patterns (Dwyer, Avrunin, Corbett, ICSE 1999): absence, existence, universality, precedence, response | the shapes of rules | search summary |
| Robotic mission patterns (Menghi et al., arXiv 1901.02077): 22 patterns in core movement, avoidance, trigger | visit orders, avoidance, waiting, reactions | tables read from the PDF |
| Lang2LTL (Liu et al., CoRL 2023): formula templates filled with map referents | bounded templates and held-out generalisation | search summary |

## 2. Core operators (all already in the monitor)
| kind | operators |
|---|---|
| predicates | in_zone, on_surface, near_path, dist_le, dist_ge, look_at, signal_is |
| logic | not, and, or, implies |
| temporal | eventually F[a,b], always G[a,b], until U[a,b] |
Not used in generated data: `event` (internal names), `prev` (only inside the signal rule), `then` (shorthand for nested F).

Time is counted from the start of the task.

## 3. Step templates (what has to be achieved)
| id | step | formula | source pattern | request example |
|---|---|---|---|---|
| S1 | reach | F in(p) | visit | "walk to bench_1" |
| S2 | reach in time | F[0,T] in(p) | bounded existence in time (MTL) | "reach bench_1 within 20 s" |
| S3 | stay | F G[0,s] in(p) | existence + universality | "go to bench_1 and stay 5 s" |
| S4 | either | F (in(p) or in(q)) | visit with disjunction | "go to bench_1 or to tree_2" |
| S5 | look | F[0,T] look_at(v) | existence | "look at Car1" |
| S6 | wait for green | F (in(k) and (in(k) U green)) | wait | "wait at crossing_1 for green" |
| S7 | cross | F in(far side) | visit | "cross crossing_1" |

## 4. Rule templates (what must hold meanwhile)
| id | rule | formula | source pattern | request example |
|---|---|---|---|---|
| R1 | keep distance | G dist_ge(v,d) | global avoidance | "stay 1 m away from Car1" |
| R2 | avoid a place | G not in(z) | global avoidance | "do not go near bench_2" |
| R3 | stay on sidewalk | G F[0,1] on(sidewalk) | universality | "stay on the sidewalk" |
| R4 | stay near a line | G F[0,1] near(path,w) | universality | "stay within 2 m of the line from A to B" |
| R6 | obey signal | G (entering crossing -> green) | conditional precedence | "enter only on green" |
| R7 | look before the road | (not on(road)) U look_at(v) | past avoidance, precedence | "do not step on the road before looking at Car1" |

## 5. Order between steps
| order | meaning | source pattern |
|---|---|---|
| sequence | step 2 starts when step 1 is done | sequenced visit |
| ordered | as sequence, and a later place must not be visited earlier | ordered visit |
| any | all steps, order free | visit |

## 6. Bounds that make the count finite
* 1-3 steps; 0-2 rules, each rule template at most once; no free nesting: formulas come only from the templates.
* At most one cross, one wait, one look. Wait is directly followed by cross. `ordered` and `any` only for S1-S4.
* R6 needs a signalised crossing; R7 a cross, a vehicle and no look step; R1 a vehicle; R3 excludes crossing.
* A vehicle in the scene must be used by a step or a rule. Vehicle setting: none, parked or moving.

## 7. Number of types for one map (`count_l1.py`)
Type = steps, order, rules and vehicle setting, ignoring which places and numbers are used.

| window | 1 step | up to 2 steps | up to 3 steps |
|---|---|---|---|
| no crossing, no vehicle road | 28 | 322 | 1,358 |
| road, no crossing | 82 | 800 | 3,724 |
| unsignalised crossing | 100 | 976 | 4,988 |
| signalised crossing | 107 | 1,072 | 5,770 |

(At most 2 rules. With at most 3 steps, signalised window: 1 rule 2,242; 2 rules 5,770; 3 rules 8,822.)

Finite for given bounds; it grows quickly with each bound.
Filling in places multiplies it: with n candidate places a three-step visit has n(n-1)(n-2) ordered choices (720 for n = 10).
The counts are upper bounds: some types cannot be placed in a particular window, or are contradictory for particular numbers (for example a very tight time limit).

## 8. Left out, and why
| pattern | reason |
|---|---|
| walking speed (limits, slowing near a car) | speed predicates removed from the language (decided 27 Nov); R5 and R8 are unused |
| patrolling (repeat forever) | tasks end |
| counting (at most, exactly, at least k visits) | rare in pedestrian tasks, not expressible compactly with these operators |
| fair visit | needs counting |
| follow a walking person | needs walking agents in the sampler (can be added later) |
| free recursive nesting | infinite set, and requests become unreadable |

## 9. Verifier
* Different formulas can mean the same thing, so compare behaviour: run reply and reference on the same set of walks and compare the sign of every task's robustness.
* Walk set per record: the reference walk, plus walks that each break one thing (skip a step, swap the order, leave early, too close, no look, enter on red).
* Accept only if all verdicts agree. Record fields that are not formulas (start, vehicles, signal, time limits) stay field checks.
* Limit: agreement on a finite set of walks does not prove equivalence; the false-accept rate has to be measured (P18).

## 10. Errors found in the current library
| definition | current formula | fault | fix |
|---|---|---|---|
| hold(zone,s) | G[0,s] in | requires being in the zone from the start of the task: a walk there followed by a stay scores -8.5 (checked) | S3 |
| wait_for_green(zone,signal) | in U green | requires being at the kerb from the start of the task | S6 |

All `hold` records produced by the current generator carry the wrong formula, although they passed its checks.

## 11. Decisions needed
1. Bounds: proposed up to 3 steps and 2 rules.
2. Templates S1-S7, R1-R4, R6 and R7: add or remove.
3. Fix the two library definitions (changes the player's behaviour for existing scenarios too).
