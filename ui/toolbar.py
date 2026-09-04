import tkinter as tk
from tkinter import ttk

from dpi import s


class Toolbar(ttk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.buttons = {}
        self._create_widgets()

    def _add_button(self, key, text, command=None, width=14):
        btn = ttk.Button(self, text=text, command=command, width=width)
        btn.pack(side='left', padx=s(2), pady=s(2))
        self.buttons[key] = btn
        return btn

    def _add_separator(self):
        sep = ttk.Separator(self, orient='vertical')
        sep.pack(side='left', fill='y', padx=s(6), pady=s(4))

    def _create_widgets(self):
        self._add_button('refresh', 'Refresh', width=10)
        self._add_separator()
        self._add_button('pull', 'Pull', width=10)
        self._add_button('commit_push', 'Push', width=10)
        self._add_button('restore', 'Restore', width=10)
        self._add_separator()
        self._add_button('lock', 'Lock', width=8)
        self._add_button('unlock', 'Unlock', width=8)

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
