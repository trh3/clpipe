import pytest
from pathlib import Path

from clpipe.bids import get_bids
from bids import BIDSLayout, BIDSLayoutIndexer
import re


def test_get_bids(clpipe_fmriprep_dir):
    project_dir = clpipe_fmriprep_dir
    layout = get_bids(
        project_dir / "data_BIDS",
        database_path=project_dir / "BIDS_index",
        index_metadata=True,
    )
    index_sub_0_path = layout.get(subject="0", return_type="filename")[0]
    actual_sub_0_path = str(
        clpipe_fmriprep_dir / "data_BIDS/sub-0/func/sub-0_task-rest_bold.nii.gz"
    )
    assert index_sub_0_path == actual_sub_0_path


def test_ignore_BIDS_Indexer(clpipe_fmriprep_dir):
    project_dir = clpipe_fmriprep_dir
    pattern = [re.compile(r".*\.html$")]
    # layout: BIDSLayout = get_bids(
    #     project_dir / "data_BIDS",
    #     database_path=project_dir / "BIDS_index",
    #     index_metadata=True,
    #     #fmriprep_dir=project_dir / "data_fmriprep",
    #     #ignore=pattern,
    #     refresh=True,
    # )
    # temp = layout.get()
    indexer: BIDSLayoutIndexer = BIDSLayoutIndexer(ignore=pattern)
    layout: BIDSLayout = BIDSLayout(project_dir / "data_BIDS", indexer=indexer)
    temp = layout.get()
    assert True
