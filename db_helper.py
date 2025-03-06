import sqlite3
import json

DB_FILE = "global_settings.db"

def init_db():
    """Initialize the database and create tables if they don't exist."""
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

def get_score_limits():
    """Retrieve the score limits as a dictionary {machine: score_limit}."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT machine, score_limit FROM score_limits")
    rows = c.fetchall()
    conn.close()
    return {machine: score_limit for machine, score_limit in rows}

def set_score_limit(machine, score_limit):
    """Set or update a score limit for a machine."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO score_limits (machine, score_limit) VALUES (?, ?)",
              (machine, score_limit))
    conn.commit()
    conn.close()

def delete_score_limit(machine):
    """Delete a score limit for a machine."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM score_limits WHERE machine = ?", (machine,))
    conn.commit()
    conn.close()

def get_venue_machine_list(venue, list_type):
    """Retrieve the machine list for a given venue and list type ('included' or 'excluded').  
    Returns a list of machine names."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT machine FROM venue_machine_lists WHERE venue = ? AND list_type = ?", (venue, list_type))
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]

def add_machine_to_venue(venue, list_type, machine):
    """Add a machine to the venue machine list."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO venue_machine_lists (venue, list_type, machine) VALUES (?, ?, ?)",
              (venue, list_type, machine))
    conn.commit()
    conn.close()

def delete_machine_from_venue(venue, list_type, machine):
    """Remove a machine from the venue machine list."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM venue_machine_lists WHERE venue = ? AND list_type = ? AND machine = ?",
              (venue, list_type, machine))
    conn.commit()
    conn.close()

# Initialize the database when the module is imported.
init_db()
