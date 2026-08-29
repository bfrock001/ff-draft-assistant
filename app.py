"""Phase 1 — static draft board (spec §10).

A manual click-off board for a live 10-team PPR snake draft: pick tracking for
all 160 picks, team assignment, undo, my-roster panel, and per-pick state save /
resume. No recommendations yet (Phases 2-3).

Run:  streamlit run app.py
"""
from __future__ import annotations

import datetime
import math
import os

import pandas as pd
import streamlit as st

import refresh
import snapshots
from board import load_board
from config import N_TEAMS
from draft_state import DraftState, state_path
from explain import explain_candidate
from history import game_log, load_weekly, mfl_to_gsis, season_summary
from pool import PlayerPool
from sim import recommend_sim
from vona import vona_recommend

st.set_page_config(page_title="Who's Your Daddy? · Draft Assistant",
                   page_icon="💀", layout="wide")

ACTIVE = snapshots.active_snapshot()
SP = state_path(ACTIVE)
LOGO = next((f"assets/logo.{ext}" for ext in ("png", "jpg", "jpeg", "webp")
             if os.path.exists(f"assets/logo.{ext}")), None)
DISPLAY_COLS = ["rank", "name", "pos", "team", "bye", "tier", "proj_points",
                "rank_sd", "rank_best", "rank_worst", "espn_rank"]
POS_ORDER = ["QB", "RB", "WR", "TE", "K", "DST"]


@st.cache_data
def get_board(date):
    return load_board(date)


@st.cache_resource
def get_pool(date):
    return PlayerPool.from_board(load_board(date))


@st.cache_resource
def get_weekly():
    return load_weekly()


@st.cache_resource
def get_mfl_gsis():
    return mfl_to_gsis()


@st.cache_data(show_spinner="Simulating the rest of the draft…")
def sim_cached(active, drafted_key, roster_key, my_slot, my_pick, n_sims, sigma, risk_pct):
    """Cached per snapshot + draft state + settings, so it only recomputes on a
    new pick, not on every filter/search rerun. Returns (recs, seconds_taken)."""
    import time
    t = time.perf_counter()
    recs = recommend_sim(get_pool(active), set(drafted_key), my_slot, my_pick,
                         list(roster_key), n_sims=n_sims, sigma=sigma,
                         risk_pct=risk_pct, seed=0)
    return recs, time.perf_counter() - t


def team_label(t: int, my_slot: int) -> str:
    return f"Team {t}" + (" (YOU)" if t == my_slot else "")


# --- Update-data panel (spec §3.5): upload new FantasyPros files -> new snapshot ---
def _do_build(active, new_date, rankings_up, proj_files):
    import re
    st.session_state.pop("build_report", None)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", new_date or ""):
        st.error("Snapshot date must be YYYY-MM-DD.")
        return
    if rankings_up is None:
        st.error("Upload the consensus rankings CSV.")
        return
    missing = [p for p in POS_ORDER if proj_files.get(p) is None]
    if missing:
        st.error("Missing projection files for: " + ", ".join(missing))
        return
    d = snapshots.snapshot_dir(new_date)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "rankings.csv"), "wb") as f:
        f.write(rankings_up.getvalue())
    for pos in POS_ORDER:
        with open(os.path.join(d, snapshots.PROJ_RAW[pos]), "wb") as f:
            f.write(proj_files[pos].getvalue())
    carried = refresh.carry_espn_forward(active, new_date)
    try:
        manifest = refresh.rebuild(new_date)
    except Exception as e:  # noqa: BLE001 — surfaced to the user, not fatal
        st.error(f"Build failed: {e}")
        return
    diff = None
    if active != new_date:
        try:
            diff = refresh.diff(active, new_date)
        except Exception:  # noqa: BLE001
            diff = None
    st.cache_data.clear()
    st.cache_resource.clear()
    st.session_state.build_report = {"date": new_date, "manifest": manifest,
                                     "diff": diff, "carried_espn": carried}


