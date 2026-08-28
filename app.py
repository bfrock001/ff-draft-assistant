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

import streamlit as st

from board import SNAP_DATE, load_board
from config import N_TEAMS
from draft_state import DraftState, state_path

st.set_page_config(page_title="Draft Assistant", layout="wide")

SP = state_path(SNAP_DATE)
DISPLAY_COLS = ["rank", "name", "pos", "team", "bye", "tier", "proj_points",
                "rank_sd", "rank_best", "rank_worst", "espn_rank"]


@st.cache_data
def get_board():
    return load_board()


def team_label(t: int, my_slot: int) -> str:
    return f"Team {t}" + (" (YOU)" if t == my_slot else "")


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
            st.session_state.ds = DraftState(my_slot=3, date=SNAP_DATE)
            st.session_state.ds.save(SP)
            st.rerun()
        st.stop()
    else:
        st.session_state.ds = DraftState(my_slot=3, date=SNAP_DATE)

ds: DraftState = st.session_state.ds
board = get_board()
drafted = ds.drafted_ids()
avail = board[~board["canonical_id"].isin(drafted)]

# --- sidebar: settings + data freshness + controls ---
with st.sidebar:
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

    st.caption(f"Data as of {SNAP_DATE}")
    age = (datetime.date.today() - datetime.date.fromisoformat(SNAP_DATE)).days
    if age > 7:
        st.warning(f"Snapshot is {age} days old — consider refreshing.")

    st.divider()
    if st.button("Undo last pick", disabled=len(ds.picks) == 0,
                 width="stretch"):
        ds.undo()
        ds.save(SP)
        st.rerun()
    if st.button("Reset draft", width="stretch"):
        st.session_state.ds = DraftState(my_slot=ds.my_slot, date=SNAP_DATE)
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
