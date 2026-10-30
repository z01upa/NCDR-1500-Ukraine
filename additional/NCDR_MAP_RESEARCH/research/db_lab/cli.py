from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from .analysis.runner import run_analysis

def main(argv=None):
    ap=argparse.ArgumentParser(description="Local read-only NCDR DB_0 analysis")
    ap.add_argument("db0",nargs="?",type=Path)
    ap.add_argument("--analysis-folder",type=Path,required=True,help="Parent folder where timestamped run results are saved")
    ap.add_argument("--resume",action="store_true",help="Resume most recent matching run")
    ap.add_argument("--mode",choices=("Quick","Standard","Deep","Experimental"),default="Standard")
    ap.add_argument("--cpu-load",choices=("25%","50%","75%","100%"),default="50%")
    ap.add_argument("--gpu-load",choices=("25%","50%","75%","100%"),default="50%")
    ap.add_argument("--max-ram",choices=("AUTO","2 GB","4 GB","8 GB","Custom"),default="AUTO")
    ap.add_argument("--backend",choices=("AUTO","CPU","GPU"),default="AUTO")
    ap.add_argument("--stop-after-index",action="store_true",help=argparse.SUPPRESS)
    args=ap.parse_args(argv)
    if not args.db0:
        ap.error("DB_0 path is required")
    try:
        run,zip_path=run_analysis(args.db0,args.analysis_folder,args.resume,args.mode,"index" if args.stop_after_index else None,args.cpu_load,args.gpu_load,args.max_ram,args.backend)
        print(json.dumps({"run_folder":run,"chatgpt_zip":zip_path},indent=2),flush=True)
    except KeyboardInterrupt:
        print("Interrupted. Use --resume with the same DB_0 and analysis folder.",file=sys.stderr); return 130
    except Exception as e:
        print(f"ERROR: {e}",file=sys.stderr); return 1
    return 0

if __name__=="__main__": raise SystemExit(main())
