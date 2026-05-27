"""Evaluate geli model on its dataset."""
import os
import sys

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE)

from ultralytics import YOLO

DATA_YAML = os.path.join(_BASE, "datasets", "geli", "data.yaml")
MODEL_PATH = os.path.join(_BASE, "models", "geli.pt")


def main():
    print(f"模型: {MODEL_PATH}")
    print(f"数据: {DATA_YAML}")

    model = YOLO(MODEL_PATH)

    for conf in [0.2, 0.4, 0.5]:
        print(f"\n{'='*60}")
        print(f"conf={conf}")
        print(f"{'='*60}")
        metrics = model.val(data=DATA_YAML, conf=conf, workers=0, plots=False, verbose=False)

        print(f"mAP@50:      {metrics.box.map50:.4f}")
        print(f"mAP@50-95:   {metrics.box.map:.4f}")
        mp = getattr(metrics.box, 'mp', None)
        mr = getattr(metrics.box, 'mr', None)
        if mp is not None:
            print(f"Precision:   {mp:.4f}")
        if mr is not None:
            print(f"Recall:      {mr:.4f}")

        # Per-class results
        if hasattr(metrics, 'ap_class_index'):
            for i, cls_idx in enumerate(metrics.ap_class_index):
                names = getattr(metrics, 'names', {})
                name = names.get(cls_idx, str(cls_idx))
                ap50 = metrics.box.ap50[i]
                ap = metrics.box.ap[i]
                print(f"  {name}: AP@50={ap50:.4f}  AP@50-95={ap:.4f}")


if __name__ == "__main__":
    main()
