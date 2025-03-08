import sqlite3
import json
import os
import streamlit as st
from github_integration import (
    get_score_limits_github, set_score_limit_github, delete_score_limit_github,
    get_venue_machine_list_github, add_machine_to_venue_github, delete_machine_from_venue_github,
    get_machine_mapping_github, save_machine_mapping_github
)

# Local database for fallback/development
DB_FILE = "global_settings.db"

# Flag to determine whether to use GitHub or local storage
USE_GITHUB = True

def init_db():
    """Initialize the database and create tables if they don't exist."""
    # Always initialize local DB for fallback/development
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Table for score limits: each row is (machine TEXT PRIMARY KEY, score_limit INTEGER)
    c.execute('''
        CREATE TABLE IF NOT EXISTS score_limits (
            machine TEXT PRIMARY KEY,
            score_limit INTEGER
        )
    ''')
    # Table for venue machine lists:
    # Each row: (venue TEXT, list_type TEXT, machine TEXT)
    # list_type is either "included" or "excluded".
    c.execute('''
        CREATE TABLE IF NOT EXISTS venue_machine_lists (
            venue TEXT,
            list_type TEXT,
            machine TEXT,
            PRIMARY KEY (venue, list_type, machine)
        )
    ''')
    conn.commit()
    conn.close()

    # Check if we're running in Streamlit Cloud by looking for 'github' in secrets
    global USE_GITHUB
    USE_GITHUB = 'github' in st.secrets if hasattr(st, 'secrets') else False

def get_score_limits():
    """Retrieve the score limits as a dictionary {machine: score_limit}."""
    if USE_GITHUB:
        limits, _ = get_score_limits_github()
        return limits
    else:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT machine, score_limit FROM score_limits")
        rows = c.fetchall()
        conn.close()
        return {machine: score_limit for machine, score_limit in rows}

def set_score_limit(machine, score_limit):
    """Set or update a score limit for a machine."""
    if USE_GITHUB:
        return set_score_limit_github(machine, score_limit)
    else:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO score_limits (machine, score_limit) VALUES (?, ?)",
                (machine, score_limit))
        conn.commit()
        conn.close()
        return True

def delete_score_limit(machine):
    """Delete a score limit for a machine."""
    if USE_GITHUB:
        return delete_score_limit_github(machine)
    else:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM score_limits WHERE machine = ?", (machine,))
        conn.commit()
        conn.close()
        return True

def get_venue_machine_list(venue, list_type):
    """Retrieve the machine list for a given venue and list type ('included' or 'excluded').  
    Returns a list of machine names."""
    if USE_GITHUB:
        return get_venue_machine_list_github(venue, list_type)
    else:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT machine FROM venue_machine_lists WHERE venue = ? AND list_type = ?", (venue, list_type))
        rows = c.fetchall()
        conn.close()
        return [row[0] for row in rows]

def add_machine_to_venue(venue, list_type, machine):
    """Add a machine to the venue machine list."""
    if USE_GITHUB:
        return add_machine_to_venue_github(venue, list_type, machine)
    else:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO venue_machine_lists (venue, list_type, machine) VALUES (?, ?, ?)",
                (venue, list_type, machine))
        conn.commit()
        conn.close()
        return True

def delete_machine_from_venue(venue, list_type, machine):
    """Remove a machine from the venue machine list."""
    if USE_GITHUB:
        return delete_machine_from_venue_github(venue, list_type, machine)
    else:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM venue_machine_lists WHERE venue = ? AND list_type = ? AND machine = ?",
                (venue, list_type, machine))
        conn.commit()
        conn.close()
        return True

def load_machine_mapping(file_path=None):
    """Load machine mapping from GitHub or local JSON file."""
    if USE_GITHUB:
        mapping, _ = get_machine_mapping_github()
        return mapping
    else:
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

def save_machine_mapping(file_path, mapping):
    """Save the machine mapping to GitHub or a local JSON file."""
    if USE_GITHUB:
        return save_machine_mapping_github(mapping)
    else:
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(mapping, f, indent=2)
            return True
        except Exception as e:
            st.error(f"Error saving machine mapping: {e}")
            return False

# Initialize the database when the module is imported.
init_db()
