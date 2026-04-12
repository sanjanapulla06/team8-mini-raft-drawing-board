# log.py — Append-only stroke log with commit index tracking
# Week 2 — Shrivadhu

class Log:
    def __init__(self):
        self.entries = []        # [ { "index", "term", "stroke" } ]
        self.commit_index = -1   # highest committed index

    def append(self, term, stroke):
        """Leader appends a new stroke entry before replication"""
        index = len(self.entries)
        entry = {"index": index, "term": term, "stroke": stroke}
        self.entries.append(entry)
        print(f"[LOG] Appended index={index} term={term}")
        return entry

    def get_entry(self, index):
        """Get entry at a specific index"""
        if 0 <= index < len(self.entries):
            return self.entries[index]
        return None

    def get_from(self, from_index):
        """Get all entries from from_index onward — used for sync-log catch-up"""
        return self.entries[from_index:]

    @property
    def length(self):
        return len(self.entries)

    @property
    def last_term(self):
        """Term of last log entry, -1 if empty"""
        if not self.entries:
            return -1
        return self.entries[-1]["term"]

    @property
    def last_index(self):
        """Index of last log entry, -1 if empty"""
        return len(self.entries) - 1

    def append_entries(self, prev_log_index, prev_log_term, entries):
        """
        Follower: check consistency, truncate conflicts, append new entries.
        Returns True if ok, False if prevLogIndex check fails.
        """
        if prev_log_index >= 0:
            prev = self.get_entry(prev_log_index)
            if prev is None or prev["term"] != prev_log_term:
                print(f"[LOG] Consistency fail: prev_log_index={prev_log_index} prev_log_term={prev_log_term}")
                return False

        # Truncate conflicting entries
        self.entries = self.entries[:prev_log_index + 1]

        # Append new entries
        for entry in entries:
            self.entries.append(entry)
            print(f"[LOG] Follower appended index={entry['index']} term={entry['term']}")

        return True

    def advance_commit(self, leader_commit):
        """Advance commit_index forward only — never go back"""
        new_commit = min(leader_commit, len(self.entries) - 1)
        if new_commit > self.commit_index:
            print(f"[LOG] Commit index advanced {self.commit_index} → {new_commit}")
            self.commit_index = new_commit

    def committed_entries(self):
        """Return all committed entries"""
        return self.entries[:self.commit_index + 1]