"""Persistent operation feedback with a bounded, copyable session history."""
import time
import tkinter as tk
import ttkbootstrap as ttk

from dpi import s


class ActivityPanel(ttk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, padding=(s(10), s(6)), style='Card.TFrame', **kwargs)
        self._started = None
        self._timer = None
        self._warnings = False
        self._title = ''
        self._history = []
        self._expanded = False
        self._batch = False
        header = ttk.Frame(self, style='Card.TFrame')
        header.pack(fill='x')
        self.heading = ttk.Label(header, text='Ready to work', font=('Segoe UI', 10, 'bold'), style='Card.TLabel')
        self.heading.pack(side='left')
        self.elapsed = ttk.Label(header, text='', style='Muted.Card.TLabel')
        self.elapsed.pack(side='right')
        self.detail = ttk.Label(self, text='Pull the latest files, then lock a file before editing.',
                                anchor='w', wraplength=s(760), style='Card.TLabel')
        self.detail.pack(fill='x', pady=(s(3), s(4)))
        self._wrap_width = None
        self.bind('<Configure>', self._resize)
        self.bar = ttk.Progressbar(self, maximum=100, bootstyle='info')
        self.bar.pack(fill='x')
        footer = ttk.Frame(self, style='Card.TFrame')
        footer.pack(fill='x', pady=(s(4), 0))
        self.hint = ttk.Label(footer, text='Operation details stay here after completion.', style='Muted.Card.TLabel')
        self.hint.pack(side='left')
        self.toggle = ttk.Button(footer, text='Show activity', command=self._toggle,
                                 bootstyle='secondary-link', padding=(s(6), s(2)))
        self.toggle.pack(side='right')
        self.copy_button = ttk.Button(footer, text='Copy activity', command=self.copy,
                                      bootstyle='secondary-link', padding=(s(6), s(2)))
        self.log_frame = ttk.Frame(self)
        self.log = tk.Text(self.log_frame, height=4, wrap='word', state='disabled',
                           font=('Consolas', 10), relief='flat', padx=s(8), pady=s(8))
        scroll = ttk.Scrollbar(self.log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.log.pack(fill='both', expand=True)

    def _resize(self, event):
        width = max(100, event.width - s(32))
        if width != self._wrap_width:
            self._wrap_width = width
            self.detail.configure(wraplength=width)

    def _toggle(self):
        self._expanded = not self._expanded
        if self._expanded:
            self.log_frame.pack(fill='both', expand=True, pady=(s(8), 0))
            self.copy_button.pack(side='right')
        else:
            self.log_frame.pack_forget()
            self.copy_button.pack_forget()
        self.toggle.configure(text='Hide activity' if self._expanded else 'Show activity')

    def _append(self, message, level='info'):
        entry = '{}  {}{}'.format(time.strftime('%H:%M:%S'),
                                  'WARNING: ' if level == 'warning' else '', message)
        self._history.append(entry)
        self._history = self._history[-250:]
        self.log.configure(state='normal')
        self.log.delete('1.0', 'end')
        self.log.insert('end', '\n'.join(self._history))
        self.log.see('end')
        self.log.configure(state='disabled')

    def copy(self):
        self.clipboard_clear()
        self.clipboard_append('\n'.join(self._history))

    def begin(self, title):
        self._title = title
        self._batch = False
        self._warnings = False
        self._started = time.monotonic()
        self.heading.configure(text=title, style='info.Card.TLabel')
        self.detail.configure(text='Starting…')
        self.hint.configure(text='Working in the background. Please keep GCAD open.')
        self.bar.configure(bootstyle='info', mode='indeterminate', value=0)
        self.bar.start(15)
        self._append(title)
        self._tick()

    def _tick(self):
        seconds = int(time.monotonic() - self._started)
        self.elapsed.configure(text='{}:{:02d} elapsed'.format(seconds // 60, seconds % 60))
        if seconds >= 20 and not self._batch:
            self.hint.configure(text='Still working. Complete any Git sign-in window that appears.')
        self._timer = self.after(1000, self._tick)

    def update_progress(self, message, completed=None, total=None, level='info'):
        self._batch = bool(total)
        self._warnings |= level == 'warning'
        self.detail.configure(text=message if len(message) <= 220 else message[:217] + '…')
        self._append(message, level)
        self.bar.stop()
        if total:
            self.bar.configure(mode='determinate', maximum=total, value=completed or 0)
            self.hint.configure(text='{} of {} files processed in this stage'.format(completed or 0, total))
        else:
            self.hint.configure(text='Working in the background. Please keep GCAD open.')
            self.bar.configure(mode='indeterminate', maximum=100, value=0)
            self.bar.start(15)

    def finish(self, message, error=False):
        if self._timer:
            self.after_cancel(self._timer)
            self._timer = None
        self.bar.stop()
        style = 'danger' if error else 'warning' if self._warnings else 'success'
        self.heading.configure(text=self._title + (' · Failed' if error else
                               ' · Completed with warnings' if self._warnings else ' · Complete'), style=style + '.Card.TLabel')
        self.detail.configure(text=message if len(message) <= 220 else message[:217] + '…')
        self.bar.configure(mode='determinate', maximum=100, value=0 if error else 100, bootstyle=style)
        self.hint.configure(text='Review the activity details before continuing.' if error or self._warnings
                            else 'Finished. You can start another operation.')
        self._append(('FAILED: ' if error else '') + message)
        if (error or self._warnings) and not self._expanded:
            self._toggle()

    def destroy(self):
        if self._timer:
            self.after_cancel(self._timer)
        super().destroy()