def _render_report(rep, has_picks):
    m, date = rep["manifest"], rep["date"]
    g, cov = m["gate"], m.get("coverage", {})
    st.markdown(f"**Built snapshot `{date}`**")
    if g["unmatched_top_n_count"] == 0:
        st.success(f"ID gate ✅ — 0 unmatched in the top {g['top_n']} "
                   f"({g['n_rankings']} players).")
    else:
        st.error(f"ID gate ⚠️ — {g['unmatched_top_n_count']} unmatched in the top "
                 f"{g['top_n']}. Add them to data/manual_id_overrides.csv and rebuild:")
        for u in g["unmatched_top_n"]:
            st.caption("• " + u)
    if "error" not in cov:
        st.caption(f"Coverage: projections {cov['proj_have']}/{cov['total']} · "
                   f"ESPN {cov['espn_have']}/{cov['total']} of top {cov['top_n']}"
                   + ("  ·  ESPN carried forward" if rep["carried_espn"] else ""))
    d = rep["diff"]
    if d:
        st.markdown(f"**Changes vs `{d['old_date']}`:**")
        if d["entrants"]:
            st.caption("New in top 200: " + ", ".join(d["entrants"][:15])
                       + (" …" if len(d["entrants"]) > 15 else ""))
        if d["dropped"]:
            st.caption("Dropped from top 200: " + ", ".join(d["dropped"][:15])
                       + (" …" if len(d["dropped"]) > 15 else ""))
        if d["movers"]:
            st.caption("Biggest rank moves: " + " · ".join(
                f"{mv['name']} {mv['old']}→{mv['new']}" for mv in d["movers"][:8]))
        if not (d["entrants"] or d["dropped"] or d["movers"]):
            st.caption("No material changes vs the previous snapshot.")
    if g["unmatched_top_n_count"] == 0:
        if has_picks:
            st.info("Finish or reset the current draft before activating a new "
                    "snapshot — it changes the player data.")
        elif st.button(f"Activate snapshot {date}", type="primary", key="activate"):
            snapshots.set_active_snapshot(date)
            st.session_state.ds = DraftState(my_slot=st.session_state.ds.my_slot,
                                             date=date)
            st.session_state.ds.save(state_path(date))
            st.session_state.pop("build_report", None)
            st.cache_data.clear()
            st.cache_resource.clear()
            st.rerun()


def render_update_panel(active, has_picks):
    with st.expander("⟳ Update data — upload new FantasyPros files", expanded=False):
        st.caption("Upload a fresh FantasyPros consensus-rankings export and the six "
                   "per-position projection exports, then Build. The ESPN board is "
                   "carried forward from the current snapshot (a dedicated ESPN "
                   "refresh button comes next). Nothing changes until you Activate.")
        rankings_up = st.file_uploader("Consensus rankings (1 CSV)", type="csv",
                                       key="up_rankings")
        st.markdown("**Projection exports (FantasyPros, per position)**")
        pcols = st.columns(3)
        proj_files = {pos: pcols[i % 3].file_uploader(pos, type="csv",
                      key=f"up_proj_{pos}") for i, pos in enumerate(POS_ORDER)}
        new_date = st.text_input("Snapshot date (folder name)",
                                 value=datetime.date.today().isoformat(), key="up_date")
        if st.button("Build snapshot", type="primary", key="up_build"):
            _do_build(active, new_date, rankings_up, proj_files)
        rep = st.session_state.get("build_report")
        if rep:
            st.divider()
            _render_report(rep, has_picks)


# --- resume / init (spec §10) ---
if "ds" not in st.session_state:
    st.session_state.ds = None

if st.session_state.ds is None:
    if os.path.exists(SP):
        st.info("A saved draft for today was found.")
        c1, c2 = st.columns(2)
        if c1.button("Resume saved draft", type="primary"):
            st.session_state.ds = DraftState.load(SP)
            st.rerun()
        if c2.button("Start new (discard saved)"):
            st.session_state.ds = DraftState(my_slot=3, date=ACTIVE)
            st.session_state.ds.save(SP)
            st.rerun()
        st.stop()
    else:
        st.session_state.ds = DraftState(my_slot=3, date=ACTIVE)

ds: DraftState = st.session_state.ds
board = get_board(ACTIVE)
drafted = ds.drafted_ids()
avail = board[~board["canonical_id"].isin(drafted)]

