"""Download the large public datasets used by the eval scripts into data/real/hf/.
Usage: pip install huggingface_hub ; python tools/fetch_data.py
The MCA company master CSVs must be downloaded by hand from data.gov.in (see data/README.md)."""
import os, sys
from huggingface_hub import snapshot_download

SETS = {
    "Divya52/indian-gst-invoices": "data/real/hf/gst_full",
    "arunchincheti/handwritten_and_cheques_dataset": "data/real/hf/cheques_idrbt",
    "jaganadhg/cheque-synthetic-images": "data/real/hf/cheques",
}
root = os.path.join(os.path.dirname(__file__), "..")
for repo, dest in SETS.items():
    path = os.path.join(root, dest)
    print("fetching", repo, "->", dest)
    try:
        snapshot_download(repo_id=repo, repo_type="dataset", local_dir=path)
    except Exception as e:
        print("  failed:", e, file=sys.stderr)
print("done")
