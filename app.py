##############################################
# Section 1: Imports & Session State Setup
##############################################
import streamlit as st
import json
import pandas as pd
import subprocess
import os
import glob
import numpy as np
from io import BytesIO
import time
import re
import requests
from bs4 import BeautifulSoup
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode, ColumnsAutoSizeMode
from typing import Callable, Any, List, Dict, Tuple
main: Callable[[List[Dict], str, str, Dict, Dict], Tuple[pd.DataFrame, Dict, pd.DataFrame, pd.DataFrame]] = None
selected_team: str = st.session_state.get("select_team_json", "")
selected_venue: str = st.session_state.get("select_venue_json", "")

# Import database helper functions (ensure you have db_helper.py in your repo)
from db_helper import init_db, get_score_limits, set_score_limit, delete_score_limit, \
    get_venue_machine_list, add_machine_to_venue, delete_machine_from_venue, save_machine_mapping_strategy

# Initialize database (if not already)
init_db()

# Initialize session state flags
if "roster_data" not in st.session_state:
    st.session_state.roster_data = None
if "rosters_scraped" not in st.session_state:
    st.session_state.rosters_scraped = False
if "modify_menu_open" not in st.session_state:
    st.session_state.modify_menu_open = False
if "column_options_open" not in st.session_state:
    st.session_state.column_options_open = False
if "set_score_limit_open" not in st.session_state:
    st.session_state.set_score_limit_open = False

# Path to store the machine mapping file.
repository_url = 'https://github.com/Invader-Zim/mnp-data-archive'
repo_dir = "mnp-data-archive"

##############################################
# Section 1.1: Load All JSON Files from Repository
##############################################
def load_all_json_files(repo_dir, seasons):
    all_data = []
    for season in seasons:
        directory = os.path.join(repo_dir, f"season-{season}", "matches")
        json_files = glob.glob(os.path.join(directory, "**", "*.json"), recursive=True)
        if not json_files:
            st.warning(f"No JSON files found for season {season}.")
        for file_path in json_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    all_data.append(data)
            except Exception as e:
                st.error(f"Error loading {file_path}: {e}")
    return all_data

st.write("Debug: all_data type:", type(all_data))
st.write("Debug: selected_team:", selected_team)
st.write("Debug: selected_venue:", selected_venue)
st.write("Debug: roster_data:", st.session_state.roster_data)
st.write("Debug: column_config:", st.session_state["column_config"])

result_df, debug_outputs, team_player_stats, twc_player_stats = main(
    all_data, selected_team, selected_venue, st.session_state.roster_data, st.session_state["column_config"]
)

##############################################
# Section 1.2: Season Selection
##############################################
def parse_seasons(season_str):
    season_str = season_str.replace(" ", "")
    seasons = []
    if "-" in season_str:
        parts = season_str.split("-")
        try:
            start = int(parts[0])
            end = int(parts[1])
            seasons = list(range(start, end + 1))
        except:
            st.error("Invalid season range format. Please enter something like '20-21'.")
    elif "," in season_str:
        parts = season_str.split(",")
        try:
            seasons = [int(p) for p in parts]
        except:
            st.error("Invalid season list format. Please enter something like '14,16,19'.")
    else:
        try:
            seasons = [int(season_str)]
        except:
            st.error("Invalid season format. Please enter a number, e.g. '19'.")
    return seasons

# Use st.text_input with a unique key that changes with season input
season_input = st.text_input(
    "Enter season(s) to process (e.g., '19' or '20-21')", 
    "20-21", 
    key=f"seasons_input_{'-'.join(map(str, st.session_state.get('seasons_to_process', [])))} "
)

# Parse seasons
seasons_to_process = parse_seasons(season_input)

# Check if seasons have changed
if "previous_seasons" not in st.session_state:
    st.session_state.previous_seasons = seasons_to_process

if seasons_to_process != st.session_state.previous_seasons:
    with st.spinner("Reprocessing data for new seasons..."):
        # Update previous seasons
        st.session_state.previous_seasons = seasons_to_process
        
        # Store the new seasons
        st.session_state["seasons_to_process"] = seasons_to_process
        
        # Load and process data
        all_data = load_all_json_files(repo_dir, seasons_to_process)
        result_df, debug_outputs, team_player_stats, twc_player_stats = (
        all_data, selected_team, selected_venue, st.session_state.roster_data, st.session_state["column_config"]
    )
        
        # Update session state
        st.session_state["result_df"] = result_df
        st.session_state["team_player_stats"] = team_player_stats
        st.session_state["twc_player_stats"] = twc_player_stats

        # Create Excel file
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            result_df.to_excel(writer, index=False, sheet_name='Results')
            team_player_stats.to_excel(writer, index=False, sheet_name=f'{selected_team} Players')
            twc_player_stats.to_excel(writer, index=False, sheet_name='TWC Players')
        st.session_state["processed_excel"] = output.getvalue()
        st.session_state["debug_outputs"] = debug_outputs
        st.session_state["kellanate_output"] = True
    
    st.success("Data processed for new seasons!")

##############################################
# Section 2: Repository Management
##############################################

def load_machine_mapping(file_path):
    """Load machine mapping from a JSON file. Return default mapping if file doesn't exist."""
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            st.error(f"Error loading machine mapping: {e}")
            return {}
    else:
        # Default mapping.
        return {
            'pulp': 'pulp fiction',
            'bksor': 'black knight sor'
        }

if "machine_mapping" not in st.session_state:
    st.session_state.machine_mapping = load_machine_mapping("kellanator/machine_mapping.json")

def save_machine_mapping(file_path, mapping):
    """Save the machine mapping to a JSON file."""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, indent=2)
    except Exception as e:
        st.error(f"Error saving machine mapping: {e}")

def update_repo(repo_path):
    """Runs 'git pull' in the specified repository directory."""
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "pull"],
            capture_output=True, text=True, check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"An error occurred: {e.stderr}"

st.title("The Kellanator 9000")

##############################################
# Section 3: Dynamic Teams & Venues from JSON Files (Most Recent Season Only)
##############################################
import glob
import json
import os
import re

def get_latest_season(repo_dir):
    """
    Scans the repository directory for folders named "season-<number>" 
    and returns the highest season number found.
    """
    season_dirs = glob.glob(os.path.join(repo_dir, "season-*"))
    season_numbers = []
    for season_dir in season_dirs:
        match = re.search(r"season-(\d+)", season_dir)
        if match:
            season_numbers.append(int(match.group(1)))
    if season_numbers:
        return max(season_numbers)
    else:
        return None

@st.cache_data(show_spinner=True)
def get_teams_and_venues_from_json(repo_dir):
    """
    Scans through the JSON files for the most recent season and extracts:
      - Venues: from data["venue"]["name"]
      - Teams: from data["away"] and data["home"] (using their "name" and "key")
    Returns:
      - A sorted list of unique venue names.
      - A sorted list of unique team names.
      - A dictionary mapping team names to their abbreviations (keys).
    """
    latest_season = get_latest_season(repo_dir)
    if latest_season is None:
        st.error("No season directories found in the repository.")
        return [], [], {}
    
    venues = set()
    team_abbr_dict = {}
    directory = os.path.join(repo_dir, f"season-{latest_season}", "matches")
    json_files = glob.glob(os.path.join(directory, "**", "*.json"), recursive=True)
    
    for file_path in json_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Extract venue
                venue_name = data.get("venue", {}).get("name", "")
                if venue_name:
                    venues.add(venue_name)
                
                # Extract away team info
                away = data.get("away", {})
                if away:
                    team_name = away.get("name", "")
                    team_key = away.get("key", "")
                    if team_name:
                        team_abbr_dict[team_name] = team_key
                
                # Extract home team info
                home = data.get("home", {})
                if home:
                    team_name = home.get("name", "")
                    team_key = home.get("key", "")
                    if team_name:
                        team_abbr_dict[team_name] = team_key
        except Exception as e:
            st.error(f"Error loading {file_path}: {e}")
    
    # Sort the results alphabetically
    venues_list = sorted(list(venues))
    team_names = sorted(list(team_abbr_dict.keys()))
    return venues_list, team_names, team_abbr_dict

# Retrieve teams and venues from JSON files (most recent season only)
dynamic_venues, dynamic_team_names, team_abbr_dict = get_teams_and_venues_from_json(repo_dir)

# Use these select boxes (only one set)
selected_venue = st.selectbox("Select Venue", dynamic_venues, key="select_venue_json")
selected_team = st.selectbox("Select Team", dynamic_team_names, key="select_team_json")

##############################################
# Section 4: Get Unique Machine List from JSON Data
##############################################
@st.cache_data(show_spinner=True)
def get_all_machines(repo_dir):
    """
    Scans JSON files (seasons 14-21) and returns a sorted list of unique machine names.
    """
    machine_set = set()
    for season in range(14, 22):
        directory = os.path.join(repo_dir, f"season-{season}", "matches")
        json_files = glob.glob(os.path.join(directory, "**", "*.json"), recursive=True)
        for file_path in json_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for round_info in data.get("rounds", []):
                        for game in round_info.get("games", []):
                            machine = game.get("machine", "").strip()
                            if machine:
                                machine_set.add(machine.lower())
            except Exception:
                continue
    return sorted(machine_set)

all_machines_from_data = get_all_machines(repo_dir)

##############################################
# Section 5.1: Toggle and Display Column Options (Persistent)
##############################################
# Initialize persistent column configuration if not already set.
if "column_config" not in st.session_state:
    default_twcs = True if selected_venue.lower() == "georgetown pizza and arcade" else False
    
    # Use min and max of seasons_to_process to create a tuple for seasons
    min_season = min(seasons_to_process) if seasons_to_process else 20
    max_season = max(seasons_to_process) if seasons_to_process else 21
    seasons_tuple = (min_season, max_season)
    
    st.session_state.column_config = {
         'Team Average': {'include': True, 'seasons': seasons_tuple, 'venue_specific': True, 'backfill': False},
         'TWC Average': {'include': True, 'seasons': seasons_tuple, 'venue_specific': default_twcs, 'backfill': False},
         'Venue Average': {'include': True, 'seasons': seasons_tuple, 'venue_specific': True, 'backfill': False},
         'Team Highest Score': {'include': True, 'seasons': seasons_tuple, 'venue_specific': True, 'backfill': False},
         '% of V. Avg.': {'include': True, 'seasons': seasons_tuple, 'venue_specific': True, 'backfill': False},
         'TWC % V. Avg.': {'include': True, 'seasons': seasons_tuple, 'venue_specific': default_twcs, 'backfill': False},
         'Times Played': {'include': True, 'seasons': seasons_tuple, 'venue_specific': True, 'backfill': False},
         'TWC Times Played': {'include': True, 'seasons': seasons_tuple, 'venue_specific': default_twcs, 'backfill': False},
         'Times Picked': {'include': True, 'seasons': seasons_tuple, 'venue_specific': True, 'backfill': False},
         'TWC Times Picked': {'include': True, 'seasons': seasons_tuple, 'venue_specific': default_twcs, 'backfill': False}
    }

# Toggle Column Options display.
if st.button("Hide Column Options" if st.session_state.column_options_open else "Show Column Options", key="toggle_column_options"):
    st.session_state.column_options_open = not st.session_state.column_options_open
    st.rerun()

# When open, display the options and update the persistent config.
if st.session_state.column_options_open:
    st.markdown("#### Column Options")
    current_config = st.session_state.column_config  # Use the saved config
    updated_config = {}
    for col, config in current_config.items():
        col1, col2 = st.columns([0.6, 0.4])
        with col1:
            include_column = st.checkbox(f"{col}", value=config.get("include", True), key=f"inc_{col}")
        with col2:
            venue_spec = st.checkbox("Venue Specific", value=config.get("venue_specific", False), key=f"vs_{col}")
        
        # Use min and max of seasons_to_process to ensure consistency
        min_season = min(seasons_to_process) if seasons_to_process else 20
        max_season = max(seasons_to_process) if seasons_to_process else 21
        seasons_tuple = (min_season, max_season)
        
        updated_config[col] = {
            'include': include_column,
            'seasons': seasons_tuple,  # Always use the global seasons setting
            'venue_specific': venue_spec,
            'backfill': config['backfill']
        }
    # Update the persistent column_config.
    st.session_state.column_config = updated_config


##############################################
# Section 5.2: Toggle and Display Set Machine Score Limits
##############################################
if st.button("Hide Machine Score Limits" if st.session_state.set_score_limit_open else "Set Machine Score Limits", key="toggle_machine_score_limits"):
    st.session_state.set_score_limit_open = not st.session_state.set_score_limit_open
    st.rerun()

if st.session_state.set_score_limit_open:
    st.markdown("#### Set Machine Score Limits")
    st.markdown("##### Add New Score Limit")
    available_machines = [m for m in all_machines_from_data if m not in get_score_limits()]
    new_machine = st.selectbox("Select Machine", options=available_machines, key="score_limit_machine_dropdown")
    new_machine_text = st.text_input("Or type machine name", "", key="score_limit_machine_text")
    machine_to_add = new_machine_text.strip() if new_machine_text.strip() else new_machine

    new_score_str = st.text_input("Enter Score Limit", "", key="score_limit_value")
    if st.button("Add Score Limit", key="add_score_limit_btn"):
        try:
            cleaned = re.sub(r"[^\d,]", "", new_score_str)
            score_limit = int(cleaned.replace(",", "").strip())
            if machine_to_add:
                set_score_limit(machine_to_add, score_limit)
                st.success(f"Score limit for {machine_to_add} set to {score_limit:,}")
                st.rerun()
        except Exception as e:
            st.error("Invalid score input. Please enter a valid number (commas allowed).")

    st.markdown("##### Current Score Limits")
    current_score_limits = get_score_limits()
    for machine, limit in current_score_limits.items():
        col1, col2, col3 = st.columns([0.5, 0.3, 0.2])
        col1.write(machine)
        col2.write(f"{limit:,}")
        if col3.button("🗑️", key=f"del_score_{machine}"):
            delete_score_limit(machine)
            st.rerun()
        new_edit_score = st.text_input(f"Edit {machine} Score Limit", value=f"{limit:,}", key=f"edit_{machine}")
        if st.button("Update", key=f"update_{machine}"):
            try:
                updated_score = int(new_edit_score.replace(",", "").strip())
                set_score_limit(machine, updated_score)
                st.success(f"Updated {machine} score limit to {updated_score:,}")
                st.rerun()
            except Exception as e:
                st.error("Invalid score. Please enter a valid number.")

##############################################
# Section 5.3: Toggle and Display Modify Venue Machine List
##############################################
if st.button("Hide Modify Venue Machine List" if st.session_state.modify_menu_open else "Modify Venue Machine List", key="toggle_modify_venue_machine_list"):
    st.session_state.modify_menu_open = not st.session_state.modify_menu_open
    st.rerun()

