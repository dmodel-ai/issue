"""TUI: Textual-based interface."""
import subprocess
import yaml

from .store import all_issues, load, num, resolve, refs
from .views import inbox_issues, outbox_issues

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

        def matches_filter(self, issue):
            for term in self.filter_text.split():
                negate = term.startswith('-')
                if negate:
                    term = term[1:]
                if ':' in term:
                    field, val = term.split(':', 1)
                    val = val.lower()
                    if field == 'owner':
                        match = val in issue.get('owner', '').lower()
                    elif field == 'status':
                        match = val in issue.get('status', '').lower()
                    elif field == 'label':
                        match = any(val in l.lower() for l in issue.get('labels', []))
                    elif field == 'reviewer':
                        match = any(val in r.lower() for r in issue.get('reviewers', []))
                    elif field == 'cc':
                        match = any(val in c.lower() for c in issue.get('cc', []))
                    elif field == 'attention':
                        match = any(val in a.lower() for a in issue.get('attention', []))
                    elif field == 'blocks':
                        match = any(val in str(num(b)) for b in issue.get('blocks', []))
                    elif field == 'blocked':
                        match = any(val in str(num(b)) for b in issue.get('blocked_by', []))
                    else:
                        match = val in yaml.dump(issue).lower()
                else:
                    match = term.lower() in yaml.dump(issue).lower()
                if negate:
                    match = not match
                if not match:
                    return False
            return True

        def load_issues(self):
            table = self.query_one("#issues", DataTable)
            table.clear(columns=True)
            table.add_columns("#", "Status", "Owner", "Title", "Deps")
            table.cursor_type = "row"
            issues = self.get_issues()
            if self.filter_text:
                issues = [i for i in issues if self.matches_filter(i)]
            self.query_one("#filter", Static).update(f"[bold]{self.view}[/]" + (f" /{self.filter_text}" if self.filter_text else ""))
            for i in issues:
                deps = f"→{refs(i['blocks'])}" if i.get('blocks') else \
                       f"←{refs(i['blocked_by'])}" if i.get('blocked_by') else ""
                attn = "⚠️" if i.get('attention') else ""
                table.add_row(
                    f"#{num(i['id'])}", i['status'], i['owner'],
                    f"{attn} {i['title'][:40]}", deps,
                    key=i['id']
                )

        def get_selected_id(self):
            table = self.query_one("#issues", DataTable)
            if table.cursor_row is not None:
                return table.get_row_at(table.cursor_row)[0].lstrip('#')
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
                    lines = [
                        f"[bold]#{n}[/] {i['title']}",
                        f"status: {i['status']}  owner: {i['owner']}",
                        f"attention: {', '.join(i.get('attention', []))}",
                    ]
                    if i.get('comments'):
                        lines.append("")
                        for c in i['comments'][-3:]:
                            lines.append(f"  {c['author']}: {c['text'][:60]}")
                    detail.update("\n".join(lines))

        def action_refresh(self):
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

        def action_search(self):
            from textual.widgets import Input
            self.mount(Input(placeholder="Filter...", id="search_input"), before="#issues")
            self.query_one("#search_input").focus()

        def on_input_submitted(self, event):
            self.filter_text = event.value
            event.input.remove()
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
            opts = [Option(f"#{num(i)} {load(i)['title'][:40]}", id=i) for i in ids]
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
            subprocess.run(["issue", "s", n])
        elif cmd == "comment":
            subprocess.run(["issue", "c", n])
        elif cmd == "edit":
            subprocess.run(["issue", "e", n])
        input("\nPress Enter to return to TUI...")