# --- sidebar: settings + data freshness + controls ---
with st.sidebar:
    if LOGO:
        st.image(LOGO, width=220)
    st.header("Settings")
    if len(ds.picks) == 0:
        slot = st.selectbox("My draft slot", range(1, N_TEAMS + 1),
                            index=ds.my_slot - 1)
        if slot != ds.my_slot:
            ds.my_slot = slot
            ds.save(SP)
            st.rerun()
    else:
        st.write(f"My draft slot: **{ds.my_slot}**")

    snaps = snapshots.list_snapshots()
    picked = st.selectbox("Data snapshot", snaps, index=snaps.index(ACTIVE),
                          disabled=len(ds.picks) > 0,
                          help="Newest first. Switch the dataset the app reads "
                               "(locked once a draft is underway).")
    if picked != ACTIVE and len(ds.picks) == 0:
        snapshots.set_active_snapshot(picked)
        st.session_state.ds = DraftState(my_slot=ds.my_slot, date=picked)
        st.session_state.ds.save(state_path(picked))
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()
    age = snapshots.age_days(ACTIVE)
    st.caption(f"Data as of {ACTIVE} · {age} day(s) old")
    if age > 7:
        st.warning(f"Snapshot is {age} days old — consider refreshing.")

    st.divider()
    engine = st.radio("Engine", ["VONA (instant)", "Simulation"], key="engine")
    risk_pct, sim_sigma, sim_nsims, risk = 50, 8.0, 500, "Balanced"
    if engine == "Simulation":
        risk = st.select_slider("Risk dial", ["Safe", "Balanced", "Upside"],
                                value="Balanced", key="risk")
        risk_pct = {"Safe": 30, "Balanced": 50, "Upside": 70}[risk]
        sim_sigma = st.slider("Opponent randomness σ", 0.0, 16.0, 8.0, 1.0, key="sigma")
        sim_nsims = st.select_slider("Simulations", [250, 500, 1000], value=500,
                                     key="nsims")

    st.divider()
    if st.button("Undo last pick", disabled=len(ds.picks) == 0,
                 width="stretch"):
        ds.undo()
        ds.save(SP)
        st.rerun()
    if st.button("Reset draft", width="stretch"):
        st.session_state.ds = DraftState(my_slot=ds.my_slot, date=ACTIVE)
        st.session_state.ds.save(SP)
        st.rerun()

# --- header: where are we in the draft ---
oc = ds.on_the_clock()
mine_now = oc == ds.my_slot
h = st.columns(4)
h[0].metric("Pick", "done" if ds.is_complete() else ds.current_pick)
h[1].metric("Round", "-" if ds.is_complete() else ds.current_round)
h[2].metric("On the clock", "-" if oc is None else ("YOU" if mine_now else f"Team {oc}"))
utn = ds.picks_until_my_turn()
h[3].metric("Picks to my turn", "-" if utn is None else ("YOU'RE UP" if utn == 0 else utn))

render_update_panel(ACTIVE, len(ds.picks) > 0)

# --- recommendation cards (§8, §10 top) ---
if not ds.is_complete():
    upcoming = [p for p in ds.my_pick_numbers() if p >= ds.current_pick]
    if upcoming:
        my_pick = upcoming[0]
        my_next_pick = upcoming[1] if len(upcoming) > 1 else None
        roster_pos = [p["pos"] for p in ds.my_roster()]
        pool = get_pool(ACTIVE)
        on_clock = ("You're on the clock." if my_pick == ds.current_pick
                    else f"Targets for your next pick (overall {my_pick}).")

        def why_expander(cid):  # offline, instant rationale (Phase 5)
            idx = pool.id_to_idx.get(cid)
            if idx is None:
                return
            with st.expander("Why?"):
                exp = explain_candidate(pool, idx, ds.drafted_ids(), roster_pos,
                                        my_pick, my_next_pick)
                for line in exp["lines"]:
                    st.markdown(f"- {line}")

        if engine == "Simulation":
            recs, secs = sim_cached(
                ACTIVE, frozenset(ds.drafted_ids()),
                tuple(p["player_id"] for p in ds.my_roster()),
                ds.my_slot, my_pick, sim_nsims, sim_sigma, risk_pct)
            over = "  ·  ⚠️ over 3s — lower Simulations" if secs > 3 else ""
            st.markdown("#### Recommended picks · Simulation")
            st.caption(f"{on_clock}  ·  {sim_nsims} sims · σ={sim_sigma:.0f} · "
                       f"{risk} · {secs:.2f}s{over}")
            for col, r in zip(st.columns(3), recs):
                with col.container(border=True):
                    st.markdown(f"**{r['name']}** · {r['pos']} {r['team']}")
                    st.metric("Proj lineup", f"{r['score']:.0f}")
                    st.caption(r["reasoning"])
                    why_expander(r["canonical_id"])
        else:
            recs = vona_recommend(pool, ds.drafted_ids(), my_pick, my_next_pick,
                                  roster_pos, k=3)
            st.markdown("#### Recommended picks · VONA")
            st.caption(on_clock)
            for col, r in zip(st.columns(3), recs):
                with col.container(border=True):
                    st.markdown(f"**{r['name']}** · {r['pos']} {r['team']}")
                    st.metric("Proj points", f"{r['proj_points']:.0f}",
                              delta=f"VONA {r['adj_vona']:.0f}")
                    st.caption(r["reasoning"])
                    why_expander(r["canonical_id"])

left, right = st.columns([3, 1])

