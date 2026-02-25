"""TUI: Textual-based interface."""
import subprocess
from datetime import datetime, timedelta

from .store import all_issues, load, num, resolve, refs
from .cli.views import inbox_issues, outbox_issues
from .workflows import status_colors, DONE_STATE, phase_order
from .query import filter_issues, parse_query

# Owner -> Rich color mapping
OWNER_COLORS = {
    'alex': 'white on red', 'anish': 'white on purple', 'adam': 'black on green',
    'dmoon': 'white on navy_blue', 'curry': 'black on yellow',
}

def cmd_tui(_):
    from textual.app import App, ComposeResult
    from textual.widgets import DataTable, Footer, Header, Static
    from textual.binding import Binding

    class IssueApp(App):
        BINDINGS = [
            Binding("q", "quit", "Quit"),
            Binding("r", "refresh", "Refresh"),
            Binding("c", "comment", "Comment"),
            Binding("e", "edit", "Edit"),
            Binding("i", "view_inbox", "Inbox"),
            Binding("o", "view_outbox", "Outbox"),
            Binding("a", "view_all", "All"),
            Binding("g", "view_gantt", "Gantt"),
            Binding("v", "toggle_verbose", "Verbose"),
            Binding("/", "search", "Search"),
            Binding("l", "goto_blocker", "→Blocker"),
            Binding("h", "goto_blocked", "←Blocked"),
        ]
        CSS = """
        DataTable { height: 1fr; }
        #detail { height: auto; max-height: 40%; border-top: solid green; padding: 1; }
        #filter { height: 1; }
        """

        def __init__(self):
            super().__init__()
            self.view = "inbox"
            self.filter_text = ""
            self.gantt_verbose = False

        def compose(self) -> ComposeResult:
            yield Header()
            yield Static("", id="filter")
            yield DataTable(id="issues")
            yield Static("", id="detail")
            yield Footer()

        def on_mount(self):
            self.load_issues()

        def get_issues(self):
            if self.view == "inbox":
                return inbox_issues()
            elif self.view == "outbox":
                return outbox_issues()
            else:
                return all_issues()

        def load_issues(self):
            table = self.query_one("#issues", DataTable)
            table.clear(columns=True)
            table.add_columns("#", "Status", "Owner", "Title", "Deps")
            table.cursor_type = "row"
            issues = self.get_issues()
            if self.filter_text:
                issues = filter_issues(issues, self.filter_text)
            self.query_one("#filter", Static).update(f"[bold]{self.view}[/]" + (f" /{self.filter_text}" if self.filter_text else ""))
            for i in issues:
                deps = f"→{refs(i['blocks'])}" if i.get('blocks') else \
                       f"←{refs(i['blocked_by'])}" if i.get('blocked_by') else ""
                attn = "⚠️" if i.get('attention') else ""
                sc = status_colors.get(i['status'], '')
                status = f"[{sc}]{i['status']}[/{sc}]" if sc else i['status']
                table.add_row(
                    f"#{num(i['id'])}", status, i['owner'],
                    f"{attn} {i['title'][:37]}..." if len(i['title']) > 40 else f"{attn} {i['title']}", deps,
                    key=i['id']
                )

        def get_selected_id(self):
            from textual.widgets.data_table import RowDoesNotExist
            table = self.query_one("#issues", DataTable)
            if table.cursor_row is not None:
                try:
                    return table.get_row_at(table.cursor_row)[0].lstrip('#')
                except RowDoesNotExist:
                    return None
            return None

        def on_data_table_row_selected(self, event):
            n = self.get_selected_id()
            if n:
                self.app.exit(result=("show", n))

        def on_data_table_row_highlighted(self, event):
            self.show_issue_detail()

        def show_issue_detail(self):
            n = self.get_selected_id()
            if n:
                id = resolve(n)
                if id:
                    i = load(id)
                    detail = self.query_one("#detail", Static)
                    sc = status_colors.get(i['status'], '')
                    status = f"[{sc}]{i['status']}[/{sc}]" if sc else i['status']
                    lines = [
                        f"[bold]#{n}[/] {i['title']}",
                        f"status: {status}  owner: {i['owner']}",
                        f"attention: {', '.join(i.get('attention', []))}",
                    ]
                    if i.get('comments'):
                        lines.append("")
                        for c in i['comments'][-3:]:
                            lines.append(f"  {c['author']}: {c['text'][:57]}..." if len(c['text']) > 60 else f"  {c['author']}: {c['text']}")
                    detail.update("\n".join(lines))

        def action_refresh(self):
            if self.view == "gantt":
                self.load_gantt()
            else:
                self.load_issues()
            self.query_one("#detail", Static).update("")

        def action_view_inbox(self):
            self.view = "inbox"
            self.load_issues()

        def action_view_outbox(self):
            self.view = "outbox"
            self.load_issues()

        def action_view_all(self):
            self.view = "all"
            self.load_issues()

        def action_view_gantt(self):
            self.view = "gantt"
            self.load_gantt()

        def action_toggle_verbose(self):
            if self.view == "gantt":
                self.gantt_verbose = not self.gantt_verbose
                self.load_gantt()

        def load_gantt(self):
            table = self.query_one("#issues", DataTable)
            table.clear(columns=True)
            table.cursor_type = "row"

            # Parse query to separate phase filter from issue filter
            phase_filter = ""
            issue_query = self.filter_text
            if self.filter_text:
                terms = parse_query(self.filter_text)
                phase_terms = [t for t in terms if t.field == 'phase']
                other_terms = [t for t in terms if t.field != 'phase']
                if phase_terms:
                    phase_filter = phase_terms[0].value
                if other_terms:
                    # Rebuild query string without phase terms
                    parts = []
                    for t in other_terms:
                        prefix = '-' if t.negate else ''
                        if t.field:
                            parts.append(f"{prefix}{t.field}:{t.value}")
                        else:
                            parts.append(f"{prefix}{t.value}")
                    issue_query = ' '.join(parts)
                else:
                    issue_query = ""

            issues = [i for i in all_issues() if i.get('due')]
            if issue_query:
                issues = filter_issues(issues, issue_query)
            if not issues:
                self.query_one("#filter", Static).update("[bold]gantt[/] (no issues with due dates)")
                return

            today = datetime.now().date()
            start_date = today - timedelta(days=today.weekday())
            weeks = 6
            end_date = start_date + timedelta(weeks=weeks)
            total_days = (end_date - start_date).days
            days_per_week = 7
            def parse_date(s):
                try:
                    return datetime.strptime(s[:10], "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    return None

            def render_week_bar(bar_start, bar_end, owner, behind=False, done=False):
                """Render bar split into week columns."""
                week_bars = []
                for w in range(weeks):
                    start_idx = w * days_per_week
                    end_idx = start_idx + days_per_week
                    week_bar = []
                    for day in range(start_idx, min(end_idx, total_days)):
                        d = start_date + timedelta(days=day)
                        if bar_start and bar_end and bar_start <= d <= bar_end:
                            color = OWNER_COLORS.get(owner, 'white on navy_blue')
                            fill = '-' if done else '*' if behind else ' '
                            week_bar.append(f"[{color}]{fill}[/]")
                        elif d == today:
                            week_bar.append("[bold]|[/]")
                        else:
                            week_bar.append(".")
                    week_bars.append("".join(week_bar))
                return week_bars

            # Build week headers
            header_dates = []
            d = start_date
            while d < end_date:
                header_dates.append(d.strftime('%m/%d'))
                d += timedelta(weeks=1)
            table.add_columns("Issue", *header_dates)

            # Legend
            legend_parts = [f"[{c}]{n}[/]" for n, c in OWNER_COLORS.items()]
            verbose_indicator = " [v]" if self.gantt_verbose else ""
            filter_indicator = f" /{self.filter_text}" if self.filter_text else ""
            self.query_one("#filter", Static).update(
                f"[bold]gantt{verbose_indicator}[/]{filter_indicator} " +
                " ".join(legend_parts) + " [-]=done [*]=behind"
            )

            for i in issues:
                alias = i.get('alias') or f"#{num(i['id'])}"
                due = i.get('due', {})
                owner = i.get('owner', '')
                reviewers = i.get('reviewers', [])
                reviewer = reviewers[0] if reviewers else owner
                current_idx = phase_order.index(i['status']) if i['status'] in phase_order else 0

                phases = [(s, parse_date(due[s])) for s in phase_order if s in due and s != DONE_STATE]
                done_date = parse_date(due.get(DONE_STATE, ''))
                if not phases:
                    continue

                any_behind = any(today > start and phase_order.index(s) > current_idx for s, start in phases)
                is_done = i['status'] == DONE_STATE
                header_end = done_date or phases[-1][1]

                # Header row
                week_bars = render_week_bar(phases[0][1], header_end, owner, any_behind, is_done)
                table.add_row(alias, *week_bars, key=i['id'])

                # Phase breakdown rows in verbose mode
                if self.gantt_verbose:
                    for idx, (state, phase_start) in enumerate(phases):
                        if phase_filter and phase_filter not in state:
                            continue
                        if idx + 1 < len(phases):
                            phase_end = phases[idx + 1][1]
                        else:
                            phase_end = done_date or phase_start
                        phase_idx = phase_order.index(state)
                        phase_done = current_idx > phase_idx
                        behind = today > phase_start and current_idx < phase_idx
                        phase_owner = reviewer if state in ('pqa', 'iqa') else owner
                        week_bars = render_week_bar(phase_start, phase_end, phase_owner, behind, phase_done)
                        table.add_row(f"  {state}", *week_bars, key=f"{i['id']}_{state}")

        def action_search(self):
            from textual.widgets import Input
            self.mount(Input(placeholder="Filter...", id="search_input"), before="#issues")
            self.query_one("#search_input").focus()

        def on_input_submitted(self, event):
            self.filter_text = event.value
            event.input.remove()
            if self.view == "gantt":
                self.load_gantt()
            else:
                self.load_issues()

        def action_comment(self):
            n = self.get_selected_id()
            if n:
                self.app.exit(result=("comment", n))

        def action_edit(self):
            n = self.get_selected_id()
            if n:
                self.app.exit(result=("edit", n))

        def goto_issue(self, target_id):
            self.view = "all"
            self.filter_text = ""
            self.load_issues()
            table = self.query_one("#issues", DataTable)
            for row_idx, row_key in enumerate(table.rows):
                if row_key.value == target_id:
                    table.cursor_coordinate = (row_idx, 0)
                    break

        def action_goto_blocker(self):
            n = self.get_selected_id()
            if not n:
                return
            issue = load(resolve(n))
            blockers = issue.get('blocked_by', [])
            if not blockers:
                return
            if len(blockers) == 1:
                self.goto_issue(blockers[0])
            else:
                self.show_picker(blockers, "Blocked by:")

        def action_goto_blocked(self):
            n = self.get_selected_id()
            if not n:
                return
            issue = load(resolve(n))
            blocked = issue.get('blocks', [])
            if not blocked:
                return
            if len(blocked) == 1:
                self.goto_issue(blocked[0])
            else:
                self.show_picker(blocked, "Blocks:")

        def show_picker(self, ids, title):
            from textual.widgets import OptionList
            from textual.widgets.option_list import Option
            opts = [Option(f"#{num(i)} {load(i)['title'][:37]}..." if len(load(i)['title']) > 40 else f"#{num(i)} {load(i)['title']}", id=i) for i in ids]
            picker = OptionList(*opts, id="picker")
            self.query_one("#filter", Static).update(title)
            self.mount(picker, after="#filter")
            picker.focus()

        def on_option_list_option_selected(self, event):
            target_id = event.option.id
            event.option_list.remove()
            self.goto_issue(target_id)

    while True:
        result = IssueApp().run()
        if not result:
            break
        cmd, n = result
        if cmd == "show":
            subprocess.run(["issue", "show", n])
        elif cmd == "comment":
            subprocess.run(["issue", "comment", n])
        elif cmd == "edit":
            subprocess.run(["issue", "edit", n])
        input("\nPress Enter to return to TUI...")