if st.session_state.modify_menu_open:
    st.markdown("#### Modify Venue Machine List")
    st.markdown("##### Included Machines")
    included_machines = get_venue_machine_list(selected_venue, "included")
    for machine in included_machines:
        col1, col2 = st.columns([0.8, 0.2])
        col1.write(machine)
        if col2.button("🗑️", key=f"del_inc_{machine}_{selected_venue}"):
            delete_machine_from_venue(selected_venue, "included", machine)
            st.rerun()
    st.markdown("Add machine to **Included**:")
    available_included = [m for m in all_machines_from_data if m not in included_machines]
    add_inc_dropdown = st.selectbox("Select from list", options=available_included, key=f"add_inc_dropdown_{selected_venue}")
    add_inc_text = st.text_input("Or type machine name (must match format)", "", key=f"add_inc_text_{selected_venue}")
    if st.button("Add to Included", key=f"add_inc_btn_{selected_venue}"):
        new_machine = add_inc_text.strip() if add_inc_text.strip() else add_inc_dropdown
        if new_machine:
            add_machine_to_venue(selected_venue, "included", new_machine)
            st.rerun()
        
    st.markdown("##### Excluded Machines")
    excluded_machines = get_venue_machine_list(selected_venue, "excluded")
    for machine in excluded_machines:
        col1, col2 = st.columns([0.8, 0.2])
        col1.write(machine)
        if col2.button("🗑️", key=f"del_exc_{machine}_{selected_venue}"):
            delete_machine_from_venue(selected_venue, "excluded", machine)
            st.rerun()
    st.markdown("Add machine to **Excluded**:")
    available_excluded = [m for m in all_machines_from_data if m not in excluded_machines]
    add_exc_dropdown = st.selectbox("Select from list", options=available_excluded, key=f"add_exc_dropdown_{selected_venue}")
    add_exc_text = st.text_input("Or type machine name (must match format)", "", key=f"add_exc_text_{selected_venue}")
    if st.button("Add to Excluded", key=f"add_exc_btn_{selected_venue}"):
        new_machine = add_exc_text.strip() if add_exc_text.strip() else add_exc_dropdown
        if new_machine:
            add_machine_to_venue(selected_venue, "excluded", new_machine)
            st.rerun()

##############################################
# Section 5.4: Standardize Machines (Add/Edit) - Persistent Across Refreshes
##############################################

MACHINE_MAPPING_FILE = "kellanator/machine_mapping.json"

if "standardize_machines_open" not in st.session_state:
    st.session_state.standardize_machines_open = False

if st.button("Hide Standardize Machines" if st.session_state.standardize_machines_open else "Show Standardize Machines", key="toggle_standardize_machines"):
    st.session_state.standardize_machines_open = not st.session_state.standardize_machines_open
    st.rerun()

if st.session_state.standardize_machines_open:
    st.markdown("### Standardize Machines")
    
    # --- Section for adding a new machine mapping ---
    st.markdown("#### Add New Machine Mapping")
    # Dropdown with all games (from all_machines_from_data) and a text field for manual entry.
    new_alias_dropdown = st.selectbox("Select a machine alias from existing games", all_machines_from_data, key="new_alias_dropdown")
    new_alias_manual = st.text_input("Or type a new machine alias", "", key="new_alias_text")
    # Use manual input if provided; otherwise, use dropdown.
    alias_to_add = new_alias_manual.strip() if new_alias_manual.strip() else new_alias_dropdown
    # Text input for the standardized name, defaulting to the alias.
    new_standardized = st.text_input("Enter standardized name for this machine", alias_to_add, key="new_standardized")
    
    if st.button("Add Machine Mapping", key="add_machine_mapping"):
        if alias_to_add:
            # Update the mapping
            mapping = st.session_state.machine_mapping
            mapping[alias_to_add] = new_standardized.strip() if new_standardized.strip() else alias_to_add.lower()
            st.session_state.machine_mapping = mapping
            
            # Use the robust save method
            save_machine_mapping_strategy(mapping)
            
            st.success(f"Added mapping: {alias_to_add} -> {st.session_state.machine_mapping[alias_to_add]}")
            st.rerun()

    # --- Section for displaying current mappings with edit/delete options ---
    st.markdown("#### Current Machine Mappings")
    mapping = st.session_state.machine_mapping
    # Use a copy to safely iterate while modifying.
    for alias, std_val in mapping.copy().items():
        col1, col2, col3, col4 = st.columns([0.3, 0.3, 0.2, 0.2])
        with col1:
            st.write(f"Alias: {alias}")
        with col2:
            st.write(f"Standardized: {std_val}")
        with col3:
            # Edit: show a text input and an "Update" button.
            new_val = st.text_input("New Standardized Name", std_val, key=f"edit_input_{alias}")
            if st.button("Update", key=f"update_{alias}"):
                mapping[alias] = new_val.strip() if new_val.strip() else alias.lower()
                st.session_state.machine_mapping = mapping
                save_machine_mapping(None, mapping)  # Use helper function
                st.success(f"Updated mapping for {alias}")
                st.rerun()
        with col4:
            if st.button("Delete", key=f"delete_{alias}"):
                mapping.pop(alias)
                st.session_state.machine_mapping = mapping
                save_machine_mapping(None, mapping)  # Use helper function
                st.success(f"Deleted mapping for {alias}")
                st.rerun()

##############################################
# Section 5.5: Edit Rosters (Players Cannot Be Deleted; Original Roster Uneditable)
##############################################

# Helper function: Get available players for the team from already loaded all_data.
def get_available_players_for_team(team, all_data):
    players_set = set()
    for match in all_data:
        # Check home team.
        if match.get('home', {}).get('name', "").strip().lower() == team.strip().lower():
            for player in match.get('home', {}).get('lineup', []):
                players_set.add(player.get("name", "").strip())
        # Check away team.
        if match.get('away', {}).get('name', "").strip().lower() == team.strip().lower():
            for player in match.get('away', {}).get('lineup', []):
                players_set.add(player.get("name", "").strip())
    return sorted(players_set)

# Ensure that all_data is loaded in session state.
if "all_data" not in st.session_state:
    st.session_state.all_data = load_all_json_files(repo_dir, seasons_to_process)

# Toggle the Edit Roster section.
if st.button("Hide Edit Roster" if st.session_state.get("edit_roster_open", False) else "Edit Roster", key="toggle_edit_roster"):
    st.session_state.edit_roster_open = not st.session_state.get("edit_roster_open", False)
    st.rerun()

if st.session_state.get("edit_roster_open", False):
    st.markdown("### Edit Roster")
    # Determine the team abbreviation for the selected team.
    team_abbr = team_abbr_dict.get(selected_team)
    if not team_abbr:
        st.error("No team abbreviation found for the selected team.")
    else:
        # Initialize a persistent edited roster for the team if not already set.
        # Original CSV players are stored as non-editable.
        if f"edited_roster_{team_abbr}" not in st.session_state:
            original_roster = st.session_state.roster_data.get(team_abbr, [])
            st.session_state[f"edited_roster_{team_abbr}"] = [
                {"name": p, "include": True, "editable": False} for p in original_roster
            ]
        edited_roster = st.session_state[f"edited_roster_{team_abbr}"]
        
        st.markdown(f"**Current Roster for {selected_team} ({team_abbr}):**")
        # Display each roster entry.
        for i, entry in enumerate(edited_roster.copy()):
            player = entry["name"]
            included = entry["include"]
            editable = entry.get("editable", False)
            col1, col2, col3 = st.columns([0.6, 0.2, 0.2])
            with col1:
                st.write(player)
            with col2:
                # Checkbox to toggle inclusion (unchecking excludes the player but does not remove it).
                new_included = st.checkbox("", value=included, key=f"include_{team_abbr}_{i}")
                if new_included != included:
                    edited_roster[i]["include"] = new_included
                    st.session_state[f"edited_roster_{team_abbr}"] = edited_roster
                    # Update global roster_data: include only players that are checked.
                    st.session_state.roster_data[team_abbr] = [e["name"] for e in edited_roster if e["include"]]
                    st.rerun()
            with col3:
                # Show an Edit button only if the entry is editable.
                if editable:
                    if st.button("Edit", key=f"edit_roster_{team_abbr}_{i}"):
                        new_name = st.text_input("New name", player, key=f"edit_input_roster_{team_abbr}_{i}")
                        if new_name:
                            edited_roster[i]["name"] = new_name.strip()
                            st.session_state[f"edited_roster_{team_abbr}"] = edited_roster
                            st.session_state.roster_data[team_abbr] = [e["name"] for e in edited_roster if e["include"]]
                            st.rerun()
        
        # Compute available players for the selected team from all_data.
        available_players = get_available_players_for_team(selected_team, st.session_state.all_data)
        # Exclude those already in the roster.
        existing_players = set(e["name"] for e in edited_roster)
        available_players = sorted(set(available_players) - existing_players)
        if not available_players:
            available_players = ["No available players"]
        
        st.markdown("#### Add Player to Roster")
        new_player_dropdown = st.selectbox("Select a player", available_players, key="new_player_dropdown")
        new_player_manual = st.text_input("Or type a new player's name", "", key="new_player_manual")
        # Manual input takes precedence.
        if new_player_manual.strip():
            player_to_add = new_player_manual.strip()
        else:
            player_to_add = new_player_dropdown if new_player_dropdown != "No available players" else ""
        
        if st.button("Add Player", key="add_player_btn"):
            if player_to_add:
                if player_to_add not in [e["name"] for e in edited_roster]:
                    # New players are marked as editable.
                    edited_roster.append({"name": player_to_add, "include": True, "editable": True})
                    st.session_state[f"edited_roster_{team_abbr}"] = edited_roster
                    st.session_state.roster_data[team_abbr] = [e["name"] for e in edited_roster if e["include"]]
                    st.success(f"Added {player_to_add} to the roster.")
                    st.rerun()
                else:
                    st.warning(f"{player_to_add} is already in the roster.")
            else:
                st.warning("Please enter a player's name.")

# Toggle the Edit TWC Roster section
if st.button("Hide Edit TWC Roster" if st.session_state.get("edit_twc_roster_open", False) else "Edit TWC Roster", key="toggle_edit_twc_roster"):
    st.session_state.edit_twc_roster_open = not st.session_state.get("edit_twc_roster_open", False)
    st.rerun()

if st.session_state.get("edit_twc_roster_open", False):
    st.markdown("### Edit TWC Roster")
    
    # Determine the TWC team abbreviation
    twc_team_name = "The Wrecking Crew"
    twc_abbr = "TWC"
    
    if not twc_abbr:
        st.error("No team abbreviation found for The Wrecking Crew.")
    else:
        # Initialize a persistent edited roster for TWC if not already set
        if f"edited_roster_{twc_abbr}" not in st.session_state:
            original_roster = st.session_state.roster_data.get(twc_abbr, [])
            st.session_state[f"edited_roster_{twc_abbr}"] = [
                {"name": p, "include": True, "editable": False} for p in original_roster
            ]
        edited_roster = st.session_state[f"edited_roster_{twc_abbr}"]
        
        st.markdown(f"**Current TWC Roster:**")
        # Display each roster entry
        for i, entry in enumerate(edited_roster.copy()):
            player = entry["name"]
            included = entry["include"]
            editable = entry.get("editable", False)
            col1, col2, col3 = st.columns([0.6, 0.2, 0.2])
            with col1:
                st.write(player)
            with col2:
                # Checkbox to toggle inclusion
                new_included = st.checkbox("", value=included, key=f"include_twc_{twc_abbr}_{i}")
                if new_included != included:
                    edited_roster[i]["include"] = new_included
                    st.session_state[f"edited_roster_{twc_abbr}"] = edited_roster
                    # Update global roster_data: include only players that are checked
                    st.session_state.roster_data[twc_abbr] = [e["name"] for e in edited_roster if e["include"]]
                    st.rerun()
            with col3:
                # Show an Edit button only if the entry is editable
                if editable:
                    if st.button("Edit", key=f"edit_twc_roster_{twc_abbr}_{i}"):
                        new_name = st.text_input("New name", player, key=f"edit_input_twc_roster_{twc_abbr}_{i}")
                        if new_name:
                            edited_roster[i]["name"] = new_name.strip()
                            st.session_state[f"edited_roster_{twc_abbr}"] = edited_roster
                            st.session_state.roster_data[twc_abbr] = [e["name"] for e in edited_roster if e["include"]]
                            st.rerun()
        
        # Get players from JSON data for TWC
        available_players = set()
        for match in st.session_state.all_data:
            if match.get('home', {}).get('name', "").strip().lower() == twc_team_name.strip().lower():
                for player in match.get('home', {}).get('lineup', []):
                    available_players.add(player.get("name", "").strip())
            if match.get('away', {}).get('name', "").strip().lower() == twc_team_name.strip().lower():
                for player in match.get('away', {}).get('lineup', []):
                    available_players.add(player.get("name", "").strip())
        
        # Exclude those already in the roster
        existing_players = set(e["name"] for e in edited_roster)
        available_players = sorted(available_players - existing_players)
        
        if not available_players:
            available_players = ["No available players"]
        
        st.markdown("#### Add Player to TWC Roster")
        new_player_dropdown = st.selectbox("Select a player", available_players, key="new_twc_player_dropdown")
        new_player_manual = st.text_input("Or type a new player's name", "", key="new_twc_player_manual")
        
        # Manual input takes precedence
        if new_player_manual.strip():
            player_to_add = new_player_manual.strip()
        else:
            player_to_add = new_player_dropdown if new_player_dropdown != "No available players" else ""
        
        if st.button("Add Player", key="add_twc_player_btn"):
            if player_to_add:
                if player_to_add not in [e["name"] for e in edited_roster]:
                    # New players are marked as editable
                    edited_roster.append({"name": player_to_add, "include": True, "editable": True})
                    st.session_state[f"edited_roster_{twc_abbr}"] = edited_roster
                    st.session_state.roster_data[twc_abbr] = [e["name"] for e in edited_roster if e["include"]]
                    st.success(f"Added {player_to_add} to the TWC roster.")
                    st.rerun()
                else:
                    st.warning(f"{player_to_add} is already in the roster.")
            else:
                st.warning("Please enter a player's name.")


##############################################
# Section 6: Load Team Rosters from CSV Files
##############################################
@st.cache_data(show_spinner=True)
def load_team_rosters_from_csv(repo_dir):
    """
    Loads the team rosters from the rosters.csv file in the most recent season folder.
    The CSV is expected to have lines formatted as:
      Player Name,TeamAbbr,Letter
    The third field is ignored.
    
    Returns a dictionary mapping team abbreviations to a list of player names.
    """
    latest_season = get_latest_season(repo_dir)
    if latest_season is None:
        st.error("No season directories found in the repository.")
        return {}
    
    csv_path = os.path.join(repo_dir, f"season-{latest_season}", "rosters.csv")
    roster_data = {}
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # Split by comma; expect at least two parts: name and team abbreviation.
                parts = line.split(',')
                if len(parts) < 2:
                    continue
                player_name = parts[0].strip()
                team_abbr = parts[1].strip()
                # Add player_name under the team abbreviation key.
                if team_abbr not in roster_data:
                    roster_data[team_abbr] = []
                roster_data[team_abbr].append(player_name)
    except Exception as e:
        st.error(f"Error reading rosters CSV: {e}")
    return roster_data

# Load roster data if not already loaded.
if not st.session_state.rosters_scraped:
    st.session_state.roster_data = load_team_rosters_from_csv(repo_dir)
    st.session_state.rosters_scraped = True


##############################################
# Section 9: Processing Functions
##############################################
def standardize_machine_name(machine_name):
    """
    Standardize machine names using the most up-to-date mapping.
    """
    # Get the current machine mapping from session state
    machine_mapping = st.session_state.machine_mapping
    
    # Convert to lowercase for case-insensitive matching
    machine_lower = machine_name.lower().strip()
    
    # First check the exact mapping
    if machine_lower in machine_mapping:
        return machine_mapping[machine_lower]
    
    # If no exact match, check if the machine is already the standardized name
    for alias, standard_name in machine_mapping.items():
        if machine_lower == standard_name.lower():
            return standard_name
    
    # If no mapping found, return the original name (lowercase)
    return machine_lower

def get_player_name(player_key, match):
    for team in ['home', 'away']:
        for player in match[team]['lineup']:
            if player['key'] == player_key:
                return player['name']
    return player_key

def is_roster_player(player_name, team, team_roster):
    """
    Determines if the given player_name is on the roster for the team.
    Since the CSV-based rosters are keyed by team abbreviation, we first
    convert the full team name (as used in the match data) to its abbreviation
    using the global team_abbr_dict. If roster data is missing, returns False.
    """
    if team_roster is None:
        return False
    # Convert full team name to abbreviation using team_abbr_dict.
    abbr = team_abbr_dict.get(team)
    if not abbr:
        return False
    return player_name in team_roster.get(abbr, [])

