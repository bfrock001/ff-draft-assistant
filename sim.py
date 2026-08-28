"""Monte Carlo simulation engine (spec §7, §8, §9).

Vectorized ACROSS simulations: every pick step (opponent or mine) is a single
NumPy op over the (n_sims, N) arrays, so the only Python loop is over remaining
picks x candidates. No pandas/Polars here (§9).

Two independent random axes per sim (they meet only inside one sim):
  performance:  perf ~ N(proj_points, points_sd)  -> future-me picks + lineup score
  opponent:     adp_s = espn_adp + N(0, sigma)     -> opponent picks only
sigma=0 makes opponents pick in exact ESPN ADP order (required sanity mode, §12).
"""
from __future__ import annotations

import numpy as np

from config import N_ROUNDS, N_TEAMS, NO_KDST_BEFORE_ROUND, picks_for_slot
from pool import POSITIONS

QB, RB, WR, TE, K, DST = 0, 1, 2, 3, 4, 5
NEG = -1e18
POS_INF = 1e18


def _fillable(counts):
    """counts (n_sims,6) -> (n_sims,6) bool: positions that can fill a starting
    slot now (§8.1). When all 9 starters are filled, future-me takes best
    available RB/WR/TE (bench)."""
    n = counts.shape[0]
    qb, rb, wr, te, k, dst = (counts[:, i] for i in range(6))
    flex_open = (np.maximum(rb - 2, 0) + np.maximum(wr - 2, 0)
                 + np.maximum(te - 1, 0)) < 1
    f = np.empty((n, 6), dtype=bool)
    f[:, QB] = qb < 1
    f[:, RB] = (rb < 2) | flex_open
    f[:, WR] = (wr < 2) | flex_open
    f[:, TE] = (te < 1) | flex_open
    f[:, K] = k < 1
    f[:, DST] = dst < 1
    full = ~f.any(axis=1)
    if full.any():
        bench = np.zeros(6, dtype=bool)
        bench[[RB, WR, TE]] = True
        f[full] = bench
    return f


def optimal_lineup_points(mine, perf, pos_code):
    """Greedy optimal starting-lineup total per sim (§8.2), vectorized.

    Greedy by position then best remaining RB/WR/TE into FLEX is provably optimal
    for this slot structure. Empty slots contribute 0.
    """
    n = mine.shape[0]
    need = {QB: 1, RB: 3, WR: 3, TE: 2, K: 1, DST: 1}  # one spare where FLEX can draw
    top = {}
    for p, cnt in need.items():
        vals = np.where(mine & (pos_code[None, :] == p), perf, NEG)
        top[p] = -np.sort(-vals, axis=1)[:, :cnt]  # descending top-cnt per sim

    def g(p, j):
        col = top[p][:, j] if j < top[p].shape[1] else np.full(n, NEG)
        return np.where(col > NEG / 2, col, 0.0)

    total = (g(QB, 0) + g(RB, 0) + g(RB, 1) + g(WR, 0) + g(WR, 1) + g(TE, 0)
             + g(DST, 0) + g(K, 0))
    flex = np.maximum(np.maximum(g(RB, 2), g(WR, 2)), g(TE, 1))
    return total + flex


def top_k_available(pool, avail_base, k):
    """Candidate set: best available at each position (diversity — so a TE is
    always evaluated) then filled out by consensus rank."""
    idx = np.where(avail_base)[0]
    chosen = []
    for p in range(6):
        pi = idx[pool.pos_code[idx] == p]
        if pi.size:
            chosen.append(int(pi[np.argmax(pool.proj_points[pi])]))
    for i in idx[np.argsort(pool.consensus_rank[idx])]:
        if len(chosen) >= k:
            break
        if int(i) not in chosen:
            chosen.append(int(i))
    return chosen[:k]


def opponent_draft_order(pool, drafted, sigma, seed, n_picks,
                         n_teams=N_TEAMS, start_pick=1):
    """One-sim opponent-only draft order (debug/sanity mode, §7). With sigma=0
    this is exactly ESPN ADP order, subject to the round-13 K/DST gate."""
    rng = np.random.default_rng(seed)
    N = len(pool)
    taken = np.array([pid in drafted for pid in pool.ids])
    adp_s = (pool.espn_adp.copy() if sigma == 0
             else pool.espn_adp + sigma * rng.standard_normal(N))
    kd = (pool.pos_code == K) | (pool.pos_code == DST)
    order = []
    for t in range(n_picks):
        rnd = (start_pick + t - 1) // n_teams + 1
        ok = ~taken
        if rnd < NO_KDST_BEFORE_ROUND:
            ok = ok & ~kd
        i = int(np.argmin(np.where(ok, adp_s, POS_INF)))
        order.append(i)
        taken[i] = True
    return order


