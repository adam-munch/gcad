import tkinter as tk
import ttkbootstrap as ttk

from dpi import s


class Toolbar(ttk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.buttons = {}
        self._create_widgets()

    def _add_button(self, key, text, command=None, width=14, style='secondary-outline'):
        btn = ttk.Button(self._button_row, text=text, command=command, width=width, bootstyle=style, padding=(s(8), s(3)))
        btn.pack(side='left', padx=s(2), pady=s(2))
        self.buttons[key] = btn
        return btn

    def _add_separator(self):
        sep = ttk.Separator(self._button_row, orient='vertical')
        sep.pack(side='left', fill='y', padx=s(6), pady=s(4))

    def _create_widgets(self):
        self._button_row = ttk.Frame(self)
        self._button_row.pack(fill='x')
        self._add_button('pull', 'Pull latest', width=11, style='primary-outline')
        self._add_button('refresh', 'Refresh', width=9)
        self._add_separator()
        self._add_button('lock', 'Lock', width=8)
        self._add_button('unlock', 'Unlock', width=8)
        self._add_button('commit_push', 'Push changes', width=13, style='primary')
        self._add_separator()
        self._add_button('restore', 'Restore', width=9, style='danger-outline')
        self._button_row = ttk.Frame(self)
        self._button_row.pack(fill='x')
        self._add_button('open_file', 'Open file', width=11, style='secondary-link')
        self._add_button('open_folder', 'Open containing folder', width=23, style='secondary-link')

    def set_command(self, key, command):
        if key in self.buttons:
            self.buttons[key].config(command=command)

    def set_enabled(self, key, enabled):
        if key in self.buttons:
            state = 'normal' if enabled else 'disabled'
            self.buttons[key].config(state=state)

    def set_all_enabled(self, enabled):
        state = 'normal' if enabled else 'disabled'
        for btn in self.buttons.values():
            btn.config(state=state)

    def enable_defaults(self):
        for key in self.buttons:
            self.set_enabled(key, True)