def process_all_rounds_and_games(all_data, team_name, venue_name, twc_team_name, team_roster, included_machines_for_venue, excluded_machines_for_venue):
    processed_data = []
    recent_machines = set(included_machines_for_venue or [])
    overall_latest_season = max(int(match['key'].split('-')[1]) for match in all_data)
    current_limits = get_score_limits()  # Use user-defined score limits from the database

    for match in all_data:
        match_venue = match['venue']['name']
        season = int(match['key'].split('-')[1])
        home_team = match['home']['name']
        away_team = match['away']['name']

        # Determine the selected team's role based on the match.
        if team_name == home_team:
            selected_team_role = "home"
        elif team_name == away_team:
            selected_team_role = "away"
        else:
            # Fallback if team_name does not match either team (should not happen)
            selected_team_role = "away"

        # TWC's role is the opposite of the selected team.
        twc_role = "home" if selected_team_role == "away" else "away"

        # Define pick rounds based on role:
        # Away picks in rounds 1 and 3; Home picks in rounds 2 and 4.
        selected_team_pick_rounds = [1, 3] if selected_team_role == "away" else [2, 4]
        twc_pick_rounds = [1, 3] if twc_role == "away" else [2, 4]

        for round_info in match['rounds']:
            round_number = round_info['n']
            
            # Determine who picks machines in this round
            is_selected_team_pick_round = round_number in selected_team_pick_rounds
            is_twc_pick_round = round_number in twc_pick_rounds
            
            # We'll track machines in this round to ensure we count each unique machine exactly once
            machines_in_round = set()
            
            # Process all games in the round
            for game in round_info['games']:
                machine = standardize_machine_name(game.get('machine', '').lower())
                if not machine:
                    continue

                # Add to recent machines list if appropriate
                if season == overall_latest_season and match_venue == venue_name:
                    if not excluded_machines_for_venue or machine not in excluded_machines_for_venue:
                        recent_machines.add(machine)

                # Only count each machine once per round for pick statistics
                is_team_pick = is_selected_team_pick_round and machine not in machines_in_round
                is_twc_pick = is_twc_pick_round and machine not in machines_in_round
                
                # Add the machine to our tracking set
                machines_in_round.add(machine)

                for pos in ['1', '2', '3', '4']:
                    player_key = game.get(f'player_{pos}')
                    score = game.get(f'score_{pos}', 0)
                    if score == 0:
                        continue
                    limit = current_limits.get(machine)
                    if limit is not None and score > limit:
                        continue
                    player_name = get_player_name(player_key, match)
                    player_team = home_team if any(player['key'] == player_key for player in match['home']['lineup']) else away_team
                    processed_data.append({
                        'season': season,
                        'machine': machine,
                        'player_name': player_name,
                        'score': score,
                        'team': player_team,
                        'match': match['key'],
                        'round': round_number,
                        'game_number': game['n'],
                        'venue': match_venue,
                        # This "picked_by" res for reference – it reflects the team that was designated to pick for that round.
                        'picked_by': away_team if round_number in [1, 3] else home_team,
                        'is_pick': is_team_pick,
                        'is_pick_twc': is_twc_pick,
                        'is_roster_player': is_roster_player(player_name, player_team, team_roster)
                    })
    return pd.DataFrame(processed_data), recent_machines

def filter_data(df, team=None, seasons=None, venue=None, roster_only=False):
    filtered = df.copy()
    if team:
        # Perform a case-insensitive comparison after stripping extra whitespace
        filtered = filtered[filtered['team'].str.strip().str.lower() == team.strip().lower()]
        if roster_only:
            filtered = filtered[filtered['is_roster_player']]
    if seasons:
        filtered = filtered[filtered['season'].between(seasons[0], seasons[1])]
    if venue:
        # You can also do similar normalization for venue if needed
        filtered = filtered[filtered['venue'].str.strip() == venue.strip()]
    return filtered

def backfill_stat(df, machine, team, seasons, venue_specific, stat_type, pick_flag='is_pick'):
    for season in range(seasons[0]-1, 0, -1):
        backfill_df = filter_data(df, team, (season, season), venue if venue_specific else None)
        stats = calculate_stats(backfill_df, machine, pick_flag)
        if stat_type in stats and stats[stat_type] > 0:
            return stats[stat_type], season
    return np.nan, None

def format_value(value, backfilled_season=None):
    if isinstance(value, (int, float)):
        formatted = f"{value:,.0f}"
    elif isinstance(value, str):
        formatted = value
    else:
        formatted = "N/A"
    if backfilled_season is not None:
        formatted += f"*S{backfilled_season}"
    return formatted

def calculate_stat_for_column(df, machine, column, team_name, twc_team_name, venue_name, column_config):
    """
    Calculate statistics for a specific column and machine.
    Each column type has its own dedicated calculation logic.
    """
    config = column_config.get(column, {})
    seasons = config.get('seasons', (1, 9999))
    venue_specific = config.get('venue_specific', False)
    
    # Handle each column type with its own specific logic
    if column == "Team Average":
        # Filter data for the selected team, roster players only
        filtered_df = filter_data(df, team_name, seasons, venue_name if venue_specific else None, roster_only=True)
        # Get scores for this machine
        machine_data = filtered_df[filtered_df['machine'] == machine]
        if len(machine_data) == 0:
            return "N/A"
        # Calculate average score
        average = np.mean(machine_data['score'].tolist())
        return f"{average:,.2f}"
        
    elif column == "TWC Average":
        # Filter data for TWC, roster players only
        filtered_df = filter_data(df, twc_team_name, seasons, venue_name if venue_specific else None, roster_only=True)
        # Get scores for this machine
        machine_data = filtered_df[filtered_df['machine'] == machine]
        if len(machine_data) == 0:
            return "N/A"
        # Calculate average score
        average = np.mean(machine_data['score'].tolist())
        return f"{average:,.2f}"
        
    elif column == "Venue Average":
        # Filter by venue and seasons only (all teams)
        filtered_df = filter_data(df, None, seasons, venue_name)
        # Get scores for this machine
        machine_data = filtered_df[filtered_df['machine'] == machine]
        if len(machine_data) == 0:
            return "N/A"
        # Calculate average score
        average = np.mean(machine_data['score'].tolist())
        return f"{average:,.2f}"
        
    elif column == "Team Highest Score":
        # Filter data for the selected team, roster players only
        filtered_df = filter_data(df, team_name, seasons, venue_name if venue_specific else None, roster_only=True)
        # Get scores for this machine
        machine_data = filtered_df[filtered_df['machine'] == machine]
        if len(machine_data) == 0:
            return "N/A"
        # Get highest score
        highest = max(machine_data['score'].tolist())
        return f"{highest:,}"
        
    elif column == "Times Played":
        # Filter data for the selected team
        filtered_df = filter_data(df, team_name, seasons, venue_name if venue_specific else None, roster_only=True)
        # Get data for this machine
        machine_data = filtered_df[filtered_df['machine'] == machine]
        if len(machine_data) == 0:
            return "N/A"
        # Count unique games (match + round combinations)
        unique_games = machine_data.groupby(['match', 'round']).first().reset_index()
        times_played = len(unique_games)
        return f"{times_played:,}"
        
    elif column == "TWC Times Played":
        # Filter data for TWC
        filtered_df = filter_data(df, twc_team_name, seasons, venue_name if venue_specific else None, roster_only=True)
        # Get data for this machine
        machine_data = filtered_df[filtered_df['machine'] == machine]
        if len(machine_data) == 0:
            return "N/A"
        # Count unique games
        unique_games = machine_data.groupby(['match', 'round']).first().reset_index()
        times_played = len(unique_games)
        return f"{times_played:,}"
        
    elif column == "Times Picked":
        # Filter data for the selected team
        filtered_df = filter_data(df, team_name, seasons, venue_name if venue_specific else None, roster_only=True)
        # Get data for this machine
        machine_data = filtered_df[filtered_df['machine'] == machine]
        if len(machine_data) == 0:
            return "N/A"
        # Get unique games first
        unique_games = machine_data.groupby(['match', 'round']).first().reset_index()
        # Then filter for games where this team picked
        times_picked = len(unique_games[unique_games['is_pick'] == True])
        return f"{times_picked:,}"
        
    elif column == "TWC Times Picked":
        # Filter data for TWC
        filtered_df = filter_data(df, twc_team_name, seasons, venue_name if venue_specific else None, roster_only=True)
        # Get data for this machine
        machine_data = filtered_df[filtered_df['machine'] == machine]
        if len(machine_data) == 0:
            return "N/A"
        # Get unique games first
        unique_games = machine_data.groupby(['match', 'round']).first().reset_index()
        # Then filter for games where TWC picked
        times_picked = len(unique_games[unique_games['is_pick_twc'] == True])
        return f"{times_picked:,}"
        
    # Handle percentage columns directly
    elif column == "% of V. Avg.":
        # These values should be calculated after all the averages are computed
        return "Calculated later"
        
    elif column == "TWC % V. Avg.":
        # These values should be calculated after all the averages are computed
        return "Calculated later"
        
    # Default case
    return "N/A"

def calculate_averages(df, recent_machines, team_name, twc_team_name, venue_name, column_config):
    """
    Build the final result DataFrame with separate calculation logic for each column type.
    """
    data = []
    for machine in sorted(recent_machines):
        row = {'Machine': machine.title()}
        
        # Calculate each column individually
        for column, config in column_config.items():
            if not config.get('include', True):
                continue
                
            # Use dedicated calculation logic for each column
            row[column] = calculate_stat_for_column(
                df, machine, column, team_name, twc_team_name, venue_name, column_config
            )
        
        # Calculate percentage columns after all averages are computed
        def safe_get(key):
            v = row.get(key, "N/A")
            try:
                return float(v.replace(",", "").split("*")[0])
            except Exception:
                return np.nan
                
        team_avg = safe_get("Team Average")
        twc_avg = safe_get("TWC Average")
        venue_avg = safe_get("Venue Average")
        
        row["% of V. Avg."] = f"{(team_avg / venue_avg * 100):.2f}%" if not np.isnan(team_avg) and not np.isnan(venue_avg) and venue_avg != 0 else "N/A"
        row["TWC % V. Avg."] = f"{(twc_avg / venue_avg * 100):.2f}%" if not np.isnan(twc_avg) and not np.isnan(venue_avg) and venue_avg != 0 else "N/A"
        
        data.append(row)
        
    return pd.DataFrame(data)

def generate_debug_outputs(df, team_name, twc_team_name, venue_name):
    seasons = st.session_state.get("seasons_to_process", [20, 21])
    season_tuple = (min(seasons), max(seasons))
    debug_outputs = {
        'all_data': df,
        'filtered_data_by_team': filter_data(df, team_name),
        'filtered_data_by_team_and_seasons': filter_data(df, team_name, season_tuple),
        'filtered_data_by_team_seasons_and_venue': filter_data(df, team_name, season_tuple, venue_name),
        'filtered_data_by_twc': filter_data(df, twc_team_name),
        'filtered_data_by_twc_and_seasons': filter_data(df, twc_team_name, season_tuple),
        'filtered_data_by_twc_seasons_and_venue': filter_data(df, twc_team_name, season_tuple, venue_name),
    }
    return debug_outputs


def generate_player_stats_tables(df, team_name, venue_name, seasons_to_process, roster_data):
    """
    Generate player statistics tables for the selected team and TWC at the selected venue.
    
    Parameters:
    df (DataFrame): Processed data from process_all_rounds_and_games
    team_name (str): Name of the selected team
    venue_name (str): Name of the selected venue
    seasons_to_process (list): List of seasons to include
    roster_data (dict): Dictionary mapping team abbreviations to roster player lists
    
    Returns:
    tuple: (team_table, twc_table) - DataFrames for the selected team and TWC
    """
    # Use the is_roster_player flag that's already in the data
    # That flag should have been set correctly during processing
    
    # Function to process team data
    def process_team_data(df, team_name, venue_name):
        # Filter for this team and venue
        team_data = df[(df['team'] == team_name) & (df['venue'] == venue_name)]
        team_data = team_data[team_data['season'].isin(seasons_to_process)]
        
        # Get all machines played by this team at this venue
        machines = team_data['machine'].unique()
        
        player_machine_stats = {}
        for machine in machines:
            machine_data = team_data[team_data['machine'] == machine]
            
            # Group players by roster status
            roster_players = []
            substitutes = []
            
            # Get unique players
            for player in machine_data['player_name'].unique():
                # Check if this player is flagged as a roster player
                is_roster = machine_data[machine_data['player_name'] == player]['is_roster_player'].any()
                if is_roster:
                    roster_players.append(player)
                else:
                    substitutes.append(player)
            
            player_machine_stats[machine] = {
                'Roster Players Count': len(roster_players),
                'Roster Players': ', '.join(sorted(roster_players)),
                'Number of Substitutes': len(substitutes),
                'Substitutes': ', '.join(sorted(substitutes))
            }
        
        # Convert to DataFrame and sort by roster player count in descending order
        result_df = pd.DataFrame.from_dict(player_machine_stats, orient='index')
        if not result_df.empty:
            result_df = result_df.sort_values(by='Roster Players Count', ascending=False)
        result_df.index.name = 'Machine'
        result_df.reset_index(inplace=True)
        
        return result_df
    
    # Generate tables for both teams
    team_table = process_team_data(df, team_name, venue_name)
    twc_table = process_team_data(df, "The Wrecking Crew", venue_name)
    
    return team_table, twc_table

def main(all_data, selected_team, selected_venue, team_roster, column_config):
    try:
        # Get seasons from session state explicitly
        current_seasons = st.session_state.get("seasons_to_process", [20, 21])
        
        team_name = selected_team
        twc_team_name = "The Wrecking Crew"
        # Refresh the included and excluded machine lists from your persistent store.
        included_list = get_venue_machine_list(selected_venue, "included")
        excluded_list = get_venue_machine_list(selected_venue, "excluded")
        
        all_data_df, recent_machines = process_all_rounds_and_games(
            all_data, team_name, selected_venue, twc_team_name, team_roster,
            included_list, excluded_list
        )
        debug_outputs = generate_debug_outputs(all_data_df, team_name, twc_team_name, selected_venue)
        result_df = calculate_averages(all_data_df, recent_machines, team_name, twc_team_name, selected_venue, column_config)
        result_df = result_df.sort_values('% of V. Avg.', ascending=False, na_position='last')
        
        # Generate player statistics tables
        team_player_stats, twc_player_stats = generate_player_stats_tables(
            all_data_df, team_name, selected_venue, current_seasons, team_roster
        )
        
        return result_df, debug_outputs, team_player_stats, twc_player_stats
    
    except Exception as e:
        print(f"Error in main function: {e}")
        raise