with left:
    if ds.is_complete():
        st.success("Draft complete — all 160 picks are in.")
    else:
        st.subheader(f"Pick {ds.current_pick} · round {ds.current_round}")

    # filters (reset to the full board each pick)
    fc = st.columns([1, 2])
    pos_filter = fc[0].selectbox(
        "Position", ["All", "QB", "RB", "WR", "TE", "FLEX", "K", "DST"],
        key=f"pos_{ds.current_pick}")
    search = fc[1].text_input("Search", placeholder="player name…",
                              key=f"search_{ds.current_pick}")
    view = avail
    if pos_filter == "FLEX":
        view = view[view["pos"].isin(["RB", "WR", "TE"])]
    elif pos_filter != "All":
        view = view[view["pos"] == pos_filter]
    if search:
        view = view[view["name"].str.contains(search, case=False, na=False)]
    view = view.reset_index(drop=True)
    table = view[DISPLAY_COLS].round({"proj_points": 1, "rank_sd": 1})

    if ds.is_complete():
        st.dataframe(table, hide_index=True, width="stretch", height=460)
    else:
        st.caption("Click a player's row, set the team, then Draft.")
        # key changes per pick and per filter so the selection never points at
        # a stale row after a pick or a filter change.
        sel = st.dataframe(
            table, hide_index=True, width="stretch", height=420,
            on_select="rerun", selection_mode="single-row",
            key=f"board_{ds.current_pick}_{pos_filter}_{search}")
        rows = sel.selection["rows"] if sel and sel.selection else []
        if rows:
            prow = view.iloc[rows[0]]
            proj = prow["proj_points"]
            proj_str = ("" if not isinstance(proj, (int, float)) or math.isnan(proj)
                        else f" · proj {proj:.0f}")
            cta = st.columns([3, 1, 1])
            cta[0].markdown(f"**{prow['name']}** — {prow['pos']} {prow['team']} "
                            f"· #{int(prow['rank'])}{proj_str}")
            team = cta[1].selectbox(
                "Drafted by", range(1, N_TEAMS + 1), index=(oc - 1),
                format_func=lambda t: team_label(t, ds.my_slot),
                key=f"team_{ds.current_pick}")
            cta[2].write("")
            if cta[2].button("Draft", type="primary", width="stretch"):
                cid = prow["canonical_id"]
                if not isinstance(cid, str):
                    cid = f"NM_{prow['name']}"
                ds.make_pick(cid, prow["name"], prow["pos"], team=team)
                ds.save(SP)
                st.rerun()

with right:
    st.markdown("#### My roster")
    slots, bench = ds.roster_slots()
    for label, p in slots:
        st.write(f"**{label}** · " + (p["player_name"] if p else "—"))
    if bench:
        st.caption("Bench: " + ", ".join(b["player_name"] for b in bench))

    st.markdown("#### Recent picks")
    for p in reversed(ds.picks[-8:]):
        who = "YOU" if p["team"] == ds.my_slot else f"T{p['team']}"
        st.caption(f"{p['overall']}. [{who}] {p['player_name']} ({p['pos']})")

# --- player detail / history drill-down (spec §10 bottom, Phase 4) ---
st.divider()
st.markdown("### Player detail")
sel = st.selectbox("Inspect a player", board["name"].tolist(), key="detail_player")
prow = board[board["name"] == sel].iloc[0]
st.caption(f"{prow['pos']} {prow['team']} · proj {prow['proj_points']:.0f} · "
           f"consensus rank {prow['consensus_rank']:.1f} "
           f"(best {int(prow['rank_best'])} / worst {int(prow['rank_worst'])}, "
           f"analyst spread ±{prow['rank_sd']:.1f})")

gsis = get_mfl_gsis().get(str(prow["canonical_id"]))
if prow["pos"] == "DST" or gsis is None:
    st.info("No game-level history here — team D/ST (and a few unmatched players) "
            "aren't in the weekly player data.")
else:
    weekly = get_weekly()
    summ = season_summary(weekly, gsis)
    st.dataframe(
        pd.DataFrame(summ).rename(columns={
            "season": "Season", "total": "PPR", "ppg": "PPG", "games": "G",
            "boom_pct": "Boom% (≥20)", "bust_pct": "Bust% (≤5)", "missed": "Missed"}),
        hide_index=True, width="stretch")
    played = [s["season"] for s in summ if s["games"] > 0]
    if played:
        season = st.radio("Game log", played, horizontal=True,
                          index=len(played) - 1, key="detail_season")
        gl = (game_log(weekly, gsis, season).to_pandas()
              .rename(columns={"week": "Wk", "opponent_team": "Opp", "ppr": "PPR"}))
        gc, cc = st.columns(2)
        gc.dataframe(gl, hide_index=True, width="stretch", height=320)
        cc.bar_chart(gl.set_index("Wk")["PPR"], height=320)
    else:
        st.info("No 2023-2025 regular-season games (rookie or no data).")
