--- START OF FILE ---

# Season 16 Champion and Objective Bounties

Last updated: September 2026
Applies to: Standard Summoner's Rift
Primary sources:
- Riot Games Patch 14.21
- Riot Games Patch 14.22
- Riot Games Patch 14.21 Objective Bounty update
- Riot Games Patch 25.09
- Riot Games Patch 25.14
- Riot Games Patch 26.3

# Quick Reference

- Champion bounties and objective bounties are comeback systems, but they should be treated as additional rewards rather than reasons to take losing plays.
- A champion's K/D/A does NOT directly determine whether that champion has a bounty.
- Do not infer bounty status simply from kills, deaths, or scoreboard appearance.
- Champion bounty calculations depend on the underlying advantage/comeback system described in the detailed mechanics below.
- Objective bounties can apply to structures and major objectives when the game determines that one team is sufficiently behind.
- During an objective-bounty window, ordinary cross-map trades can become significantly more valuable because the losing team receives additional comeback gold.
- A behind team can sometimes intentionally concede an unbountied structure or low-priority resource while taking a bountied structure/objective elsewhere.
- Only make that trade if the sacrificed structure does not expose the Nexus, create an unrecoverable inhibitor/base state, or allow the enemy to convert immediately into a game-ending push.
- When several bountied targets are available, prioritize targets that can be taken safely and chained into additional resources rather than simply choosing the largest displayed reward.
- A winning team should account for active bounties when making trades; an apparently equal turret-for-turret exchange may financially favor the losing team.
- Protect large champion shutdowns when the enemy has realistic access to them; unnecessary deaths can accelerate a comeback.
- For exact activation/deactivation timers, bounty calculations, values, and structure/objective rules, use the detailed sections below.

# Purpose

Bounties are comeback mechanics.

There are two separate systems:

1. Champion Bounties
2. Objective Bounties

They behave differently.

Champion Bounties reward killing an individually valuable enemy champion.

Objective Bounties reward the team that is sufficiently behind for taking marked map objectives.

Do NOT treat either system as being based directly on K/D/A.

---

# CHAMPION BOUNTIES

# Most Important Rule

Champion bounties are based primarily on GOLD.

They are NOT directly based on:

- kill streak
- death streak
- K/D ratio
- K/D/A
- CS compared directly against the opposing laner

A champion can be:

0 / 0 / 0

and still develop a bounty if they have earned enough gold through farming.

A champion with many kills may also have their visible bounty suppressed if their overall team is not sufficiently ahead.

Therefore never say:

"They have a bounty because they are 5/0."

Instead say:

"Their bounty reflects the gold they have accumulated, with team-state adjustments."

Kills matter because kills generate gold.

The K/D/A itself is not the bounty formula.

---

# Base Champion Kill Gold

Champion base kill gold scales with champion level.

Levels 1-6:

300 gold

Level 7:

310 gold

Level 8:

320 gold

Level 9:

330 gold

Level 10:

340 gold

Level 11:

350 gold

Level 12:

360 gold

Level 13:

370 gold

Level 14:

380 gold

Level 15:

390 gold

Level 16:

400 gold

Level 17:

410 gold

Level 18:

420 gold

Therefore even before additional shutdown gold, killing a high-level champion is worth more than killing a low-level champion.

---

# Positive Bounty Accrual

A champion's positive bounty accumulates continuously rather than in old-style bounty tiers.

## Gold From Kills and Assists

While the champion is in a neutral or positive bounty state:

Approximately:

1 bounty gold
per
3 gold earned from kills and assists

Example:

Earn 300 gold from champion combat.

Approximate bounty accrual:

100 bounty gold

This does NOT mean the champion immediately displays a +100 bounty, because the positive bounty system includes a buffer before additional shutdown gold is paid.

---

# Gold From Farming

Current rate after Patch 25.14:

1 bounty gold
per
20 gold earned from Gold Value sources

Gold Value sources include primarily:

- minions
- jungle monsters
- Support item generation

Example:

Earn 1000 qualifying gold from farming.

Approximate positive bounty accrual:

1000 / 20
=
50 bounty gold

