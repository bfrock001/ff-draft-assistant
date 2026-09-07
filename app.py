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

import espn_live
import overrides
import refresh
import snapshots
from board import load_board
from strategy import suggest_risk
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
_OV = overrides.load()
OV_SIG = overrides.signature()               # cache key: changes when overrides change
EXCLUDE = frozenset(overrides.excluded_ids(_OV))
LOGO = next((f"assets/logo.{ext}" for ext in ("png", "jpg", "jpeg", "webp")
             if os.path.exists(f"assets/logo.{ext}")), None)
DISPLAY_COLS = ["rank", "name", "pos", "team", "bye", "tier", "proj_points",
                "rank_sd", "rank_best", "rank_worst", "espn_rank"]
POS_ORDER = ["QB", "RB", "WR", "TE", "K", "DST"]


@st.cache_data
def get_base_board(date):
    """The source board, no overrides — cached per snapshot (the editor's base)."""
    return load_board(date)


@st.cache_data
def get_board(date, ov_sig):
    return overrides.apply(get_base_board(date), overrides.load())


@st.cache_resource
def get_pool(date, ov_sig):
    return PlayerPool.from_board(overrides.apply(get_base_board(date), overrides.load()))


@st.cache_resource
def get_weekly():
    return load_weekly()


@st.cache_resource
def get_mfl_gsis():
    return mfl_to_gsis()


@st.cache_data(show_spinner="Simulating the rest of the draft…")
def sim_cached(active, ov_sig, exclude_key, drafted_key, roster_key, my_slot, my_pick,
               n_sims, sigma, risk_pct):
    """Cached per snapshot + overrides + draft state + settings, so it only
    recomputes on a new pick, not on every rerun. Returns (recs, seconds)."""
    import time
    t = time.perf_counter()
    recs = recommend_sim(get_pool(active, ov_sig), set(drafted_key), my_slot, my_pick,
                         list(roster_key), n_sims=n_sims, sigma=sigma,
                         risk_pct=risk_pct, seed=0, exclude=set(exclude_key))
    return recs, time.perf_counter() - t


def team_label(t: int, my_slot: int) -> str:
    return f"Team {t}" + (" (YOU)" if t == my_slot else "")


def _apply_sugg_risk():
    st.session_state.risk = st.session_state.get("_sugg_risk", "Balanced")


# --- Update-data panel (spec §3.5): upload new FantasyPros files -> new snapshot ---
def _do_build(active, new_date, rankings_up, proj_files):
    import re
    st.session_state.pop("build_report", None)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", new_date or ""):
        st.error("Snapshot date must be YYYY-MM-DD.")
        return
    provided_proj = [p for p in POS_ORDER if proj_files.get(p) is not None]
    if rankings_up is None and not provided_proj:
        st.error("Upload at least the consensus rankings or one projection file — "
                 "anything you skip is carried forward from the current snapshot.")
        return
    d = snapshots.snapshot_dir(new_date)
    os.makedirs(d, exist_ok=True)
    if rankings_up is not None:
        with open(os.path.join(d, "rankings.csv"), "wb") as f:
            f.write(rankings_up.getvalue())
    for pos in provided_proj:
        with open(os.path.join(d, snapshots.PROJ_RAW[pos]), "wb") as f:
            f.write(proj_files[pos].getvalue())
    # carry forward anything NOT uploaded (rankings / projections) + the ESPN board
    if new_date != active:
        refresh.carry_fantasypros_forward(active, new_date)
    carried_espn = refresh.carry_espn_forward(active, new_date)
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
    fresh = (["rankings"] if rankings_up is not None else []) + provided_proj
    st.session_state.build_report = {"date": new_date, "manifest": manifest,
                                     "diff": diff, "carried_espn": carried_espn,
                                     "fresh": fresh, "src": active}


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
                   f"ESPN {cov['espn_have']}/{cov['total']} of top {cov['top_n']}")
    fresh = rep.get("fresh") or []
    carried = [x for x in (["rankings"] + list(POS_ORDER)) if x not in fresh]
    if rep.get("carried_espn"):
        carried.append("ESPN")
    st.caption("🆕 fresh this build: " + (", ".join(fresh) or "none")
               + ("  ·  ♻️ carried forward: " + ", ".join(carried) if carried else ""))
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