def get_detailed_data_for_column(all_data_df, machine, column, team_name, twc_team_name, venue_name, column_config, current_seasons):
    """
    Returns detailed data for a specific column and machine.
    Each column type has its own dedicated filtering logic to ensure consistency.
    
    Parameters:
    - current_seasons: The current seasons_to_process list from the user input
    
    Returns:
    - filtered: DataFrame with the filtered data
    - details: Dictionary with summary and title information
    """
    config = column_config.get(column, {})
    venue_specific = config.get('venue_specific', False)
    
    # Create a seasons tuple from the current seasons list
    if current_seasons:
        seasons = (min(current_seasons), max(current_seasons))
    else:
        # Fallback to config or default
        seasons = config.get('seasons', (1, 9999))
    
    # Convert input strings to lowercase for case-insensitive comparison
    machine_lower = machine.lower() if isinstance(machine, str) else ""
    team_name_lower = team_name.lower().strip() if isinstance(team_name, str) else ""
    twc_team_name_lower = twc_team_name.lower().strip() if isinstance(twc_team_name, str) else ""
    venue_name_strip = venue_name.strip() if isinstance(venue_name, str) else ""
    
    # Initial filter for the machine (always applied)
    filtered = all_data_df[all_data_df["machine"].str.lower() == machine_lower]
    
    # Apply column-specific filters
    if column == "Team Average":
        # Filter data for the selected team, roster players only
        filtered = filtered[filtered["team"].str.strip().str.lower() == team_name_lower]
        filtered = filtered[filtered["is_roster_player"] == True]
        filtered = filtered[filtered["season"].between(seasons[0], seasons[1])]
        if venue_specific:
            filtered = filtered[filtered["venue"].str.strip() == venue_name_strip]
            
    elif column == "TWC Average":
        # Filter data for TWC, roster players only
        filtered = filtered[filtered["team"].str.strip().str.lower() == twc_team_name_lower]
        filtered = filtered[filtered["is_roster_player"] == True]
        filtered = filtered[filtered["season"].between(seasons[0], seasons[1])]
        if venue_specific:
            filtered = filtered[filtered["venue"].str.strip() == venue_name_strip]
            
    elif column == "Venue Average":
        # No team filtering, just venue and seasons
        filtered = filtered[filtered["season"].between(seasons[0], seasons[1])]
        filtered = filtered[filtered["venue"].str.strip() == venue_name_strip]
            
    elif column == "Team Highest Score":
        # Filter data for the selected team, roster players only
        filtered = filtered[filtered["team"].str.strip().str.lower() == team_name_lower]
        filtered = filtered[filtered["is_roster_player"] == True]
        filtered = filtered[filtered["season"].between(seasons[0], seasons[1])]
        if venue_specific:
            filtered = filtered[filtered["venue"].str.strip() == venue_name_strip]
            
    elif column == "Times Played":
        # Filter data for the selected team
        filtered = filtered[filtered["team"].str.strip().str.lower() == team_name_lower]
        filtered = filtered[filtered["is_roster_player"] == True]
        filtered = filtered[filtered["season"].between(seasons[0], seasons[1])]
        if venue_specific:
            filtered = filtered[filtered["venue"].str.strip() == venue_name_strip]
        
        # Get unique games via groupby to match the count
        unique_games = filtered.groupby(['match', 'round']).first().reset_index()
        num_unique_games = len(unique_games)
            
    elif column == "TWC Times Played":
        # Filter data for TWC
        filtered = filtered[filtered["team"].str.strip().str.lower() == twc_team_name_lower]
        filtered = filtered[filtered["is_roster_player"] == True]
        filtered = filtered[filtered["season"].between(seasons[0], seasons[1])]
        if venue_specific:
            filtered = filtered[filtered["venue"].str.strip() == venue_name_strip]
            
        # Get unique games via groupby to match the count
        unique_games = filtered.groupby(['match', 'round']).first().reset_index()
        num_unique_games = len(unique_games)
            
    elif column == "Times Picked":
        # Filter data for the selected team
        filtered = filtered[filtered["team"].str.strip().str.lower() == team_name_lower]
        filtered = filtered[filtered["is_roster_player"] == True]
        filtered = filtered[filtered["season"].between(seasons[0], seasons[1])]
        if venue_specific:
            filtered = filtered[filtered["venue"].str.strip() == venue_name_strip]
            
        # First, identify the unique match+round combinations that were picked
        unique_games = filtered.groupby(['match', 'round']).first().reset_index()
        picked_games = unique_games[unique_games["is_pick"] == True]
        num_picked_games = len(picked_games)
        
        # Create a list of (match, round) tuples that were picked
        picked_tuples = list(zip(picked_games['match'], picked_games['round']))
        
        # Filter to include only the team's scores from these match+round combinations
        filtered = filtered[filtered.apply(lambda row: (row['match'], row['round']) in picked_tuples, axis=1)]
        
        # Add a Pick Group column for clarity
        filtered['Pick Group'] = filtered.apply(
            lambda row: f"S{row['season']} - {row['match']} - R{row['round']}", axis=1
        )
            
    elif column == "TWC Times Picked":
        # Filter data for TWC
        filtered = filtered[filtered["team"].str.strip().str.lower() == twc_team_name_lower]
        filtered = filtered[filtered["is_roster_player"] == True]
        filtered = filtered[filtered["season"].between(seasons[0], seasons[1])]
        if venue_specific:
            filtered = filtered[filtered["venue"].str.strip() == venue_name_strip]
            
        # First, identify the unique match+round combinations that were picked
        unique_games = filtered.groupby(['match', 'round']).first().reset_index()
        picked_games = unique_games[unique_games["is_pick_twc"] == True]
        num_picked_games = len(picked_games)
        
        # Create a list of (match, round) tuples that were picked
        picked_tuples = list(zip(picked_games['match'], picked_games['round']))
        
        # Filter to include only TWC's scores from these match+round combinations
        filtered = filtered[filtered.apply(lambda row: (row['match'], row['round']) in picked_tuples, axis=1)]
        
        # Add a Pick Group column for clarity
        filtered['Pick Group'] = filtered.apply(
            lambda row: f"S{row['season']} - {row['match']} - R{row['round']}", axis=1
        )
            
    elif column == "% of V. Avg.":
        # Show the data that was used for Team Average
        filtered = filtered[filtered["team"].str.strip().str.lower() == team_name_lower]
        filtered = filtered[filtered["is_roster_player"] == True]
        filtered = filtered[filtered["season"].between(seasons[0], seasons[1])]
        if venue_specific:
            filtered = filtered[filtered["venue"].str.strip() == venue_name_strip]
            
    elif column == "TWC % V. Avg.":
        # Show the data that was used for TWC Average
        filtered = filtered[filtered["team"].str.strip().str.lower() == twc_team_name_lower]
        filtered = filtered[filtered["is_roster_player"] == True]
        filtered = filtered[filtered["season"].between(seasons[0], seasons[1])]
        if venue_specific:
            filtered = filtered[filtered["venue"].str.strip() == venue_name_strip]
    
    # Make sure score is numeric for proper sorting
    if "score" in filtered.columns:
        filtered['score'] = pd.to_numeric(filtered['score'], errors='coerce')
        
    # Sort appropriately based on column type
    if "Times Picked" in column and "Pick Group" in filtered.columns:
        # For picked games, sort first by Pick Group, then by score (descending)
        filtered = filtered.sort_values(by=["Pick Group", "score"], ascending=[True, False])
    else:
        # For other columns, just sort by score descending
        filtered = filtered.sort_values(by="score", ascending=False)
    
    # Create a summary based on the column type
    if "Average" in column:
        avg_score = filtered["score"].mean() if not filtered.empty else 0
        num_scores = len(filtered)
        summary = f"{column}: {avg_score:,.2f} (based on {num_scores} scores)"
    elif column == "Times Played":
        # Use the calculated unique games count
        summary = f"{column}: {num_unique_games:,} (showing {len(filtered):,} scores)"
    elif column == "TWC Times Played":
        # Use the calculated unique games count
        summary = f"{column}: {num_unique_games:,} (showing {len(filtered):,} scores)"
    elif column == "Times Picked":
        # Use the calculated unique games count
        if "Pick Group" in filtered.columns:
            summary = f"{column}: {num_picked_games:,} (showing {len(filtered):,} {team_name} scores)"
        else:
            summary = f"{column}: (no picked games found)"
    elif column == "TWC Times Picked":
        # Use the calculated unique games count
        if "Pick Group" in filtered.columns:
            summary = f"{column}: {num_picked_games:,} (showing {len(filtered):,} TWC scores)"
        else:
            summary = f"{column}: (no picked games found)"
    elif "%" in column:
        # For percentage columns, reference the related average columns
        base_col = "Team Average" if column == "% of V. Avg." else "TWC Average"
        avg_score = filtered["score"].mean() if not filtered.empty else 0
        num_scores = len(filtered)
        summary = f"{column} (based on {base_col}): {avg_score:,.2f} (from {num_scores} scores)"
    else:
        summary = f"Details for {column}: {machine}"
    
    # Add seasons info to the summary
    season_str = f"S{seasons[0]}-S{seasons[1]}" if seasons[0] != seasons[1] else f"S{seasons[0]}"
    summary += f" ({season_str})"
    
    details = {
        "summary": summary,
        "title": f"{column} for {machine}"
    }
    
    return filtered, details
    
# Update the cell click handling portion of Section 12
def handle_cell_click(clicked_cell, all_data_df, team_name, twc_team_name, venue_name, column_config):
    """
    Handle a cell click in the main grid and return the appropriate detailed data.
    """
    column = clicked_cell["col"]
    machine = clicked_cell["machine"]
    
    # Get detailed data using the column-specific logic
    detailed_df = get_detailed_data_for_column(
        all_data_df, machine, column, team_name, twc_team_name, venue_name, column_config
    )
    
    # Create a summary based on the column type
    if "Average" in column:
        avg_score = detailed_df["score"].mean() if not detailed_df.empty else 0
        num_scores = len(detailed_df)
        summary = f"{column}: {avg_score:,.2f} (based on {num_scores} scores)"
    elif "Times" in column:
        count = len(detailed_df)
        summary = f"{column}: {count:,}"
    elif "%" in column:
        # For percentage columns, reference the related average columns
        base_col = "Team Average" if column == "% of V. Avg." else "TWC Average"
        avg_score = detailed_df["score"].mean() if not detailed_df.empty else 0
        num_scores = len(detailed_df)
        summary = f"{column} (based on {base_col}): {avg_score:,.2f} (from {num_scores} scores)"
    else:
        summary = f"Details for {column}: {machine}"
    
    # Format scores with commas for display
    display_df = detailed_df.copy()
    if "score" in display_df.columns:
        display_df["score"] = display_df["score"].apply(
            lambda x: f"{x:,.0f}" if pd.notnull(x) else "N/A"
        )
    
    return display_df, {
        "summary": summary,
        "title": f"{column} for {machine}"
    }

def format_no_decimals_keep_commas(df):
    """
    Format all numeric values in the DataFrame to not have any decimals,
    while maintaining comma formatting for large numbers.
    """
    formatted_df = df.copy()
    
    for col in formatted_df.columns:
        if col == "Machine":
            continue  # Skip the machine name column
            
        if "%" in col:
            # Format percentage columns to whole numbers
            formatted_df[col] = formatted_df[col].apply(
                lambda x: f"{float(x.replace('%', '')):.0f}%" if isinstance(x, str) and "%" in x else x
            )
        elif "Average" in col:
            # Format average columns to whole numbers with commas
            formatted_df[col] = formatted_df[col].apply(
                lambda x: f"{int(float(x.replace(',', ''))):,}" if isinstance(x, str) and not x == "N/A" else x
            )
    
    return formatted_df

def configure_grid_with_custom_comparators(result_df_reset):
    """
    Configure AgGrid with proper sorting for all numeric columns that are formatted as strings.
    This includes percentage columns and comma-formatted numbers.
    """
    # First, format the DataFrame to have no decimals but keep commas
    formatted_df = format_no_decimals_keep_commas(result_df_reset)
    
    # Custom comparator function for percentage columns
    percentage_comparator = JsCode("""
    function(valueA, valueB, nodeA, nodeB, isInverted) {
        // Extract numeric values from the percentage strings
        const numA = parseFloat(valueA.replace('%', ''));
        const numB = parseFloat(valueB.replace('%', ''));
        
        // Handle NaN cases
        if (isNaN(numA) && isNaN(numB)) return 0;
        if (isNaN(numA)) return 1;
        if (isNaN(numB)) return -1;
        
        // Standard numeric comparison
        return numA - numB;
    }
    """)
    
    # Custom comparator for comma-formatted numbers (like "1,234")
    number_comparator = JsCode("""
    function(valueA, valueB, nodeA, nodeB, isInverted) {
        // Remove commas and convert to numbers
        const numA = parseFloat(valueA.replace(/,/g, ''));
        const numB = parseFloat(valueB.replace(/,/g, ''));
        
        // Handle NaN and "N/A" cases
        if (isNaN(numA) && isNaN(numB)) return 0;
        if (isNaN(numA) || valueA === "N/A") return 1;
        if (isNaN(numB) || valueB === "N/A") return -1;
        
        // Standard numeric comparison
        return numA - numB;
    }
    """)
    
    # Configure grid options
    gb = GridOptionsBuilder.from_dataframe(formatted_df)
    gb.configure_default_column(flex=1, resizable=True)
    gb.configure_column("Machine", pinned='left', flex=1)
    
    # Apply custom renderer and comparator to each column based on its type
    for col in formatted_df.columns:
        if "%" in col:
            # For percentage columns, use the percentage comparator
            gb.configure_column(col, cellRenderer=BtnCellRenderer, comparator=percentage_comparator)
        elif "Times" in col or "Highest" in col or "Average" in col:
            # For numeric columns with possible comma formatting, use the number comparator
            gb.configure_column(col, cellRenderer=BtnCellRenderer, comparator=number_comparator)
        else:
            # For other columns, just use the custom renderer
            gb.configure_column(col, cellRenderer=BtnCellRenderer)
    
    grid_options = gb.build()
    
    return grid_options, formatted_df

def add_color_coding_to_grid(formatted_df):
    """
    Add a hidden column with color codes based on the difference between 
    % of V. Avg. and TWC % V. Avg.
    Colors are semi-transparent for better readability.
    
    Returns DataFrame with an added color coding column.
    
    Special cases:
    - If team has stats but TWC doesn't: Translucent red (strongest team advantage)
    - If TWC has stats but team doesn't: Translucent green (strongest TWC advantage)
    - If neither team has stats: Translucent yellow (neutral 50/50)
    """
    df_with_colors = formatted_df.copy()
    
    # Check if both percentage columns are present
    if "% of V. Avg." in df_with_colors.columns and "TWC % V. Avg." in df_with_colors.columns:
        # Extract numeric values from percentage strings
        def extract_percent(val):
            if isinstance(val, str) and "%" in val:
                try:
                    return float(val.replace("%", "").strip())
                except:
                    return None
            return None
        
        df_with_colors['_team_pct'] = df_with_colors["% of V. Avg."].apply(extract_percent)
        df_with_colors['_twc_pct'] = df_with_colors["TWC % V. Avg."].apply(extract_percent)
        
        # Calculate ratio and determine color
        def calculate_color(row):
            team_pct = row.get('_team_pct')
            twc_pct = row.get('_twc_pct')
            
            # Set transparency level (80% opaque)
            alpha = 0.5
            
            # Special case 1: Team has stats but TWC doesn't - translucent red (strongest team advantage)
            if (team_pct is not None and not pd.isna(team_pct) and team_pct > 0) and \
               (twc_pct is None or pd.isna(twc_pct) or twc_pct == 0):
                # Translucent dark red
                return f"rgba(255, 0, 0, {alpha})"
                
            # Special case 2: TWC has stats but team doesn't - translucent green (strongest TWC advantage)
            if (twc_pct is not None and not pd.isna(twc_pct) and twc_pct > 0) and \
               (team_pct is None or pd.isna(team_pct) or team_pct == 0):
                # Translucent dark green
                return f"rgba(0, 128, 0, {alpha})"
                
            # Special case 3: Neither team has stats - translucent yellow (neutral 50/50)
            if (team_pct is None or pd.isna(team_pct) or team_pct == 0) and \
               (twc_pct is None or pd.isna(twc_pct) or twc_pct == 0):
                # Translucent yellow
                return f"rgba(255, 255, 0, {alpha})"
            
            try:
                # Calculate ratio between team and TWC
                if twc_pct >= team_pct:
                    ratio = twc_pct / team_pct
                    # Scale from 1.0 (yellow) to 2.0 or higher (dark green)
                    # Clamp ratio to max of 2.0 for color scaling
                    clamped_ratio = min(ratio, 2.0)
                    intensity = (clamped_ratio - 1.0) / 1.0  # 0.0 to 1.0
                    
                    # Green increases as TWC advantage increases (yellow to green)
                    red = int(255 * (1 - intensity))
                    green = 255 - int((255 - 128) * intensity)
                    blue = 0
                    
                    return f"rgba({red}, {green}, {blue}, {alpha})"
                else:
                    ratio = team_pct / twc_pct
                    # Scale from 1.0 (yellow) to 2.0 or higher (dark red)
                    # Clamp ratio to max of 2.0 for color scaling
                    clamped_ratio = min(ratio, 2.0)
                    intensity = (clamped_ratio - 1.0) / 1.0  # 0.0 to 1.0
                    
                    # Red increases as team advantage increases (yellow to red)
                    red = 255
                    green = int(255 * (1 - intensity))
                    blue = 0
                    
                    return f"rgba({red}, {green}, {blue}, {alpha})"
            except Exception as e:
                # If any calculation error occurs, return translucent yellow as default
                return f"rgba(255, 255, 0, {alpha})"
        
        # Apply the color calculation
        df_with_colors['_row_color'] = df_with_colors.apply(calculate_color, axis=1)
    else:
        # If percentage columns are missing, use translucent yellow for all rows
        df_with_colors['_row_color'] = "rgba(255, 255, 0, 0.5)"
    
    return df_with_colors
    