Therefore strong farming alone can eventually create a shutdown.

This is why:

0/0/0 with excellent farm

can be worth more than:

2/2/2 with poor farm.

---

# Special Gold That Does NOT Count

Champion-specific / special gold generation is excluded from bounty calculations.

Examples historically called out by Riot include:

- Draven Adoration bonus gold
- Twisted Fate Loaded Dice
- similar special gold-generation effects

Do not assume every extra gold mechanic increases a champion bounty.

---

# Shutdown Gold Buffer

The first portion of positive bounty accrual is buffered.

A champion begins displaying shutdown value once their total kill value becomes meaningfully higher than base value.

At normal 300 base kill gold, a displayed shutdown begins around:

400 total kill gold

This corresponds to roughly:

+100 visible extra value

after the bounty-system buffer rules.

The scoreboard rounds displayed bounty values for readability.

Always prefer the CURRENT SCOREBOARD VALUE over trying to manually reconstruct the exact bounty during a live game.

---

# Maximum Gold From One Shutdown

A single champion kill cannot pay more than:

base kill bounty
+
700 additional bounty gold

Example at level 18:

base:
420

maximum additional:
700

maximum killer payout from one death:

1120 gold

However, champions can accumulate an EXTENDED BOUNTY beyond the amount payable in one death.

Excess bounty can carry into the champion's next life.

Therefore an extremely wealthy champion may need to be shut down more than once before returning to normal value.

---

# Assist Gold

Assists generate additional gold separate from the killer's bounty.

Total assist bounty is generally based on a fraction of the slain champion's kill bounty and is divided among assisting champions.

Therefore a shutdown can create more total team gold than simply the number displayed above the enemy champion.

When evaluating a shutdown play:

consider both:

- gold received by killer
- gold distributed to assistants

---

# Champion Bounty Updates During Combat

On Summoner's Rift, bounty changes are not intended to constantly flicker during champion combat.

Current bounty recalculation waits until approximately:

5 seconds after leaving combat with enemy champions.

This prevents awkward cases where:

Champion A gets a kill
→ immediately gains a larger bounty
→ dies one second later in the same fight

and disproportionately rewards the opponent.

---

# Team-Based Bounty Suppression

This is extremely important.

A player's raw individual bounty can exist internally while some or all of that shutdown gold is SUPPRESSED because of their team's overall game state.

Starting at:

6:00

team-state bounty suppression can apply.

The system looks at team advantage including:

- team gold
- team experience
- turrets
- epic objectives

Gold is currently weighted most heavily.

Suppression levels can reduce positive shutdown gold by approximately:

30%
60%
90%
100%

depending on team advantage.

The exact internal thresholds are not publicly exposed.

---

# Meaning of Suppression

A champion may personally be extremely strong but have little or no visible shutdown because their TEAM is not convincingly winning.

Example:

Blue ADC:
very farmed

Blue team:
5000 gold behind

The ADC may have accumulated raw positive bounty value.

However:

much or all of it can be suppressed.

If Blue later takes control of the game:

the bounty can reappear dynamically.

---

# Objective Bounties and Champion Bounty Suppression

When Objective Bounties are active for the losing team:

positive shutdown gold on members of that losing team is fully suppressed.

This prevents the comeback team from being punished for beginning to recover.

Example:

Blue team is significantly behind.

Objective Bounties activate for Blue.

Blue ADC begins farming well.

Blue ADC should not immediately become a huge shutdown target while Blue is still the comeback team.

---

# Negative Champion Bounties

A champion who repeatedly gives away gold can eventually become worth LESS than normal base kill gold.

This is also based on gold value rather than a traditional "death streak tier."

Patch 26.1 accelerated this system.

Patch 26.3 partially reverted the acceleration because kills against heavily losing champions had become too low-value.

Current Patch 26.3 tuning includes:

Death devaluation rate:

1 bounty-value reduction
per
3.5 gold given out

Farming recovery rate:

1 bounty-value increase
per
7 gold earned

for the relevant negative-bounty recovery state.

---

# Macro Implication of Negative Bounties

Repeatedly killing the same far-behind player becomes less valuable.

