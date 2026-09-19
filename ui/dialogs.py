import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from ui.setup_wizard import SetupWizard

import ttkbootstrap as tb

from dpi import s


def _raise_on_top(dlg):
    """Bring a dialog above all other windows.

    Tk does not guarantee a newly created (even transient/grab) window maps
    above its parent on all window managers, so explicitly lift it and keep it
    raised for the (modal) lifetime of the dialog.
    """
    try:
        dlg.lift()
        dlg.attributes('-topmost', True)
    except tk.TclError:
        pass


def show_error(title, message, parent=None):
    messagebox.showerror(title, message, parent=parent or tk._default_root)


def show_info(title, message, parent=None):
    messagebox.showinfo(title, message, parent=parent or tk._default_root)


def show_confirm(title, message, parent=None):
    return messagebox.askyesno(title, message, parent=parent or tk._default_root)


class CommitDialog(tb.Toplevel):
    def __init__(self, master, files):
        super().__init__(master)
        self.result = None
        self.title('Push')
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        _raise_on_top(self)

        frame = ttk.Frame(self, padding=s(20))
        frame.pack(fill='both', expand=True)

        ttk.Label(frame, text='Commit Message', font=('', s(12), 'bold')).pack(anchor='w')

        deleted = [f for f in files if f['status'] == 'deleted']
        modified = [f for f in files if f['status'] != 'deleted']
        if len(files) == 1:
            verb = 'Deleted' if deleted else 'Updated'
            default_msg = '{} {}'.format(verb, files[0]['name'])
        elif not deleted or not modified:
            verb = 'Deleted' if deleted else 'Updated'
            names = [f['name'] for f in files]
            default_msg = '{} {}'.format(verb, ', '.join(names)) if len(files) <= 3 else '{} {} files'.format(verb, len(files))
        else:
            parts = []
            if modified:
                parts.append('{} {}'.format('Updated', ', '.join(f['name'] for f in modified)) if len(modified) <= 3 else 'Updated {} files'.format(len(modified)))
            if deleted:
                parts.append('{} {}'.format('Deleted', ', '.join(f['name'] for f in deleted)) if len(deleted) <= 3 else 'Deleted {} files'.format(len(deleted)))
            default_msg = '; '.join(parts)

        self.msg_text = tk.Text(frame, height=4, width=60, wrap='word')
        self.msg_text.insert('1.0', default_msg)
        self.msg_text.pack(fill='x', pady=(s(5), s(10)))
        self.msg_text.focus_set()

        ttk.Label(frame, text='Files to commit:', font=('', s(10), 'bold')).pack(anchor='w')

        list_frame = ttk.Frame(frame)
        list_frame.pack(fill='both', expand=True, pady=(0, s(10)))
        listbox = tk.Listbox(list_frame, height=6)
        scroll = ttk.Scrollbar(list_frame, orient='vertical', command=listbox.yview)
        listbox.config(yscrollcommand=scroll.set)
        listbox.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')

        for f in files:
            listbox.insert('end', f['path'])

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill='x')
        ttk.Button(btn_frame, text='Cancel', command=self.destroy).pack(side='right', padx=(s(5), 0))
        ttk.Button(btn_frame, text='Push', command=self._commit).pack(side='right')

        self.bind('<Control-Return>', lambda e: self._commit())
        self.bind('<Escape>', lambda e: self.destroy())

        self.wait_window()

    def _commit(self):
        msg = self.msg_text.get('1.0', 'end').strip()
        if not msg:
            show_error('Error', 'Please enter a commit message.')
            return
        self.result = msg
        self.destroy()
