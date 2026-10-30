"""Small native Tkinter GUI for NCDR DB Laboratory."""
from __future__ import annotations
import json, os, subprocess, sys, threading, time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from .acceleration.backend import Backend
from .core.db_reader import DBReader

class App:
    def __init__(self,root):
        self.root=root; root.title("NCDR DB Laboratory"); root.geometry("950x720")
        self.package_root=Path(__file__).resolve().parent
        self.db=tk.StringVar(); self.folder=tk.StringVar(); self.mode=tk.StringVar(value="Standard")
        self.backend=tk.StringVar(value="AUTO"); self.cpu=tk.StringVar(value="50%"); self.gpu=tk.StringVar(value="50%"); self.ram=tk.StringVar(value="AUTO")
        self.run_dir=None; self.proc=None; self.started=None
        self._layout()

    def _layout(self):
        f=ttk.Frame(self.root,padding=14); f.pack(fill="both",expand=True)
        ttk.Label(f,text="NCDR DB Laboratory",font=("TkDefaultFont",18,"bold")).grid(row=0,column=0,columnspan=4,sticky="w",pady=(0,12))
        ttk.Label(f,text="DB_0 file").grid(row=1,column=0,sticky="w"); ttk.Entry(f,textvariable=self.db).grid(row=1,column=1,columnspan=2,sticky="ew",padx=6); ttk.Button(f,text="Select DB_0",command=self.pick_db).grid(row=1,column=3)
        ttk.Label(f,text="Analysis folder").grid(row=2,column=0,sticky="w",pady=6); ttk.Entry(f,textvariable=self.folder).grid(row=2,column=1,columnspan=2,sticky="ew",padx=6); ttk.Button(f,text="Choose analysis folder",command=self.pick_folder).grid(row=2,column=3)
        ttk.Label(f,text="Analysis mode").grid(row=3,column=0,sticky="w"); ttk.Combobox(f,textvariable=self.mode,values=("Quick","Standard","Deep","Experimental"),state="readonly",width=17).grid(row=3,column=1,sticky="w",padx=6)
        ttk.Label(f,text="Compute backend").grid(row=3,column=2,sticky="e"); ttk.Combobox(f,textvariable=self.backend,values=("AUTO","CPU","GPU"),state="readonly",width=12).grid(row=3,column=3,sticky="w")
        ttk.Label(f,text="CPU load").grid(row=4,column=0,sticky="w",pady=6); ttk.Combobox(f,textvariable=self.cpu,values=("25%","50%","75%","100%"),state="readonly",width=14).grid(row=4,column=1,sticky="w",padx=6)
        ttk.Label(f,text="GPU load").grid(row=4,column=2,sticky="e"); ttk.Combobox(f,textvariable=self.gpu,values=("25%","50%","75%","100%"),state="readonly",width=12).grid(row=4,column=3,sticky="w")
        ttk.Label(f,text="Maximum RAM").grid(row=5,column=0,sticky="w"); ttk.Combobox(f,textvariable=self.ram,values=("AUTO","2 GB","4 GB","8 GB","Custom"),state="readonly",width=14).grid(row=5,column=1,sticky="w",padx=6)
        bar=ttk.Frame(f); bar.grid(row=6,column=0,columnspan=4,sticky="w",pady=10)
        ttk.Button(bar,text="Start analysis",command=self.start).pack(side="left",padx=(0,6)); ttk.Button(bar,text="Pause",command=self.pause).pack(side="left",padx=6); ttk.Button(bar,text="Resume",command=self.resume).pack(side="left",padx=6); ttk.Button(bar,text="Stop",command=self.stop).pack(side="left",padx=6); ttk.Button(bar,text="Create ChatGPT analysis package",command=self.package_run).pack(side="left",padx=6)
        self.status=tk.StringVar(value="Ready"); ttk.Label(f,textvariable=self.status).grid(row=7,column=0,columnspan=4,sticky="w")
        self.progress=ttk.Progressbar(f,mode="indeterminate"); self.progress.grid(row=8,column=0,columnspan=4,sticky="ew",pady=6)
        ttk.Label(f,text="Live analysis log").grid(row=9,column=0,sticky="w",pady=(8,2)); self.log=tk.Text(f,height=19,wrap="word",state="disabled"); self.log.grid(row=10,column=0,columnspan=4,sticky="nsew")
        inspector=ttk.LabelFrame(f,text="Block inspector",padding=7); inspector.grid(row=11,column=0,columnspan=4,sticky="ew",pady=10)
        ttk.Label(inspector,text="Sector").pack(side="left"); self.sector=tk.StringVar(); ttk.Entry(inspector,textvariable=self.sector,width=14).pack(side="left",padx=6); ttk.Button(inspector,text="Inspect",command=self.inspect).pack(side="left"); self.inspect_out=ttk.Label(inspector,text="Header and payload preview appear here",wraplength=700); self.inspect_out.pack(side="left",padx=8)
        f.columnconfigure(1,weight=1); f.rowconfigure(10,weight=1)
        detected=Backend(); names=[b.name+(': available' if b.available else ': unavailable') for b in detected.backends]
        self._append("Detected backends: "+", ".join(names)); self._append(f"Selected backend: {detected.selected} (benchmark {detected.backends[0].seconds_per_mb:.3f} sec/MB)")

    def _append(self,s):
        self.log.configure(state="normal"); self.log.insert("end",s+"\n"); self.log.see("end"); self.log.configure(state="disabled")
    def pick_db(self):
        p=filedialog.askopenfilename(title="Select DB_0");
        if p: self.db.set(p)
    def pick_folder(self):
        p=filedialog.askdirectory(title="Choose analysis folder");
        if p: self.folder.set(p)
    def start(self,resume=False):
        if self.proc and self.proc.poll() is None: messagebox.showinfo("Analysis running","Analysis is already running."); return
        if not self.db.get() or not Path(self.db.get()).is_file(): messagebox.showerror("Select DB_0","Choose a readable DB_0 file first."); return
        if not self.folder.get(): messagebox.showerror("Choose analysis folder","Choose where run folders and reports should be saved."); return
        if resume:
            runs=sorted(Path(self.folder.get()).glob("NCDR_DB_LAB_*/run_manifest.json"),reverse=True)
            if not runs: messagebox.showerror("No checkpoint","No previous run is available to resume."); return
            self.run_dir=runs[0].parent
            (self.run_dir/"pause.flag").unlink(missing_ok=True)
            (self.run_dir/"stop.flag").unlink(missing_ok=True)
        args=[sys.executable,"-m","db_lab.cli",self.db.get(),"--analysis-folder",self.folder.get(),"--mode",self.mode.get(),"--cpu-load",self.cpu.get(),"--gpu-load",self.gpu.get(),"--max-ram",self.ram.get(),"--backend",self.backend.get()]
        if resume: args.append("--resume")
        env=os.environ.copy(); env["PYTHONPATH"]=str(self.package_root.parent)+os.pathsep+env.get("PYTHONPATH","")
        self.proc=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,env=env)
        self.started=time.time(); self.status.set("Analysis running"); self.progress.start(10)
        threading.Thread(target=self._read_output,daemon=True).start(); self.root.after(500,self._watch)
    def _read_output(self):
        if not self.proc:return
        for line in self.proc.stdout:
            self.root.after(0,self._append,line.rstrip())
            if line.startswith("RUN_FOLDER="):
                self.run_dir=Path(line.strip().split("=",1)[1])
            if line.lstrip().startswith('{'):
                try: self.run_dir=Path(json.loads(line)["run_folder"])
                except Exception: pass
    def _watch(self):
        if self.proc and self.proc.poll() is None:
            elapsed=int(time.time()-(self.started or time.time())); details=f"Analysis running · elapsed {elapsed//60}m {elapsed%60}s"
            try:
                usage=subprocess.check_output(["ps","-o","%cpu=,%mem=","-p",str(self.proc.pid)],text=True,stderr=subprocess.DEVNULL).strip().split()
                if len(usage)>=2: details+=f" · CPU {usage[0]}% · process RAM {usage[1]}% · GPU utilization unavailable"
            except Exception: details+=" · CPU/RAM monitor unavailable · GPU utilization unavailable"
            if self.run_dir and (self.run_dir/"progress.json").exists():
                try:
                    p=json.loads((self.run_dir/"progress.json").read_text()); eta=p.get("remaining_seconds")
                    remain=f"{int(eta)//60}m {int(eta)%60}s remaining" if eta is not None else "estimating remaining time"
                    details=f"{p['stage']} · {p['processed']:,}/{p['total']:,} blocks · {p['blocks_per_second']} blocks/sec · {remain} · sector {p.get('sector')} · type 0x{(p.get('block_type') or 0):02x} · compression 0x{(p.get('compression') or 0):02x} · candidates {p.get('candidate_count',0)} · best {p.get('best_candidate_score') or '—'} · elapsed {elapsed//60}m {elapsed%60}s"
                except Exception: pass
            self.status.set(details); self.root.after(1000,self._watch)
        else:
            self.progress.stop()
            if self.proc:
                if self.proc.returncode==0 and self.run_dir and (self.run_dir/"summary.json").exists():
                    try:
                        summary=json.loads((self.run_dir/"summary.json").read_text()); best=(summary.get("top_candidates") or [{}])[0]
                        self.status.set(f"Analysis finished · {summary.get('total_blocks',0):,} blocks · {summary.get('hypotheses_tested',0)} hypotheses · best score {best.get('score','—')} ({best.get('transform','—')}) · report ZIP ready")
                    except Exception: self.status.set("Analysis finished")
                else: self.status.set("Analysis stopped or needs attention")
    def pause(self):
        if self.run_dir: (self.run_dir/"pause.flag").write_text("pause")
        self.status.set("Pausing at the next checkpoint")
    def resume(self):
        if self.proc and self.proc.poll() is None and self.run_dir:
            (self.run_dir/"pause.flag").unlink(missing_ok=True); self.status.set("Resumed"); return
        self.start(resume=True)
    def stop(self):
        if self.run_dir: (self.run_dir/"stop.flag").write_text("stop")
        self.status.set("Stopping at the next checkpoint")
    def package_run(self):
        if not self.run_dir or not (self.run_dir/"summary.json").exists(): messagebox.showinfo("No completed run","Complete an analysis before creating a report package."); return
        # Recreate a compact package from the completed run's current contents.
        from .analysis.runner import _package
        summary=json.loads((self.run_dir/"summary.json").read_text()); path=_package(self.run_dir,summary)
        messagebox.showinfo("Package created",path)
    def inspect(self):
        try:
            if not self.db.get(): raise ValueError("Select a DB_0 file first")
            sector=int(self.sector.get(),0)
            with DBReader(self.db.get()) as db:
                b=db.by_sector.get(sector)
                if not b: raise ValueError("Sector is not an indexed record header")
                raw=bytes(db.raw(b)[:40]).hex(" ")
                logical_text="logical preview unavailable for compression 0x01"
                if b.compression in (0,2):
                    logical=db.logical(b); logical_text=logical[:40].hex(" ")
                candidate_text=""
                if b.compression==1 and self.run_dir and (self.run_dir/"analysis.sqlite").exists():
                    import sqlite3
                    from .compression.comp01_lab import transforms
                    con=sqlite3.connect(self.run_dir/"analysis.sqlite")
                    names=[r[0] for r in con.execute("SELECT transform FROM candidates ORDER BY score DESC LIMIT 3")]; con.close()
                    found=dict(transforms(bytes(db.raw(b)[8:])))
                    candidate_text="\nTop compression 0x01 samples: "+" | ".join(f"{n}: {found[n][:16].hex()}" for n in names if n in found)
                self.inspect_out.configure(text=f"sector {b.sector} · type 0x{b.block_type:02x} · compression 0x{b.compression:02x} · span {b.span} · logical {b.logical_size:,} B\nheader {db.header_hex(b)} · raw {raw}\nlogical preview: {logical_text}{candidate_text}\nBL_ADDR-shaped references are not indexed in this milestone.")
        except Exception as e: messagebox.showerror("Could not inspect block",str(e))

def main():
    root=tk.Tk(); App(root); root.mainloop()
if __name__=="__main__": main()