Example:

Enemy Top:
severely behind
worth very little kill gold

Enemy ADC:
high farm
large shutdown

A team may gain substantially more comeback value by:

- setting vision around the ADC
- forcing the ADC into a dangerous rotation
- collapsing on the ADC

rather than repeatedly diving the already-losing Top laner.

---

# Champion Bounty Target Selection

When behind, prioritize shutdowns based on:

1. bounty size
2. probability of securing the kill
3. who receives the shutdown
4. resources required to make the play
5. objective consequences
6. risk of dying afterward

Do NOT chase a 700g shutdown through three enemy turrets if the play is low probability.

Expected value matters.

---

# Example — Shutdown Opportunity

Enemy ADC bounty:

+700

Normal level-18 base gold:

420

Potential killer payout:

1120

If this ADC is isolated and can be killed with a 4v1 collapse:

very high-value comeback play.

But if taking the shutdown requires:

- losing Baron
- losing Dragon Soul
- three teammates dying

then the shutdown may not be worth pursuing.

---

# Protecting Your Own Bounty

When ahead with a large personal bounty:

avoid giving it away for low-value gains.

Bad trade:

You have +700 shutdown.

You dive enemy Support for 300g.

You kill Support.

You die.

Potentially:

gain ~300g

give enemy carry ~1000+ gold

This can dramatically shift the game.

Large-bounty players should value survival more highly.

---

# OBJECTIVE BOUNTIES

Objective Bounties are TEAM-WIDE comeback rewards.

They activate when one team is sufficiently behind according to the game's team-state model.

The calculation considers:

- team gold
- team XP
- turret difference
- Dragon / epic-objective difference
- Void Grubs and other relevant objective state

Gold difference currently receives the greatest weighting.

The precise activation formula and thresholds are intentionally not publicly exposed.

Therefore do NOT attempt to calculate:

"Objective bounties activate at exactly X gold deficit."

That is not a reliable rule.

Use the in-game bounty indicators as the source of truth.

---

# When Objective Bounties Can Appear

Standard Summoner's Rift objective bounties become relevant in the midgame rather than immediately from game start.

Current reference rules place the system after approximately:

14:00

Once the losing team crosses the required deficit threshold, there is an activation delay before objectives become bountied.

Current reference behavior uses approximately:

60 seconds

before the bounty objectives are placed after falling sufficiently behind.

Because the game's internal deficit calculation changes continuously, do not make macro decisions by manually predicting the exact activation second.

Watch:

- scoreboard
- minimap
- objective bounty icons

---

# Objectives That Can Receive Bounties

Eligible objectives include:

- Outer Turrets
- Inner Turrets
- Inhibitor / Base Turrets
- Elemental Dragons
- Rift Herald
- Baron Nashor
- Elder Dragon

The available bounties are shown:

- on the minimap
- in the scoreboard / tab menu

---

# Base Objective Bounty Values

Historical/current baseline categories include:

## Outer Turret

Base objective bounty:

250 team gold

## Inner Turret

Base objective bounty:

400 team gold

## Base / Inhibitor Turret

Base objective bounty:

400 team gold

## Dragon

Base objective bounty:

500 team gold

## Rift Herald

Base objective bounty:

500 team gold

## Baron Nashor

Current base objective bounty after Patch 14.21:

300 team gold

## Elder Dragon

Base objective bounty:

500 team gold

These are EXTRA bounty rewards.

They are added on top of the normal objective rewards.

---

# Objective Bounty Scaling — Current System

Patch 25.09 significantly changed how larger objective bounty payouts are calculated.

Old system:

base bounty
+
up to 60% bonus

was removed.

Current system:

objective bounty can include up to approximately:

10% of the calculated team gold difference

on top of the base bounty payment.

Maximum total objective bounty:

1000 gold

Lower-value objectives such as Outer Turrets receive proportionally lower scaling.

Therefore the losing team can sometimes receive very large payouts for major objectives.

---

# Example — Large Team Deficit

Suppose Blue is approximately:

7000 gold behind

and receives a major bountied objective.

10% of gold difference:

700 gold