def configure_grid_with_color_coding(result_df_reset, use_color_coding=False):
    """
    Configure AgGrid with proper sorting and optional color coding with transparency.
    """
    # First, format the DataFrame to have no decimals but keep commas
    formatted_df = format_no_decimals_keep_commas(result_df_reset)
    
    # Add color coding if enabled
    if use_color_coding:
        formatted_df = add_color_coding_to_grid(formatted_df)
    
    # Custom comparator function for percentage columns
    percentage_comparator = JsCode("""
    function(valueA, valueB, nodeA, nodeB, isInverted) {
        // Extract numeric values from the percentage strings
        const numA = parseFloat(valueA.replace('%', ''));
        const numB = parseFloat(valueB.replace('%', ''));
        
        // Handle NaN cases
        if (isNaN(numA) && isNaN(numB)) return 0;
        if (isNaN(numA)) return 1;
        if (isNaN(numB)) return -1;
        
        // Standard numeric comparison
        return numA - numB;
    }
    """)
    
    # Custom comparator for comma-formatted numbers (like "1,234")
    number_comparator = JsCode("""
    function(valueA, valueB, nodeA, nodeB, isInverted) {
        // Remove commas and convert to numbers
        const numA = parseFloat(valueA.replace(/,/g, ''));
        const numB = parseFloat(valueB.replace(/,/g, ''));
        
        // Handle NaN and "N/A" cases
        if (isNaN(numA) && isNaN(numB)) return 0;
        if (isNaN(numA) || valueA === "N/A") return 1;
        if (isNaN(numB) || valueB === "N/A") return -1;
        
        // Standard numeric comparison
        return numA - numB;
    }
    """)
    
    # Configure grid options
    gb = GridOptionsBuilder.from_dataframe(formatted_df)
    gb.configure_default_column(flex=1, resizable=True)
    gb.configure_column("Machine", pinned='left', flex=1)
    
    # Apply custom renderer and comparator to each column based on its type
    for col in formatted_df.columns:
        if col.startswith('_'):
            # Hide helper columns
            gb.configure_column(col, hide=True)
        elif "%" in col:
            # For percentage columns, use the percentage comparator
            gb.configure_column(col, cellRenderer=BtnCellRenderer, comparator=percentage_comparator)
        elif "Times" in col or "Highest" in col or "Average" in col:
            # For numeric columns with possible comma formatting, use the number comparator
            gb.configure_column(col, cellRenderer=BtnCellRenderer, comparator=number_comparator)
        else:
            # For other columns, just use the custom renderer
            gb.configure_column(col, cellRenderer=BtnCellRenderer)
    
    # Add row styling if color coding is enabled
    if use_color_coding:
        gb.configure_grid_options(
            getRowStyle=JsCode("""
            function(params) {
                if (params.data._row_color) {
                    return {
                        'background-color': params.data._row_color
                    };
                }
                return null;
            }
            """)
        )
    
    grid_options = gb.build()
    
    return grid_options, formatted_df

##############################################
# Section 12: "Kellanate" Button, Persistent Output, Cell Selection & Detailed Scores
##############################################

# Define a custom cell renderer that marks a cell on click
BtnCellRenderer = JsCode(
    """
class ClickCellRenderer {
    init(params) {
        this.params = params;
        this.eGui = document.createElement('div');
        this.eGui.innerHTML = `<div style="cursor: pointer;">${this.params.value}</div>`;
        this.eGui.addEventListener('click', this.onClick.bind(this));
    }
    
    onClick(event) {
        // Mark this cell with a unique timestamp to ensure multiple clicks are detected
        const timestamp = new Date().getTime();
        this.params.setValue(`[clicked:${timestamp}]` + this.params.value);
    }
    
    getGui() {
        return this.eGui;
    }
    
    refresh(params) {
        return true;
    }
    
    destroy() {
        this.eGui.removeEventListener('click', this.onClick);
    }
}
"""
)

# Process data when "Kellanate" is pressed
if st.button("Kellanate", key="kellanate_btn"):
    with st.spinner("Loading JSON files from repository and processing data..."):
        all_data = load_all_json_files(repo_dir, seasons_to_process)
        result_df, debug_outputs, team_player_stats, twc_player_stats = main(
            all_data, selected_team, selected_venue, st.session_state.roster_data, st.session_state["column_config"]
        )
        st.session_state["result_df"] = result_df
        st.session_state["team_player_stats"] = team_player_stats
        st.session_state["twc_player_stats"] = twc_player_stats

        # Create an Excel file for download
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            result_df.to_excel(writer, index=False, sheet_name='Results')
            team_player_stats.to_excel(writer, index=False, sheet_name=f'{selected_team} Players')
            twc_player_stats.to_excel(writer, index=False, sheet_name='TWC Players')
        st.session_state["processed_excel"] = output.getvalue()
        st.session_state["debug_outputs"] = debug_outputs
        st.session_state["kellanate_output"] = True
    st.success("Data processed successfully!")

