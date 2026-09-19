"""Shared desktop palette and live Windows appearance preference."""
import sys
import tkinter as tk
from tkinter import font as tkfont

from ttkbootstrap import Style
from ttkbootstrap.style import ThemeDefinition

from dpi import s

THEME_OPTIONS = {'Follow system': 'system', 'Light': 'light', 'Dark': 'dark'}
PALETTES = {
    'light': dict(primary='#315AE8', secondary='#617087', success='#187451',
                  info='#2563A6', warning='#946000', danger='#B83A4B',
                  light='#EEF2F8', dark='#202C40', bg='#F4F6FA', fg='#202C40',
                  selectbg='#DCE6FF', selectfg='#183875', border='#DCE2EC',
                  inputfg='#202C40', inputbg='#FFFFFF', active='#E8EDF6'),
    'dark': dict(primary='#7596FF', secondary='#A3AFC4', success='#70D6AB',
                 info='#83BBF4', warning='#EBC477', danger='#FF96A2',
                 light='#283449', dark='#101722', bg='#101722', fg='#E4EAF5',
                 selectbg='#304B7B', selectfg='#FFFFFF', border='#303D53',
                 inputfg='#E4EAF5', inputbg='#192334', active='#283449'),
}


def system_theme():
    """Use the Windows app preference; default to light when unavailable."""
    if sys.platform == 'win32':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
                value, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
                return 'light' if value else 'dark'
        except OSError:
            pass
    return 'light'


class ThemeManager:
    def __init__(self, root, preference='system'):
        self.root = root
        self.style = Style()
        self.preference = 'system'
        self.resolved = None
        self._timer = None
        for mode, colors in PALETTES.items():
            self.style.register_theme(ThemeDefinition(
                name='gcad-' + mode, colors=colors, themetype=mode))
        for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont'):
            tkfont.nametofont(name).configure(family='Segoe UI', size=10)
        self.set_preference(preference)
        self._timer = root.after(1500, self._poll)
        root.bind('<Destroy>', self._destroy, add='+')
        root.bind_all('<Map>', self._mapped, add='+')

    def set_preference(self, preference):
        self.preference = preference if preference in THEME_OPTIONS.values() else 'system'
        self._apply()

    def _apply(self):
        mode = system_theme() if self.preference == 'system' else self.preference
        if mode == self.resolved:
            return
        self.resolved = mode
        self.style.theme_use('gcad-' + mode)
        c = PALETTES[mode]
        style = self.style
        style.configure('TButton', padding=(s(12), s(7)))
        style.configure('Card.TFrame', background=c['inputbg'])
        style.configure('Card.TLabel', background=c['inputbg'], foreground=c['fg'])
        style.configure('Muted.Card.TLabel', background=c['inputbg'], foreground=c['secondary'])
        for role in ('primary', 'warning', 'info', 'danger', 'success', 'secondary'):
            style.configure(role + '.Card.TLabel', background=c['inputbg'], foreground=c[role])
            style.configure(role + '.Metric.TLabel', background=c['inputbg'],
                            foreground=c[role], font=('Segoe UI', 12, 'bold'))
        style.configure('Treeview', rowheight=tkfont.nametofont('TkTextFont').metrics('linespace') + s(8),
                        indent=s(24), background=c['inputbg'], fieldbackground=c['inputbg'],
                        foreground=c['fg'], borderwidth=0, relief='flat')
        style.configure('Treeview.Heading', padding=(s(10), s(5)),
                        font=('Segoe UI', 10, 'bold'), background=c['inputbg'], foreground=c['secondary'])
        style.map('Treeview', background=[('selected', c['selectbg'])],
                  foreground=[('selected', c['selectfg'])])
        self.root.configure(background=c['bg'])
        self._style_native(self.root)

    def _style_native(self, widget):
        """Also update hidden history and classic inputs in newly opened dialogs."""
        c = PALETTES[self.resolved]
        if isinstance(widget, (tk.Text, tk.Listbox)):
            widget.configure(background=c['inputbg'], foreground=c['inputfg'],
                             selectbackground=c['selectbg'], selectforeground=c['selectfg'],
                             highlightbackground=c['border'], highlightcolor=c['primary'],
                             relief='flat', borderwidth=0)
            if isinstance(widget, tk.Text):
                widget.configure(insertbackground=c['inputfg'])
        for child in widget.winfo_children():
            self._style_native(child)

    def _mapped(self, event):
        # Tcl-owned popdowns do not have a Python widget object.
        if isinstance(event.widget, tk.Misc):
            self._style_native(event.widget)

    def _poll(self):
        self._apply()
        self._timer = self.root.after(1500, self._poll)

    def _destroy(self, event):
        if event.widget is self.root and self._timer is not None:
            self.root.after_cancel(self._timer)
            self._timer = None