def _render_espn_report(rep):
    if "error" in rep:
        st.error("ESPN update failed — the previous board is unchanged.\n\n"
                 + rep["error"])
        return
    res = rep["res"]
    rows, m = res["rows"], res["manifest"]
    cov = m.get("coverage", {})
    when = m.get("espn_refreshed_at", "")
    if res.get("created_new"):
        head = (f"Created snapshot `{res['target']}` (FantasyPros carried forward) "
                f"with fresh ESPN — {len(rows)} players")
    else:
        head = f"ESPN board updated — {len(rows)} players pulled"
    st.success(head + (f" · {when}" if when else ""))
    if "error" not in cov:
        st.caption(f"Coverage: {cov['espn_have']}/{cov['total']} of your top "
                   f"{cov['top_n']} have an ESPN rank.")
    st.caption("Top of ESPN board: " + " · ".join(
        f"{r['name']} ({r['pos']}" + (f", ADP {r['adp']}" if r['adp'] != "" else "")
        + ")" for r in rows[:5]))
    miss = res.get("missing") or []
    if miss:
        st.caption(f"{len(miss)} of your top-200 aren't on ESPN's board: "
                   + ", ".join(x["name"] for x in miss[:10])
                   + (" …" if len(miss) > 10 else ""))


def render_espn_update(active, has_picks):
    today = datetime.date.today().isoformat()
    with st.expander("⟳ Update ESPN board (opponent model)", expanded=False):
        if today == active:
            st.caption(f"Pulls the latest ESPN PPR draft ranks + ADP into today's "
                       f"snapshot ({active}). Pre-draft only — the draft never "
                       "touches the network.")
        else:
            st.caption(f"Pulls the latest ESPN board into a NEW snapshot dated "
                       f"{today} (your current FantasyPros data carried forward), "
                       f"keeping {active} pristine. Pre-draft only.")
        if not espn_live.cookies_configured():
            st.warning("ESPN cookies aren't set up. Copy "
                       "`config/espn_cookies.example.json` to "
                       "`config/espn_cookies.json` and paste your `espn_s2` + `SWID` "
                       "(DevTools → Application → Cookies → fantasy.espn.com).")
        elif today != active and has_picks:
            st.info("This would create a new dated snapshot (changing the active "
                    "dataset) — finish or reset the current draft first.")
        elif st.button("Update ESPN now", type="primary", key="espn_update"):
            try:
                with st.spinner("Fetching the latest ESPN board…"):
                    res = refresh.refresh_espn_smart(active)
            except Exception as e:  # noqa: BLE001 — surfaced to the user
                st.session_state.espn_report = {"error": str(e)}
            else:
                st.session_state.espn_report = {"res": res}
                if res.get("created_new"):
                    st.session_state.ds = DraftState(
                        my_slot=st.session_state.ds.my_slot, date=res["target"])
                    st.session_state.ds.save(state_path(res["target"]))
                st.cache_data.clear()
                st.cache_resource.clear()
                st.rerun()
        rep = st.session_state.get("espn_report")
        if rep:
            st.divider()
            _render_espn_report(rep)


def _ov_changed(edited, base) -> bool:
    a_na = edited is None or (isinstance(edited, float) and math.isnan(edited))
    b_na = base is None or (isinstance(base, float) and math.isnan(base))
    if a_na and b_na:
        return False
    if a_na or b_na:
        return True
    return abs(float(edited) - float(base)) > 0.05