The exact payout is NOT simply:

base + 700

because Riot scales different objective types differently and caps the result.

The scoreboard provides the actual current payout.

Use displayed bounty numbers rather than manually predicting them.

---

# Objective Bounty Distribution

Objective bounty gold is TEAM GOLD.

When a bountied objective is taken:

the bounty reward is distributed across the losing team.

Example:

400 total turret bounty

approximately:

80 additional gold per player

for five teammates.

This is separate from:

- local turret plate gold
- normal global turret gold
- waves
- objective kill gold

This distinction is crucial when comparing cross-map trades.

---

# Example — Bountied Tier 2 Turret

Assume Tier 2 has:

3 plates remaining

Each plate:

120 local gold

Three plates:

360 local gold

Full bounty displayed:

400 team gold

Destroying the turret may therefore produce:

360 local plate gold
+
normal turret global gold
+
400 bounty team gold
+
wave gold
+
map-control value

This can be a very large comeback conversion.

---

# Ending Soon / Linger Timer

Objective Bounties do not always disappear instantly when the losing team improves its position.

Patch 14.21 set the "Objective Bounties Ending Soon" timer to:

30 seconds

During this period:

the comeback team has a brief window to finish another objective.

However, bounty behavior during the linger window is restrictive.

If the comeback team claims an objective bounty while the system is already in its ending / linger state:

the remaining active bounties can immediately disappear.

Therefore:

do NOT assume you can chain every marked turret during the final 30-second window.

---

# How Long Do Objective Bounties Last?

There is no fixed total lifetime such as:

"bounties last 5 minutes."

They remain active while the game continues to consider that team sufficiently behind.

Therefore they can last:

- a short period
- several minutes
- disappear and later reactivate

depending on the game state.

The important fixed timing is the deactivation warning:

approximately 30 seconds

once the system decides the comeback team has recovered sufficiently.

---

# Bounty Reactivation

If the losing team recovers:

bounties can disappear.

If that team later falls sufficiently far behind again:

Objective Bounties can reactivate.

Therefore the system is dynamic.

---

# MAXIMIZING AN OBJECTIVE-BOUNTY WINDOW

This is one of the most important comeback macro concepts.

When Objective Bounties activate, do NOT automatically group as five and fight the winning team.

Instead ask:

"Which marked objective can we take with the lowest risk?"

Often the best answer is:

a cross-map turret.

---

# Why Turret Bounties Can Be Excellent

A bountied turret provides:

1. objective bounty team gold
2. plate gold
3. normal turret gold
4. wave gold
5. map pressure
6. potentially safer access than Baron/Dragon

Therefore a bountied turret can sometimes be the safest and most efficient comeback objective.

---

# Trading Your Turret for Their Bountied Turret

This can be a very strong comeback technique.

Example:

Your team is behind.

Objective Bounties are active.

Enemy sends four players Bot to take your non-critical outer or inner turret.

Your Top side-laner can take an enemy bountied Tier 2 turret.

Instead of defending a turret that may already be impossible to save:

allow enemy to take yours

while taking:

enemy bountied turret
+
plates
+
wave
+
possibly jungle camps

This can produce a favorable gold trade.

---

# Example — Cross-Map Turret Trade

Enemy takes your Tier 1 turret.

Your split pusher takes enemy bountied Tier 2.

Possible value:

Enemy:

outer turret reward

Your team:

up to 600 local Tier 2 plate gold
+
normal turret global gold
+
400+ objective bounty
+
wave gold

This can be an excellent comeback trade.

---

# Why Sacrificing Your Own Turret Can Preserve Bounty Value

Objective Bounties depend partly on:

- turret difference
- overall team gold
- overall team advantage

If the comeback team takes several enemy structures while losing nothing:

their deficit shrinks rapidly.

The bounty system may begin its 30-second ending timer.

Sometimes allowing the opponent to take a LOW-STRATEGIC-VALUE structure while taking a MORE VALUABLE bountied structure can:

- keep the gold difference from closing too abruptly
- maintain the game-state deficit
- potentially preserve the bounty window longer
- improve your actual position anyway

