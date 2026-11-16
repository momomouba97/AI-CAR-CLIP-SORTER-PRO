"""Library logic independent of the UI: paging, search/sort/filter and selection."""
import math


def format_duration(seconds) -> str:
    s = int(seconds or 0)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


class VideoManager:
    def __init__(self, db, page_size=50):
        self.db = db
        self.page_size = max(1, int(page_size))
        self.channel_id = None
        self.search = ""
        self.sort = "date"
        self.descending = True
        self.status = "all"
        self.page = 0  # zero-based

    # ---- query state -----------------------------------------------------
    def set_channel(self, channel_id):
        self.channel_id = channel_id or None
        self.page = 0

    def set_search(self, text):
        self.search = (text or "").strip()
        self.page = 0

    def set_sort(self, sort, descending=None):
        self.sort = sort
        if descending is not None:
            self.descending = descending
        self.page = 0

    def set_filter(self, status):
        self.status = status
        self.page = 0

    # ---- paging ----------------------------------------------------------
    def total(self):
        return self.db.count_videos(self.channel_id, self.search, self.status)

    def total_pages(self):
        return max(1, math.ceil(self.total() / self.page_size))

    def goto(self, page):
        self.page = max(0, min(int(page), self.total_pages() - 1))
        return self.page

    def next_page(self):
        return self.goto(self.page + 1)

    def prev_page(self):
        return self.goto(self.page - 1)

    def rows(self):
        self.goto(self.page)  # clamp if the result set shrank
        return self.db.query_videos(self.channel_id, self.search, self.status, self.sort,
                                    self.descending, self.page_size, self.page * self.page_size)

    # ---- selection (stored in SQLite, survives page changes and restarts) ---
    def toggle(self, video_id, checked):
        self.db.set_selected([video_id], checked)
        row = self.db.get_video(video_id)
        return bool(row and row["selected"]) == bool(checked)

    def select_current_page(self, selected=True):
        ids = [r["video_id"] for r in self.rows()]
        self.db.set_selected(ids, selected)
        return len(ids)

    def select_entire_channel(self):
        return self.db.select_where(self.channel_id, "", "all", True)

    def select_matching(self):
        """Select every video matching the current search and filter (all pages)."""
        return self.db.select_where(self.channel_id, self.search, self.status, True)

    def deselect_all(self):
        self.db.clear_selection(None)

    def summary(self):
        s = self.db.selection_summary(None)
        on_page = sum(1 for r in self.rows() if r["selected"])
        return {"selected": s["count"], "on_page": on_page,
                "duration": s["duration"], "duration_text": format_duration(s["duration"])}