def render_overrides_panel(active):
    with st.expander("✏️ Edit rankings & projections (your overrides)", expanded=False):
        st.caption("Disagree with the board? Edit a player's **proj** (the points "
                   "both engines optimize) or **cons.rank** (candidate order), or "
                   "tick **exclude** to keep him out of your recommendations "
                   "(opponents can still draft him, and he stays on the board so you "
                   "can track the pick). Saved globally, applied over whichever "
                   "snapshot is active.")
        base = get_base_board(active).reset_index(drop=True)
        ov = overrides.load()
        cids = base["canonical_id"].tolist()
        disp = pd.DataFrame({
            "rank": base["rank"], "name": base["name"], "pos": base["pos"],
            "team": base["team"],
            "cons.rank": [ov.get(c, {}).get("consensus_rank", r)
                          for c, r in zip(cids, base["consensus_rank"])],
            "proj": [ov.get(c, {}).get("proj_points", p)
                     for c, p in zip(cids, base["proj_points"])],
            "exclude": [bool(ov.get(c, {}).get("exclude", False)) for c in cids],
        })
        edited = st.data_editor(
            disp, hide_index=True, height=400, width="stretch",
            key=f"editor_{overrides.signature()}",
            disabled=["rank", "name", "pos", "team"],
            column_config={
                "proj": st.column_config.NumberColumn("proj", format="%.1f", step=1.0),
                "cons.rank": st.column_config.NumberColumn("cons.rank", format="%.1f", step=1.0),
                "exclude": st.column_config.CheckboxColumn("exclude"),
            })
        new_ov = {}
        for i, cid in enumerate(cids):
            if not isinstance(cid, str):
                continue
            o = {}
            if _ov_changed(edited.iloc[i]["cons.rank"], base["consensus_rank"].iloc[i]):
                o["consensus_rank"] = float(edited.iloc[i]["cons.rank"])
            if _ov_changed(edited.iloc[i]["proj"], base["proj_points"].iloc[i]):
                o["proj_points"] = float(edited.iloc[i]["proj"])
            if bool(edited.iloc[i]["exclude"]):
                o["exclude"] = True
            if o:
                new_ov[cid] = o
        c1, c2 = st.columns([4, 1])
        c1.caption(f"{len(new_ov)} player override(s) active.")
        if c2.button("Clear all", key="clear_ov", disabled=not ov, width="stretch"):
            overrides.save({})
            st.cache_data.clear()
            st.cache_resource.clear()
            st.rerun()
        if new_ov != ov:
            overrides.save(new_ov)
            st.cache_data.clear()
            st.cache_resource.clear()
            st.rerun()


