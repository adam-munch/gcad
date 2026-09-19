import tkinter as tk
from tkinter import ttk

from ttkbootstrap import Style as BootstrapStyle

from dpi import s

STATUS_LABELS = {
    'unchanged': 'Ready',
    'modified': 'Modified',
    'new': 'New',
    'deleted': 'Deleted',
    'conflicted': 'Conflicted',
    'locked_by_me': 'Locked (You)',
    'locked_by_other': 'Locked',
    'locked_by_me_modified': 'Locked (You) * Modified',
    'locked_by_other_modified': 'Locked * Modified',
    'locked_by_me_new': 'Locked (You) * New',
    'locked_by_other_new': 'Locked * New',
}

STATUS_ROLES = {
    'unchanged': 'secondary',
    'modified': 'warning',
    'new': 'success',
    'deleted': 'danger',
    'conflicted': 'danger',
    'locked_by_me': 'info',
    'locked_by_other': 'danger',
    'locked_by_me_modified': 'info',
    'locked_by_other_modified': 'danger',
    'locked_by_me_new': 'success',
    'locked_by_other_new': 'danger',
}


class FileTable(ttk.Frame):
    def __init__(self, master, on_file_select=None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_file_select = on_file_select
        self._file_map = {}

        self._create_widgets()

    def _create_widgets(self):
        vsb = ttk.Scrollbar(self, orient='vertical')
        hsb = ttk.Scrollbar(self, orient='horizontal')

        self.tree = ttk.Treeview(
            self,
            columns=('status', 'locked_by'),
            show='tree headings',
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set,
            selectmode='extended',
        )

        vsb.config(command=self.tree.yview)
        hsb.config(command=self.tree.xview)

        self.tree.heading('#0', text='File', anchor='w')
        self.tree.heading('status', text='Status', anchor='w')
        self.tree.heading('locked_by', text='Locked By', anchor='w')

        self.tree.column('#0', width=s(500), minwidth=s(200), stretch=True)
        self.tree.column('status', width=s(180), minwidth=s(100), stretch=False)
        self.tree.column('locked_by', width=s(120), minwidth=s(80), stretch=False)

        self._apply_theme()
        self.tree.bind('<<ThemeChanged>>', self._apply_theme, add='+')

        self.tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.tree.bind('<<TreeviewSelect>>', self._on_select)

    def _apply_theme(self, event=None):
        colors = BootstrapStyle().colors
        for status, role in STATUS_ROLES.items():
            self.tree.tag_configure(status, foreground=getattr(colors, role))
        self.tree.tag_configure('folder', foreground=colors.fg, font=('Segoe UI', 10, 'bold'))
        self.tree.tag_configure('empty', foreground=colors.secondary)

    def _on_select(self, event):
        if self.on_file_select:
            self.on_file_select(self.get_selected_files())

    def populate(self, statuses):
        selected = set(self.tree.selection())
        expanded = set()
        def remember(parent=''):
            for iid in self.tree.get_children(parent):
                if iid.startswith('dir:'):
                    if self.tree.item(iid, 'open'):
                        expanded.add(iid)
                    remember(iid)
        remember()
        self.tree.delete(*self.tree.get_children())
        self._file_map = {}

        path_nodes = {}

        for info in statuses:
            parts = info['path'].split('/')
            parent_iid = ''

            for i, part in enumerate(parts[:-1]):
                dir_iid = 'dir:' + '/'.join(parts[:i + 1]) + '/'
                if dir_iid not in path_nodes:
                    display = part + '/'
                    parent = path_nodes.get('dir:' + '/'.join(parts[:i]) + '/', '') if i > 0 else ''
                    node = self.tree.insert(
                        parent, 'end',
                        iid=dir_iid,
                        text=display,
                        values=('', ''),
                        open=dir_iid in expanded,
                        tags=('folder',),
                    )
                    path_nodes[dir_iid] = node
                parent_iid = dir_iid

            if parent_iid == '':
                parent_iid = ''

            file_name = parts[-1]
            status_label = STATUS_LABELS.get(info['status'], info['status'])
            locked_by = info.get('locked_by', '') or ''
            if not info.get('locks_verified', True):
                if info['status'] == 'unchanged':
                    status_label = 'Unchanged'
                locked_by = 'Not verified'
            values = (status_label, locked_by)

            file_iid = 'file:' + info['path']
            self.tree.insert(
                parent_iid, 'end',
                iid=file_iid,
                text=file_name,
                values=values,
                tags=(info['status'],),
            )
            self._file_map[file_iid] = info

        self.tree.selection_set([iid for iid in selected if self.tree.exists(iid)])
        if not statuses:
            self.tree.insert('', 'end', text='No CAD files or local changes to display', iid='empty', tags=('empty',))

    def get_selected_files(self):
        selected = []
        for iid in self.tree.selection():
            if iid.startswith('file:'):
                info = self._file_map.get(iid)
                if info:
                    selected.append(info)
            elif iid.startswith('dir:'):
                children = self._collect_files(iid)
                selected.extend(children)
        return list({info['path']: info for info in selected}.values())

    def _collect_files(self, parent_iid):
        files = []
        for child in self.tree.get_children(parent_iid):
            if child.startswith('file:'):
                info = self._file_map.get(child)
                if info:
                    files.append(info)
            elif child.startswith('dir:'):
                files.extend(self._collect_files(child))
        return files

    def clear(self):
        self.tree.delete(*self.tree.get_children())
        self._file_map = {}
