"""Cheat Sheet & Notes — a second page (sidebar nav) for draft prep.

Your whole board in one filterable, sortable table with an editable **note**
column per player. Notes save automatically to data/manual_notes.csv, keyed by
canonical id, so they persist across FantasyPros/ESPN refreshes. Drafted players
(from the live draft on the main page) are flagged so you can hide them.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import overrides
import snapshots
from board import load_board

st.set_page_config(page_title="Cheat Sheet & Notes", page_icon="📋", layout="wide")


@st.cache_data(show_spinner="Loading the board…")
def _cheat_board(date, ov_sig):
    return overrides.apply(load_board(date), overrides.load())


@st.cache_data(show_spinner="Loading player history…")
def _history():
    """(gsis -> {season: total PPR}, mfl -> gsis) for the prior-season columns."""
    from history import load_weekly, mfl_to_gsis, season_totals
    return season_totals(load_weekly()), mfl_to_gsis()


active = snapshots.active_snapshot()
board = _cheat_board(active, overrides.signature()).reset_index(drop=True)
ds = st.session_state.get("ds")
drafted = ds.drafted_ids() if ds is not None else set()
notes = overrides.load_notes()
try:
    totals, m2g = _history()
except Exception:   # weekly cache unavailable (e.g. offline first run) — degrade
    totals, m2g = {}, {}

st.title("📋 Cheat Sheet & Notes")
st.caption(
    f"Your board for **{active}**, with an editable note per player — targets, "
    "sleepers, handcuffs, avoid-list, whatever. Notes save automatically and "
    "carry across data refreshes. "
    + ("A draft is in progress — drafted players are flagged below."
       if ds is not None and len(ds.picks) else
       "Start a draft on the main page and drafted players will be flagged here."))

pos_f = st.segmented_control(
    "Position", ["All", "QB", "RB", "WR", "TE", "FLEX", "K", "DST"],
    default="All") or "All"
fc = st.columns([3, 1])
search = fc[0].text_input("Search", placeholder="player name…")
hide_drafted = fc[1].checkbox("Hide drafted", value=False)

view = board.copy()
if pos_f == "FLEX":
    view = view[view["pos"].isin(["RB", "WR", "TE"])]
elif pos_f != "All":
    view = view[view["pos"] == pos_f]
if search:
    view = view[view["name"].str.contains(search, case=False, na=False)]
view["drafted"] = view["canonical_id"].isin(drafted)
if hide_drafted:
    view = view[~view["drafted"]]
view = view.sort_values("rank").reset_index(drop=True)

cids = view["canonical_id"].tolist()


def _yr(cid, season):
    g = m2g.get(str(cid)) if isinstance(cid, str) else None
    return totals.get(g, {}).get(season) if g else None


disp = pd.DataFrame({
    "rank": view["rank"].values,
    "tier": (view["tier"] if "tier" in view else pd.Series([""] * len(view))).values,
    "name": view["name"].values,
    "pos": view["pos"].values,
    "team": view["team"].values,
    "2023": [_yr(c, 2023) for c in cids],
    "2024": [_yr(c, 2024) for c in cids],
    "2025": [_yr(c, 2025) for c in cids],
    "proj": view["proj_points"].values,
    "drafted": view["drafted"].values,
    "note": [notes.get(c if isinstance(c, str) else "", "") for c in cids],
})

edited = st.data_editor(
    disp, hide_index=True, width="stretch", height=600,
    key=f"cheat_{overrides.notes_signature()}_{pos_f}_{search}_{hide_drafted}",
    disabled=["rank", "tier", "name", "pos", "team", "2023", "2024", "2025",
              "proj", "drafted"],
    column_config={
        "2023": st.column_config.NumberColumn("2023", format="%.0f",
                                              help="Actual PPR points that season"),
        "2024": st.column_config.NumberColumn("2024", format="%.0f"),
        "2025": st.column_config.NumberColumn("2025", format="%.0f"),
        "proj": st.column_config.NumberColumn("'26 proj", format="%.0f",
                                              help="This season's projected PPR points"),
        "drafted": st.column_config.CheckboxColumn("drafted"),
        "note": st.column_config.TextColumn(
            "your note", width="large",
            help="Type anything — target round, sleeper, handcuff, avoid…"),
    })

# persist changed notes, then rerun so the (signature-keyed) editor rebuilds clean
new_notes = dict(notes)
changed = False
for i, cid in enumerate(cids):
    if not isinstance(cid, str):
        continue
    n = (edited.iloc[i]["note"] or "").strip()
    if n and new_notes.get(cid, "") != n:
        new_notes[cid], changed = n, True
    elif not n and cid in new_notes:
        del new_notes[cid]
        changed = True
if changed:
    overrides.save_notes(new_notes)
    st.rerun()

n_notes = sum(1 for v in new_notes.values() if v)
c1, c2 = st.columns([4, 1])
c1.caption(f"📝 {n_notes} player note(s) saved · {len(view)} players shown.")
if c2.button("Clear all notes", disabled=not notes, width="stretch"):
    overrides.save_notes({})
    st.rerun()