def render_update_panel(active, has_picks):
    with st.expander("⟳ Update data — upload new FantasyPros files", expanded=False):
        st.caption("Upload only what changed — the rankings, some or all projections, "
                   f"or everything. **Anything you skip is carried forward from the "
                   f"current snapshot ({active}).** So a routine news update can be "
                   "just the rankings file. Nothing changes until you Activate.")
        rankings_up = st.file_uploader("Consensus rankings — 1 CSV (optional)",
                                       type="csv", key="up_rankings")
        st.markdown("**Projection exports (per position — upload only the ones you're "
                    "updating; the rest carry forward)**")
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
board = get_board(ACTIVE, OV_SIG)
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
    st.session_state.setdefault("risk", "Balanced")
    engine = st.radio("Engine", ["VONA (instant)", "Simulation"], key="engine")
    risk_pct, sim_sigma, sim_nsims, risk = 50, 8.0, 500, "Balanced"
    # round/roster-aware risk suggestion — see suggest_risk() for the rationale
    _up = [p for p in ds.my_pick_numbers() if p >= ds.current_pick]
    _my_round = ((_up[0] - 1) // N_TEAMS + 1) if _up else None
    _starters_open = sum(1 for _, p in ds.roster_slots()[0] if p is None)
    sugg_risk, sugg_reason = suggest_risk(_my_round, _starters_open)
    st.session_state._sugg_risk = sugg_risk
    if engine == "Simulation":
        risk = st.select_slider("Risk dial", ["Safe", "Balanced", "Upside"],
                                key="risk")
        _rd = f"round {_my_round}" if _my_round else "this pick"
        st.caption(f"💡 Suggested for {_rd}: **{sugg_risk}** — {sugg_reason}")
        if st.session_state.risk != sugg_risk:
            st.button(f"Use {sugg_risk}", key="apply_risk",
                      on_click=_apply_sugg_risk, width="stretch")
        risk_pct = {"Safe": 30, "Balanced": 50, "Upside": 70}[risk]
        sim_sigma = st.slider("Opponent randomness σ", 0.0, 16.0, 8.0, 1.0, key="sigma")
        st.caption("💡 Suggested ~8 (realistic draft chaos). Lower toward 6 if your "
                   "league drafts chalk / has auto-drafters; raise toward 10 if wild.")
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

render_espn_update(ACTIVE, len(ds.picks) > 0)
render_update_panel(ACTIVE, len(ds.picks) > 0)
render_overrides_panel(ACTIVE)

# --- recommendation cards (§8, §10 top) ---
if not ds.is_complete():
    upcoming = [p for p in ds.my_pick_numbers() if p >= ds.current_pick]
    if upcoming:
        my_pick = upcoming[0]
        my_next_pick = upcoming[1] if len(upcoming) > 1 else None
        roster_pos = [p["pos"] for p in ds.my_roster()]
        pool = get_pool(ACTIVE, OV_SIG)
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

        # The simulation only runs when you're actually on the clock — so clicking
        # off a fast run of opponent picks stays instant. Off-turn (or on VONA) it
        # shows the instant VONA read instead.
        if engine == "Simulation" and mine_now:
            recs, secs = sim_cached(
                ACTIVE, OV_SIG, EXCLUDE, frozenset(ds.drafted_ids()),
                tuple(p["player_id"] for p in ds.my_roster()),
                ds.my_slot, my_pick, sim_nsims, sim_sigma, risk_pct)
            over = "  ·  ⚠️ over 3s — lower Simulations" if secs > 3 else ""
            nudge = (f"  ·  💡 try **{sugg_risk}** this round"
                     if sugg_risk and risk != sugg_risk else "")
            st.markdown("#### Recommended picks · Simulation")
            st.caption(f"You're on the clock.  ·  {sim_nsims} sims · σ={sim_sigma:.0f} · "
                       f"{risk} · {secs:.2f}s{over}{nudge}")
            for col, r in zip(st.columns(3), recs):
                with col.container(border=True):
                    st.markdown(f"**{r['name']}** · {r['pos']} {r['team']}")
                    st.metric("Proj lineup", f"{r['score']:.0f}")
                    st.caption(r["reasoning"])
                    why_expander(r["canonical_id"])
        else:
            recs = vona_recommend(pool, ds.drafted_ids(), my_pick, my_next_pick,
                                  roster_pos, k=3, exclude=EXCLUDE)
            preview = engine == "Simulation"   # sim selected but not my turn
            st.markdown("#### " + ("Your next pick · VONA preview" if preview
                                   else "Recommended picks · VONA"))
            st.caption(f"Overall {my_pick} — the full simulation runs when you're on "
                       "the clock; instant VONA read for now." if preview else on_clock)
            for col, r in zip(st.columns(3), recs):
                with col.container(border=True):
                    st.markdown(f"**{r['name']}** · {r['pos']} {r['team']}")
                    st.metric("Proj points", f"{r['proj_points']:.0f}",
                              delta=f"VONA {r['adj_vona']:.0f}")
                    st.caption(r["reasoning"])
                    if not preview:
                        why_expander(r["canonical_id"])

left, right = st.columns([3, 1])

with left:
    if ds.is_complete():
        st.success("Draft complete — all 160 picks are in.")
    else:
        st.subheader(f"Pick {ds.current_pick} · round {ds.current_round}")

    if EXCLUDE:
        ex_names = board[board["canonical_id"].isin(EXCLUDE)]["name"].tolist()
        if ex_names:
            st.caption("🚫 Excluded from your recs: " + ", ".join(ex_names[:12])
                       + (" …" if len(ex_names) > 12 else "")
                       + " — opponents can still draft them (they stay on the board).")

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
        st.caption("Click a player's row, then **Draft** (one pick at a time).")
        # key changes per pick and per filter so the selection never points at
        # a stale row after a pick or a filter change.
        board_key = f"board_{ds.current_pick}_{pos_filter}_{search}"

        def draft_bar(selected, bar_key, empty_hint=False):
            if not selected:
                if empty_hint:
                    st.caption("Click a player's row in the board below, then Draft.")
                return
            p = selected[0]
            st.caption(f"**{p['name']}** — {p['pos']} {p['team']} → pick {ds.current_pick}")
            if st.button(f"Draft {p['name']}", type="primary", key=bar_key,
                         width="stretch"):
                cid = p["canonical_id"]
                if not isinstance(cid, str):
                    cid = f"NM_{p['name']}"
                ds.make_pick(cid, p["name"], p["pos"])   # team auto = pick order
                ds.save(SP)
                st.rerun()

        top_bar = st.container()          # rendered ABOVE the board
        # single-row selection — no "select all" header checkbox, so a stray click
        # can never mass-draft the board.
        sel = st.dataframe(
            table, hide_index=True, width="stretch", height=420,
            on_select="rerun", selection_mode="single-row", key=board_key)
        selrows = sel.selection["rows"] if sel and sel.selection else []
        selected = [view.iloc[i] for i in selrows]

        # the selection also drives the Player-detail stats below
        if selrows:
            picked_name = view.iloc[selrows[0]]["name"]
            if st.session_state.get("_last_board_sel") != picked_name:
                st.session_state._last_board_sel = picked_name
                st.session_state.detail_player = picked_name

        with top_bar:
            draft_bar(selected, "draft_top", empty_hint=True)
        draft_bar(selected, "draft_bottom")

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