# Display output if processing has completed
if st.session_state.get("kellanate_output", False) and "result_df" in st.session_state:
    # Initialize a last clicked timestamp in session state if not already set
    if "last_click_time" not in st.session_state:
        st.session_state.last_click_time = 0
    
    # Close button to clear session
    col1, col2 = st.columns([0.9, 0.1])
    with col2:
        if st.button("X", key="close_kellanate_output"):
            for key in ["kellanate_output", "result_df", "team_player_stats", "twc_player_stats", 
                       "processed_excel", "debug_outputs", "last_click_time"]:
                st.session_state.pop(key, None)
            st.rerun()  # Use st.rerun() instead of deprecated st.experimental_rerun()

    result_df_reset = st.session_state["result_df"].reset_index(drop=True)
    
    # Add a prominent header and toggle for color coding
    st.markdown(f"### {selected_team} @ {selected_venue}")
    
    # Create a container for the toggle to ensure it appears
    toggle_container = st.container()
    with toggle_container:
        use_color_coding = st.checkbox(
            "Color code by advantage ratio", 
            value=False,
            key="color_toggle"
        )
    
    # Configure AgGrid with custom comparators and optional color coding
    grid_options, formatted_df = configure_grid_with_color_coding(result_df_reset, use_color_coding)
    
    # Display the AgGrid
    response = AgGrid(
        formatted_df, 
        gridOptions=grid_options, 
        height=400, 
        fit_columns_on_grid_load=True,
        allow_unsafe_jscode=True,
        columns_auto_size_mode=ColumnsAutoSizeMode.FIT_CONTENTS,
        resizable=True,
        key=f"main_grid_{use_color_coding}"  # Update key when toggle changes to force refresh
    )
    
    # Clear previous debug output and parse the returned dataframe for the clicked cell
    debug_placeholder = st.empty()
    debug_placeholder.empty()
    df_out = response["data"]
    clicked_cells = []
    
    # Find cells with [clicked:timestamp] prefix - timestamp helps identify the most recent click
    most_recent_click = {"timestamp": 0, "col": "", "idx": 0, "machine": ""}
    
    for idx, row in df_out.iterrows():
        for col in df_out.columns:
            val = row[col]
            if isinstance(val, str) and "[clicked:" in val:
                # Extract timestamp from the clicked cell format: [clicked:timestamp]value
                try:
                    # Parse the timestamp from the marker
                    timestamp_str = val.split("[clicked:")[1].split("]")[0]
                    timestamp = int(timestamp_str)
                    
                    # Record the cell position and timestamp
                    machine_name = row["Machine"]
                    clicked_cells.append({
                        "col": col, 
                        "idx": idx, 
                        "machine": machine_name,
                        "timestamp": timestamp
                    })
                    
                    # Update most recent click if this is newer
                    if timestamp > most_recent_click["timestamp"]:
                        most_recent_click = {
                            "timestamp": timestamp,
                            "col": col,
                            "idx": idx,
                            "machine": machine_name
                        }
                except Exception as e:
                    # If parsing fails, just record without timestamp
                    machine_name = row["Machine"]
                    clicked_cells.append({
                        "col": col, 
                        "idx": idx, 
                        "machine": machine_name,
                        "timestamp": 0
                    })
    
    # Only trigger a detailed view update if we have a new click
    new_click_detected = False
    if most_recent_click["timestamp"] > st.session_state.last_click_time:
        st.session_state.last_click_time = most_recent_click["timestamp"]
        new_click_detected = True
    
    # Debug info
    if clicked_cells:
        debug_placeholder.write("Detected clicked cells:")
        debug_placeholder.write(clicked_cells)
        debug_placeholder.write(f"Most recent click: {most_recent_click}")
    
    # If a new click is detected or we have a most recent click, show detailed data
    if new_click_detected or most_recent_click["timestamp"] > 0:
        selected_col = most_recent_click["col"]
        machine = most_recent_click["machine"]
        
        # Get the all_data_df from debug_outputs
        all_data_df = st.session_state["debug_outputs"].get("all_data")
        
        if all_data_df is not None and not all_data_df.empty:
            # Use our column-specific handler function with current seasons
            detailed_df, details = get_detailed_data_for_column(
                all_data_df, 
                machine, 
                selected_col, 
                selected_team, 
                "The Wrecking Crew", 
                selected_venue, 
                st.session_state["column_config"],
                seasons_to_process  # Pass the current seasons from user input
            )
            
            # Display the summary and title
            st.markdown(f"### {details['title']}")
            st.markdown(f"**{details['summary']}**")
            
            if not detailed_df.empty:
                # Create a display DataFrame with the columns we want to show
                if "Times Picked" in selected_col and "Pick Group" in detailed_df.columns:
                    display_cols = ["Pick Group", "player_name", "team", "score", "season", "venue"]
                else:
                    display_cols = ["player_name", "team", "score", "season", "venue"]
                
                # Keep only the columns that exist in the DataFrame
                display_cols = [col for col in display_cols if col in detailed_df.columns]
                display_df = detailed_df[display_cols].copy()
                
                # Format scores with commas
                if "score" in display_df.columns:
                    display_df["score"] = display_df["score"].apply(
                        lambda x: f"{x:,.0f}" if pd.notnull(x) else "N/A"
                    )
                
                # Display the detailed data
                AgGrid(
                    display_df, 
                    height=300, 
                    fit_columns_on_grid_load=True,
                    key=f"detailed_grid_{most_recent_click['timestamp']}"  # Use timestamp in key for forced refresh
                )
            else:
                st.write("No detailed data available for this selection after applying all filters.")
        else:
            st.write("No detailed data available in debug outputs.")
    
    # Checkbox to toggle display of player statistics
    if st.checkbox("Show Unique Players", key="player_stats_toggle"):
        st.markdown(f"### {selected_team} Player Statistics at {selected_venue}")
        AgGrid(st.session_state["team_player_stats"], height=400, fit_columns_on_grid_load=True)
        st.markdown(f"### TWC Player Statistics at {selected_venue}")
        AgGrid(st.session_state["twc_player_stats"], height=400, fit_columns_on_grid_load=True)
    
    # Download button for the Excel file
    st.download_button(
        label="Download Excel file",
        data=st.session_state["processed_excel"],
        file_name="final_stats.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
else:
    st.write("Press 'Kellanate' to Kellanate.")

##############################################
# Section 12.5: Optional Debug Outputs Toggle
##############################################
if st.checkbox("Show Debug Outputs", key="debug_toggle"):
    if "debug_outputs" in st.session_state:
        for name, debug_df in st.session_state.debug_outputs.items():
            st.markdown(f"### Debug Output: {name}")
            st.dataframe(debug_df)
    else:
        st.info("No debug outputs available. Please run 'Kellanate' first.")


##############################################
# Debug Info Toggle for Roster, Team Names, Venues, and Abbreviations
##############################################
if st.checkbox("Debug Info", key="debug_info_toggle"):
    st.markdown("### Debug Information")
    st.write("**DEBUG: Sorted Venues extracted from JSON:**", dynamic_venues)
    st.write("**DEBUG: Sorted Teams extracted from JSON:**", dynamic_team_names)
    st.write("**DEBUG: Team Abbreviations:**", team_abbr_dict)
    # Display the roster for the selected team (if available)
    if selected_team and team_abbr_dict and st.session_state.roster_data:
        team_abbr = team_abbr_dict.get(selected_team)
        if team_abbr:
            selected_team_roster = st.session_state.roster_data.get(team_abbr, [])
            st.write(f"**DEBUG: Roster for {selected_team} ({team_abbr}):**", selected_team_roster)
        else:
            st.write(f"**DEBUG: No team abbreviation found for {selected_team}.**")
    else:
        st.write("**DEBUG: Team roster data is not available.**")

##############################################
# Section 13: machine picking algorithm - data structure
##############################################

def build_player_machine_stats(all_data_df, opponent_team_name, venue_name, seasons_to_process, roster_data, included_machines, excluded_machines):
    """
    Build a comprehensive player-machine statistics database for strategic picking.
    This is from TWC's perspective against the opponent team.
    
    Parameters:
    - all_data_df: DataFrame with processed match data
    - opponent_team_name: Name of the opposing team
    - venue_name: Name of the selected venue
    - seasons_to_process: List of seasons to include
    - roster_data: Dictionary mapping team abbreviations to roster player lists
    - included_machines: List of machines specifically included at the venue
    - excluded_machines: List of machines specifically excluded at the venue
    
    Returns:
    - player_machine_stats: Dictionary with player stats
    - machine_advantage_metrics: DataFrame with machine advantage metrics
    """
    import pandas as pd
    import numpy as np
    
    # TWC is always the primary team we're analyzing
    twc_team_name = "The Wrecking Crew"
    
    # Filter data for the venue and seasons
    venue_data = all_data_df[all_data_df['venue'] == venue_name]
    venue_data = venue_data[venue_data['season'].isin(seasons_to_process)]
    
    # Get team abbreviation for roster filtering
    twc_abbr = "TWC"
    
    # Initialize data structures
    player_machine_stats = {}
    machine_venue_averages = {}
    opponent_machine_stats = {}
    machine_experience = {}
    
    # Start with all machines from the venue
    all_machines_set = set(venue_data['machine'].unique())
    
    # Add any machines explicitly included (even if not in the venue data)
    if included_machines:
        all_machines_set.update(included_machines)
    
    # Remove any machines explicitly excluded
    if excluded_machines:
        all_machines_set.difference_update(excluded_machines)
    
    # Convert back to a sorted list if needed
    filtered_machines = sorted(all_machines_set)

    
    # Calculate venue averages for each filtered machine
    for machine in filtered_machines:
        machine_data = venue_data[venue_data['machine'] == machine]
        machine_venue_averages[machine] = machine_data['score'].mean()
        
        # Track experience counts for opponent on this machine
        opponent_machine_data = machine_data[machine_data['team'] == opponent_team_name]
        opponent_plays = len(opponent_machine_data.groupby(['match', 'round']).first())
        opponent_players = opponent_machine_data['player_name'].nunique()
        
        # Store opponent averages and experience
        opponent_machine_stats[machine] = {
            'average_score': opponent_machine_data['score'].mean() if len(opponent_machine_data) > 0 else None,
            'plays_count': opponent_plays,
            'players_count': opponent_players,
            'scores': opponent_machine_data['score'].tolist() if len(opponent_machine_data) > 0 else []
        }
        
        # Initialize machine experience tracking for TWC
        machine_experience[machine] = {
            'team_plays': 0,
            'team_players': set(),
            'team_players_with_experience': []
        }
    
    # Process each TWC player
    twc_players = set()
    if twc_abbr and twc_abbr in roster_data:
        twc_players = set(roster_data[twc_abbr])
    
    # Also include any player who has played for TWC at this venue
    twc_venue_data = venue_data[venue_data['team'] == twc_team_name]
    for player in twc_venue_data['player_name'].unique():
        twc_players.add(player)
    
    # Build stats for each TWC player
    for player in twc_players:
        player_data = venue_data[venue_data['player_name'] == player]
        player_twc_data = player_data[player_data['team'] == twc_team_name]
        
        # Initialize player stats
        player_machine_stats[player] = {
            'machines': {},
            'overall_average_pct_of_venue': 0,
            'total_games_played': len(player_twc_data),
            'experience_breadth': 0  # How many machines they've played
        }
        
        # Only process if the player has games at this venue
        if len(player_twc_data) > 0:
            # Calculate overall average percentage of venue average
            player_pcts = []
            
            # Process each machine the player has played (filtering for included/excluded)
            player_machines = [m for m in player_twc_data['machine'].unique() if m in filtered_machines]
            player_machine_stats[player]['experience_breadth'] = len(player_machines)
            
            for machine in player_machines:
                player_machine_data = player_twc_data[player_twc_data['machine'] == machine]
                venue_avg = machine_venue_averages.get(machine, 0)
                
                # Calculate stats for this player on this machine
                scores = player_machine_data['score'].tolist()
                avg_score = np.mean(scores) if scores else 0
                pct_of_venue = (avg_score / venue_avg * 100) if venue_avg > 0 else 0
                plays_count = len(player_machine_data)
                
                # Track TWC experience on this machine
                machine_experience[machine]['team_plays'] += plays_count
                machine_experience[machine]['team_players'].add(player)
                machine_experience[machine]['team_players_with_experience'].append({
                    'player': player,
                    'plays_count': plays_count,
                    'avg_score': avg_score,
                    'pct_of_venue': pct_of_venue
                })
                
                # Store the player's stats for this machine
                player_machine_stats[player]['machines'][machine] = {
                    'scores': scores,
                    'average_score': avg_score,
                    'pct_of_venue': pct_of_venue,
                    'plays_count': plays_count,
                    'rank_on_team': 0  # Will be calculated after all players are processed
                }
                
                # Add to the player's overall percentage calculations
                player_pcts.append(pct_of_venue)
            
            # Calculate overall average percentage across machines
            if player_pcts:
                player_machine_stats[player]['overall_average_pct_of_venue'] = np.mean(player_pcts)
    
    # Calculate TWC rankings for each machine
    machine_rankings = {}
    for machine in filtered_machines:
        # Get all players who have played this machine
        players_with_experience = []
        for player, stats in player_machine_stats.items():
            if machine in stats['machines']:
                players_with_experience.append({
                    'player': player,
                    'pct_of_venue': stats['machines'][machine]['pct_of_venue'],
                    'plays_count': stats['machines'][machine]['plays_count']
                })
        
        # Sort by percentage of venue average
        players_with_experience.sort(key=lambda x: x['pct_of_venue'], reverse=True)
        
        # Assign rankings
        machine_rankings[machine] = players_with_experience
        for rank, player_data in enumerate(players_with_experience, 1):
            player = player_data['player']
            if player in player_machine_stats and machine in player_machine_stats[player]['machines']:
                player_machine_stats[player]['machines'][machine]['rank_on_team'] = rank
    
    # Calculate machine advantage metrics
    machine_advantage_data = []
    for machine in filtered_machines:
        venue_avg = machine_venue_averages.get(machine, 0)
        opponent_avg = opponent_machine_stats[machine]['average_score'] if opponent_machine_stats[machine]['average_score'] else 0
        opponent_pct = (opponent_avg / venue_avg * 100) if venue_avg > 0 and opponent_avg > 0 else 0
        
        # Get TWC average for this machine
        twc_scores = []
        for player in machine_experience[machine]['team_players_with_experience']:
            twc_scores.extend([player['avg_score']] * player['plays_count'])
        
        twc_avg = np.mean(twc_scores) if twc_scores else 0
        twc_pct = (twc_avg / venue_avg * 100) if venue_avg > 0 and twc_avg > 0 else 0
        
        # Calculate experience advantage
        twc_plays = machine_experience[machine]['team_plays']
        twc_players = len(machine_experience[machine]['team_players'])
        opponent_plays = opponent_machine_stats[machine]['plays_count']
        opponent_players = opponent_machine_stats[machine]['players_count']
        
        experience_advantage = twc_plays - opponent_plays
        player_coverage_advantage = twc_players - opponent_players
        
        # Calculate statistical advantage
        statistical_advantage = twc_pct - opponent_pct if twc_pct > 0 and opponent_pct > 0 else None
        
        # Special cases for advantage calculation
        if twc_pct > 0 and opponent_pct == 0:
            # TWC has played it but opponent hasn't - strong advantage
            advantage_level = "Strong TWC Advantage"
            composite_score = 100
        elif twc_pct == 0 and opponent_pct > 0:
            # Opponent has played it but TWC hasn't - strong disadvantage
            advantage_level = "Strong Opponent Advantage"
            composite_score = -100
        elif twc_pct == 0 and opponent_pct == 0:
            # Neither has played it - neutral
            advantage_level = "Neutral"
            composite_score = 0
        elif statistical_advantage is not None:
            # Both have played it - calculate real advantage
            if statistical_advantage > 20:
                advantage_level = "TWC Advantage"
            elif statistical_advantage < -20:
                advantage_level = "Opponent Advantage"
            else:
                advantage_level = "Slight/No Advantage"
            
            # Create a composite score combining statistical and experience advantages
            # Weight can be adjusted based on strategic importance
            statistical_weight = 0.7
            experience_weight = 0.3
            
            # Normalize experience advantage to similar scale as percentage advantage
            normalized_exp_adv = min(max(experience_advantage / 5 * 20, -100), 100)
            
            composite_score = (statistical_advantage * statistical_weight + 
                              normalized_exp_adv * experience_weight)
        else:
            advantage_level = "Unknown"
            composite_score = 0
        
        # Add machine data to the advantage metrics
        machine_advantage_data.append({
            'Machine': machine,
            'Venue Average': venue_avg,
            'TWC Average': twc_avg,
            'TWC % of Venue': twc_pct,
            'Opponent Average': opponent_avg,
            'Opponent % of Venue': opponent_pct,
            'Statistical Advantage': statistical_advantage,
            'TWC Plays': twc_plays,
            'Opponent Plays': opponent_plays,
            'Experience Advantage': experience_advantage,
            'TWC Players': twc_players,
            'Opponent Players': opponent_players,
            'Player Coverage Advantage': player_coverage_advantage,
            'Advantage Level': advantage_level,
            'Composite Score': composite_score,
            'Top TWC Players': [p['player'] for p in machine_rankings.get(machine, [])[:3]],
            'Available at Venue': True  # Will be True for all filtered machines
        })
    
    # Convert to DataFrame and sort by composite score
    machine_advantage_df = pd.DataFrame(machine_advantage_data)
    machine_advantage_df = machine_advantage_df.sort_values('Composite Score', ascending=False)
    
    return player_machine_stats, machine_advantage_df

##############################################
# Section 13.1: machine picking algorithm - optimization
##############################################

def optimize_machine_selections(player_machine_stats, machine_advantage_df, format_type, available_players, num_machines_to_pick):
    """
    Optimize machine selections and player assignments to maximize advantage.
    
    Parameters:
    - player_machine_stats: Dictionary with player performance statistics
    - machine_advantage_df: DataFrame with machine advantage metrics
    - format_type: Either "Singles" or "Doubles"
    - available_players: List of player names who are available for this format
    - num_machines_to_pick: Number of machines to select (typically 4 for doubles, 7 for singles)
    
    Returns:
    - selected_machines: List of selected machines
    - player_assignments: Dictionary mapping machines to assigned players
    """
    import numpy as np
    import pandas as pd
    from scipy.optimize import linear_sum_assignment
    
    # Determine if this is doubles or singles
    is_doubles = format_type.lower() == "doubles"
    is_singles = format_type.lower() == "singles"
    
    # Filter the machine advantage DataFrame to only include available machines
    available_machines_df = machine_advantage_df[machine_advantage_df['Available at Venue'] == True]
    
    # Create a player-machine score matrix
    player_machine_scores = {}
    
    for player in available_players:
        player_machine_scores[player] = {}
        player_stats = player_machine_stats.get(player, {'machines': {}, 'overall_average_pct_of_venue': 0})
        
        # Get the player's overall average as a fallback
        player_overall_avg = player_stats['overall_average_pct_of_venue']
        
        for _, machine_row in available_machines_df.iterrows():
            machine = machine_row['Machine']
            
            # Get this player's stats on this machine if available
            machine_stats = player_stats['machines'].get(machine, {})
            
            if machine_stats:
                # Player has played this machine before
                player_pct = machine_stats['pct_of_venue']
                plays_count = machine_stats['plays_count']
                
                # Confidence factor based on number of plays (higher is better)
                confidence = min(plays_count / 3, 1.0)  # Maxes out at 3+ plays
                
                # Calculate player's advantage over opponent average
                opponent_pct = machine_row['Opponent % of Venue']
                if opponent_pct > 0:
                    player_advantage = player_pct - opponent_pct
                else:
                    # Opponent hasn't played this machine - big advantage
                    player_advantage = player_pct * 0.5  # Scale factor to avoid overly favoring unknown machines
                
                # Calculate final score considering confidence
                final_score = player_advantage * confidence
                
            else:
                # Player hasn't played this machine - use overall average as estimate
                # This is heavily discounted due to uncertainty
                if player_overall_avg > 0:
                    opponent_pct = machine_row['Opponent % of Venue']
                    if opponent_pct > 0:
                        # Estimate advantage based on overall player average
                        player_advantage = player_overall_avg - opponent_pct
                    else:
                        # Neither player nor opponent has played this
                        player_advantage = 0
                    
                    # Very low confidence for machines the player hasn't played
                    final_score = player_advantage * 0.3
                else:
                    # No data for this player at all
                    final_score = 0
            
            # Store the final score
            player_machine_scores[player][machine] = final_score
    
    # Optimization strategy differs for doubles and singles
    if is_singles:
        # For singles, this is a standard assignment problem
        return optimize_singles_format(player_machine_scores, available_machines_df, available_players, num_machines_to_pick)
    else:
        # For doubles, we need to optimize pairs
        return optimize_doubles_format(player_machine_scores, available_machines_df, available_players, num_machines_to_pick)

def optimize_singles_format(player_machine_scores, available_machines_df, available_players, num_machines_to_pick):
    """
    Optimize machine selections and player assignments for singles format.
    
    Parameters:
    - player_machine_scores: Dictionary of dictionaries with player-machine scores
    - available_machines_df: DataFrame with filtered machine advantage metrics
    - available_players: List of player names who are available
    - num_machines_to_pick: Number of machines to select (typically 7 for singles)
    
    Returns:
    - selected_machines: List of selected machines
    - player_assignments: Dictionary mapping machines to assigned players
    """
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    
    # Ensure we don't try to pick more machines than available
    num_machines_to_pick = min(num_machines_to_pick, len(available_machines_df), len(available_players))
    
    if num_machines_to_pick == 0:
        return [], {}
    
    # Convert available machines to a list
    available_machines = available_machines_df['Machine'].tolist()
    
    # Create a score matrix for the Hungarian algorithm
    # We'll use negative scores since the algorithm minimizes cost
    cost_matrix = np.zeros((len(available_players), len(available_machines)))
    
    for i, player in enumerate(available_players):
        for j, machine in enumerate(available_machines):
            score = player_machine_scores[player].get(machine, 0)
            # Convert to cost (negative score)
            cost_matrix[i, j] = -score
    
    # Use the Hungarian algorithm to find the optimal assignment
    row_ind, col_ind = linear_sum_assignment(cost_matrix)
    
    # Sort assignments by score (highest first)
    assignments = []
    for i, j in zip(row_ind, col_ind):
        player = available_players[i]
        machine = available_machines[j]
        score = -cost_matrix[i, j]  # Convert back to positive score
        assignments.append((player, machine, score))
    
    # Sort by score, highest first
    assignments.sort(key=lambda x: x[2], reverse=True)
    
    # Take top N assignments
    top_assignments = assignments[:num_machines_to_pick]
    
    # Create the results
    selected_machines = [machine for _, machine, _ in top_assignments]
    player_assignments = {machine: [player] for player, machine, _ in top_assignments}
    
    return selected_machines, player_assignments

def optimize_doubles_format(player_machine_scores, available_machines_df, available_players, num_machines_to_pick):
    """
    Optimize machine selections and player pair assignments for doubles format.
    
    Parameters:
    - player_machine_scores: Dictionary of dictionaries with player-machine scores
    - available_machines_df: DataFrame with filtered machine advantage metrics
    - available_players: List of player names who are available
    - num_machines_to_pick: Number of machines to select (typically 4 for doubles)
    
    Returns:
    - selected_machines: List of selected machines
    - player_assignments: Dictionary mapping machines to assigned player pairs
    """
    import itertools
    import numpy as np
    
    # Ensure we have enough players for doubles
    if len(available_players) < num_machines_to_pick * 2:
        return [], {}
    
    # Get all possible player pairs
    player_pairs = list(itertools.combinations(available_players, 2))
    
    # Convert available machines to a list
    available_machines = available_machines_df['Machine'].tolist()
    
    # Create a score dictionary for each pair-machine combination
    pair_machine_scores = {}
    for pair in player_pairs:
        player1, player2 = pair
        pair_machine_scores[pair] = {}
        
        for machine in available_machines:
            # Combine individual player scores
            score1 = player_machine_scores[player1].get(machine, 0)
            score2 = player_machine_scores[player2].get(machine, 0)
            
            # We want pairs where both players are good, not just one excellent player
            # This is a weighted average that favors balanced pairs
            combined_score = (score1 + score2) * 0.5 + min(score1, score2) * 0.5
            
            pair_machine_scores[pair][machine] = combined_score
    
    # Now we need to find the optimal selection of machines and assignment of pairs
    # This is more complex than the singles case as we need to:
    # 1. Select machines
    # 2. Assign player pairs
    # 3. Ensure each player is only used once
    
    # We'll use a greedy approach:
    # 1. Calculate scores for all pair-machine combinations
    # 2. Sort by score (highest first)
    # 3. Take combinations in order, skipping those that use already assigned players
    
    # Calculate all pair-machine scores
    all_combinations = []
    for pair in player_pairs:
        for machine in available_machines:
            score = pair_machine_scores[pair].get(machine, 0)
            all_combinations.append((pair, machine, score))
    
    # Sort by score, highest first
    all_combinations.sort(key=lambda x: x[2], reverse=True)
    
    # Select the top combinations, ensuring no player is used twice
    selected_combinations = []
    used_players = set()
    used_machines = set()
    
    for pair, machine, score in all_combinations:
        player1, player2 = pair
        
        # Skip if we've reached our limit
        if len(selected_combinations) >= num_machines_to_pick:
            break
            
        # Skip if this machine or any player is already used
        if machine in used_machines or player1 in used_players or player2 in used_players:
            continue
        
        # Add this combination
        selected_combinations.append((pair, machine, score))
        used_players.add(player1)
        used_players.add(player2)
        used_machines.add(machine)
    
    # Create the results
    selected_machines = [machine for _, machine, _ in selected_combinations]
    player_assignments = {machine: list(pair) for pair, machine, _ in selected_combinations}
    
    return selected_machines, player_assignments

##############################################
# Section 13.2: machine picking algorithm - TWC Picks
##############################################

def analyze_picking_strategy(all_data, opponent_team_name, venue_name, team_roster):
    """
    Analyze and recommend optimal machine picking strategy for TWC.
    
    Parameters:
    - all_data: Processed match data
    - opponent_team_name: Name of the opposing team (the selected team)
    - venue_name: Name of the selected venue
    - team_roster: Dictionary mapping team abbreviations to roster player lists
    
    Returns:
    - recommendation_df: DataFrame with machine recommendations
    - player_stats: Player performance statistics
    """
    import pandas as pd
    import streamlit as st
    
    # Convert all_data to DataFrame if it's not already
    if not isinstance(all_data, pd.DataFrame):
        all_data_df = pd.DataFrame(all_data)
    else:
        all_data_df = all_data
    
    # Get current seasons from session state
    seasons_to_process = st.session_state.get("seasons_to_process", [20, 21])
    
    # Get venue machine lists (included/excluded)
    venue_machine_lists = get_venue_machine_list(venue_name, "all")
    
    # Check the type of venue_machine_lists
    st.write(f"Venue Machine Lists Type: {type(venue_machine_lists)}")
    st.write(f"Venue Machine Lists: {venue_machine_lists}")
    
    # Handle different possible return types
    if isinstance(venue_machine_lists, dict):
        included_machines = venue_machine_lists.get("included", [])
        excluded_machines = venue_machine_lists.get("excluded", [])
    elif isinstance(venue_machine_lists, list):
        # If it's a list, assume empty dictionaries
        included_machines = []
        excluded_machines = []
    else:
        # Unexpected type
        st.warning(f"Unexpected venue machine lists type: {type(venue_machine_lists)}")
        included_machines = []
        excluded_machines = []
    
    # Diagnostic Streamlit output
    st.write(f"Venue: {venue_name}")
    st.write(f"Included Machines: {included_machines}")
    st.write(f"Excluded Machines: {excluded_machines}")
    
    # Build comprehensive player and machine statistics
    player_machine_stats, machine_advantage_df = build_player_machine_stats(
        all_data_df, opponent_team_name, venue_name, seasons_to_process, team_roster,
        included_machines, excluded_machines
    )
    
    # Display the strategic analysis
    st.markdown(f"## Strategic Picking Analysis for TWC vs {opponent_team_name} at {venue_name}")
    
    # Display player roster management
    st.markdown("### TWC Player Availability")
    st.markdown("Select players available for this match:")
    
    # Get all players who have played at this venue for TWC
    all_players = list(player_machine_stats.keys())
    all_players_sorted = sorted(all_players)
    
    # Initialize all as checked
    if "available_players" not in st.session_state:
        st.session_state.available_players = {player: True for player in all_players_sorted}
    
    # Create rows of checkboxes for players
    cols_per_row = 3
    for i in range(0, len(all_players_sorted), cols_per_row):
        cols = st.columns(cols_per_row)
        for j in range(cols_per_row):
            if i + j < len(all_players_sorted):
                player = all_players_sorted[i + j]
                idx = j % cols_per_row
                st.session_state.available_players[player] = cols[idx].checkbox(
                    player, 
                    value=st.session_state.available_players.get(player, True),
                    key=f"player_{player}"
                )
    
    # Get currently available players
    available_players = [p for p, available in st.session_state.available_players.items() if available]
    
    # Display top advantage machines
    st.markdown("### Machine Advantage Analysis")
    st.markdown("Machines ranked by strategic advantage for TWC:")
    
    # Display advantage table
    display_columns = [
        'Machine', 'Composite Score', 'TWC % of Venue', 'Opponent % of Venue', 
        'Statistical Advantage', 'Experience Advantage', 'Player Coverage Advantage',
        'Advantage Level', 'Top TWC Players'
    ]
    
    # Format the dataframe for display
    display_df = machine_advantage_df[display_columns].copy()
    
    # Format numeric columns
    display_df['Composite Score'] = display_df['Composite Score'].round(1)
    display_df['TWC % of Venue'] = display_df['TWC % of Venue'].round(1)
    display_df['Opponent % of Venue'] = display_df['Opponent % of Venue'].round(1)
    display_df['Statistical Advantage'] = display_df['Statistical Advantage'].round(1)
    
    # Display the table
    st.dataframe(display_df)
    
    # Add optimization section for each format type
    st.markdown("### Format-Specific Picking Strategy")
    
    # Create tabs for Singles and Doubles
    tabs = st.tabs(["Singles", "Doubles"])
    
    format_recommendations = {}
    
    # Tab for Singles format
    with tabs[0]:
        # Singles settings
        st.markdown("#### Singles Format")
        
        # Number of machines to pick for singles (default 7)
        num_singles_machines = st.number_input("Number of machines to pick:", min_value=1, max_value=10, value=7, key="singles_num")
        
        st.markdown(f"Selecting {num_singles_machines} machines and assigning one player to each.")
        
        # Add a button to run the optimization
        if st.button("Optimize Singles Picks", key="optimize_singles"):
            # Check if we have enough players
            if len(available_players) >= num_singles_machines:
                # Run the optimization
                selected_machines, player_assignments = optimize_machine_selections(
                    player_machine_stats, 
                    machine_advantage_df,
                    "Singles",
                    available_players,
                    num_singles_machines
                )
                
                # Store results
                format_recommendations["Singles"] = {
                    'selected_machines': selected_machines,
                    'player_assignments': player_assignments
                }
                
                # Display results
                if selected_machines:
                    st.markdown("**Recommended Machine Picks:**")
                    for idx, machine in enumerate(selected_machines, 1):
                        machine_data = machine_advantage_df[machine_advantage_df['Machine'] == machine].iloc[0]
                        assigned_players = player_assignments.get(machine, [])
                        
                        st.markdown(f"{idx}. **{machine.title()}** - Composite Score: {machine_data['Composite Score']:.1f}")
                        if assigned_players:
                            st.markdown(f"   Assigned Player: {', '.join(assigned_players)}")
                        
                        # Display more detailed stats for this machine
                        expander = st.expander(f"View details for {machine.title()}")
                        with expander:
                            st.markdown(f"**Machine**: {machine.title()}")
                            st.markdown(f"**Advantage Level**: {machine_data['Advantage Level']}")
                            st.markdown(f"**TWC % of Venue**: {machine_data['TWC % of Venue']:.1f}%")
                            st.markdown(f"**Opponent % of Venue**: {machine_data['Opponent % of Venue']:.1f}%")
                            st.markdown(f"**Statistical Advantage**: {machine_data['Statistical Advantage']:.1f}")
                            st.markdown(f"**Experience Advantage**: {machine_data['Experience Advantage']} plays")
                            st.markdown(f"**Player Coverage**: {machine_data['TWC Players']} TWC players vs {machine_data['Opponent Players']} opponent players")
                            
                            # Display player performance on this machine
                            st.markdown("#### Player Performance on this Machine")
                            player_data = []
                            for player in available_players:
                                if player in player_machine_stats and machine in player_machine_stats[player]['machines']:
                                    stats = player_machine_stats[player]['machines'][machine]
                                    player_data.append({
                                        'Player': player,
                                        'Average Score': stats['average_score'],
                                        '% of Venue': stats['pct_of_venue'],
                                        'Times Played': stats['plays_count'],
                                        'Team Rank': stats['rank_on_team']
                                    })
                            
                            if player_data:
                                player_df = pd.DataFrame(player_data)
                                player_df = player_df.sort_values('% of Venue', ascending=False)
                                st.dataframe(player_df)
                            else:
                                st.markdown("No TWC players have experience on this machine.")
                else:
                    st.warning("Not enough available machines or players to make recommendations.")
            else:
                st.error(f"Not enough available players. Need {num_singles_machines}, have {len(available_players)}.")
        
        # If we already have recommendations for singles, display them
        if "Singles" in format_recommendations:
            rec = format_recommendations["Singles"]
            st.markdown("**Current Recommended Singles Picks:**")
            for idx, machine in enumerate(rec['selected_machines'], 1):
                machine_data = machine_advantage_df[machine_advantage_df['Machine'] == machine].iloc[0]
                st.markdown(f"{idx}. **{machine.title()}** - Players: {', '.join(rec['player_assignments'].get(machine, []))}")
    
    # Tab for Doubles format
    with tabs[1]:
        # Doubles settings
        st.markdown("#### Doubles Format")
        
        # Number of machines to pick for doubles (default 4)
        num_doubles_machines = st.number_input("Number of machines to pick:", min_value=1, max_value=8, value=4, key="doubles_num")
        
        st.markdown(f"Selecting {num_doubles_machines} machines and assigning two players to each.")
        
        # Add a button to run the optimization
        if st.button("Optimize Doubles Picks", key="optimize_doubles"):
            # Check if we have enough players
            if len(available_players) >= num_doubles_machines * 2:
                # Run the optimization
                selected_machines, player_assignments = optimize_machine_selections(
                    player_machine_stats, 
                    machine_advantage_df,
                    "Doubles",
                    available_players,
                    num_doubles_machines
                )
                
                # Store results
                format_recommendations["Doubles"] = {
                    'selected_machines': selected_machines,
                    'player_assignments': player_assignments
                }
                
                # Display results
                if selected_machines:
                    st.markdown("**Recommended Machine Picks:**")
                    for idx, machine in enumerate(selected_machines, 1):
                        machine_data = machine_advantage_df[machine_advantage_df['Machine'] == machine].iloc[0]
                        assigned_players = player_assignments.get(machine, [])
                        
                        st.markdown(f"{idx}. **{machine.title()}** - Composite Score: {machine_data['Composite Score']:.1f}")
                        if assigned_players:
                            st.markdown(f"   Assigned Players: {', '.join(assigned_players)}")
                        
                        # Display more detailed stats for this machine
                        expander = st.expander(f"View details for {machine.title()}")
                        with expander:
                            st.markdown(f"**Machine**: {machine.title()}")
                            st.markdown(f"**Advantage Level**: {machine_data['Advantage Level']}")
                            st.markdown(f"**TWC % of Venue**: {machine_data['TWC % of Venue']:.1f}%")
                            st.markdown(f"**Opponent % of Venue**: {machine_data['Opponent % of Venue']:.1f}%")
                            st.markdown(f"**Statistical Advantage**: {machine_data['Statistical Advantage']:.1f}")
                            st.markdown(f"**Experience Advantage**: {machine_data['Experience Advantage']} plays")
                            st.markdown(f"**Player Coverage**: {machine_data['TWC Players']} TWC players vs {machine_data['Opponent Players']} opponent players")
                            
                            # Display player performance on this machine
                            st.markdown("#### Player Performance on this Machine")
                            player_data = []
                            for player in available_players:
                                if player in player_machine_stats and machine in player_machine_stats[player]['machines']:
                                    stats = player_machine_stats[player]['machines'][machine]
                                    player_data.append({
                                        'Player': player,
                                        'Average Score': stats['average_score'],
                                        '% of Venue': stats['pct_of_venue'],
                                        'Times Played': stats['plays_count'],
                                        'Team Rank': stats['rank_on_team']
                                    })
                            
                            if player_data:
                                player_df = pd.DataFrame(player_data)
                                player_df = player_df.sort_values('% of Venue', ascending=False)
                                st.dataframe(player_df)
                            else:
                                st.markdown("No TWC players have experience on this machine.")
                else:
                    st.warning("Not enough available machines or players to make recommendations.")
            else:
                st.error(f"Not enough available players. Need {num_doubles_machines * 2}, have {len(available_players)}.")
        
        # If we already have recommendations for doubles, display them
        if "Doubles" in format_recommendations:
            rec = format_recommendations["Doubles"]
            st.markdown("**Current Recommended Doubles Picks:**")
            for idx, machine in enumerate(rec['selected_machines'], 1):
                machine_data = machine_advantage_df[machine_advantage_df['Machine'] == machine].iloc[0]
                st.markdown(f"{idx}. **{machine.title()}** - Players: {', '.join(rec['player_assignments'].get(machine, []))}")
    
    # Player analysis section
    st.markdown("### Player Analysis")
    selected_player = st.selectbox("Select player to analyze:", [""] + sorted(available_players))
    
    if selected_player:
        st.markdown(f"#### Performance Profile for {selected_player}")
        
        if selected_player in player_machine_stats:
            player_data = player_machine_stats[selected_player]
            
            # Show overall stats
            st.markdown(f"**Overall Average % of Venue**: {player_data['overall_average_pct_of_venue']:.1f}%")
            st.markdown(f"**Total Games Played at {venue_name}**: {player_data['total_games_played']}")
            st.markdown(f"**Machine Experience Breadth**: {player_data['experience_breadth']} machines")
            
            # Show machine-specific performance
            st.markdown("#### Machine Performance")
            
            # Prepare data for table
            machine_data = []
            for machine, stats in player_data['machines'].items():
                # Get the corresponding machine advantage data
                machine_adv = machine_advantage_df[machine_advantage_df['Machine'] == machine]
                
                if not machine_adv.empty:
                    opponent_pct = machine_adv.iloc[0]['Opponent % of Venue']
                    advantage = stats['pct_of_venue'] - opponent_pct if opponent_pct > 0 else None
                    
                    machine_data.append({
                        'Machine': machine,
                        'Average Score': stats['average_score'],
                        '% of Venue': stats['pct_of_venue'],
                        'Times Played': stats['plays_count'],
                        'Team Rank': stats['rank_on_team'],
                        'Opponent % of Venue': opponent_pct,
                        'Player Advantage': advantage
                    })
            
            if machine_data:
                # Convert to DataFrame and sort by advantage
                machine_df = pd.DataFrame(machine_data)
                machine_df = machine_df.sort_values('Player Advantage', ascending=False)
                
                # Format numeric columns
                machine_df['Average Score'] = machine_df['Average Score'].round(0).astype(int)
                machine_df['% of Venue'] = machine_df['% of Venue'].round(1)
                machine_df['Opponent % of Venue'] = machine_df['Opponent % of Venue'].round(1)
                machine_df['Player Advantage'] = machine_df['Player Advantage'].round(1)
                
                st.dataframe(machine_df)
                
                # Show top machines for this player
                st.markdown("#### Best Machines for this Player")
                top_machines = machine_df.sort_values('Player Advantage', ascending=False).head(3)
                
                for i, (_, row) in enumerate(top_machines.iterrows(), 1):
                    machine = row['Machine']
                    st.markdown(f"{i}. **{machine.title()}** - {row['% of Venue']:.1f}% of venue average, " + 
                              f"{row['Player Advantage']:.1f} advantage over opponent")
            else:
                st.markdown("No machine data available for this player at this venue.")
        else:
            st.markdown("No data available for this player.")
    
    return machine_advantage_df, player_machine_stats

def add_strategic_picking_section():
    """
    Add the strategic picking section to the Streamlit app.
    """
    import streamlit as st
    import pandas as pd
    
    st.markdown("## Strategic Machine Picking")
    
    # This section should only be run after data has been processed
    if not st.session_state.get("kellanate_output", False) or "debug_outputs" not in st.session_state:
        st.warning("Please run 'Kellanate' first to process the data.")
        return
    
    # Get the required data from session state
    all_data_df = st.session_state["debug_outputs"].get("all_data")
    selected_team = st.session_state.get("select_team_json", "")
    selected_venue = st.session_state.get("select_venue_json", "")
    roster_data = st.session_state.get("roster_data", {})
    
    if all_data_df is not None and not all_data_df.empty:
        # Run the strategic picking analysis
        machine_recommendations, player_stats = analyze_picking_strategy(
            all_data_df, selected_team, selected_venue, roster_data
        )
        
        # Store the results in session state for later use
        st.session_state["machine_recommendations"] = machine_recommendations
        st.session_state["player_stats"] = player_stats
    else:
        st.error("No data available. Please make sure you've loaded match data.")

##############################################
# Section 13.3: machine picking algorithm - Opponent Picks
##############################################

def analyze_player_assignment_strategy(all_data, opponent_team_name, venue_name, team_roster):
    """
    When the opponent has picked machines, analyze and recommend optimal TWC player assignments.
    
    Parameters:
    - all_data: Processed match data
    - opponent_team_name: Name of the opposing team (the selected team)
    - venue_name: Name of the selected venue
    - team_roster: Dictionary mapping team abbreviations to roster player lists
    
    Returns:
    - player_assignments: Dictionary with recommended player assignments
    """
    import pandas as pd
    import streamlit as st
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    
    # Convert all_data to DataFrame if it's not already
    if not isinstance(all_data, pd.DataFrame):
        all_data_df = pd.DataFrame(all_data)
    else:
        all_data_df = all_data
    
    # Get current seasons from session state
    seasons_to_process = st.session_state.get("seasons_to_process", [20, 21])
    
    # Get venue machine lists (included/excluded)
    included_machines = get_venue_machine_list(venue_name, "included")
    excluded_machines = get_venue_machine_list(venue_name, "excluded")
    
    # Build comprehensive player and machine statistics (for TWC)
    player_machine_stats, machine_advantage_df = build_player_machine_stats(
        all_data_df, opponent_team_name, venue_name, seasons_to_process, team_roster,
        included_machines, excluded_machines
    )
    
    # Display the title
    st.markdown(f"## Player Assignment Strategy for TWC vs {opponent_team_name} at {venue_name}")
    st.markdown("When the opponent has picked machines, use this tool to assign your players optimally.")
    
    # Player roster management
    st.markdown("### TWC Player Availability")
    st.markdown("Select players available for this match:")
    
    # Get all players who have played at this venue for TWC
    all_players = list(player_machine_stats.keys())
    all_players_sorted = sorted(all_players)
    
    # Initialize all as checked
    if "defense_available_players" not in st.session_state:
        st.session_state.defense_available_players = {player: True for player in all_players_sorted}
    
    # Create rows of checkboxes for players
    cols_per_row = 3
    for i in range(0, len(all_players_sorted), cols_per_row):
        cols = st.columns(cols_per_row)
        for j in range(cols_per_row):
            if i + j < len(all_players_sorted):
                player = all_players_sorted[i + j]
                idx = j % cols_per_row
                st.session_state.defense_available_players[player] = cols[idx].checkbox(
                    player, 
                    value=st.session_state.defense_available_players.get(player, True),
                    key=f"defense_player_{player}"
                )
    
    # Get currently available players
    available_players = [p for p, available in st.session_state.defense_available_players.items() if available]
    
    # Create tabs for Singles and Doubles formats
    tabs = st.tabs(["Singles", "Doubles"])
    
    format_assignments = {}
    
    # Tab for Singles format
    with tabs[0]:
        st.markdown("#### Singles Format")
        st.markdown("Enter machines picked by the opponent:")
        
        # Initialize picked machines in session state if not already there
        if "singles_opponent_picks" not in st.session_state:
            st.session_state["singles_opponent_picks"] = []
        
        # Allow adding new picked machines
        all_machines = sorted(machine_advantage_df['Machine'].tolist())
        new_machine = st.selectbox(
            "Add a machine:", 
            [""] + [m for m in all_machines if m not in st.session_state["singles_opponent_picks"]],
            key=f"add_machine_singles"
        )
        
        if new_machine and st.button("Add Machine", key="add_btn_singles"):
            st.session_state["singles_opponent_picks"].append(new_machine)
            st.rerun()
        
        # Display current picked machines with option to remove
        if st.session_state["singles_opponent_picks"]:
            st.markdown("**Machines Picked by Opponent:**")
            
            for idx, machine in enumerate(st.session_state["singles_opponent_picks"]):
                col1, col2 = st.columns([0.8, 0.2])
                
                with col1:
                    st.markdown(f"{idx+1}. {machine.title()}")
                    
                with col2:
                    if st.button("Remove", key=f"remove_singles_{idx}"):
                        st.session_state["singles_opponent_picks"].remove(machine)
                        st.rerun()
            
            # If we have machines picked, allow player assignment optimization
            if len(st.session_state["singles_opponent_picks"]) > 0:
                st.markdown("#### Optimize Player Assignments")
                
                if st.button("Optimize Singles Assignments", key="optimize_defense_singles"):
                    picked_machines = st.session_state["singles_opponent_picks"]
                    
                    # Make sure we have enough players
                    players_needed = len(picked_machines)
                    
                    if len(available_players) >= players_needed:
                        # Create a score matrix for the assignment problem
                        machine_player_scores = {}
                        
                        for machine in picked_machines:
                            machine_player_scores[machine] = {}
                            
                            for player in available_players:
                                # Get this player's stats on this machine
                                if player in player_machine_stats and machine in player_machine_stats[player]['machines']:
                                    # Player has played this machine
                                    machine_stats = player_machine_stats[player]['machines'][machine]
                                    pct = machine_stats['pct_of_venue']
                                    plays = machine_stats['plays_count']
                                    
                                    # Higher is better - we want our best players on these machines
                                    score = pct * (1 + min(plays / 5, 1))  # Experience bonus
                                else:
                                    # Player hasn't played this machine - use overall average
                                    if player in player_machine_stats:
                                        score = player_machine_stats[player]['overall_average_pct_of_venue'] * 0.7  # Discount for uncertainty
                                    else:
                                        # No data for this player
                                        score = 50  # Default middle score
                                
                                machine_player_scores[machine][player] = score
                        
                        # Create cost matrix for Hungarian algorithm (negative scores since it minimizes)
                        cost_matrix = np.zeros((len(picked_machines), len(available_players)))
                        
                        for i, machine in enumerate(picked_machines):
                            for j, player in enumerate(available_players):
                                cost_matrix[i, j] = -machine_player_scores[machine][player]
                        
                        # Find optimal assignment
                        row_ind, col_ind = linear_sum_assignment(cost_matrix)
                        
                        # Create player assignments
                        player_assignments = {}
                        for i, j in zip(row_ind, col_ind):
                            machine = picked_machines[i]
                            player = available_players[j]
                            player_assignments[machine] = [player]
                        
                        # Store the assignments
                        format_assignments["Singles"] = player_assignments
                        
                        # Display the assignments
                        st.markdown("**Recommended Player Assignments:**")
                        
                        for machine, players in player_assignments.items():
                            st.markdown(f"**{machine.title()}**: {', '.join(players)}")
                            
                            # Display player stats on this machine
                            expander = st.expander(f"Player stats for {machine.title()}")
                            with expander:
                                for player in players:
                                    if player in player_machine_stats:
                                        player_stats = player_machine_stats[player]
                                        if machine in player_stats['machines']:
                                            machine_stats = player_stats['machines'][machine]
                                            st.markdown(f"**{player}**: {machine_stats['pct_of_venue']:.1f}% of venue average, "
                                                      f"played {machine_stats['plays_count']} times, "
                                                      f"avg score: {machine_stats['average_score']:.0f}")
                                        else:
                                            st.markdown(f"**{player}**: No experience on this machine. "
                                                      f"Overall average: {player_stats['overall_average_pct_of_venue']:.1f}%")
                                    else:
                                        st.markdown(f"**{player}**: No data available")
                    else:
                        st.error(f"Not enough available players. Need {players_needed}, have {len(available_players)}.")
        
        # If we already have assignments for singles, display them
        if "Singles" in format_assignments:
            st.markdown("**Current Assignments:**")
            for machine, players in format_assignments["Singles"].items():
                st.markdown(f"**{machine.title()}**: {', '.join(players)}")
    
    # Tab for Doubles format
    with tabs[1]:
        st.markdown("#### Doubles Format")
        st.markdown("Enter machines picked by the opponent:")
        
        # Initialize picked machines in session state if not already there
        if "doubles_opponent_picks" not in st.session_state:
            st.session_state["doubles_opponent_picks"] = []
        
        # Allow adding new picked machines
        all_machines = sorted(machine_advantage_df['Machine'].tolist())
        new_machine = st.selectbox(
            "Add a machine:", 
            [""] + [m for m in all_machines if m not in st.session_state["doubles_opponent_picks"]],
            key=f"add_machine_doubles"
        )
        
        if new_machine and st.button("Add Machine", key="add_btn_doubles"):
            st.session_state["doubles_opponent_picks"].append(new_machine)
            st.rerun()
        
        # Display current picked machines with option to remove
        if st.session_state["doubles_opponent_picks"]:
            st.markdown("**Machines Picked by Opponent:**")
            
            for idx, machine in enumerate(st.session_state["doubles_opponent_picks"]):
                col1, col2 = st.columns([0.8, 0.2])
                
                with col1:
                    st.markdown(f"{idx+1}. {machine.title()}")
                    
                with col2:
                    if st.button("Remove", key=f"remove_doubles_{idx}"):
                        st.session_state["doubles_opponent_picks"].remove(machine)
                        st.rerun()
            
            # If we have machines picked, allow player assignment optimization
            if len(st.session_state["doubles_opponent_picks"]) > 0:
                st.markdown("#### Optimize Player Assignments")
                
                if st.button("Optimize Doubles Assignments", key="optimize_defense_doubles"):
                    picked_machines = st.session_state["doubles_opponent_picks"]
                    
                    # Make sure we have enough players
                    players_needed = len(picked_machines) * 2
                    
                    if len(available_players) >= players_needed:
                        import itertools
                        
                        # For doubles, we need to assign pairs
                        # Sort players by overall skill
                        sorted_players = sorted(
                            available_players,
                            key=lambda p: player_machine_stats.get(p, {}).get('overall_average_pct_of_venue', 0),
                            reverse=True
                        )
                        
                        # Get all possible player pairs
                        player_pairs = list(itertools.combinations(available_players, 2))
                        
                        # Create a score dictionary for each pair-machine combination
                        pair_machine_scores = {}
                        for pair in player_pairs:
                            player1, player2 = pair
                            pair_machine_scores[pair] = {}
                            
                            for machine in picked_machines:
                                # Calculate scores for individual players
                                scores = []
                                for player in [player1, player2]:
                                    if player in player_machine_stats and machine in player_machine_stats[player]['machines']:
                                        stats = player_machine_stats[player]['machines'][machine]
                                        player_score = stats['pct_of_venue'] * (1 + min(stats['plays_count'] / 5, 1))
                                    else:
                                        # Use overall average for players without experience
                                        if player in player_machine_stats:
                                            player_score = player_machine_stats[player]['overall_average_pct_of_venue'] * 0.7
                                        else:
                                            player_score = 50
                                    scores.append(player_score)
                                
                                # Combine scores - we want pairs where both players are good
                                combined_score = (scores[0] + scores[1]) * 0.5 + min(scores) * 0.5
                                pair_machine_scores[pair][machine] = combined_score
                        
                        # Now optimize the assignments
                        used_players = set()
                        used_machines = set()
                        player_assignments = {}
                        
                        # For each machine, find the best available pair
                        for machine in picked_machines:
                            best_score = -1
                            best_pair = None
                            
                            for pair in player_pairs:
                                player1, player2 = pair
                                
                                # Skip if any player is already assigned
                                if player1 in used_players or player2 in used_players:
                                    continue
                                
                                # Get the score for this pair on this machine
                                score = pair_machine_scores[pair].get(machine, 0)
                                
                                # Update best pair if this is better
                                if score > best_score:
                                    best_score = score
                                    best_pair = pair
                            
                            # Assign the best pair to this machine
                            if best_pair:
                                player1, player2 = best_pair
                                player_assignments[machine] = [player1, player2]
                                used_players.add(player1)
                                used_players.add(player2)
                                used_machines.add(machine)
                        
                        # Store the assignments
                        format_assignments["Doubles"] = player_assignments
                        
                        # Display the assignments
                        st.markdown("**Recommended Player Assignments:**")
                        
                        for machine, players in player_assignments.items():
                            st.markdown(f"**{machine.title()}**: {', '.join(players)}")
                            
                            # Display player stats on this machine
                            expander = st.expander(f"Player stats for {machine.title()}")
                            with expander:
                                for player in players:
                                    if player in player_machine_stats:
                                        player_stats = player_machine_stats[player]
                                        if machine in player_stats['machines']:
                                            machine_stats = player_stats['machines'][machine]
                                            st.markdown(f"**{player}**: {machine_stats['pct_of_venue']:.1f}% of venue average, "
                                                      f"played {machine_stats['plays_count']} times, "
                                                      f"avg score: {machine_stats['average_score']:.0f}")
                                        else:
                                            st.markdown(f"**{player}**: No experience on this machine. "
                                                      f"Overall average: {player_stats['overall_average_pct_of_venue']:.1f}%")
                                    else:
                                        st.markdown(f"**{player}**: No data available")
                    else:
                        st.error(f"Not enough available players. Need {players_needed}, have {len(available_players)}.")
        
        # If we already have assignments for doubles, display them
        if "Doubles" in format_assignments:
            st.markdown("**Current Assignments:**")
            for machine, players in format_assignments["Doubles"].items():
                st.markdown(f"**{machine.title()}**: {', '.join(players)}")
    
    # Return the player assignments
    return format_assignments

def add_player_assignment_section():
    """
    Add the player assignment section to the Streamlit app.
    """
    import streamlit as st
    
    st.markdown("## Player Assignment Strategy (When Opponent Picks)")
    
    # This section should only be run after data has been processed
    if not st.session_state.get("kellanate_output", False) or "debug_outputs" not in st.session_state:
        st.warning("Please run 'Kellanate' first to process the data.")
        return
    
    # Get the required data from session state
    all_data_df = st.session_state["debug_outputs"].get("all_data")
    selected_team = st.session_state.get("select_team_json", "")
    selected_venue = st.session_state.get("select_venue_json", "")
    roster_data = st.session_state.get("roster_data", {})
    
    if all_data_df is not None and not all_data_df.empty:
        # Run the player assignment analysis for TWC
        player_assignments = analyze_player_assignment_strategy(
            all_data_df, selected_team, selected_venue, roster_data
        )
        
        # Store the results in session state for later use
        st.session_state["defense_player_assignments"] = player_assignments
    else:
        st.error("No data available. Please make sure you've loaded match data.")

##############################################
# Section 13.4: machine picking algorithm - Integration
##############################################

def add_strategic_sections():
    """
    Add the strategic picking and player assignment sections to the Streamlit app.
    This uses tabs to organize the different strategic tools.
    """
    import streamlit as st
    
    # Create tabs for the different strategic sections
    strategic_tabs = st.tabs(["Machine Picking Strategy", "Player Assignment Strategy"])
    
    with strategic_tabs[0]:
        # Add the machine picking strategy section
        add_strategic_picking_section()
    
    with strategic_tabs[1]:
        # Add the player assignment strategy section
        add_player_assignment_section()

# This section would be added to the main code, after the original "Kellanate" output is displayed
def integrate_strategic_features():
    """
    Integrate the strategic features into the main Streamlit app.
    This function would be called in the main app flow after the original Kellanate output.
    """
    import streamlit as st
    
    # Only show the strategic sections if Kellanate has been run
    if st.session_state.get("kellanate_output", False):
        # Add a section title
        st.markdown("---")
        st.markdown("## Strategic Match Planning Tools")
        
        # Add the checkbox to toggle the strategic features
        show_strategic = st.checkbox("Show Strategic Planning Tools", value=False)
        
        if show_strategic:
            # Add the strategic sections
            add_strategic_sections()

##############################################
# Section 14: Strategic Machine Picking
##############################################

if st.session_state.get("kellanate_output", False):
    # Add a section title
    st.markdown("---")
    st.markdown("## Strategic Match Planning Tools")
    
    # Add the checkbox to toggle the strategic features
    show_strategic = st.checkbox("Show Strategic Planning Tools", value=False)
    
    if show_strategic:
        # Add the strategic sections
        add_strategic_sections()
