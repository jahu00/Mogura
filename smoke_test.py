import subprocess
from mogura.cbz import CbzArchive
from mogura.app import MoguraApp

app = MoguraApp()
app.geometry("1000x750+20+20")
app._auto_load_var.set(False)
app._load_source(lambda: CbzArchive("/home/jahu/manga.cbz"), "/home/jahu/manga.cbz", "Open CBZ")
app.update(); app.update_idletasks()
app._load_mokuro("/home/jahu/manga.mokuro")
app.show_page(1)  # page with overlaps (02.png)
app.update(); app.update_idletasks()

def grab():
    p = app._right_panel
    x,y = p.winfo_rootx(), p.winfo_rooty()
    w,h = p.winfo_width(), p.winfo_height()
    subprocess.run(["import","-window","root","-crop",f"{w}x{h}+{x}+{y}","warn.png"])
    app.destroy()
app.after(500, grab); app.mainloop()
from PIL import Image
im=Image.open("warn.png")
print("captured text panel:", im.size)
