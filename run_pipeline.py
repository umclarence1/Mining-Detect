"""Run the whole pipeline in order.

    python run_pipeline.py              # everything, reusing tiles already downloaded
    python run_pipeline.py --relabel    # after hand labelling: re-download tiles with new labels, retrain
    python run_pipeline.py --from evaluate   # resume from a step

Steps: tiles -> train_rgb -> train_all -> evaluate -> predict -> change -> alerts -> turbidity -> map
"""
import argparse
import subprocess
import sys

STEPS = {
    "tiles": ["-m", "gee.export_tiles"],
    "train_rgb": ["-m", "model.train", "--experiment", "rgb"],
    "train_all": ["-m", "model.train", "--experiment", "all_bands"],
    "evaluate": ["-m", "model.evaluate"],
    "predict": ["-m", "model.predict"],
    "change": ["-m", "analysis.change"],
    "alerts": ["-m", "analysis.alerts"],
    "turbidity": ["-m", "analysis.turbidity"],
    "map": ["-m", "app.build_map"],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--relabel", action="store_true",
                        help="re-download tiles touching hand labels so they take effect, then redo everything")
    parser.add_argument("--from", dest="start", choices=list(STEPS), default="tiles")
    args = parser.parse_args()

    names = list(STEPS)[list(STEPS).index(args.start):]
    for name in names:
        cmd = [sys.executable, *STEPS[name]]
        if name == "tiles" and args.relabel:
            cmd.append("--relabel")
        print(f"\n=== {name} ===", flush=True)
        if subprocess.run(cmd).returncode != 0:
            sys.exit(f"Step '{name}' failed; fix it and resume with --from {name}")


if __name__ == "__main__":
    main()