This is a STRATEGIC INFERENCE, not a guaranteed way to manipulate the hidden bounty formula.

Never promise:

"Giving this turret guarantees bounties stay active."

The exact internal bounty thresholds are hidden.

---

# Good Structures to Sacrifice

Potentially acceptable:

## Already-damaged Outer Turret

Especially after laning phase.

If:

- turret is nearly dead
- defending requires several players
- enemy is committing multiple people
- you can take a bountied Tier 2 elsewhere

cross-map trade is often preferable.

## Low-value Side Tier 2

Potentially tradeable if:

- no inhibitor is threatened
- major objective is on opposite side
- the enemy push cannot continue deeply
- your team gains larger bounty value elsewhere

---

# Dangerous Structures to Sacrifice

## Inhibitor Turret

High strategic value.

Losing it opens:

- inhibitor
- super minions
- base pressure

Do not casually sacrifice it for one bountied outer turret.

## Inhibitor

Extremely dangerous to lose.

Super minions can remove your ability to contest later objectives.

## Nexus Turrets

Do NOT intentionally trade these for bounty gold unless your alternative play immediately ends the game.

The game can end before the bounty gold matters.

---

# "Without Losing the Game" Rule

Before sacrificing a turret, ask:

1. Can the enemy continue to the next structure?
2. What are enemy death timers?
3. How many enemies are showing?
4. Is your wave clearing safely?
5. Will losing this turret expose inhibitor?
6. Does the enemy have Baron?
7. Can they end before you recall?
8. Do you have Teleport?
9. How quickly can your cross-map player return?

Only sacrifice the structure if the opponent's push has a clear stopping point.

---

# Baron Changes Turret-Trade Rules

If the enemy has Baron:

be MUCH more cautious about sacrificing turrets.

Baron empowers minions and increases siege pressure.

What looks like:

"trade Tier 2 for Tier 2"

can become:

lose Tier 2
→ lose Tier 3
→ lose inhibitor
→ lose Nexus

before your side-laner returns.

Therefore bounty greed is much more dangerous against Baron.

---

# Elder Changes Bounty Rules

If the enemy has Elder:

do not take unnecessary fights merely for a bounty.

Elder's combat power can cause the enemy to:

kill defenders
→ take structures
→ end

Bounty gold does not matter if the Nexus falls.

---

# Soul Changes Bounty Trade Evaluation

Dragon Soul is permanent.

Taking a bountied turret while giving enemy Soul may still be a bad trade.

Example:

Your team gains:

400-800 bounty gold
+
turret value

Enemy gains:

permanent Dragon Soul

The long-term value of Soul can outweigh the immediate comeback gold.

---

# Maximizing Multiple Bounties

When several objectives are bountied:

rank them by:

Expected Comeback Value =
bounty payout
+
normal objective value
+
map value
-
risk
-
time required

Possible priority:

Safe bountied Tier 2
>
50/50 Dragon fight

even if Dragon has a larger displayed bounty.

Safety matters.

---

# Bounty Window Coordination

When bounties activate:

1. Check all marked objectives.
2. Check bounty payout numbers.
3. Push side waves.
4. Identify which objective enemy is defending.
5. Attack opposite-side bounty.
6. Avoid unnecessary deaths.
7. Watch the bounty ending timer.
8. If "Ending Soon" appears, choose the single best remaining conversion.

---

# Example — Three Bountied Turrets

Enemy has:

Top Tier 2
Mid Tier 2
Bot Tier 2

all bountied.

Your team should NOT automatically send one player to each.

Instead identify:

- which lane has wave pressure
- where enemies are visible
- which turret is easiest to take
- which turret opens most map control
- whether another bounty will remain afterward

Often:

take one guaranteed Tier 2

then immediately reassess.

---

# Example — Bounty Timer Starts Ending

"Objective Bounties Ending Soon"

Timer:

30 seconds

Top wave is already at enemy Tier 2.

Dragon is alive but enemy team controls river.

Better play may be:

finish Top Tier 2

rather than:

run across map
→ arrive at Dragon late
→ die

Once one bounty is claimed during the ending window, assume the remaining bounty opportunities may disappear.

