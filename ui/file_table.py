import tkinter as tk
from tkinter import ttk, font as tkfont

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

TAG_COLORS = {
    'unchanged': 'black',
    'modified': '#CC6600',
    'new': '#006600',
    'deleted': '#CC0000',
    'conflicted': '#CC0000',
    'locked_by_me': '#0066CC',
    'locked_by_other': '#CC0000',
    'locked_by_me_modified': '#9900CC',
    'locked_by_other_modified': '#CC0000',
    'locked_by_me_new': '#006600',
    'locked_by_other_new': '#CC0000',
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

        f = tkfont.nametofont('TkTextFont')
        style = BootstrapStyle()
        colors = style.colors
        style.configure('Treeview',
            rowheight=f.metrics('linespace') + s(8),
            indicatorsize=f.metrics('linespace'),
            indent=s(25),
            background=colors.inputbg,
            fieldbackground=colors.inputbg,
            foreground=colors.inputfg,
            bordercolor=colors.border,
            lightcolor=colors.inputbg,
            darkcolor=colors.inputbg,
            borderwidth=s(1),
            relief='raised',
        )
        style.map('Treeview',
            background=[('selected', colors.selectbg)],
            foreground=[('selected', colors.selectfg)],
        )

        for status, color in TAG_COLORS.items():
            self.tree.tag_configure(status, foreground=color)

        self.tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.tree.bind('<<TreeviewSelect>>', self._on_select)

    def _on_select(self, event):
        if self.on_file_select:
            self.on_file_select(self.get_selected_files())

    def populate(self, statuses):
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
                        open=True,
                    )
                    path_nodes[dir_iid] = node
                parent_iid = dir_iid

            if parent_iid == '':
                parent_iid = ''

            file_name = parts[-1]
            status_label = STATUS_LABELS.get(info['status'], info['status'])
            locked_by = info.get('locked_by', '') or ''
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
        return selected

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