def _simulate(pool, avail_base, my_future, cand_idx, mine_row, counts_row,
              start_pick, n_sims, sigma, rng, n_teams, n_rounds, snapshot_pick):
    N = len(pool)
    pc = pool.pos_code
    perf = pool.proj_points[None, :] + pool.points_sd[None, :] * rng.standard_normal((n_sims, N))
    if sigma > 0:
        adp_s = pool.espn_adp[None, :] + sigma * rng.standard_normal((n_sims, N))
    else:
        adp_s = np.broadcast_to(pool.espn_adp[None, :], (n_sims, N)).copy()

    taken = np.broadcast_to(~avail_base[None, :], (n_sims, N)).copy()
    mine = np.broadcast_to(mine_row[None, :], (n_sims, N)).copy()
    counts = np.broadcast_to(counts_row[None, :], (n_sims, 6)).copy()
    taken[:, cand_idx] = True
    mine[:, cand_idx] = True
    counts[:, pc[cand_idx]] += 1

    kd = (pc == K) | (pc == DST)
    rows = np.arange(n_sims)
    total_picks = n_teams * n_rounds
    snap = None
    for pk in range(start_pick + 1, total_picks + 1):
        if pk == snapshot_pick:  # availability the moment I'm next on the clock
            av = ~taken
            snap = np.stack([
                np.where(av & (pc[None, :] == p), pool.proj_points[None, :], NEG).max(axis=1)
                for p in range(6)], axis=1)
        rnd = (pk - 1) // n_teams + 1
        if pk in my_future:
            elig = (~taken) & _fillable(counts)[:, pc]
            picked = np.argmax(np.where(elig, perf, NEG), axis=1)
            mine[rows, picked] = True
            counts[rows, pc[picked]] += 1
        else:
            ok = ~taken
            if rnd < NO_KDST_BEFORE_ROUND:
                ok = ok & ~kd[None, :]
            picked = np.argmin(np.where(ok, adp_s, POS_INF), axis=1)
        taken[rows, picked] = True
    return optimal_lineup_points(mine, perf, pc), snap


def _reason(pool, c, score, survive, snapshot_pick):
    pos = POSITIONS[pool.pos_code[c]]
    base = f"Projects your final starting lineup to {score:.0f} pts."
    if snapshot_pick is None:
        return base
    gone = 1.0 - survive
    if gone >= 0.5:
        return base + f" {gone * 100:.0f}% chance no comparable {pos} lasts to pick {snapshot_pick}."
    return base + f" A comparable {pos} likely survives to pick {snapshot_pick}."


def recommend_sim(pool, drafted, my_slot, current_pick, my_roster_ids,
                  n_sims=500, sigma=8.0, risk_pct=50, k=10, seed=0,
                  n_teams=N_TEAMS, n_rounds=N_ROUNDS):
    """Top-3 by the chosen percentile of final starting-lineup points (§8).

    Deterministic for a fixed seed (common random numbers across candidates).
    """
    N = len(pool)
    avail_base = np.array([pid not in drafted for pid in pool.ids])
    my_idx = [pool.id_to_idx[i] for i in my_roster_ids if i in pool.id_to_idx]
    mine_row = np.zeros(N, dtype=bool)
    mine_row[my_idx] = True
    counts_row = np.zeros(6, dtype=int)
    for i in my_idx:
        counts_row[pool.pos_code[i]] += 1

    my_all = [p for p in picks_for_slot(my_slot, n_rounds, n_teams) if p >= current_pick]
    my_future = set(my_all[1:])                 # I take the candidate at current_pick
    snapshot_pick = my_all[1] if len(my_all) > 1 else None

    scored = []
    for c in top_k_available(pool, avail_base, k):
        rng = np.random.default_rng(seed)       # common random numbers -> deterministic + fair
        outcomes, snap = _simulate(pool, avail_base, my_future, c, mine_row,
                                   counts_row, current_pick, n_sims, sigma, rng,
                                   n_teams, n_rounds, snapshot_pick)
        survive = (float(np.mean(snap[:, pool.pos_code[c]] >= pool.proj_points[c] - 15.0))
                   if snap is not None else 0.0)
        scored.append({"idx": c, "score": float(np.percentile(outcomes, risk_pct)),
                       "survive": survive})

    scored.sort(key=lambda r: -r["score"])
    return [{
        "canonical_id": pool.ids[r["idx"]], "name": pool.names[r["idx"]],
        "pos": POSITIONS[pool.pos_code[r["idx"]]], "team": pool.teams[r["idx"]],
        "proj_points": float(pool.proj_points[r["idx"]]), "score": r["score"],
        "survive_odds": r["survive"],
        "reasoning": _reason(pool, r["idx"], r["score"], r["survive"], snapshot_pick),
    } for r in scored[:3]]