---

# Objective Bounty Defense — Winning Team

When ahead and the enemy receives Objective Bounties:

do NOT defend every bounty equally.

Prioritize:

1. inhibitor / base structures
2. Baron
3. Soul / Elder
4. high-value Tier 2 turrets
5. outer turrets

Sometimes allowing the losing team to take one low-value bountied outer turret is preferable to:

over-rotating
→ losing Baron
→ losing a teamfight.

---

# Winning Team Can Use Bounties Against the Loser

Objective Bounty icons reveal what the losing team wants.

If Bot Tier 2 is bountied and a large Bot wave is approaching:

expect the enemy to consider that turret.

This creates opportunities to:

- set an ambush
- rotate early
- force Baron on opposite side
- push another lane

Bounties create predictable incentives.

---

# Shutdown vs Objective Bounty

When behind, compare:

enemy champion shutdown

against

available objective bounty.

Example:

Enemy ADC shutdown:
700

Bountied Tier 2:
400 team bounty
+
600 possible plates
+
normal turret value

If ADC is safely protected:

turret may be the better comeback play.

If ADC is isolated:

shutdown may be faster and safer.

---

# Bounty Interaction With Tempo

Bounty value does NOT automatically mean immediate action.

Before chasing a bounty:

push the wave.

Otherwise:

take bounty
→ lose 2 waves
→ lose own turret

and the comeback gain may be much smaller than it appears.

---

# Bounty Interaction With Deaths

When behind:

dying while trying to collect a bounty can be especially damaging.

Example:

Bountied turret:
400 team gold

Two teammates die trying to take it.

Enemy receives:

600+ kill gold
+
assists

Your comeback may be negative despite successfully taking the turret.

---

# Bounty Expected-Value Example

Bountied Tier 2:

400 team bounty

Two plates available:

240 local gold

Potential immediate gain:

640+
before normal turret/global/wave gold

If the turret can be taken with:

90% success chance
and
minimal death risk

very strong comeback play.

If it requires:

3v5 dive
with
30% success chance

bad play despite the bounty.

---

# Champion Shutdown Expected-Value Example

Enemy Mid:

+500 shutdown

Potential kill payout:

base gold
+
500

If killing them also enables:

Baron

the real shutdown value is much larger.

Therefore sometimes the best bounty target is valuable not because of the gold itself, but because their death unlocks another objective.

---

# Do NOT Overemphasize K/D/A

Incorrect:

"Yone is 6/0, so he must have a bounty."

Correct:

"Yone likely accumulated significant gold, which may have generated a bounty, but the actual bounty depends on gold earned and team-state suppression. Check the scoreboard."

Incorrect:

"Jinx is 0/0, so she cannot have a bounty."

Correct:

"A high-farm Jinx can have a bounty without any kills."

Incorrect:

"This 1/5 champion cannot have a bounty."

Correct:

"If they recovered through farming and gold income, their kill value can recover."

---

# Outdated Information to Avoid

Do NOT use old kill-streak tiers such as:

2 kills = bounty tier
3 kills = larger tier
4 kills = larger tier

That system was removed.

Do NOT say objective bounties scale by:

up to +60%

Current Patch 25.09 system instead uses gold-deficit scaling with up to approximately 10% of the calculated gold difference and a 1000g total cap.

Do NOT use:

60-second "Ending Soon"

Current Patch 14.21 value:

30 seconds.

Do NOT say Baron has a 500g base objective bounty.

Current base after Patch 14.21:

300g.

Do NOT say K/D/A directly determines champion bounty.

It does not.

---

# Final Bounty Macro Rule

When behind:

do not ask only:

"Where is the biggest bounty?"

Ask:

"What is the safest way to convert the bounty window into net gold and map value?"

Evaluate:

bounty gold
+
normal gold
+
plates
+
waves
+
objective reward
+
map pressure
-
death risk
-
structures conceded
-
major objectives conceded
-
possibility of the game ending

A comeback is successful when the bounty creates a better future game state.

The goal is NOT simply to collect as many bounty icons as possible.

--- END OF FILE ---